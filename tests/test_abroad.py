from datetime import UTC, date, datetime
from decimal import Decimal

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.services import abroad_service
from tests.test_products import create_admin_product

NBG_DAY = [{
    "date": "2026-11-07T00:00:00.000Z",
    "currencies": [
        {"code": "EUR", "quantity": 1, "rate": 2.8998},
        {"code": "JPY", "quantity": 100, "rate": 1.7},
        {"code": "USD", "quantity": 1, "rate": 2.5949},
    ],
}]


@pytest.fixture(autouse=True)
def fresh_rates(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(abroad_service, "_rates", {})
    monkeypatch.setattr(abroad_service, "_rates_date", None)
    monkeypatch.setattr(abroad_service, "_fetched_at", None)


def nbg_client(calls: list[str], *, status: int = 200) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(status, json=NBG_DAY)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
async def test_rates_are_read_once_and_kept_when_the_bank_fails() -> None:
    calls: list[str] = []

    rates, day = await abroad_service.gel_rates(nbg_client(calls))
    assert rates == {"USD": Decimal("2.5949"), "EUR": Decimal("2.8998")}
    assert day == date(2026, 11, 7)

    # Fresh rates are reused without asking the bank again.
    assert await abroad_service.gel_rates(nbg_client(calls)) == (rates, day)
    assert len(calls) == 1

    # Once stale, a failed fetch keeps the last good rates.
    abroad_service._fetched_at = datetime(2000, 1, 1, tzinfo=UTC)
    assert await abroad_service.gel_rates(nbg_client(calls, status=500)) == (rates, day)
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_abroad_prices_in_lari_for_a_phone_apple_sells(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    abroad_service._rates = {"USD": Decimal("2.5"), "EUR": Decimal("3")}
    abroad_service._rates_date = date(2026, 11, 7)
    abroad_service._fetched_at = datetime.now(UTC)
    _, product = await create_admin_product(
        client, session_factory, model="iPhone 18 Pro eSIM", storage="256GB"
    )

    body = (await client.get(f"/products/{product['id']}/abroad")).json()

    assert body == {
        "items": [
            {"country": "US", "currency": "USD", "price": "1199", "price_gel": "2997.50"},
            {"country": "DE", "currency": "EUR", "price": "1449", "price_gel": "4347.00"},
        ],
        "rate_date": "2026-11-07",
    }


@pytest.mark.asyncio
async def test_no_abroad_prices_for_a_phone_apple_no_longer_sells(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    _, product = await create_admin_product(client, session_factory)

    body = (await client.get(f"/products/{product['id']}/abroad")).json()

    assert body == {"items": [], "rate_date": None}
    assert (await client.get("/products/999999/abroad")).status_code == 404
