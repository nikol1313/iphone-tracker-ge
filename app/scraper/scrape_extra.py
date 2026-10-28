import asyncio
import json
import logging
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

from app.scraper.http import (
    browser_client,
    fetch_with_retries,
    validate_retry_options,
)

BASE_URL = "https://extra.ge"
EXTRA_IPHONE_URL = f"{BASE_URL}/catalog/iphone/2376"
MAX_PAGES = 20
NEW_CONDITION = 1
ACTIVE_OFFER = 1
# Marketplace sellers list used phones with a grade, e.g. "(შეფასება B)".
USED_GRADE_MARKER = "შეფასება"
LOGGER = logging.getLogger(__name__)


class ExtraCrawlError(RuntimeError):
    """Raised when Extra.ge cannot be fetched after the retry policy."""


def _catalog_page(soup: BeautifulSoup) -> dict | None:
    # The Angular app embeds its server-side API responses in the ng-state script.
    state_script = soup.select_one("script#ng-state")
    if not state_script:
        return None

    try:
        state = json.loads(state_script.string or state_script.get_text(strip=True))
    except (json.JSONDecodeError, AttributeError):
        return None
    if not isinstance(state, dict):
        return None

    for key, value in state.items():
        if key.startswith("catalog-products") and isinstance(value, dict):
            return value
    return None


def total_from_page(soup: BeautifulSoup) -> int | None:
    total = (_catalog_page(soup) or {}).get("offerTotalCount")
    return total if isinstance(total, int) else None


def products_from_page(soup: BeautifulSoup) -> list[dict[str, object]]:
    offers = (_catalog_page(soup) or {}).get("products")
    if not isinstance(offers, list):
        return []

    products: list[dict[str, object]] = []
    for offer in offers:
        if not isinstance(offer, dict):
            continue

        title = offer.get("productTitle")
        slug = offer.get("productSlug")
        product_id = offer.get("productSecondaryId")
        price = offer.get("offerDiscountPrice") or offer.get("offerPrice")
        if (
            not isinstance(title, str)
            or "iphone" not in title.casefold()
            or USED_GRADE_MARKER in title
            or offer.get("condition") != NEW_CONDITION
            or not isinstance(slug, str)
            or product_id is None
            or not isinstance(price, (int, float))
            or price <= 0
        ):
            continue

        quantity = offer.get("quantity")
        image_url = offer.get("productMainImage")
        product: dict[str, object] = {
            "name": " ".join(title.split()),
            "price": float(price),
            "currency": "GEL",
            "url": urljoin(BASE_URL, f"/product/{slug}/{product_id}"),
            "image_url": image_url if isinstance(image_url, str) else None,
            "store": "Extra.ge",
            "is_available": offer.get("offerStatus") == ACTIVE_OFFER
            and isinstance(quantity, int)
            and quantity > 0,
        }
        if offer.get("offerSecondaryId") is not None:
            product["external_product_id"] = str(offer["offerSecondaryId"])
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
    offers_seen = 0

    for page in range(1, MAX_PAGES + 1):
        response = await fetch_with_retries(
            client,
            url,
            store="Extra.ge",
            error_type=ExtraCrawlError,
            params={"p": page},
            max_attempts=max_attempts,
            backoff_seconds=backoff_seconds,
            request_delay_seconds=request_delay_seconds,
        )
        soup = BeautifulSoup(response.text, "html.parser")
        offers = (_catalog_page(soup) or {}).get("products") or []
        if not offers:
            break
        offers_seen += len(offers)
        for product in products_from_page(soup):
            # Several sellers can offer one product page, so key by offer.
            key = product.get("external_product_id") or product["url"]
            products.setdefault(str(key), product)

        total = total_from_page(soup)
        if total is None or offers_seen >= total:
            break
    else:
        LOGGER.warning("Extra.ge has more than %d iPhone pages", MAX_PAGES)

    return list(products.values())


async def scrape_extra(
    url: str = EXTRA_IPHONE_URL,
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
    products = await scrape_extra()
    print(json.dumps(products, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
