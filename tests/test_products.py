from datetime import UTC, datetime, timedelta
from decimal import Decimal

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import PriceHist, ProductListing, Store
from tests.helpers import bearer, register_and_login


async def create_admin_product(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    *,
    model: str = "iPhone 17 Pro",
    storage: str = "256 GB",
    color: str = "Natural Titanium",
) -> tuple[str, dict]:
    token = await register_and_login(
        client,
        email="admin@example.com",
        admin=True,
        session_factory=session_factory,
    )
    response = await client.post(
        "/products",
        headers=bearer(token),
        json={
            "brand": "Apple",
            "model": model,
            "storage": storage,
            "color": color,
        },
    )
    assert response.status_code == 201, response.text
    return token, response.json()


@pytest.mark.asyncio
async def test_product_create_normalizes_identity_and_rejects_duplicate(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    token, product = await create_admin_product(client, session_factory)
    assert product["storage"] == "256GB"

    duplicate = await client.post(
        "/products",
        headers=bearer(token),
        json={
            "brand": " apple ",
            "model": "IPHONE 17 PRO",
            "storage": "256 gb",
            "color": "NATURAL TITANIUM",
        },
    )
    assert duplicate.status_code == 409


@pytest.mark.asyncio
async def test_product_pagination_filters_search_and_soft_delete(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    token, first = await create_admin_product(client, session_factory)
    second = await client.post(
        "/products",
        headers=bearer(token),
        json={
            "brand": "Apple",
            "model": "iPhone 16",
            "storage": "128 GB",
            "color": "Black",
        },
    )
    assert second.status_code == 201

    page = await client.get("/products", params={"limit": 1, "offset": 0})
    assert page.status_code == 200
    assert page.json()["total"] == 2
    assert len(page.json()["items"]) == 1
    assert (await client.get("/products", params={"limit": 101})).status_code == 422

    filtered = await client.get("/products", params={"storage": "256 gb"})
    assert [item["id"] for item in filtered.json()["items"]] == [first["id"]]

    search = await client.get("/search", params={"q": "iphone titanium"})
    assert search.status_code == 200
    assert [item["id"] for item in search.json()["items"]] == [first["id"]]
    assert (await client.get("/search", params={"q": "   "})).status_code == 422

    deleted = await client.delete(
        f"/products/{first['id']}",
        headers=bearer(token),
    )
    assert deleted.status_code == 204
    assert (await client.get(f"/products/{first['id']}")).status_code == 404
    normal = await client.get("/products")
    assert normal.json()["total"] == 1
    including = await client.get("/products", params={"include_inactive": True})
    assert including.json()["total"] == 2


@pytest.mark.asyncio
async def test_partial_update_and_conflicting_identity(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    token, first = await create_admin_product(client, session_factory)
    second_response = await client.post(
        "/products",
        headers=bearer(token),
        json={"brand": "Apple", "model": "iPhone 16", "storage": "128GB"},
    )
    second = second_response.json()

    updated = await client.patch(
        f"/products/{first['id']}",
        headers=bearer(token),
        json={"color": "Desert Titanium"},
    )
    assert updated.status_code == 200
    assert updated.json()["color"] == "Desert Titanium"

    conflict = await client.patch(
        f"/products/{first['id']}",
        headers=bearer(token),
        json={
            "model": second["model"],
            "storage": second["storage"],
            "color": second["color"],
        },
    )
    assert conflict.status_code == 409
    assert (
        await client.patch(
            "/products/99999",
            headers=bearer(token),
            json={"color": "Black"},
        )
    ).status_code == 404


@pytest.mark.asyncio
async def test_listing_and_merged_price_history_ordering(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    _, product_data = await create_admin_product(client, session_factory)
    product_id = product_data["id"]
    now = datetime.now(UTC)
    async with session_factory() as session:
        store_a = Store(title="Store A", web_url="https://a.example")
        store_b = Store(title="Store B", web_url="https://b.example")
        store_c = Store(title="Store C", web_url="https://c.example")
        session.add_all([store_a, store_b, store_c])
        await session.flush()
        expensive = ProductListing(
            product_id=product_id,
            store_id=store_a.id,
            product_url="https://a.example/phone",
            current_price=Decimal("3000.00"),
            currency="GEL",
            is_available=True,
            last_checked_at=now,
        )
        cheap = ProductListing(
            product_id=product_id,
            store_id=store_b.id,
            product_url="https://b.example/phone",
            current_price=Decimal("2500.00"),
            currency="GEL",
            is_available=True,
            last_checked_at=now,
        )
        unavailable = ProductListing(
            product_id=product_id,
            store_id=store_c.id,
            product_url="https://c.example/old",
            current_price=Decimal("2000.00"),
            currency="GEL",
            is_available=False,
            last_checked_at=now,
            external_product_id="old",
        )
        session.add_all([expensive, cheap, unavailable])
        await session.flush()
        session.add_all(
            [
                PriceHist(
                    listing_id=expensive.id,
                    price=Decimal("3100.00"),
                    currency="GEL",
                    recorded_at=now - timedelta(days=1),
                ),
                PriceHist(
                    listing_id=cheap.id,
                    price=Decimal("2500.00"),
                    currency="GEL",
                    recorded_at=now,
                ),
            ]
        )
        await session.commit()

    detail = await client.get(f"/products/{product_id}")
    assert detail.json()["lowest_price"] == "2500.00"
    assert detail.json()["listing_count"] == 3
    assert detail.json()["available_listing_count"] == 2

    listings = await client.get(f"/products/{product_id}/listings")
    assert [item["current_price"] for item in listings.json()["items"]] == [
        "2500.00",
        "3000.00",
        "2000.00",
    ]
    prices = await client.get(f"/products/{product_id}/prices")
    assert [item["price"] for item in prices.json()["items"]] == [
        "2500.00",
        "3100.00",
    ]
    extremes = await client.get(
        f"/products/{product_id}/prices/extremes",
        params={"currency": "gel"},
    )
    assert extremes.json() == {
        "currency": "GEL",
        "lowest_price": "2500.00",
        "highest_price": "3100.00",
    }
    no_usd_history = await client.get(
        f"/products/{product_id}/prices/extremes",
        params={"currency": "USD"},
    )
    assert no_usd_history.json() == {
        "currency": "USD",
        "lowest_price": None,
        "highest_price": None,
    }

    async with session_factory() as session:
        listings = list(await session.scalars(select(ProductListing)))
        for listing in listings:
            listing.is_available = False
        await session.commit()

    unavailable_detail = await client.get(f"/products/{product_id}")
    assert unavailable_detail.json()["lowest_price"] == "2000.00"
    assert unavailable_detail.json()["available_listing_count"] == 0


@pytest.mark.asyncio
async def test_catalog_reports_price_trends(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    _, product = await create_admin_product(client, session_factory)
    now = datetime.now(UTC)
    async with session_factory() as session:
        store_a = Store(title="Store A", web_url="https://a.example")
        store_b = Store(title="Store B", web_url="https://b.example")
        session.add_all([store_a, store_b])
        await session.flush()
        listings = [
            ProductListing(
                product_id=product["id"],
                store_id=store.id,
                product_url=f"{store.web_url}/phone",
                current_price=price,
                currency="GEL",
                is_available=True,
                last_checked_at=now,
            )
            for store, price in ((store_a, Decimal("2700.00")), (store_b, Decimal("2900.00")))
        ]
        session.add_all(listings)
        await session.flush()
        a, b = listings
        session.add_all(
            [
                PriceHist(listing_id=a.id, price=Decimal("3300.00"), currency="GEL", recorded_at=now - timedelta(days=20)),
                PriceHist(listing_id=a.id, price=Decimal("3100.00"), currency="GEL", recorded_at=now - timedelta(days=10)),
                PriceHist(listing_id=b.id, price=Decimal("3000.00"), currency="GEL", recorded_at=now - timedelta(days=9)),
                PriceHist(listing_id=a.id, price=Decimal("2700.00"), currency="GEL", recorded_at=now - timedelta(days=1)),
                PriceHist(listing_id=b.id, price=Decimal("2900.00"), currency="GEL", recorded_at=now - timedelta(days=1)),
            ]
        )
        await session.commit()

    for endpoint in ("/products", "/search?q=iphone"):
        response = await client.get(endpoint)
        assert response.status_code == 200, response.text
        item = response.json()["items"][0]
        assert item["lowest_price"] == "2700.00"
        # A week ago store A was at 3100 and store B at 3000.
        assert item["price_week_ago"] == "3000.00"
        assert item["lowest_price_ever"] == "2700.00"
        assert item["highest_price_ever"] == "3300.00"
