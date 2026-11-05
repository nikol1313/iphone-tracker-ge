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

BASE_URL = "https://kontakt.ge"
# The phones category filtered to Apple (Magento layered navigation).
KONTAKT_IPHONES_URL = f"{BASE_URL}/mobilurebi-da-aksesuarebi/mobiluri-telefonebi"
FILTER_PARAMS: dict[str, int | str] = {"kh_mtsarmoebeli": "Apple"}
MAX_PAGES = 10
LOGGER = logging.getLogger(__name__)


class KontaktCrawlError(RuntimeError):
    """Raised when Kontakt cannot be fetched after the retry policy."""


def _price(text: str) -> float | None:
    # Kontakt writes "4269,99 ₾": a comma before the tetri.
    return parse_price(text.replace(",", "."))


def products_from_page(soup: BeautifulSoup) -> list[dict[str, object]]:
    products: list[dict[str, object]] = []

    for card in soup.select("div.product-item"):
        name_element = card.select_one(".prodItem__title")
        link_element = card.select_one("a.prodItem__img[href]")
        # A discount shows the old price in <i> and the current one in <b>.
        price_element = card.select_one(".prodItem__prices b") or card.select_one(
            ".prodItem__prices strong"
        )
        if not name_element or not link_element or not price_element:
            continue

        name = name_element.get_text(" ", strip=True)
        price = _price(price_element.get_text(" ", strip=True))
        if "iphone" not in name.casefold() or price is None or price <= 0:
            continue

        image_element = card.select_one("img.product-image")
        image_url = image_element.get("src") if image_element else None
        product: dict[str, object] = {
            "name": name,
            "price": price,
            "currency": "GEL",
            "url": urljoin(BASE_URL, link_element["href"]),
            "image_url": urljoin(BASE_URL, image_url) if image_url else None,
            "store": "Kontakt",
            "is_available": card.select_one("button.tocart") is not None,
        }
        if card.get("id"):
            product["external_product_id"] = str(card["id"])
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
    params: dict[str, int | str] | None = FILTER_PARAMS

    for _ in range(MAX_PAGES):
        if page_url is None:
            break
        response = await fetch_with_retries(
            client,
            page_url,
            store="Kontakt",
            error_type=KontaktCrawlError,
            params=params,
            max_attempts=max_attempts,
            backoff_seconds=backoff_seconds,
            request_delay_seconds=request_delay_seconds,
        )
        soup = BeautifulSoup(response.text, "html.parser")
        for product in products_from_page(soup):
            products.setdefault(str(product["url"]), product)
        # The next-page link already carries the filter.
        next_link = soup.select_one(".pages-item-next a[href]")
        page_url = urljoin(BASE_URL, next_link["href"]) if next_link else None
        params = None
    else:
        LOGGER.warning("Kontakt has more than %d iPhone pages", MAX_PAGES)

    return list(products.values())


async def scrape_kontakt(
    url: str = KONTAKT_IPHONES_URL,
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

    # Kontakt sits behind Cloudflare, like the other proxied stores.
    async with browser_client(proxied=True) as owned_client:
        return await _scrape_pages(owned_client, url, **options)


async def main() -> None:
    products = await scrape_kontakt()
    print(json.dumps(products, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
