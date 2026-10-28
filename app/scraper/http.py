"""HTTP fetching shared by the httpx-based retailer scrapers."""

import asyncio
import logging
import re

import httpx

LOGGER = logging.getLogger(__name__)
BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 "
        "Chrome/149.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ka-GE,ka;q=0.9,en-US;q=0.8,en;q=0.7",
}


def browser_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        headers=BROWSER_HEADERS,
        timeout=httpx.Timeout(20, connect=10),
        follow_redirects=True,
    )


def parse_price(price_text: str) -> float | None:
    cleaned_price = re.sub(r"[^\d.]", "", str(price_text))

    if not cleaned_price:
        return None

    try:
        return float(cleaned_price)
    except ValueError:
        return None


def validate_retry_options(
    max_attempts: int,
    backoff_seconds: float,
    request_delay_seconds: float,
) -> None:
    if max_attempts < 1:
        raise ValueError("max_attempts must be at least 1")
    if backoff_seconds < 0 or request_delay_seconds < 0:
        raise ValueError("retry and request delays cannot be negative")


def _is_retryable(error: httpx.HTTPError) -> bool:
    if isinstance(error, httpx.RequestError):
        return True
    if isinstance(error, httpx.HTTPStatusError):
        return error.response.status_code in {408, 429} or (
            error.response.status_code >= 500
        )
    return False


async def fetch_with_retries(
    client: httpx.AsyncClient,
    url: str,
    *,
    store: str,
    error_type: type[RuntimeError],
    params: dict[str, int | str] | None = None,
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
                "%s request failed; retrying in %.1f seconds "
                "(attempt %d/%d): %s",
                store,
                retry_delay,
                attempt,
                max_attempts,
                error,
            )
            if retry_delay:
                await asyncio.sleep(retry_delay)

    raise error_type(
        f"Failed to fetch {url} {params or ''} after {attempts_made} attempt(s): "
        f"{last_error}"
    ) from last_error
