from collections import defaultdict
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from statistics import median

from sqlalchemy import Select, and_, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.db_schemas import (
    Page,
    PriceExtremesResponse,
    PriceHistoryResponse,
    ProductCreate,
    ProductListingResponse,
    ProductSummary,
    ProductUpdate,
)
from app.db.models import PriceHist, Product, ProductListing, Store
from app.services.errors import ConflictError, NotFoundError
from app.services.normalization import (
    normalize_color,
    normalize_storage,
    normalize_text,
    product_identity_key,
)

PRICE_TREND_WINDOW = timedelta(days=7)
# The Today page's "last 24 hours" list.
RECENT_CHANGE_WINDOW = timedelta(hours=24)
# "Buy now or wait?" looks at the best price over this window...
VERDICT_WINDOW = timedelta(days=90)
# ...once there is this much history: fewer days can't tell a deal from a normal price.
VERDICT_MIN_HISTORY = timedelta(days=14)
# Within 2% of the window's low is "at its low"; 5% off the typical price is a real move.
NEAR_LOW = Decimal("1.02")
GOOD_BELOW_TYPICAL = Decimal("0.95")
WAIT_ABOVE_TYPICAL = Decimal("1.05")
CENT = Decimal("0.01")

# (listing_id, price, is_available, recorded_at), oldest first.
PriceEvent = tuple[int, Decimal, bool, datetime]


def daily_best_prices(
    events: list[PriceEvent], now: datetime, window: timedelta = VERDICT_WINDOW
) -> list[Decimal]:
    """Cheapest in-stock price at the end of each day in the window, and now.

    A listing keeps its last recorded price and stock until its next record.
    """
    if not events:
        return []
    start = max(now - window, events[0][3])
    days = (now - start).days
    checkpoints = [start + timedelta(days=day) for day in range(1, days + 1)] + [now]
    latest: dict[int, tuple[Decimal, bool]] = {}
    best: list[Decimal] = []
    index = 0
    for checkpoint in checkpoints:
        while index < len(events) and events[index][3] <= checkpoint:
            listing_id, price, available, _ = events[index]
            latest[listing_id] = (price, available)
            index += 1
        in_stock = [price for price, available in latest.values() if available]
        if in_stock:
            best.append(min(in_stock))
    return best


def price_verdict(
    current: Decimal | None,
    daily_best: list[Decimal],
    tracked_since: datetime | None,
    now: datetime,
) -> str | None:
    """good: at its recent low or well under its typical price; wait: well above it."""
    if (
        current is None
        or not daily_best
        or tracked_since is None
        or now - tracked_since < VERDICT_MIN_HISTORY
    ):
        return None
    typical = median(daily_best)
    low = min(daily_best)
    # A price that never moved is "normal", not a deal.
    if current <= typical * GOOD_BELOW_TYPICAL or (low < typical and current <= low * NEAR_LOW):
        return "good"
    if current >= typical * WAIT_ABOVE_TYPICAL:
        return "wait"
    return "normal"


def _lowest_price_expression():
    available = (
        select(ProductListing.current_price)
        .where(
            ProductListing.product_id == Product.id,
            ProductListing.is_active.is_(True),
            ProductListing.is_available.is_(True),
        )
        .order_by(ProductListing.current_price, ProductListing.id)
        .limit(1)
        .correlate(Product)
        .scalar_subquery()
    )
    last_listed = (
        select(ProductListing.current_price)
        .where(
            ProductListing.product_id == Product.id,
            ProductListing.is_active.is_(True),
        )
        .order_by(ProductListing.current_price, ProductListing.id)
        .limit(1)
        .correlate(Product)
        .scalar_subquery()
    )
    return func.coalesce(available, last_listed)


def _lowest_currency_expression():
    available = (
        select(ProductListing.currency)
        .where(
            ProductListing.product_id == Product.id,
            ProductListing.is_active.is_(True),
            ProductListing.is_available.is_(True),
        )
        .order_by(ProductListing.current_price, ProductListing.id)
        .limit(1)
        .correlate(Product)
        .scalar_subquery()
    )
    last_listed = (
        select(ProductListing.currency)
        .where(
            ProductListing.product_id == Product.id,
            ProductListing.is_active.is_(True),
        )
        .order_by(ProductListing.current_price, ProductListing.id)
        .limit(1)
        .correlate(Product)
        .scalar_subquery()
    )
    return func.coalesce(available, last_listed)


