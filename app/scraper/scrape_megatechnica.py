import asyncio
import json
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

from app.scraper.http import (
    browser_client,
    fetch_with_retries,
    parse_price,
    validate_retry_options,
)

BASE_URL = "https://www.megatechnica.ge"
# All smartphones render on one page; keep the iPhones.
MEGATECHNICA_PHONES_URL = f"{BASE_URL}/ka/smartfonebi"


class MegatechnicaCrawlError(RuntimeError):
    """Raised when Megatechnica cannot be fetched after the retry policy."""


def products_from_cards(soup: BeautifulSoup) -> list[dict[str, object]]:
    products: list[dict[str, object]] = []

    for card in soup.select("li[itemprop='itemListElement']"):
        name_element = card.select_one("[itemprop='name']")
        link_element = card.select_one("a.link[href]")
        price_element = card.select_one("span.price")

        if not name_element or not link_element or not price_element:
            continue

        name = name_element.get_text(" ", strip=True)
        price = parse_price(price_element.get_text(" ", strip=True))
        if "iphone" not in name.casefold() or price is None or price <= 0:
            continue

        image_element = card.select_one("img[itemprop='image']")
        image_path = image_element.get("src") if image_element else None
        product_id = card.select_one("input[name='product_id']")
        product: dict[str, object] = {
            "name": name,
            "price": price,
            "currency": "GEL",
            "url": urljoin(BASE_URL, link_element["href"]),
            "image_url": urljoin(BASE_URL, image_path) if image_path else None,
            "store": "Megatechnica",
            "is_available": card.select_one("button.buy, button.add_to_bag") is not None,
        }
        if product_id is not None and product_id.get("value"):
            product["external_product_id"] = str(product_id["value"])
        products.append(product)

    return products


async def scrape_megatechnica(
    url: str = MEGATECHNICA_PHONES_URL,
    *,
    max_attempts: int = 3,
    backoff_seconds: float = 1.0,
    request_delay_seconds: float = 0.5,
    client: httpx.AsyncClient | None = None,
) -> list[dict[str, object]]:
    validate_retry_options(max_attempts, backoff_seconds, request_delay_seconds)

    async def scrape_with(http_client: httpx.AsyncClient) -> list[dict[str, object]]:
        response = await fetch_with_retries(
            http_client,
            url,
            store="Megatechnica",
            error_type=MegatechnicaCrawlError,
            max_attempts=max_attempts,
            backoff_seconds=backoff_seconds,
            request_delay_seconds=request_delay_seconds,
        )
        return products_from_cards(BeautifulSoup(response.text, "html.parser"))

    if client is not None:
        return await scrape_with(client)

    async with browser_client() as owned_client:
        return await scrape_with(owned_client)


async def main() -> None:
    products = await scrape_megatechnica()
    print(json.dumps(products, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
