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

BASE_URL = "https://ee.ge"
# Elit has no iPhone category, so crawl all phones and keep the iPhones.
ELIT_PHONES_URL = f"{BASE_URL}/mobiluri-telefoni-c377t"
MAX_PAGES = 40
LOGGER = logging.getLogger(__name__)


class ElitCrawlError(RuntimeError):
    """Raised when Elit Electronics cannot be fetched after the retry policy."""


def _listing_data(soup: BeautifulSoup) -> dict | None:
    next_data_script = soup.select_one("script[id='__NEXT_DATA__']")
    if not next_data_script:
        return None

    try:
        script_text = next_data_script.string or next_data_script.get_text(strip=True)
        data = json.loads(script_text)
        listing = data["props"]["pageProps"]["initialListingData"]
    except (json.JSONDecodeError, AttributeError, KeyError, TypeError):
        return None

    return listing if isinstance(listing, dict) else None


def products_from_next_data(soup: BeautifulSoup) -> list[dict[str, object]]:
    items = (_listing_data(soup) or {}).get("products")
    if not isinstance(items, list):
        return []

    products: list[dict[str, object]] = []
    for item in items:
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
            "store": "Elit Electronics",
            # Pre-order and sold-out items render a disabled buy button.
            "is_available": item.get("disableBuyButton") is not True,
        }
        if item.get("id") is not None:
            product["external_product_id"] = str(item["id"])
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

    for page in range(1, MAX_PAGES + 1):
        response = await fetch_with_retries(
            client,
            url,
            store="Elit Electronics",
            error_type=ElitCrawlError,
            params={"page": page},
            max_attempts=max_attempts,
            backoff_seconds=backoff_seconds,
            request_delay_seconds=request_delay_seconds,
        )
        soup = BeautifulSoup(response.text, "html.parser")
        page_items = (_listing_data(soup) or {}).get("products")
        if not page_items:
            break
        for product in products_from_next_data(soup):
            products.setdefault(str(product["url"]), product)
    else:
        LOGGER.warning("Elit Electronics has more than %d phone pages", MAX_PAGES)

    return list(products.values())


async def scrape_elit(
    url: str = ELIT_PHONES_URL,
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
    products = await scrape_elit()
    print(json.dumps(products, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