def _listing_count_expression():
    return (
        select(func.count(ProductListing.id))
        .where(
            ProductListing.product_id == Product.id,
            ProductListing.is_active.is_(True),
        )
        .correlate(Product)
        .scalar_subquery()
    )


def _available_listing_count_expression():
    return (
        select(func.count(ProductListing.id))
        .where(
            ProductListing.product_id == Product.id,
            ProductListing.is_active.is_(True),
            ProductListing.is_available.is_(True),
        )
        .correlate(Product)
        .scalar_subquery()
    )


def _highest_available_price_expression():
    # Paired with the lowest price, shows how much choosing the right store saves.
    return (
        select(func.max(ProductListing.current_price))
        .where(
            ProductListing.product_id == Product.id,
            ProductListing.is_active.is_(True),
            ProductListing.is_available.is_(True),
            ProductListing.currency == _lowest_currency_expression(),
        )
        .correlate(Product)
        .scalar_subquery()
    )


def _lowest_installment_expression():
    return (
        select(func.min(ProductListing.installment_monthly))
        .where(
            ProductListing.product_id == Product.id,
            ProductListing.is_active.is_(True),
            ProductListing.is_available.is_(True),
        )
        .correlate(Product)
        .scalar_subquery()
    )


def product_summary_select() -> Select:
    return select(
        Product,
        _lowest_price_expression().label("lowest_price"),
        _lowest_currency_expression().label("currency"),
        _listing_count_expression().label("listing_count"),
        _available_listing_count_expression().label("available_listing_count"),
        _highest_available_price_expression().label("highest_price"),
        _lowest_installment_expression().label("lowest_installment_monthly"),
    )


def product_summary(
    product: Product,
    lowest_price: Decimal | None,
    currency: str | None,
    listing_count: int,
    available_listing_count: int,
    highest_price: Decimal | None = None,
    lowest_installment_monthly: Decimal | None = None,
) -> ProductSummary:
    return ProductSummary(
        id=product.id,
        brand=product.brand,
        model=product.model,
        storage=product.storage,
        color=product.color,
        image_url=product.image_url,
        lowest_price=lowest_price,
        currency=currency,
        listing_count=listing_count,
        available_listing_count=available_listing_count,
        highest_price=highest_price,
        lowest_installment_monthly=lowest_installment_monthly,
    )


async def with_price_trends(
    session: AsyncSession,
    summaries: list[ProductSummary],
) -> list[ProductSummary]:
    if not summaries:
        return summaries
    rows = (
        await session.execute(
            select(
                ProductListing.product_id,
                PriceHist.listing_id,
                PriceHist.price,
                PriceHist.currency,
                PriceHist.is_available,
                PriceHist.recorded_at,
            )
            .join(ProductListing, ProductListing.id == PriceHist.listing_id)
            .where(
                ProductListing.product_id.in_([summary.id for summary in summaries]),
                ProductListing.is_active.is_(True),
            )
            .order_by(PriceHist.recorded_at, PriceHist.id)
        )
    ).all()
    currencies = {summary.id: summary.currency for summary in summaries}
    now = datetime.now(UTC)
    cutoff = now - PRICE_TREND_WINDOW
    day_cutoff = now - RECENT_CHANGE_WINDOW
    prices: dict[int, list[Decimal]] = defaultdict(list)
    events: dict[int, list[PriceEvent]] = defaultdict(list)
    # Per product, each listing's latest price at the cutoff (rows are time-ordered).
    at_cutoff: dict[int, dict[int, Decimal]] = defaultdict(dict)
    at_day_cutoff: dict[int, dict[int, Decimal]] = defaultdict(dict)
    for product_id, listing_id, price, currency, available, recorded_at in rows:
        if currency != currencies[product_id]:
            continue
        prices[product_id].append(price)
        if recorded_at.tzinfo is None:
            recorded_at = recorded_at.replace(tzinfo=UTC)
        events[product_id].append((listing_id, price, available, recorded_at))
        if recorded_at <= cutoff:
            at_cutoff[product_id][listing_id] = price
        if recorded_at <= day_cutoff:
            at_day_cutoff[product_id][listing_id] = price

    updated = []
    for summary in summaries:
        history = events[summary.id]
        tracked_since = history[0][3] if history else None
        daily_best = daily_best_prices(history, now)
        current = summary.lowest_price if summary.available_listing_count else None
        verdict = price_verdict(current, daily_best, tracked_since, now)
        updated.append(
            summary.model_copy(
                update={
                    "price_day_ago": min(at_day_cutoff[summary.id].values(), default=None),
                    "price_week_ago": min(at_cutoff[summary.id].values(), default=None),
                    "lowest_price_ever": min(prices[summary.id], default=None),
                    "highest_price_ever": max(prices[summary.id], default=None),
                    "price_verdict": verdict,
                    "typical_price": median(daily_best).quantize(CENT) if verdict else None,
                    "recent_low_price": min(daily_best) if verdict else None,
                    "price_tracked_since": tracked_since,
                }
            )
        )
    return updated


