import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

from app.scraper.http import (
    browser_client,
    fetch_with_retries,
    parse_price,
    validate_retry_options,
)

BASE_URL = "https://zoommer.ge"
ZOOMMER_APPLE_PHONES_URL = f"{BASE_URL}/mobiluri-telefonebi-apple-c724"
PAGE_SIZE = 28
MAX_PRICE = 100_000
LOGGER = logging.getLogger(__name__)


class ZoommerCrawlError(RuntimeError):
    """Raised when Zoommer cannot be fetched after the retry policy."""


def product_from_json_ld_item(item: dict) -> dict[str, object] | None:
    product = item.get("item", item)

    if not isinstance(product, dict) or product.get("@type") != "Product":
        return None

    name = product.get("name")
    offers = product.get("offers")

    if not isinstance(name, str) or not isinstance(offers, dict):
        return None

    price = parse_price(str(offers.get("price", "")))

    if price is None:
        return None

    product_url = urljoin(f"{BASE_URL}/", str(product.get("url", "")))
    image_url = product.get("image")

    return {
        "name": name.strip(),
        "price": price,
        "currency": offers.get("priceCurrency") or "GEL",
        "url": product_url,
        "image_url": image_url if isinstance(image_url, str) else None,
        "store": "Zoommer",
    }


def products_from_json_ld(soup: BeautifulSoup) -> list[dict[str, object]]:
    products: list[dict[str, object]] = []

    for script in soup.select("script[type='application/ld+json']"):
        script_text = script.string or script.get_text(strip=True)

        if not script_text:
            continue

        try:
            data = json.loads(script_text)
        except json.JSONDecodeError:
            continue

        item_lists = data if isinstance(data, list) else [data]

        for item_list in item_lists:
            if not isinstance(item_list, dict):
                continue

            if item_list.get("@type") == "ItemList":
                elements = item_list.get("itemListElement", [])
            else:
                elements = [item_list]

            if not isinstance(elements, list):
                continue

            for element in elements:
                if not isinstance(element, dict):
                    continue

                product = product_from_json_ld_item(element)

                if product:
                    products.append(product)

    return products


def _filtered_products(soup: BeautifulSoup) -> dict | None:
    next_data_script = soup.select_one("script[id='__NEXT_DATA__']")
    if not next_data_script:
        return None

    try:
        script_text = next_data_script.string or next_data_script.get_text(strip=True)
        data = json.loads(script_text)
        filtered = data["props"]["pageProps"]["initialFilteredProducts"]
    except (json.JSONDecodeError, AttributeError, KeyError, TypeError):
        return None

    return filtered if isinstance(filtered, dict) else None


def total_from_next_data(soup: BeautifulSoup) -> int | None:
    total = (_filtered_products(soup) or {}).get("productsCount")
    return total if isinstance(total, int) else None


def products_from_next_data(soup: BeautifulSoup) -> list[dict[str, object]]:
    """Read the server-rendered product payload from Zoommer's Next.js page."""
    products = (_filtered_products(soup) or {}).get("products")

    if not isinstance(products, list):
        return []

    parsed: list[dict[str, object]] = []
    for item in products:
        if not isinstance(item, dict):
            continue

        name = item.get("name")
        route = item.get("route")
        price = parse_price(item.get("price", ""))
        if (
            not isinstance(name, str)
            or "iphone" not in name.casefold()
            or not isinstance(route, str)
            or not route.strip()
            or price is None
            or price <= 0
        ):
            continue

        image_url = item.get("imageUrl")
        product: dict[str, object] = {
            "name": name.strip(),
            "price": price,
            "currency": "GEL",
            "url": urljoin(BASE_URL, f"/{route.lstrip('/')}"),
            "image_url": image_url if isinstance(image_url, str) else None,
            "store": "Zoommer",
            # Listing pages report isInStock=false for everything; coming-soon
            # and sold-out items disable the buy button instead.
            "is_available": item.get("disableBuyButton") is not True
            and item.get("onSaleSoon") is not True,
        }
        product_id = item.get("id")
        if product_id is not None:
            product["external_product_id"] = str(product_id)
        parsed.append(product)

    return parsed


