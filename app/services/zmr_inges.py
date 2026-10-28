import asyncio
import logging
from collections.abc import Awaitable, Callable, Iterable, Mapping
from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.crud import (
    complete_crawl_run,
    create_crawl_run,
    fail_crawl_run,
    get_or_create_product,
    get_or_create_store,
    last_succeeded_products_found,
    upsert_product_listing,
)
from app.db.db_schemas import ProductCreate, ProductListingCreate, StoreCreate
from app.db.sess import SESSION
from app.scraper.scrape_alta import (
    ALTA_IPHONE_URL,
    scrape_alta,
)
from app.scraper.scrape_alta import (
    BASE_URL as ALTA_BASE_URL,
)
from app.scraper.scrape_ispace import BASE_URL as ISPACE_BASE_URL
from app.scraper.scrape_ispace import scrape_ispace
from app.scraper.scrape_zoommer import BASE_URL, scrape_zoommer
from app.services.alert_service import check_and_send_alert_notifications
from app.services.errors import EmptyScrapeError, RefreshInProgressError

LOGGER = logging.getLogger(__name__)
# Warn when a crawl finds less than this share of the previous successful crawl.
SCRAPE_DROP_WARNING_RATIO = 0.5


@dataclass(frozen=True, slots=True)
class IngestionSummary:
    scraped: int
    ingested: int
    crawl_run_id: int | None = None
    listings_created: int = 0
    listings_updated: int = 0
    prices_recorded: int = 0
    crawl_run_ids: tuple[int, ...] = ()


def _required_text(item: Mapping[str, object], key: str) -> str:
    value = item.get(key)

    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Scraped product has no valid {key!r}: {item!r}")

    return value.strip()


def _optional_text(item: Mapping[str, object], key: str) -> str | None:
    value = item.get(key)

    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"Scraped product has an invalid {key!r}: {item!r}")

    return value.strip() or None


def _price(item: Mapping[str, object]) -> Decimal:
    value = item.get("price")

    try:
        price = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError(f"Scraped product has an invalid price: {item!r}") from None

    if not price.is_finite() or price <= 0:
        raise ValueError(f"Scraped product has an invalid price: {item!r}")

    return price


def _product_create(item: Mapping[str, object]) -> ProductCreate:
    brand = _optional_text(item, "brand") or "Apple"
    model = _optional_text(item, "model") or _required_text(item, "name")

    return ProductCreate(
        brand=brand,
        model=model,
        storage=_optional_text(item, "storage"),
        color=_optional_text(item, "color"),
    )


async def _ingest_store(
    session: AsyncSession,
    *,
    store_title: str,
    store_url: str,
    scraped_products: Iterable[Mapping[str, object]] | None = None,
) -> IngestionSummary:
    products = list(scraped_products) if scraped_products is not None else []

    if not products:
        return IngestionSummary(scraped=0, ingested=0)

    store = await get_or_create_store(
        session,
        StoreCreate(title=store_title, web_url=store_url),
    )

    listings_created = 0
    listings_updated = 0
    prices_recorded = 0

    for item in products:
        product = await get_or_create_product(session, _product_create(item))
        image_url = _optional_text(item, "image_url")
        if image_url:
            product.image_url = image_url
        result = await upsert_product_listing(
            session,
            ProductListingCreate(
                store_id=store.id,
                product_id=product.id,
                product_url=_required_text(item, "url"),
                current_price=_price(item),
                currency=_optional_text(item, "currency") or "GEL",
                is_available=(
                    item.get("is_available")
                    if isinstance(item.get("is_available"), bool)
                    else True
                ),
                external_product_id=(
                    str(item["external_product_id"])
                    if item.get("external_product_id") is not None
                    else None
                ),
            ),
        )
        listings_created += int(result.created)
        listings_updated += int(not result.created)
        prices_recorded += int(result.price_recorded)

    return IngestionSummary(
        scraped=len(products),
        ingested=len(products),
        listings_created=listings_created,
        listings_updated=listings_updated,
        prices_recorded=prices_recorded,
    )


