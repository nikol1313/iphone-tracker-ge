import asyncio
import json
import logging
import re
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

BASE_URL = "https://ispace.ge"
ISPACE_IPHONE_URL = f"{BASE_URL}/category/iphone"
MAX_PAGES = 20
LOGGER = logging.getLogger(__name__)


class IspaceCrawlError(RuntimeError):
    """Raised when iSpace cannot be fetched after the retry policy."""


def _is_retryable(error: httpx.HTTPError) -> bool:
    if isinstance(error, httpx.RequestError):
        return True
    if isinstance(error, httpx.HTTPStatusError):
        return error.response.status_code in {408, 429} or (
            error.response.status_code >= 500
        )
    return False


def parse_price(price_text: str) -> float | None:
    cleaned_price = re.sub(r"[^\d.]", "", str(price_text))

    if not cleaned_price:
        return None

    try:
        return float(cleaned_price)
    except ValueError:
        return None


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


async def _fetch_with_retries(
    client: httpx.AsyncClient,
    url: str,
    *,
    params: dict[str, int],
    max_attempts: int,
    backoff_seconds: float,
    request_delay_seconds: float,
) -> httpx.Response:
    last_error: httpx.HTTPError | None = None
    attempts_made = 0

    for attempt in range(1, max_attempts + 1):
        attempts_made = attempt
        if request_delay_seconds:
            await asyncio.sleep(request_delay_seconds)

        try:
            response = await client.get(url, params=params)
            response.raise_for_status()
            return response
        except httpx.HTTPError as error:
            last_error = error

            if attempt == max_attempts or not _is_retryable(error):
                break

            retry_delay = backoff_seconds * (2 ** (attempt - 1))
            LOGGER.warning(
                "iSpace request failed; retrying in %.1f seconds "
                "(attempt %d/%d): %s",
                retry_delay,
                attempt,
                max_attempts,
                error,
            )
            if retry_delay:
                await asyncio.sleep(retry_delay)

    raise IspaceCrawlError(
        f"Failed to fetch {url} {params} after {attempts_made} attempt(s): "
        f"{last_error}"
    ) from last_error


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
        response = await _fetch_with_retries(
            client,
            url,
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
    if max_attempts < 1:
        raise ValueError("max_attempts must be at least 1")
    if backoff_seconds < 0 or request_delay_seconds < 0:
        raise ValueError("retry and request delays cannot be negative")

    options = {
        "max_attempts": max_attempts,
        "backoff_seconds": backoff_seconds,
        "request_delay_seconds": request_delay_seconds,
    }

    if client is not None:
        return await _scrape_pages(client, url, **options)

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) "
            "AppleWebKit/537.36 "
            "Chrome/149.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ka-GE,ka;q=0.9,en-US;q=0.8,en;q=0.7",
    }
    async with httpx.AsyncClient(
        headers=headers,
        timeout=httpx.Timeout(20, connect=10),
        follow_redirects=True,
    ) as owned_client:
        return await _scrape_pages(owned_client, url, **options)


async def main() -> None:
    products = await scrape_ispace()
    print(json.dumps(products, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
