import asyncio
import json
from decimal import Decimal

import httpx

from app.scraper.http import browser_client, fetch_with_retries, validate_retry_options

BASE_URL = "https://icity.ge"
# WooCommerce Store API. Each iPhone model is one product; its storage/color/SIM
# options are variations with their own price and stock.
ICITY_PRODUCTS_URL = f"{BASE_URL}/wp-json/wc/store/v1/products"


class IcityCrawlError(RuntimeError):
    """Raised when iCity cannot be fetched after the retry policy."""


def products_from_variations(models: dict[int, str], variations: list[dict]) -> list[dict[str, object]]:
    products: list[dict[str, object]] = []

    for variation in variations:
        model = models.get(variation.get("parent"))
        price = Decimal(str(variation["prices"]["price"])).scaleb(
            -int(variation["prices"].get("currency_minor_unit", 0))
        )
        if model is None or price <= 0:
            continue
        # "ფერი: Silver, მოცულობა: 256GB, სიმ ბარათის ტიპი: eSIM" (color, storage, SIM type).
        options = dict(part.split(": ", 1) for part in variation["variation"].split(", "))
        sim = " eSIM" if options.get("სიმ ბარათის ტიპი") == "eSIM" else ""
        images = variation.get("images") or []
        products.append(
            {
                "name": f"{model} {options.get('მოცულობა', '')} {options.get('ფერი', '')}{sim}".strip(),
                "price": float(price),
                "currency": "GEL",
                "url": variation["permalink"],
                "image_url": images[0].get("thumbnail") if images else None,
                "store": "iCity",
                "is_available": bool(variation.get("is_in_stock")),
                "external_product_id": str(variation["id"]),
            }
        )

    return products


async def _fetch_all(client: httpx.AsyncClient, url: str, params: dict, **options) -> list[dict]:
    items: list[dict] = []
    page = 1
    while True:
        response = await fetch_with_retries(
            client, url, store="iCity", error_type=IcityCrawlError,
            params={**params, "per_page": 100, "page": page}, **options,
        )
        items.extend(response.json())
        if page >= int(response.headers.get("X-WP-TotalPages", 1)):
            return items
        page += 1


async def _scrape(client: httpx.AsyncClient, url: str, **options) -> list[dict[str, object]]:
    phones = await _fetch_all(client, url, {"category": "iphone"}, **options)
    models = {phone["id"]: phone["name"].strip() for phone in phones if phone["type"] == "variable"}
    if not models:
        return []
    variations = await _fetch_all(
        client, url, {"type": "variation", "parent[]": list(models)}, **options
    )
    return products_from_variations(models, variations)


async def scrape_icity(
    url: str = ICITY_PRODUCTS_URL,
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
        return await _scrape(client, url, **options)
    async with browser_client() as owned_client:
        return await _scrape(owned_client, url, **options)


if __name__ == "__main__":
    print(json.dumps(asyncio.run(scrape_icity()), ensure_ascii=False, indent=2))