async def require_active_product(
    session: AsyncSession,
    product_id: int,
) -> Product:
    product = await session.scalar(
        select(Product).where(
            Product.id == product_id,
            Product.is_active.is_(True),
        )
    )
    if product is None:
        raise NotFoundError("Product not found")
    return product


async def create_product(
    session: AsyncSession,
    data: ProductCreate,
) -> ProductSummary:
    product = Product(
        brand=normalize_text(data.brand),
        model=normalize_text(data.model),
        storage=normalize_storage(data.storage),
        color=normalize_color(data.color),
        identity_key=product_identity_key(
            data.brand,
            data.model,
            data.storage,
            data.color,
        ),
    )
    try:
        async with session.begin_nested():
            session.add(product)
            await session.flush()
    except IntegrityError as error:
        raise ConflictError("A product with this identity already exists") from error
    return product_summary(product, None, None, 0, 0)


def _apply_product_filters(
    statement: Select,
    *,
    brand: str | None,
    model: str | None,
    storage: str | None,
    color: str | None,
    include_inactive: bool,
) -> Select:
    if not include_inactive:
        statement = statement.where(Product.is_active.is_(True))
    if brand is not None:
        statement = statement.where(
            func.lower(Product.brand) == normalize_text(brand).casefold()
        )
    if model is not None:
        statement = statement.where(
            func.lower(Product.model) == normalize_text(model).casefold()
        )
    if storage is not None:
        statement = statement.where(Product.storage == normalize_storage(storage))
    if color is not None:
        statement = statement.where(
            func.lower(Product.color) == normalize_text(color).casefold()
        )
    return statement


async def list_products(
    session: AsyncSession,
    *,
    brand: str | None,
    model: str | None,
    storage: str | None,
    color: str | None,
    include_inactive: bool,
    limit: int,
    offset: int,
) -> Page[ProductSummary]:
    filtered = _apply_product_filters(
        select(Product),
        brand=brand,
        model=model,
        storage=storage,
        color=color,
        include_inactive=include_inactive,
    )
    total = int(
        await session.scalar(
            select(func.count()).select_from(filtered.subquery())
        )
        or 0
    )
    statement = _apply_product_filters(
        product_summary_select(),
        brand=brand,
        model=model,
        storage=storage,
        color=color,
        include_inactive=include_inactive,
    ).order_by(
        func.lower(Product.brand),
        func.lower(Product.model),
        Product.id,
    )
    rows = (await session.execute(statement.limit(limit).offset(offset))).all()
    return Page(
        items=await with_price_trends(
            session,
            [
                product_summary(*row)
                for row in rows
            ],
        ),
        total=total,
        limit=limit,
        offset=offset,
    )


async def get_product_summary(
    session: AsyncSession,
    product_id: int,
) -> ProductSummary:
    row = (
        await session.execute(
            product_summary_select().where(
                Product.id == product_id,
                Product.is_active.is_(True),
            )
        )
    ).one_or_none()
    if row is None:
        raise NotFoundError("Product not found")
    return product_summary(*row)


async def update_product(
    session: AsyncSession,
    product_id: int,
    data: ProductUpdate,
) -> ProductSummary:
    product = await require_active_product(session, product_id)
    values = data.model_dump(exclude_unset=True)
    brand = values.get("brand", product.brand)
    model = values.get("model", product.model)
    storage = values.get("storage", product.storage)
    color = values.get("color", product.color)

    product.brand = normalize_text(brand)
    product.model = normalize_text(model)
    product.storage = normalize_storage(storage)
    product.color = normalize_color(color)
    product.identity_key = product_identity_key(brand, model, storage, color)
    try:
        async with session.begin_nested():
            await session.flush()
    except IntegrityError as error:
        raise ConflictError("A product with this identity already exists") from error
    return await get_product_summary(session, product.id)


async def soft_delete_product(session: AsyncSession, product_id: int) -> None:
    product = await require_active_product(session, product_id)
    product.is_active = False
    product.deleted_at = datetime.now(UTC)
    await session.flush()


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


