from datetime import UTC, datetime
from decimal import Decimal

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import ProductListing, Store
from tests.test_products import create_admin_product


async def _priced_product(session_factory: async_sessionmaker[AsyncSession], product_id: int) -> None:
    async with session_factory() as session:
        store = Store(title="Store A", web_url="https://a.example")
        session.add(store)
        await session.flush()
        session.add(
            ProductListing(
                product_id=product_id,
                store_id=store.id,
                product_url="https://a.example/phone",
                current_price=Decimal("3199.00"),
                currency="GEL",
                is_available=True,
                last_checked_at=datetime.now(UTC),
            )
        )
        await session.commit()


@pytest.mark.asyncio
async def test_index_has_site_preview_tags(client: httpx.AsyncClient) -> None:
    response = await client.get("/")

    assert response.status_code == 200
    html = response.text
    assert "<!--server-meta-->" not in html
    assert '<meta property="og:title" content="iPhone-ის ფასები საქართველოში — iPhone Tracker">' in html
    assert '<meta property="og:image" content="http://localhost:8080/static/logo.png">' in html
    assert '<link rel="canonical" href="http://localhost:8080/">' in html


@pytest.mark.asyncio
async def test_shared_phone_link_has_its_own_preview(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    _, product = await create_admin_product(client, session_factory)
    await _priced_product(session_factory, product["id"])

    response = await client.get(f"/?page=products&id={product['id']}")

    html = response.text
    assert "<title>iPhone 17 Pro 256GB Natural Titanium — 3,199 ₾ — iPhone Tracker</title>" in html
    assert '<meta property="og:title" content="iPhone 17 Pro 256GB Natural Titanium — 3,199 ₾">' in html
    assert f'<meta property="og:url" content="http://localhost:8080/?page=products&amp;id={product["id"]}">' in html
    assert html.count('name="description"') == 1


@pytest.mark.asyncio
async def test_unknown_phone_link_falls_back_to_site_preview(client: httpx.AsyncClient) -> None:
    for query in ("?page=products&id=999", "?page=products&id=abc"):
        response = await client.get(f"/{query}")
        assert response.status_code == 200
        assert '<link rel="canonical" href="http://localhost:8080/">' in response.text


@pytest.mark.asyncio
async def test_sitemap_lists_pages_and_phones(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    _, product = await create_admin_product(client, session_factory)

    response = await client.get("/sitemap.xml")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/xml")
    assert "<loc>http://localhost:8080/</loc>" in response.text
    assert f"<loc>http://localhost:8080/?page=products&amp;id={product['id']}</loc>" in response.text


@pytest.mark.asyncio
async def test_health(client: httpx.AsyncClient) -> None:
    response = await client.get("/health")
    assert response.json() == {"status": "ok"}


def test_api_docs_are_off_in_production(monkeypatch) -> None:
    import importlib

    import app.main

    monkeypatch.setattr("app.conf.settings.PROD", True)
    try:
        prod_app = importlib.reload(app.main).app
        assert prod_app.docs_url is None
        assert prod_app.redoc_url is None
        assert prod_app.openapi_url is None
    finally:
        monkeypatch.undo()
        importlib.reload(app.main)
