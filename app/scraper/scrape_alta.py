import json
import logging
import re
import time
from collections.abc import Callable
from urllib.parse import urljoin

import cloudscraper
import requests
from bs4 import BeautifulSoup

BASE_URL = "https://alta.ge"
ALTA_IPHONE_URL = f"{BASE_URL}/search/iphone/category=mobiluri-telefonebi;"
ALTA_PHONE_CATEGORY_ID = 16
PAGE_SIZE = 20
MAX_PRICE = 100_000
LOGGER = logging.getLogger(__name__)

class AltaCrawlError(RuntimeError):
    """Raised when Alta cannot be fetched after the retry policy."""


def _is_retryable(error: Exception) -> bool:
    if isinstance(error, (requests.RequestException, requests.ConnectionError)):
        return True
    if hasattr(error, 'response') and error.response is not None:
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


def product_from_json_ld_item(item: dict) -> dict[str, object] | None:
    product = item.get("item", item)

    if not isinstance(product, dict) or product.get("@type") != "Product":
        return None

    name = product.get("name")
    offers = product.get("offers")

    if not isinstance(name, str) or not isinstance(offers, dict):
        return None

    price = parse_price(str(offers.get("price", "")))

    if price is None:
        return None

    product_url = urljoin(f"{BASE_URL}/", str(product.get("url", "")))
    image_url = product.get("image")

    return {
        "name": name.strip(),
        "price": price,
        "currency": offers.get("priceCurrency") or "GEL",
        "url": product_url,
        "image_url": image_url if isinstance(image_url, str) else None,
        "store": "Alta",
    }


def _search_data(soup: BeautifulSoup) -> dict | None:
    next_data_script = soup.select_one("script[id='__NEXT_DATA__']")
    if not next_data_script:
        return None

    try:
        script_text = next_data_script.string or next_data_script.get_text(strip=True)
        data = json.loads(script_text)
        search_data = data["props"]["pageProps"]["initialSearchData"]
    except (json.JSONDecodeError, AttributeError, KeyError, TypeError):
        return None

    return search_data if isinstance(search_data, dict) else None


def total_from_next_data(soup: BeautifulSoup) -> int | None:
    total = (_search_data(soup) or {}).get("productsCount")
    return total if isinstance(total, int) else None


def products_from_next_data(soup: BeautifulSoup) -> list[dict[str, object]]:
    products: list[dict[str, object]] = []

    products_data = (_search_data(soup) or {}).get("products")

    if not isinstance(products_data, list):
        return products

    for item in products_data:
        if not isinstance(item, dict):
            continue

        name = item.get("name")
        price = item.get("price")
        category_id = item.get("categoryId")
        route = item.get("route")

        if not isinstance(name, str) or not isinstance(price, (int, float)):
            continue
        if (
            category_id != ALTA_PHONE_CATEGORY_ID
            or "iphone" not in name.lower()
            or price <= 0
            or not isinstance(route, str)
            or not route.strip()
        ):
            continue

        product_url = urljoin(BASE_URL, f"/{route.lstrip('/')}")
        image_url = item.get("imageUrl")

        products.append({
            "name": name.strip(),
            "price": float(price),
            "currency": "GEL",
            "url": product_url,
            "image_url": image_url if isinstance(image_url, str) else None,
            "store": "Alta",
        })

    return products


def products_from_html_cards(soup: BeautifulSoup) -> list[dict[str, object]]:
    products: list[dict[str, object]] = []

    product_cards = soup.select(
        ".product-card, "
        ".product-item, "
        ".products-list-item, "
        "[class*='product-card'], "
        "[class*='product-item']"
    )

    for card in product_cards:
        name_element = card.select_one(
            ".product-name, "
            ".product-title, "
            "[class*='product-name'], "
            "[class*='product-title'], "
            "h2, h3, h4"
        )
        price_element = card.select_one(
            ".product-price, "
            ".price, "
            "[class*='price']"
        )
        link_element = card.select_one("a[href]")
        image_element = card.select_one("img")

        if not name_element or not price_element or not link_element:
            continue

        name = name_element.get_text(" ", strip=True)
        price = parse_price(price_element.get_text(" ", strip=True))

        if price is None:
            continue

        product_url = urljoin(BASE_URL, link_element.get("href", ""))
        image_url = None

        if image_element:
            image_path = (
                image_element.get("src")
                or image_element.get("data-src")
                or image_element.get("data-lazy-src")
            )

            if image_path:
                image_url = urljoin(BASE_URL, image_path)

        products.append(
            {
                "name": name,
                "price": price,
                "currency": "GEL",
                "url": product_url,
                "image_url": image_url,
                "store": "Alta",
            }
        )

    return products


