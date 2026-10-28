import asyncio
import json
import logging
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

from app.scraper.http import (
    browser_client,
    fetch_with_retries,
    parse_price,
    validate_retry_options,
)

BASE_URL = "https://ispace.ge"
ISPACE_IPHONE_URL = f"{BASE_URL}/category/iphone"
MAX_PAGES = 20
LOGGER = logging.getLogger(__name__)


class IspaceCrawlError(RuntimeError):
    """Raised when iSpace cannot be fetched after the retry policy."""


def _is_open_box(product_path: str) -> bool:
    return product_path.rstrip("/").endswith("-od")


def products_from_cards(soup: BeautifulSoup) -> list[dict[str, object]]:
    products: list[dict[str, object]] = []

    for card in soup.select(".products-grid_grid [data-test='carousel-product']"):
        name_element = card.select_one(".entity-card_name-text")
        link_element = card.select_one("a.entity-card_name[href]")
        price_element = card.select_one(
            ".carousel-product_action-price"
        ) or card.select_one(".carousel-product_price-value")

        if not name_element or not link_element or not price_element:
            continue

        name = name_element.get_text(" ", strip=True)
        product_path = link_element.get("href", "")
        price = parse_price(price_element.get_text(" ", strip=True))

        if (
            "iphone" not in name.casefold()
            or not product_path
            or _is_open_box(product_path)
            or price is None
            or price <= 0
        ):
            continue

        image_element = card.select_one("img.entity-card_image")
        image_url = image_element.get("src") if image_element else None
        # "Notify me" is a link, buy/pre-order is a button.
        action = card.select_one(".carousel-product_button")

        products.append(
            {
                "name": name,
                "price": price,
                "currency": "GEL",
                "url": urljoin(BASE_URL, product_path),
                "image_url": urljoin(BASE_URL, image_url) if image_url else None,
                "store": "iSpace",
                "is_available": action is not None and action.name == "button",
                "external_product_id": product_path.rstrip("/").rsplit("/", 1)[-1],
            }
        )

    return products


def _deduplicate(products: list[dict[str, object]]) -> list[dict[str, object]]:
    # Regional variants share a name; keep the available, cheapest one.
    best: dict[str, dict[str, object]] = {}

    for product in products:
        key = str(product["name"]).casefold()
        current = best.get(key)
        if current is None or (
            not product["is_available"],
            product["price"],
        ) < (
            not current["is_available"],
            current["price"],
        ):
            best[key] = product

    return list(best.values())


async def _scrape_pages(
    client: httpx.AsyncClient,
    url: str,
    *,
    max_attempts: int,
    backoff_seconds: float,
    request_delay_seconds: float,
) -> list[dict[str, object]]:
    products: list[dict[str, object]] = []

    for page in range(1, MAX_PAGES + 1):
        response = await fetch_with_retries(
            client,
            url,
            store="iSpace",
            error_type=IspaceCrawlError,
            params={"page": page},
            max_attempts=max_attempts,
            backoff_seconds=backoff_seconds,
            request_delay_seconds=request_delay_seconds,
        )
        soup = BeautifulSoup(response.text, "html.parser")
        if not soup.select(".products-grid_grid [data-test='carousel-product']"):
            break
        products.extend(products_from_cards(soup))

    return _deduplicate(products)


async def scrape_ispace(
    url: str = ISPACE_IPHONE_URL,
    *,
    max_attempts: int = 3,
    backoff_seconds: float = 1.0,
    request_delay_seconds: float = 0.5,
    client: httpx.AsyncClient | None = None,
) -> list[dict[str, object]]:
    validate_retry_options(max_attempts, backoff_seconds, request_delay_seconds)

    options = {
        "max_attempts": max_attempts,
        "backoff_seconds": backoff_seconds,
        "request_delay_seconds": request_delay_seconds,
    }

    if client is not None:
        return await _scrape_pages(client, url, **options)

    async with browser_client() as owned_client:
        return await _scrape_pages(owned_client, url, **options)


async def main() -> None:
    products = await scrape_ispace()
    print(json.dumps(products, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