async def search_products(
    session: AsyncSession,
    *,
    query: str,
    limit: int,
    offset: int,
) -> Page[ProductSummary]:
    tokens = normalize_text(query).split()
    conditions = []
    fields = (Product.brand, Product.model, Product.storage, Product.color)
    for token in tokens:
        pattern = f"%{_escape_like(token)}%"
        conditions.append(
            or_(*(field.ilike(pattern, escape="\\") for field in fields))
        )
    predicate = and_(Product.is_active.is_(True), *conditions)
    total = int(
        await session.scalar(
            select(func.count()).select_from(Product).where(predicate)
        )
        or 0
    )
    rows = (
        await session.execute(
            product_summary_select()
            .where(predicate)
            .order_by(func.lower(Product.brand), func.lower(Product.model), Product.id)
            .limit(limit)
            .offset(offset)
        )
    ).all()
    return Page(
        items=await with_price_trends(
            session,
            [
                product_summary(*row)
                for row in rows
            ],
        ),
        total=total,
        limit=limit,
        offset=offset,
    )


async def list_product_listings(
    session: AsyncSession,
    *,
    product_id: int,
    include_inactive: bool = False,
    limit: int,
    offset: int,
) -> Page[ProductListingResponse]:
    await require_active_product(session, product_id)
    conditions = [ProductListing.product_id == product_id]
    if not include_inactive:
        conditions.append(ProductListing.is_active.is_(True))
    predicate = and_(*conditions)
    total = int(
        await session.scalar(
            select(func.count(ProductListing.id)).where(predicate)
        )
        or 0
    )
    rows = (
        await session.execute(
            select(ProductListing, Store.title)
            .join(Store, Store.id == ProductListing.store_id)
            .where(predicate)
            .order_by(
                ProductListing.is_available.desc(),
                ProductListing.current_price,
                ProductListing.id,
            )
            .limit(limit)
            .offset(offset)
        )
    ).all()
    items = [
        ProductListingResponse(
            id=listing.id,
            product_id=listing.product_id,
            store_id=listing.store_id,
            store_name=store_name,
            product_url=listing.product_url,
            current_price=listing.current_price,
            currency=listing.currency,
            is_available=listing.is_available,
            last_checked_at=listing.last_checked_at,
            variant_name=listing.variant_name,
            installment_monthly=listing.installment_monthly,
            installment_months=listing.installment_months,
        )
        for listing, store_name in rows
    ]
    return Page(items=items, total=total, limit=limit, offset=offset)


async def list_product_prices(
    session: AsyncSession,
    *,
    product_id: int,
    limit: int,
    offset: int,
) -> Page[PriceHistoryResponse]:
    await require_active_product(session, product_id)
    predicate = ProductListing.product_id == product_id
    total = int(
        await session.scalar(
            select(func.count(PriceHist.id))
            .join(ProductListing, ProductListing.id == PriceHist.listing_id)
            .where(predicate)
        )
        or 0
    )
    rows = (
        await session.execute(
            select(PriceHist, ProductListing, Store.title)
            .join(ProductListing, ProductListing.id == PriceHist.listing_id)
            .join(Store, Store.id == ProductListing.store_id)
            .where(predicate)
            .order_by(PriceHist.recorded_at.desc(), PriceHist.id.desc())
            .limit(limit)
            .offset(offset)
        )
    ).all()
    items = [
        PriceHistoryResponse(
            id=history.id,
            product_id=listing.product_id,
            listing_id=listing.id,
            store_id=listing.store_id,
            store_name=store_name,
            price=history.price,
            currency=history.currency,
            is_available=history.is_available,
            recorded_at=history.recorded_at,
        )
        for history, listing, store_name in rows
    ]
    return Page(items=items, total=total, limit=limit, offset=offset)


async def get_product_price_extremes(
    session: AsyncSession,
    *,
    product_id: int,
    currency: str,
) -> PriceExtremesResponse:
    await require_active_product(session, product_id)
    normalized_currency = currency.strip().upper()
    lowest, highest = (
        await session.execute(
            select(func.min(PriceHist.price), func.max(PriceHist.price))
            .join(ProductListing, ProductListing.id == PriceHist.listing_id)
            .where(
                ProductListing.product_id == product_id,
                PriceHist.currency == normalized_currency,
            )
        )
    ).one()
    return PriceExtremesResponse(
        currency=normalized_currency,
        lowest_price=lowest,
        highest_price=highest,
    )
