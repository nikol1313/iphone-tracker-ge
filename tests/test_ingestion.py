from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import CrawlRun, PriceHist, Product, ProductListing, Store
from app.services import zmr_inges
from app.services.errors import EmptyScrapeError
from app.services.zmr_inges import ingest_alta, ingest_zoommer


@pytest.mark.asyncio
async def test_ingests_shared_product_for_zoommer_and_alta(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    product = {
        "name": "Apple iPhone 17 Pro 256GB Black",
        "brand": "Apple",
        "model": "iPhone 17 Pro",
        "storage": "256GB",
        "color": "Black",
        "price": 4299,
        "url": "https://example.com/iphone-17-pro",
    }

    async with session_factory() as session, session.begin():
        zoommer_summary = await ingest_zoommer(session, [product])
        alta_summary = await ingest_alta(session, [product])

        assert zoommer_summary.listings_created == 1
        assert alta_summary.listings_created == 1

    async with session_factory() as session:
        assert await session.scalar(select(func.count(Product.id))) == 1
        assert await session.scalar(select(func.count(ProductListing.id))) == 2
        assert await session.scalar(select(func.count(PriceHist.id))) == 2

        stores = set((await session.scalars(select(Store.title))).all())
        assert stores == {"Zoommer", "Alta"}

        listings = (await session.scalars(select(ProductListing))).all()
        assert {listing.current_price for listing in listings} == {Decimal("4299.00")}

PRODUCT = {
    "name": "Apple iPhone 17 Pro 256GB Black",
    "model": "iPhone 17 Pro",
    "storage": "256GB",
    "color": "Black",
    "price": 4299,
    "url": "https://example.com/iphone-17-pro",
}


def scraper_returning(*products: dict):
    async def scrape() -> list[dict[str, object]]:
        return [dict(product, url=f"{product['url']}-{i}") for i, product in enumerate(products)]

    return scrape


@pytest.mark.asyncio
async def test_empty_scrape_fails_crawl_run(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(zmr_inges, "SESSION", session_factory)

    with pytest.raises(EmptyScrapeError):
        await zmr_inges._run_store_ingestion(
            "Zoommer", "https://zoommer.ge", scraper_returning()
        )

    async with session_factory() as session:
        run = await session.scalar(select(CrawlRun))
        assert run.status == "failed"
        assert "no products" in run.error_message


@pytest.mark.asyncio
async def test_sharp_drop_in_scraped_products_logs_warning(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setattr(zmr_inges, "SESSION", session_factory)
    await zmr_inges._run_store_ingestion(
        "Zoommer", "https://zoommer.ge", scraper_returning(*[PRODUCT] * 4)
    )

    summary = await zmr_inges._run_store_ingestion(
        "Zoommer", "https://zoommer.ge", scraper_returning(PRODUCT)
    )

    assert summary.scraped == 1
    assert "down from 4 last run" in caplog.text


@pytest.mark.asyncio
async def test_retailer_titles_merge_into_one_product(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session, session.begin():
        await ingest_zoommer(
            session,
            [
                {
                    "name": "Apple iPhone 17 | 256GB Sage",
                    "price": 2969,
                    "url": "https://zoommer.example/iphone-17-sage",
                },
            ],
        )
        await ingest_alta(
            session,
            [
                {
                    "name": "Apple iPhone 17 (8GB/256GB) - Sage",
                    "price": 2849,
                    "url": "https://alta.example/iphone-17-sage",
                },
                # A second Alta listing of the same phone keeps only the cheaper offer.
                {
                    "name": "Apple iPhone 17 8GB/256GB Sage",
                    "price": 2899,
                    "url": "https://alta.example/iphone-17-sage-2",
                },
            ],
        )

    async with session_factory() as session:
        products = list(await session.scalars(select(Product)))
        listings = list(
            await session.scalars(select(ProductListing).order_by(ProductListing.id))
        )

    assert [(p.model, p.storage, p.color) for p in products] == [
        ("iPhone 17", "256GB", "Sage")
    ]
    assert [(listing.current_price, listing.variant_name) for listing in listings] == [
        (Decimal("2969.00"), "Apple iPhone 17 | 256GB Sage"),
        (Decimal("2849.00"), "Apple iPhone 17 (8GB/256GB) - Sage"),
    ]


@pytest.mark.asyncio
async def test_renamed_listing_moves_to_new_product_with_its_history(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    def item(name: str, price: int) -> dict:
        return {
            "name": name,
            "price": price,
            "url": "https://zoommer.example/p1",
            "external_product_id": "p1",
        }

    async with session_factory() as session, session.begin():
        await ingest_zoommer(session, [item("Apple iPhone 17 | 256GB Sage", 2969)])
    # The store fixes a wrong color in its title; the store's id stays the same.
    async with session_factory() as session, session.begin():
        await ingest_zoommer(session, [item("Apple iPhone 17 | 256GB Lavender", 2899)])

    async with session_factory() as session:
        listings = list(await session.scalars(select(ProductListing)))
        history = list(await session.scalars(select(PriceHist)))
        product = await session.get(Product, listings[0].product_id)

    assert len(listings) == 1
    assert product.color == "Lavender"
    assert listings[0].current_price == Decimal("2899.00")
    assert len(history) == 2


@pytest.mark.asyncio
async def test_store_id_taken_from_merged_listing(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session, session.begin():
        await ingest_zoommer(
            session,
            [
                {
                    "name": "Apple iPhone 17 | 256GB Sage",
                    "price": 2969,
                    "url": "https://zoommer.example/sage",
                    "external_product_id": "sage",
                },
                {
                    "name": "Apple iPhone 17 | 256GB Lavender",
                    "price": 2969,
                    "url": "https://zoommer.example/lavender",
                    "external_product_id": "lavender",
                },
            ],
        )
    # The "sage" store item is retitled to Lavender; both now describe one phone.
    async with session_factory() as session, session.begin():
        await ingest_zoommer(
            session,
            [
                {
                    "name": "Apple iPhone 17 | 256GB Lavender",
                    "price": 2799,
                    "url": "https://zoommer.example/sage",
                    "external_product_id": "sage",
                },
            ],
        )

    async with session_factory() as session:
        listings = {
            listing.external_product_id: listing
            for listing in await session.scalars(select(ProductListing))
        }

    assert listings["sage"].current_price == Decimal("2799.00")
    assert listings["sage"].is_active
    assert not listings[None].is_active
