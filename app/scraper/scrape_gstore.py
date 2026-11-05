import asyncio
import json
import logging
import re
from decimal import Decimal

import httpx

from app.scraper.http import browser_client, fetch_with_retries, validate_retry_options

BASE_URL = "https://gstore.ge"
# WooCommerce's public Store API: JSON with price, stock and attributes per product.
GSTORE_PRODUCTS_URL = f"{BASE_URL}/wp-json/wc/store/v1/products"
SEARCH_PARAMS: dict[str, int | str] = {"search": "iphone", "per_page": 100}
MAX_PAGES = 10
LOGGER = logging.getLogger(__name__)


class GstoreCrawlError(RuntimeError):
    """Raised when Gstore cannot be fetched after the retry policy."""


def _attribute(item: dict, name: str) -> list[str]:
    for attribute in item.get("attributes") or []:
        if attribute.get("name") == name:
            return [str(term.get("name", "")) for term in attribute.get("terms") or []]
    return []


def products_from_api(items: list[dict]) -> list[dict[str, object]]:
    products: list[dict[str, object]] = []

    for item in items:
        # Gstore spells one listing "Sliver"; keep it the same phone as everyone's Silver.
        name = re.sub(r"\bSliver\b", "Silver", str(item.get("name") or "").strip())
        # Gstore also sells used phones ("USED (A)") and iPhone accessories; keep new iPhones.
        if "iphone" not in name.casefold() or "iPhones" not in _attribute(item, "Device Type"):
            continue
        if [condition.upper() for condition in _attribute(item, "Condition")] != ["NEW"]:
            continue

        prices = item.get("prices") or {}
        try:
            price = Decimal(str(prices["price"])).scaleb(-int(prices.get("currency_minor_unit", 0)))
        except (KeyError, ArithmeticError, ValueError):
            continue
        if price <= 0 or prices.get("currency_code", "GEL") != "GEL":
            continue

        images = item.get("images") or []
        products.append(
            {
                "name": name,
                "price": float(price),
                "currency": "GEL",
                "url": item.get("permalink"),
                "image_url": (images[0].get("thumbnail") or images[0].get("src")) if images else None,
                "store": "Gstore",
                "is_available": bool(item.get("is_in_stock")) and bool(item.get("is_purchasable")),
                "external_product_id": str(item["id"]),
            }
        )

    return products


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
            store="Gstore",
            error_type=GstoreCrawlError,
            params={**SEARCH_PARAMS, "page": page},
            max_attempts=max_attempts,
            backoff_seconds=backoff_seconds,
            request_delay_seconds=request_delay_seconds,
        )
        items = response.json()
        if not isinstance(items, list):
            raise GstoreCrawlError("Gstore returned an unexpected product list")
        products.extend(products_from_api(items))
        if page >= int(response.headers.get("X-WP-TotalPages", 1)):
            break
    else:
        LOGGER.warning("Gstore has more than %d iPhone pages", MAX_PAGES)

    return products


async def scrape_gstore(
    url: str = GSTORE_PRODUCTS_URL,
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
    products = await scrape_gstore()
    print(json.dumps(products, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
