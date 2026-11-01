import asyncio
import json
import re
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

from app.scraper.http import (
    browser_client,
    fetch_with_retries,
    parse_price,
    validate_retry_options,
)

BASE_URL = "https://metromart.ge"
# "Cell Phones" filtered to the Apple brand.
METROMART_IPHONES_URL = f"{BASE_URL}/shop/category/Cell-Phones-385"
APPLE_BRAND_ID = 111
# The category page lists only product ids; each card's HTML comes from this
# Odoo JSON-RPC endpoint, the same call the site's own lazy loader makes.
PRODUCT_FRAME_URL = f"{BASE_URL}/render-category-product-frame"
# Safety stop for pagination; the site currently fits every iPhone on page 1.
MAX_PAGES = 10
STORE = "Metromart"
# Odoo prefixes card titles with an internal SKU: "[7923] Apple iPhone 17 …".
SKU_PREFIX = re.compile(r"^\[\d+\]\s*")


class MetromartCrawlError(RuntimeError):
    """Raised when Metromart cannot be fetched after the retry policy."""


def product_ids_from_category(soup: BeautifulSoup) -> list[int]:
    return [
        int(element["product-id"])
        for element in soup.select(".js-category[product-id]")
        if str(element["product-id"]).isdigit()
    ]


def product_from_frame(product_id: int, html: str) -> dict[str, object] | None:
    soup = BeautifulSoup(html, "html.parser")
    name_element = soup.select_one("a[itemprop='name']")
    price_element = soup.select_one(".oe_currency_value")
    if not name_element or not name_element.get("href") or not price_element:
        return None

    name = SKU_PREFIX.sub("", name_element.get_text(" ", strip=True))
    price = parse_price(price_element.get_text("", strip=True))
    if "iphone" not in name.casefold() or price is None or price <= 0:
        return None

    image_element = soup.select_one("img[itemprop='image']")
    image_path = image_element.get("src") if image_element else None
    return {
        "name": name,
        "price": price,
        "currency": "GEL",
        "url": urljoin(BASE_URL, str(name_element["href"])),
        "image_url": urljoin(BASE_URL, str(image_path)) if image_path else None,
        "store": STORE,
        # The site lists only orderable products and shows no stock flag on cards.
        "is_available": True,
        "external_product_id": str(product_id),
    }


async def scrape_metromart(
    url: str = METROMART_IPHONES_URL,
    *,
    max_attempts: int = 3,
    backoff_seconds: float = 1.0,
    request_delay_seconds: float = 0.5,
    client: httpx.AsyncClient | None = None,
) -> list[dict[str, object]]:
    validate_retry_options(max_attempts, backoff_seconds, request_delay_seconds)
    retry = {
        "store": STORE,
        "error_type": MetromartCrawlError,
        "max_attempts": max_attempts,
        "backoff_seconds": backoff_seconds,
        "request_delay_seconds": request_delay_seconds,
    }

    async def scrape_with(http_client: httpx.AsyncClient) -> list[dict[str, object]]:
        product_ids: list[int] = []
        for page in range(1, MAX_PAGES + 1):
            page_url = url if page == 1 else f"{url}/page/{page}"
            response = await fetch_with_retries(
                http_client, page_url, params={"brand": APPLE_BRAND_ID}, **retry
            )
            # Pages past the end repeat page 1, so stop once nothing new appears.
            new_ids = [
                product_id
                for product_id in product_ids_from_category(
                    BeautifulSoup(response.text, "html.parser")
                )
                if product_id not in product_ids
            ]
            if not new_ids:
                break
            product_ids.extend(new_ids)

        products: list[dict[str, object]] = []
        for product_id in product_ids:
            response = await fetch_with_retries(
                http_client,
                PRODUCT_FRAME_URL,
                json={
                    "jsonrpc": "2.0",
                    "method": "call",
                    "params": {"product_id": product_id, "view_mode": "grid"},
                    "id": product_id,
                },
                **retry,
            )
            result = response.json().get("result") or {}
            product = product_from_frame(product_id, str(result.get("html") or ""))
            if product is not None:
                products.append(product)
        return products

    if client is not None:
        return await scrape_with(client)

    async with browser_client() as owned_client:
        return await scrape_with(owned_client)


async def main() -> None:
    products = await scrape_metromart()
    print(json.dumps(products, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