def _fetch_with_retries(
    scraper: cloudscraper.CloudScraper,
    url: str,
    *,
    params: dict[str, int] | None = None,
    max_attempts: int,
    backoff_seconds: float,
    request_delay_seconds: float,
) -> requests.Response:
    last_error: Exception | None = None
    attempts_made = 0

    for attempt in range(1, max_attempts + 1):
        attempts_made = attempt
        if request_delay_seconds:
            time.sleep(request_delay_seconds)

        try:
            response = scraper.get(url, params=params)
            response.raise_for_status()
            return response
        except Exception as error:
            last_error = error

            if attempt == max_attempts or not _is_retryable(error):
                break

            retry_delay = backoff_seconds * (2 ** (attempt - 1))
            LOGGER.warning(
                "Alta request failed; retrying in %.1f seconds "
                "(attempt %d/%d): %s",
                retry_delay,
                attempt,
                max_attempts,
                error,
            )
            if retry_delay:
                time.sleep(retry_delay)

    raise AltaCrawlError(
        f"Failed to fetch {url} {params or ''} after {attempts_made} attempt(s): "
        f"{last_error}"
    ) from last_error


def _scrape_price_windows(
    fetch: Callable[[dict[str, int]], requests.Response],
) -> list[dict[str, object]]:
    # Alta only renders the first PAGE_SIZE results, so split by price until each window fits.
    products: dict[str, dict[str, object]] = {}
    windows = [(0, MAX_PRICE)]

    while windows:
        price_from, price_to = windows.pop()
        response = fetch(
            {
                "cats": ALTA_PHONE_CATEGORY_ID,
                "priceFrom": price_from,
                "priceTo": price_to,
            }
        )
        soup = BeautifulSoup(response.text, "html.parser")
        page_products = (
            products_from_next_data(soup)
            if _search_data(soup) is not None
            else products_from_html_cards(soup)
        )
        for product in page_products:
            products.setdefault(str(product["url"]), product)

        total = total_from_next_data(soup)
        if total is None or total <= PAGE_SIZE:
            continue
        if price_to - price_from <= 1:
            LOGGER.warning(
                "Alta has %d iPhones priced %d-%d; only %d are visible",
                total,
                price_from,
                price_to,
                PAGE_SIZE,
            )
            continue
        middle = (price_from + price_to) // 2
        windows.extend([(middle, price_to), (price_from, middle)])

    return list(products.values())


def scrape_alta(
    url: str = ALTA_IPHONE_URL,
    *,
    max_attempts: int = 3,
    backoff_seconds: float = 1.0,
    request_delay_seconds: float = 0.5,
    scraper: cloudscraper.CloudScraper | None = None,
) -> list[dict[str, object]]:
    if max_attempts < 1:
        raise ValueError("max_attempts must be at least 1")
    if backoff_seconds < 0 or request_delay_seconds < 0:
        raise ValueError("retry and request delays cannot be negative")

    if scraper is None:
        scraper = cloudscraper.create_scraper(
            browser={
                'browser': 'chrome',
                'platform': 'linux',
                'desktop': True
            }
        )

    return _scrape_price_windows(
        lambda params: _fetch_with_retries(
            scraper,
            url,
            params=params,
            max_attempts=max_attempts,
            backoff_seconds=backoff_seconds,
            request_delay_seconds=request_delay_seconds,
        )
    )


def main() -> None:
    products = scrape_alta()
    print(json.dumps(products, ensure_ascii=False, indent=3))


if __name__ == "__main__":
    main()
