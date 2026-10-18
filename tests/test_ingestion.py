from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import PriceHist, Product, ProductListing, Store
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