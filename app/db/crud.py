from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.db_schemas import (
    PriceHistCreate,
    ProductCreate,
    ProductListingCreate,
    StoreCreate,
)

#impts
from app.db.models import CrawlRun, PriceHist, Product, ProductListing, Store
from app.services.normalization import (
    normalize_color,
    normalize_optional_text,
    normalize_storage,
    normalize_text,
    product_identity_key,
)


@dataclass(frozen=True, slots=True)
class ListingUpsertResult:
    listing: ProductListing
    created: bool
    price_recorded: bool


def _normalize_currency(currency: str) -> str:
    return currency.strip().upper()


async def get_store(session: AsyncSession, store_id: int) -> Store | None:
    return await session.get(Store, store_id)


async def get_store_by_title(session: AsyncSession, title: str) -> Store | None:
    statement = select(Store).where(Store.title == title.strip())
    return await session.scalar(statement)


async def create_store(session: AsyncSession, store_data: StoreCreate) -> Store:
    store = Store(title=store_data.title, web_url=store_data.web_url)
    session.add(store)
    await session.flush()
    return store


async def get_or_create_store(session: AsyncSession, store_data: StoreCreate) -> Store:
    statement = (
        insert(Store)
        .values(title=store_data.title, web_url=store_data.web_url)
        .on_conflict_do_nothing()
        .returning(Store)
    )
    store = await session.scalar(statement)

    if store is None:
        store = await get_store_by_title(session, store_data.title)

    if store is None:
        raise RuntimeError("Store upsert completed without returning a row")

    return store


async def get_product(session: AsyncSession, product_id: int) -> Product | None:
    return await session.get(Product, product_id)


async def get_product_by_details(
    session: AsyncSession,
    *,
    brand: str,
    model: str,
    storage: str | None = None,
    color: str | None = None,
) -> Product | None:
    statement = select(Product).where(
        Product.identity_key
        == product_identity_key(brand, model, storage, color)
    )
    return await session.scalar(statement)


async def create_product(session: AsyncSession, product_data: ProductCreate) -> Product:
    product = Product(
        brand=normalize_text(product_data.brand),
        model=normalize_text(product_data.model),
        storage=normalize_storage(product_data.storage),
        color=normalize_color(product_data.color),
        identity_key=product_identity_key(
            product_data.brand,
            product_data.model,
            product_data.storage,
            product_data.color,
        ),
    )
    session.add(product)
    await session.flush()
    return product


async def get_or_create_product(
    session: AsyncSession,
    product_data: ProductCreate,
) -> Product:
    statement = (
        insert(Product)
        .values(
            brand=normalize_text(product_data.brand),
            model=normalize_text(product_data.model),
            storage=normalize_storage(product_data.storage),
            color=normalize_color(product_data.color),
            identity_key=product_identity_key(
                product_data.brand,
                product_data.model,
                product_data.storage,
                product_data.color,
            ),
            is_active=True,
        )
        .on_conflict_do_nothing()
        .returning(Product)
    )
    product = await session.scalar(statement)

    if product is None:
        product = await get_product_by_details(
            session,
            brand=product_data.brand,
            model=product_data.model,
            storage=product_data.storage,
            color=product_data.color,
        )

    if product is None:
        raise RuntimeError("Product upsert completed without returning a row")

    return product


async def get_crawl_run(
    session: AsyncSession,
    crawl_run_id: int,
) -> CrawlRun | None:
    return await session.get(CrawlRun, crawl_run_id)


async def last_succeeded_products_found(
    session: AsyncSession,
    store_id: int,
) -> int | None:
    statement = (
        select(CrawlRun.products_found)
        .where(CrawlRun.store_id == store_id, CrawlRun.status == "succeeded")
        .order_by(CrawlRun.started_at.desc())
        .limit(1)
    )
    return await session.scalar(statement)


async def create_crawl_run(session: AsyncSession, store_id: int) -> CrawlRun:
    crawl_run = CrawlRun(
        store_id=store_id,
        status="running",
        started_at=datetime.now(UTC),
        products_found=0,
        products_ingested=0,
    )
    session.add(crawl_run)
    await session.flush()
    return crawl_run


async def complete_crawl_run(
    session: AsyncSession,
    crawl_run_id: int,
    *,
    products_found: int,
    products_ingested: int,
) -> CrawlRun:
    crawl_run = await get_crawl_run(session, crawl_run_id)

    if crawl_run is None:
        raise LookupError(f"Crawl run {crawl_run_id} does not exist")

    crawl_run.status = "succeeded"
    crawl_run.finished_at = datetime.now(UTC)
    crawl_run.products_found = products_found
    crawl_run.products_ingested = products_ingested
    crawl_run.error_message = None
    await session.flush()
    return crawl_run


