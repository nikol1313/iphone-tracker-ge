from datetime import UTC, datetime, timedelta
from decimal import Decimal

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import PriceHist, ProductListing, Store
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

    assert product["slug"] == "iphone-17-pro-256gb-natural-titanium"

    response = await client.get("/iphone-17-pro-256gb-natural-titanium")

    assert response.status_code == 200
    html = response.text
    assert "<title>iPhone 17 Pro 256GB Natural Titanium — 3,199 ₾ — iPhone Tracker</title>" in html
    assert '<meta property="og:title" content="iPhone 17 Pro 256GB Natural Titanium — 3,199 ₾">' in html
    assert '<meta property="og:url" content="http://localhost:8080/iphone-17-pro-256gb-natural-titanium">' in html
    assert html.count('name="description"') == 1


@pytest.mark.asyncio
async def test_old_phone_link_redirects_to_its_own_address(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    _, product = await create_admin_product(client, session_factory)

    response = await client.get(f"/?page=products&id={product['id']}")

    assert response.status_code == 301
    assert response.headers["location"] == "http://localhost:8080/iphone-17-pro-256gb-natural-titanium"


@pytest.mark.asyncio
async def test_unknown_phone_or_path_is_a_404_page(client: httpx.AsyncClient) -> None:
    for path in ("/?page=products&id=999", "/?page=products&id=abc", "/iphone-99-1tb-gold", "/nope"):
        response = await client.get(path)
        assert response.status_code == 404, path
        assert '<meta name="robots" content="noindex">' in response.text


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
    assert f"<loc>http://localhost:8080/{product['slug']}</loc>" in response.text


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


def test_preview_uses_the_larger_store_photo() -> None:
    from app.api.pages import _preview_image

    asbis = "https://prod-cdn.prod.asbis.io/s3size/el:t/f:webp/rt:fill/w:512/plain/s3://cms/a.webp"
    assert _preview_image(asbis) == "https://prod-cdn.prod.asbis.io/s3size/el:t/f:jpg/rt:fill/w:1200/plain/s3://cms/a.webp"
    assert _preview_image("https://www.megatechnica.ge/storage/x/abc_200.jpg") == "https://www.megatechnica.ge/storage/x/abc.jpg"
    assert _preview_image("https://s3.zoommer.ge/site/a_Thumb.jpeg") == "https://s3.zoommer.ge/site/a_Thumb.jpeg"


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
    assert '<span class="model-price-name">iPhone 17 Pro</span>' in html
    assert '<span class="model-price-value">3,199 ₾</span>' in html
    assert (
        '<span class="model-price-meta">256GB · <span class="color-name">'
        '<span class="swatch" data-color="Natural Titanium" aria-hidden="true"></span>'
        "Natural Titanium</span> · 1 მაღაზია</span>"
    ) in html
    assert "model-price-store" not in html
    # The only model in stock leads the headline, with its cheapest store.
    assert (
        '<h1 id="overviewTitle" data-model="iPhone 17 Pro" data-price="3199.00" data-store="Store A">'
        "iPhone 17 Pro დღეს ყველაზე იაფია Store A-ში: 3,199\u00a0₾</h1>"
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
    assert html.index("iPhone 17</span>") < html.index("iPhone 9</span>")
    assert html.count('tabindex="0" hidden>') == 3
    assert "<span>ყველა 9 მოდელის ჩვენება</span>" in html
    assert 'aria-expanded="false"><span>' in html


@pytest.mark.asyncio
async def test_headline_has_the_models_30_day_price_line(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    _, product = await create_admin_product(client, session_factory)
    await _priced_product(session_factory, product["id"])
    async with session_factory() as session:
        listing_id = await session.scalar(select(ProductListing.id))
        now = datetime.now(UTC)
        session.add_all([
            PriceHist(listing_id=listing_id, price=Decimal("3399.00"), recorded_at=now - timedelta(days=10)),
            PriceHist(listing_id=listing_id, price=Decimal("3199.00"), recorded_at=now - timedelta(days=2)),
        ])
        await session.commit()

    html = (await client.get("/")).text

    assert '<figure class="intro-trend" id="introTrend" data-low="3199.00" data-high="3399.00" data-series=' in html
    assert '<svg id="introChart"' in html
    assert "ბოლო 30 დღე: 3,199 ₾ – 3,399 ₾</figcaption>" in html
    # Only the price changes go to the chart: 3,399 then 3,199.
    assert html.count("&quot;price&quot;") == 2
    # The history speaks: a 10-day low, reached by one cut.
    assert '<li data-insight="low" data-days="10">10 დღის ყველაზე დაბალი ფასი</li>' in html
    assert 'data-insight="moves" data-days="10" data-up="0" data-down="1">ბოლო 10 დღეში 1-ჯერ გაიაფდა</li>' in html


@pytest.mark.asyncio
async def test_headline_lists_every_stores_price_with_its_gap(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    _, product = await create_admin_product(client, session_factory)
    await _priced_product(session_factory, product["id"])
    async with session_factory() as session:
        store = Store(title="Store B", web_url="https://b.example")
        session.add(store)
        await session.flush()
        session.add(ProductListing(
            product_id=product["id"], store_id=store.id, product_url="https://b.example/phone",
            current_price=Decimal("3349.00"), currency="GEL", is_available=True,
            last_checked_at=datetime.now(UTC),
        ))
        await session.commit()

    html = (await client.get("/")).text

    table = html[html.index('<table class="intro-stores"'):html.index("</table>")]
    assert "<caption>iPhone 17 Pro 256GB</caption>" in table
    assert table.index("Store A") < table.index("Store B")
    assert '<td class="intro-store-gap best" data-i18n="intro.cheapest">ყველაზე იაფი</td>' in table
    assert '<td class="intro-store-price">3,349 ₾</td><td class="intro-store-gap">+150 ₾</td>' in table
    # Cheapest sits at the left of today's spread, priciest at the right.
    assert table.count('style="--pos:0%"') == 1
    assert table.count('style="--pos:100%"') == 1
    # Each row opens that store's own page for the phone.
    assert '<a class="store-go" href="https://b.example/phone" target="_blank"' in table


@pytest.mark.asyncio
async def test_headline_hides_the_price_line_without_history(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    _, product = await create_admin_product(client, session_factory)
    await _priced_product(session_factory, product["id"])

    html = (await client.get("/")).text

    assert '<figure class="intro-trend" id="introTrend" hidden></figure>' in html


def test_prices_are_whole_lari_and_drops_show_a_percentage() -> None:
    from app.api.pages import _model_row, _price
    from app.db.db_schemas import ProductSummary

    assert _price(Decimal("5999.99")) == "6,000 ₾"
    assert _price(Decimal("8339")) == "8,339 ₾"
    product = ProductSummary(
        id=1,
        brand="Apple",
        model="iPhone 18 Pro",
        storage="256GB",
        color="Black",
        image_url=None,
        lowest_price=Decimal("6369"),
        lowest_price_store="Zoommer",
        price_week_ago=Decimal("6999"),
        currency="GEL",
        listing_count=2,
        available_listing_count=2,
    )

    row = _model_row(product, hidden=False)

    assert "Zoommer" not in row
    assert "2 მაღაზია" in row
    assert '<span class="change-pill drop">−630 ₾ · −9%</span>' in row


@pytest.mark.asyncio
async def test_headline_names_the_store_that_cuts_prices_on_one_weekday(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    _, product = await create_admin_product(client, session_factory)
    await _priced_product(session_factory, product["id"])
    # Noon UTC on each of the last four Fridays (afternoon in Tbilisi): a raise, then a cut that day.
    today = datetime.now(UTC).replace(hour=12, minute=0, second=0, microsecond=0)
    last_friday = today - timedelta(days=(today.weekday() - 4) % 7 or 7)
    async with session_factory() as session:
        listing_id = await session.scalar(select(ProductListing.id))
        for week in range(4):
            friday = last_friday - timedelta(weeks=week)
            session.add_all([
                PriceHist(listing_id=listing_id, price=Decimal("3399.00"), recorded_at=friday - timedelta(hours=2)),
                PriceHist(listing_id=listing_id, price=Decimal("3199.00"), recorded_at=friday),
            ])
        await session.commit()

    html = (await client.get("/")).text

    assert '<li data-insight="weekday" data-store="Store A" data-day="4">Store A ფასებს ჩვეულებრივ პარასკევობით აკლებს</li>' in html


def test_store_logos_and_row_photos() -> None:
    from app.api.pages import _row_photo, _store_logo

    # Every tracked store's saved icon is found by its name; an unknown store gets none.
    for store in ("Zoommer", "Alta", "iSpace", "Elit Electronics", "Megatechnica", "Extra.ge",
                  "PCShop", "Metromart", "Gstore", "Kontakt", "iCity"):
        assert "/static/img/stores/" in _store_logo(store), store
    assert _store_logo("Store B") == ""
    assert '<img class="store-logo" src="/static/img/stores/extra-ge.png"' in _store_logo("Extra.ge")

    assert _row_photo(None) == '<span class="row-photo"></span>'
    assert _row_photo("javascript:alert(1)") == '<span class="row-photo"></span>'
    assert 'src="https://cdn.example/a.webp?x=1&amp;y=2"' in _row_photo("https://cdn.example/a.webp?x=1&y=2")
