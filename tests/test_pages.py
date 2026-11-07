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


def test_preview_tags_escape_product_text() -> None:
    from app.api.pages import render_index
    from app.db.db_schemas import ProductSummary

    product = ProductSummary(
        id=1,
        brand="Apple",
        model='iPhone "17" <b>',
        storage="256GB",
        color="Black",
        image_url='https://img.example/a.jpg?x="1"',
        lowest_price=None,
        currency="GEL",
        listing_count=0,
        available_listing_count=0,
    )

    html = render_index(product)

    assert "<b>" not in html
    assert 'content="iPhone &quot;17&quot; &lt;b&gt; 256GB Black"' in html
    assert 'content="https://img.example/a.jpg?x=&quot;1&quot;"' in html


@pytest.mark.asyncio
async def test_index_lists_cheapest_price_per_model(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    _, product = await create_admin_product(client, session_factory)
    await _priced_product(session_factory, product["id"])

    html = (await client.get("/")).text

    assert "<!--server-models-->" not in html
    assert 'data-server-rendered' in html
    assert f'data-product-id="{product["id"]}" tabindex="0">' in html
    assert '<span class="model-price-name">iPhone 17 Pro<small>256GB · Natural Titanium</small></span>' in html
    assert '<span class="model-price-value">3,199 ₾</span>' in html
    assert "მარაგშია 1 მაღაზიაში" in html
    # The only model in stock leads the headline, with its cheapest store.
    assert (
        '<h1 id="overviewTitle" data-model="iPhone 17 Pro" data-price="3199.00" data-store="Store A">'
        "iPhone 17 Pro დღეს ყველაზე იაფია Store A-ში: 3,199 ₾</h1>"
    ) in html
    assert 'data-models="1" data-stores="1"' in html


def test_headline_prefers_the_newest_standard_model() -> None:
    from app.api.pages import _headline_product
    from app.db.db_schemas import ProductSummary

    models = [
        ProductSummary(
            id=number,
            brand="Apple",
            model=model,
            storage="256GB",
            color="Black",
            image_url=None,
            lowest_price=Decimal("2000"),
            currency="GEL",
            listing_count=1,
            available_listing_count=1,
        )
        for number, model in enumerate(["iPhone 16", "iPhone 18 Pro", "iPhone 17", "iPhone Duo"])
    ]

    assert _headline_product(models).model == "iPhone 17"
    assert _headline_product(models[1:2]).model == "iPhone 18 Pro"
    assert _headline_product([]) is None


def test_index_folds_the_model_list_like_the_page() -> None:
    from app.api.pages import render_index
    from app.db.db_schemas import ProductSummary

    models = [
        ProductSummary(
            id=number,
            brand="Apple",
            model=f"iPhone {number}",
            storage="128GB",
            color="Black",
            image_url=None,
            lowest_price=Decimal("2000"),
            currency="GEL",
            listing_count=1,
            available_listing_count=1,
        )
        for number in range(9, 18)
    ]

    html = render_index(None, models)

    # Newest first, with 17 before 9 (natural order), and three rows past the fold hidden.
    assert html.index("iPhone 17<small>") < html.index("iPhone 9<small>")
    assert html.count('tabindex="0" hidden>') == 3
    assert "<span>ყველა 9 მოდელის ჩვენება</span>" in html
    assert 'aria-expanded="false"><span>' in html
