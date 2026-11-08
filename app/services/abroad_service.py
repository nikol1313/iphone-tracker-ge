"""Apple's own price for a phone in the US and Germany, in lari at the National Bank's rate.

Apple changes its prices about once a year, when new iPhones come out in September; update
APPLE_PRICES then from apple.com/shop/buy-iphone and apple.com/de/shop/buy-iphone (each model
page lists every storage with its price). Phones Apple no longer sells have no entry.
US prices are before sales tax; German prices include 19% VAT.
"""

import logging
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import httpx

from app.db.db_schemas import AbroadPrice, AbroadPricesResponse

logger = logging.getLogger(__name__)

# (model, storage) -> (US dollars, euros in Germany), checked on apple.com 2026-11-08.
APPLE_PRICES: dict[tuple[str, str], tuple[int, int]] = {
    ("iPhone 16", "128GB"): (829, 999),
    ("iPhone 17", "256GB"): (929, 1099),
    ("iPhone 17", "512GB"): (1129, 1349),
    ("iPhone 17e", "256GB"): (699, 849),
    ("iPhone 17e", "512GB"): (899, 1099),
    ("iPhone Air", "256GB"): (1099, 1299),
    ("iPhone Air", "512GB"): (1299, 1549),
    ("iPhone Air", "1TB"): (1699, 2049),
    ("iPhone 18 Pro", "256GB"): (1199, 1449),
    ("iPhone 18 Pro", "512GB"): (1399, 1699),
    ("iPhone 18 Pro", "1TB"): (1799, 2199),
    ("iPhone 18 Pro", "2TB"): (2399, 2949),
    ("iPhone 18 Pro Max", "256GB"): (1299, 1599),
    ("iPhone 18 Pro Max", "512GB"): (1499, 1849),
    ("iPhone 18 Pro Max", "1TB"): (1899, 2349),
    ("iPhone 18 Pro Max", "2TB"): (2499, 3099),
    ("iPhone Duo", "256GB"): (1999, 2299),
    ("iPhone Duo", "512GB"): (2199, 2549),
    ("iPhone Duo", "1TB"): (2599, 3049),
    ("iPhone Duo", "2TB"): (3199, 3799),
}

NBG_RATES_URL = "https://nbg.gov.ge/gw/api/ct/monetarypolicy/currencies/en/json/"
# The National Bank sets one rate a day; a failed fetch waits this long before trying again.
RATES_MAX_AGE = timedelta(hours=6)
CENT = Decimal("0.01")

# Last good rates (lari per unit), the day they're for, and when they were last fetched.
_rates: dict[str, Decimal] = {}
_rates_date: date | None = None
_fetched_at: datetime | None = None


async def gel_rates(client: httpx.AsyncClient | None = None) -> tuple[dict[str, Decimal], date | None]:
    """USD and EUR in lari; on failure the last good rates (or none) until the next try."""
    global _rates, _rates_date, _fetched_at
    now = datetime.now(UTC)
    if _fetched_at is not None and now - _fetched_at < RATES_MAX_AGE:
        return _rates, _rates_date
    _fetched_at = now
    try:
        async with client or httpx.AsyncClient(timeout=5) as http:
            response = await http.get(NBG_RATES_URL)
            response.raise_for_status()
            day = response.json()[0]
        _rates = {
            currency["code"]: Decimal(str(currency["rate"])) / currency["quantity"]
            for currency in day["currencies"]
            if currency["code"] in ("USD", "EUR")
        }
        _rates_date = date.fromisoformat(day["date"][:10])
    except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError) as error:
        logger.warning("National Bank rates unavailable: %s", error)
    return _rates, _rates_date


async def abroad_prices(model: str, storage: str | None) -> AbroadPricesResponse:
    """Apple's US and German price for this phone; empty when Apple doesn't sell it or no rate."""
    prices = APPLE_PRICES.get((model.removesuffix(" eSIM"), storage or ""))
    if prices is None:
        return AbroadPricesResponse(items=[], rate_date=None)
    rates, rate_date = await gel_rates()
    items = [
        AbroadPrice(
            country=country,
            currency=currency,
            price=Decimal(price),
            price_gel=(price * rates[currency]).quantize(CENT),
        )
        for country, currency, price in (("US", "USD", prices[0]), ("DE", "EUR", prices[1]))
        if currency in rates
    ]
    return AbroadPricesResponse(items=items, rate_date=rate_date if items else None)