async def fail_crawl_run(
    session: AsyncSession,
    crawl_run_id: int,
    error: Exception,
    *,
    products_found: int = 0,
) -> CrawlRun:
    crawl_run = await get_crawl_run(session, crawl_run_id)

    if crawl_run is None:
        raise LookupError(f"Crawl run {crawl_run_id} does not exist")

    crawl_run.status = "failed"
    crawl_run.finished_at = datetime.now(UTC)
    crawl_run.products_found = products_found
    crawl_run.products_ingested = 0
    crawl_run.error_message = f"{type(error).__name__}: {error}"[:2000]
    await session.flush()
    return crawl_run


async def get_product_listing(
    session: AsyncSession,
    listing_id: int,
) -> ProductListing | None:
    return await session.get(ProductListing, listing_id)


async def get_listing_by_store_product(
    session: AsyncSession,
    *,
    store_id: int,
    product_id: int,
) -> ProductListing | None:
    statement = select(ProductListing).where(
        ProductListing.store_id == store_id,
        ProductListing.product_id == product_id,
    )
    return await session.scalar(statement)


async def create_product_listing(
    session: AsyncSession,
    listing_data: ProductListingCreate,
) -> ProductListing:
    listing = ProductListing(
        store_id=listing_data.store_id,
        product_id=listing_data.product_id,
        product_url=listing_data.product_url,
        current_price=listing_data.current_price,
        currency=_normalize_currency(listing_data.currency),
        last_checked_at=datetime.now(UTC),
        is_active=True,
        is_available=listing_data.is_available,
        last_seen_at=listing_data.last_seen_at or datetime.now(UTC),
        variant_name=normalize_optional_text(listing_data.variant_name),
        external_product_id=normalize_optional_text(listing_data.external_product_id),
    )
    session.add(listing)
    await session.flush()
    return listing


async def create_price_history(
    session: AsyncSession,
    price_history_data: PriceHistCreate,
) -> PriceHist:
    price_history = PriceHist(
        listing_id=price_history_data.listing_id,
        price=price_history_data.price,
        currency=_normalize_currency(price_history_data.currency),
        is_available=price_history_data.is_available,
        recorded_at=datetime.now(UTC),
    )
    session.add(price_history)
    await session.flush()
    return price_history


async def upsert_product_listing(
    session: AsyncSession,
    listing_data: ProductListingCreate,
    *,
    record_unchanged_price: bool = False,
) -> ListingUpsertResult:
    listing = await get_listing_by_store_product(
        session,
        store_id=listing_data.store_id,
        product_id=listing_data.product_id,
    )
    price = Decimal(listing_data.current_price)
    currency = _normalize_currency(listing_data.currency)

    if listing is None:
        listing = await create_product_listing(session, listing_data)
        await create_price_history(
            session,
            PriceHistCreate(
                listing_id=listing.id,
                price=price,
                currency=currency,
                is_available=listing_data.is_available,
            ),
        )
        return ListingUpsertResult(
            listing=listing,
            created=True,
            price_recorded=True,
        )

    price_changed = listing.current_price != price or listing.currency != currency
    listing.product_url = listing_data.product_url
    listing.current_price = price
    listing.currency = currency
    listing.last_checked_at = datetime.now(UTC)
    listing.is_active = True
    listing.is_available = listing_data.is_available
    listing.last_seen_at = listing_data.last_seen_at or datetime.now(UTC)
    listing.variant_name = normalize_optional_text(listing_data.variant_name)
    listing.external_product_id = normalize_optional_text(
        listing_data.external_product_id
    )

    if price_changed or record_unchanged_price:
        await create_price_history(
            session,
            PriceHistCreate(
                listing_id=listing.id,
                price=price,
                currency=currency,
                is_available=listing_data.is_available,
            ),
        )

    await session.flush()
    return ListingUpsertResult(
        listing=listing,
        created=False,
        price_recorded=price_changed or record_unchanged_price,
    )


async def list_product_listings(
    session: AsyncSession,
    *,
    store_id: int | None = None,
    product_id: int | None = None,
) -> list[ProductListing]:
    statement = select(ProductListing).options(
        selectinload(ProductListing.store),
        selectinload(ProductListing.product),
    )

    if store_id is not None:
        statement = statement.where(ProductListing.store_id == store_id)

    if product_id is not None:
        statement = statement.where(ProductListing.product_id == product_id)

    return list(await session.scalars(statement))


async def list_price_history(
    session: AsyncSession,
    listing_id: int,
) -> list[PriceHist]:
    statement = (
        select(PriceHist)
        .where(PriceHist.listing_id == listing_id)
        .order_by(PriceHist.recorded_at.desc())
    )
    return list(await session.scalars(statement))