async def ingest_zoommer(
    session: AsyncSession,
    scraped_products: Iterable[Mapping[str, object]] | None = None,
) -> IngestionSummary:
    products = (
        list(scraped_products)
        if scraped_products is not None
        else await scrape_zoommer()
    )
    return await _ingest_store(
        session,
        store_title="Zoommer",
        store_url=BASE_URL,
        scraped_products=products,
    )


async def ingest_alta(
    session: AsyncSession,
    scraped_products: Iterable[Mapping[str, object]] | None = None,
) -> IngestionSummary:
    products = (
        list(scraped_products)
        if scraped_products is not None
        else await asyncio.to_thread(scrape_alta, ALTA_IPHONE_URL)
    )
    return await _ingest_store(
        session,
        store_title="Alta",
        store_url=ALTA_BASE_URL,
        scraped_products=products,
    )


async def _run_store_ingestion(
    store_title: str,
    store_url: str,
    scrape_products: Callable[[], Awaitable[list[dict[str, object]]]],
) -> IngestionSummary:
    async with SESSION() as session:
        try:
            async with session.begin():
                store = await get_or_create_store(
                    session,
                    StoreCreate(title=store_title, web_url=store_url),
                )
                previous_found = await last_succeeded_products_found(
                    session, store.id
                )
                crawl_run = await create_crawl_run(session, store.id)
                crawl_run_id = crawl_run.id
        except IntegrityError as error:
            raise RefreshInProgressError(
                f"A {store_title} refresh is already running"
            ) from error

        products_found = 0

        try:
            scraped_products = await scrape_products()
            products_found = len(scraped_products)
            if not products_found:
                raise EmptyScrapeError(
                    f"{store_title} scraper returned no products; "
                    "the store page layout may have changed"
                )
            if (
                previous_found
                and products_found < previous_found * SCRAPE_DROP_WARNING_RATIO
            ):
                LOGGER.warning(
                    "%s scraper found %d products, down from %d last run; "
                    "the store page layout may have changed",
                    store_title,
                    products_found,
                    previous_found,
                )

            async with session.begin():
                summary = await _ingest_store(
                    session,
                    store_title=store_title,
                    store_url=store_url,
                    scraped_products=scraped_products,
                )
                await complete_crawl_run(
                    session,
                    crawl_run_id,
                    products_found=summary.scraped,
                    products_ingested=summary.ingested,
                )

            async with session.begin():
                await check_and_send_alert_notifications(session)

            return IngestionSummary(
                scraped=summary.scraped,
                ingested=summary.ingested,
                crawl_run_id=crawl_run_id,
                listings_created=summary.listings_created,
                listings_updated=summary.listings_updated,
                prices_recorded=summary.prices_recorded,
                crawl_run_ids=(crawl_run_id,),
            )
        except Exception as error:
            if session.in_transaction():
                await session.rollback()

            async with session.begin():
                await fail_crawl_run(
                    session,
                    crawl_run_id,
                    error,
                    products_found=products_found,
                )

            raise


async def run_zoommer_ingestion() -> IngestionSummary:
    return await _run_store_ingestion("Zoommer", BASE_URL, scrape_zoommer)


async def run_alta_ingestion() -> IngestionSummary:
    async def scrape_in_worker() -> list[dict[str, object]]:
        return await asyncio.to_thread(scrape_alta, ALTA_IPHONE_URL)

    return await _run_store_ingestion(
        "Alta",
        ALTA_BASE_URL,
        scrape_in_worker,
    )


async def run_ispace_ingestion() -> IngestionSummary:
    return await _run_store_ingestion("iSpace", ISPACE_BASE_URL, scrape_ispace)


async def main() -> None:
    summary = await run_zoommer_ingestion()
    print(asdict(summary))


if __name__ == "__main__":
    asyncio.run(main())