def products_from_html_cards(soup: BeautifulSoup) -> list[dict[str, object]]:
    products: list[dict[str, object]] = []

    product_cards = soup.select(
        ".product-card, "
        ".product-item, "
        ".products-list-item, "
        "[class*='product-card'], "
        "[class*='product-item']"
    )

    for card in product_cards:
        name_element = card.select_one(
            ".product-name, "
            ".product-title, "
            "[class*='product-name'], "
            "[class*='product-title'], "
            "h2, h3, h4"
        )
        price_element = card.select_one(
            ".product-price, "
            ".price, "
            "[class*='price']"
        )
        link_element = card.select_one("a[href]")
        image_element = card.select_one("img")

        if not name_element or not price_element or not link_element:
            continue

        name = name_element.get_text(" ", strip=True)
        price = parse_price(price_element.get_text(" ", strip=True))

        if price is None:
            continue

        product_url = urljoin(BASE_URL, link_element.get("href", ""))
        image_url = None

        if image_element:
            image_path = (
                image_element.get("src")
                or image_element.get("data-src")
                or image_element.get("data-lazy-src")
            )

            if image_path:
                image_url = urljoin(BASE_URL, image_path)

        products.append(
            {
                "name": name,
                "price": price,
                "currency": "GEL",
                "url": product_url,
                "image_url": image_url,
                "store": "Zoommer",
            }
        )

    return products


def products_from_page(soup: BeautifulSoup) -> list[dict[str, object]]:
    # The Next.js payload carries stock and ids; JSON-LD and cards are fallbacks.
    return (
        products_from_next_data(soup)
        or products_from_json_ld(soup)
        or products_from_html_cards(soup)
    )


async def _scrape_price_windows(
    fetch: Callable[[dict[str, int]], Awaitable[httpx.Response]],
) -> list[dict[str, object]]:
    # Zoommer ignores ?page= and renders PAGE_SIZE results, so split by price until each window fits.
    products: dict[str, dict[str, object]] = {}
    windows = [(0, MAX_PRICE)]

    while windows:
        price_from, price_to = windows.pop()
        response = await fetch({"priceFrom": price_from, "priceTo": price_to})
        soup = BeautifulSoup(response.text, "html.parser")
        for product in products_from_page(soup):
            products.setdefault(str(product["url"]), product)

        total = total_from_next_data(soup)
        if total is None or total <= PAGE_SIZE:
            continue
        if price_to - price_from <= 1:
            LOGGER.warning(
                "Zoommer has %d iPhones priced %d-%d; only %d are visible",
                total,
                price_from,
                price_to,
                PAGE_SIZE,
            )
            continue
        middle = (price_from + price_to) // 2
        windows.extend([(middle, price_to), (price_from, middle)])

    return list(products.values())


async def scrape_zoommer(
    url: str = ZOOMMER_APPLE_PHONES_URL,
    *,
    max_attempts: int = 3,
    backoff_seconds: float = 1.0,
    request_delay_seconds: float = 0.5,
    client: httpx.AsyncClient | None = None,
) -> list[dict[str, object]]:
    validate_retry_options(max_attempts, backoff_seconds, request_delay_seconds)

    def scrape_with(http_client: httpx.AsyncClient) -> Awaitable[list[dict[str, object]]]:
        return _scrape_price_windows(
            lambda params: fetch_with_retries(
                http_client,
                url,
                store="Zoommer",
                error_type=ZoommerCrawlError,
                params=params,
                max_attempts=max_attempts,
                backoff_seconds=backoff_seconds,
                request_delay_seconds=request_delay_seconds,
            )
        )

    if client is not None:
        return await scrape_with(client)

    async with browser_client() as owned_client:
        return await scrape_with(owned_client)


async def main() -> None:
    products = await scrape_zoommer()
    print(json.dumps(products, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
