from datetime import UTC, datetime
from decimal import Decimal

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import PriceAlert, ProductListing, Store
from tests.helpers import bearer, register_and_login
from tests.test_products import create_admin_product


@pytest.mark.asyncio
async def test_tracking_duplicate_ownership_and_removal(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    _, product = await create_admin_product(client, session_factory)
    user_token = await register_and_login(
        client,
        email="user@example.com",
        session_factory=session_factory,
    )
    other_token = await register_and_login(
        client,
        email="other@example.com",
        session_factory=session_factory,
    )

    created = await client.post(
        "/tracked-products",
        headers=bearer(user_token),
        json={"product_id": product["id"]},
    )
    assert created.status_code == 201
    assert (
        await client.post(
            "/tracked-products",
            headers=bearer(user_token),
            json={"product_id": product["id"]},
        )
    ).status_code == 409
    assert (
        await client.get("/tracked-products", headers=bearer(user_token))
    ).json()["total"] == 1
    assert (
        await client.get("/tracked-products", headers=bearer(other_token))
    ).json()["total"] == 0
    assert (
        await client.delete(
            f"/tracked-products/{product['id']}",
            headers=bearer(other_token),
        )
    ).status_code == 404
    assert (
        await client.delete(
            f"/tracked-products/{product['id']}",
            headers=bearer(user_token),
        )
    ).status_code == 204


@pytest.mark.asyncio
async def test_alert_validation_trigger_and_ownership(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    _, product = await create_admin_product(client, session_factory)
    user_token = await register_and_login(
        client,
        email="user@example.com",
        session_factory=session_factory,
    )
    other_token = await register_and_login(
        client,
        email="other@example.com",
        session_factory=session_factory,
    )
    now = datetime.now(UTC)
    async with session_factory() as session:
        store_a = Store(title="Available", web_url="https://a.example")
        store_b = Store(title="Unavailable", web_url="https://b.example")
        session.add_all([store_a, store_b])
        await session.flush()
        session.add_all(
            [
                ProductListing(
                    product_id=product["id"],
                    store_id=store_a.id,
                    product_url="https://a.example/phone",
                    current_price=Decimal("2400.00"),
                    currency="GEL",
                    is_available=True,
                    last_checked_at=now,
                ),
                ProductListing(
                    product_id=product["id"],
                    store_id=store_b.id,
                    product_url="https://b.example/phone",
                    current_price=Decimal("1000.00"),
                    currency="GEL",
                    is_available=False,
                    last_checked_at=now,
                ),
            ]
        )
        await session.commit()

    invalid_price = await client.post(
        f"/products/{product['id']}/alerts",
        headers=bearer(user_token),
        json={"target_price": "0", "currency": "GEL"},
    )
    invalid_currency = await client.post(
        f"/products/{product['id']}/alerts",
        headers=bearer(user_token),
        json={"target_price": "2500.00", "currency": "GE1"},
    )
    assert invalid_price.status_code == invalid_currency.status_code == 422

    created = await client.post(
        f"/products/{product['id']}/alerts",
        headers=bearer(user_token),
        json={"target_price": "2500.00", "currency": "gel"},
    )
    assert created.status_code == 201, created.text
    assert created.json()["current_lowest_price"] == "2400.00"
    assert created.json()["is_triggered"] is True
    alert_id = created.json()["id"]
    assert (
        await client.post(
            f"/products/{product['id']}/alerts",
            headers=bearer(user_token),
            json={"target_price": "2300.00", "currency": "GEL"},
        )
    ).status_code == 409

    async with session_factory() as session:
        alert = await session.get(PriceAlert, alert_id)
        assert alert is not None
        alert.notified_at = now
        await session.commit()
    edited = await client.put(
        f"/alerts/{alert_id}",
        headers=bearer(user_token),
        json={"target_price": "2300.00", "currency": "GEL"},
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["target_price"] == "2300.00"
    assert edited.json()["is_triggered"] is False
    async with session_factory() as session:
        alert = await session.get(PriceAlert, alert_id)
        assert alert is not None
        # A new target emails again once reached.
        assert alert.notified_at is None
    assert (
        await client.put(
            f"/alerts/{alert_id}",
            headers=bearer(other_token),
            json={"target_price": "1.00", "currency": "GEL"},
        )
    ).status_code == 404
    assert (
        await client.put(
            f"/alerts/{alert_id}",
            headers=bearer(user_token),
            json={"target_price": "0", "currency": "GEL"},
        )
    ).status_code == 422

    mine = await client.get("/alerts", headers=bearer(user_token))
    other = await client.get("/alerts", headers=bearer(other_token))
    assert mine.json()["total"] == 1
    assert other.json()["total"] == 0
    assert (
        await client.delete(
            f"/alerts/{alert_id}",
            headers=bearer(other_token),
        )
    ).status_code == 404
    assert (
        await client.delete(
            f"/alerts/{alert_id}",
            headers=bearer(user_token),
        )
    ).status_code == 204


@pytest.mark.asyncio
async def test_alert_adds_product_to_watchlist_and_untrack_removes_it(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    _, product = await create_admin_product(client, session_factory)
    token = await register_and_login(
        client,
        email="watcher@example.com",
        session_factory=session_factory,
    )

    created = await client.post(
        f"/products/{product['id']}/alerts",
        headers=bearer(token),
        json={"target_price": "2100", "currency": "GEL"},
    )
    assert created.status_code == 201

    watchlist = await client.get("/tracked-products", headers=bearer(token))
    [item] = watchlist.json()["items"]
    assert item["product"]["id"] == product["id"]
    assert item["active_alert"]["target_price"] == "2100.00"

    # Alerting on an already tracked product keeps one watchlist row.
    await client.delete(f"/alerts/{created.json()['id']}", headers=bearer(token))
    again = await client.post(
        f"/products/{product['id']}/alerts",
        headers=bearer(token),
        json={"target_price": "2000", "currency": "GEL"},
    )
    assert again.status_code == 201
    watchlist = await client.get("/tracked-products", headers=bearer(token))
    assert len(watchlist.json()["items"]) == 1

    removed = await client.delete(
        f"/tracked-products/{product['id']}",
        headers=bearer(token),
    )
    assert removed.status_code == 204
    alerts = await client.get("/alerts", headers=bearer(token))
    assert alerts.json()["items"] == []
