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

BASE_URL = "https://pcshop.ge"
PCSHOP_SMARTPHONES_URL = f"{BASE_URL}/product-category/smartphones-tablets/smartphones/"
# WooCommerce product search, narrowed to the smartphones category.
SEARCH_PARAMS: dict[str, int | str] = {"s": "iphone", "post_type": "product"}
MAX_PAGES = 10
LOGGER = logging.getLogger(__name__)


class PcshopCrawlError(RuntimeError):
    """Raised when PCShop cannot be fetched after the retry policy."""


def products_from_page(soup: BeautifulSoup) -> list[dict[str, object]]:
    products: list[dict[str, object]] = []

    for card in soup.select("li.product"):
        name_element = card.select_one(".woocommerce-loop-product__title")
        link_element = card.select_one("a.woocommerce-LoopProduct-link[href]")
        # A sale shows the old price struck through and the current one in <ins>.
        price_element = card.select_one(".price ins .amount") or card.select_one(
            ".price .amount"
        )
        if not name_element or not link_element or not price_element:
            continue

        name = name_element.get_text(" ", strip=True)
        price = parse_price(price_element.get_text(" ", strip=True))
        if "iphone" not in name.casefold() or price is None or price <= 0:
            continue

        image_element = card.select_one("img")
        image_path = image_element.get("src") if image_element else None
        product_id = card.select_one("[data-product_id]")
        product: dict[str, object] = {
            "name": name,
            "price": price,
            "currency": "GEL",
            "url": urljoin(BASE_URL, link_element["href"]),
            "image_url": urljoin(BASE_URL, image_path) if image_path else None,
            "store": "PCShop",
            "is_available": "instock" in (card.get("class") or []),
        }
        if product_id is not None and product_id.get("data-product_id"):
            product["external_product_id"] = str(product_id["data-product_id"])
        products.append(product)

    return products


async def _scrape_pages(
    client: httpx.AsyncClient,
    url: str,
    *,
    max_attempts: int,
    backoff_seconds: float,
    request_delay_seconds: float,
) -> list[dict[str, object]]:
    products: dict[str, dict[str, object]] = {}
    page_url: str | None = url

    for _ in range(MAX_PAGES):
        if page_url is None:
            break
        response = await fetch_with_retries(
            client,
            page_url,
            store="PCShop",
            error_type=PcshopCrawlError,
            params=SEARCH_PARAMS,
            max_attempts=max_attempts,
            backoff_seconds=backoff_seconds,
            request_delay_seconds=request_delay_seconds,
        )
        soup = BeautifulSoup(response.text, "html.parser")
        for product in products_from_page(soup):
            products.setdefault(str(product["url"]), product)
        next_link = soup.select_one("a.next.page-numbers[href]")
        # The next link already carries the search query.
        page_url = urljoin(BASE_URL, next_link["href"]).split("?")[0] if next_link else None
    else:
        LOGGER.warning("PCShop has more than %d iPhone pages", MAX_PAGES)

    return list(products.values())


async def scrape_pcshop(
    url: str = PCSHOP_SMARTPHONES_URL,
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
    products = await scrape_pcshop()
    print(json.dumps(products, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
