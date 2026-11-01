import logging
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.db_schemas import (
    AlertBrief,
    AlertCreate,
    AlertResponse,
    Page,
    ProductResponse,
    TrackedProductResponse,
)
from app.db.models import (
    PriceAlert,
    Product,
    ProductListing,
    Store,
    TrackedProduct,
    User,
)
from app.services.email_service import (
    EmailNotificationError,
    send_price_alert_notification,
)
from app.services.errors import ConflictError, NotFoundError
from app.services.product_service import (
    product_summary,
    product_summary_select,
    require_active_product,
    with_price_trends,
)

logger = logging.getLogger(__name__)


def _lowest_price(product_id_column, currency_column=None):
    conditions = [
        ProductListing.product_id == product_id_column,
        ProductListing.is_active.is_(True),
        ProductListing.is_available.is_(True),
    ]
    if currency_column is not None:
        conditions.append(ProductListing.currency == currency_column)
    return (
        select(ProductListing.current_price)
        .where(*conditions)
        .order_by(ProductListing.current_price, ProductListing.id)
        .limit(1)
        .correlate(Product, PriceAlert, TrackedProduct)
        .scalar_subquery()
    )


def alert_reached(price: Decimal | None, target: Decimal | None) -> bool:
    """An in-stock price reaches a target at or above it; with no target, any in-stock price does."""
    return price is not None and (target is None or price <= target)


async def _reject_back_in_stock_while_in_stock(
    session: AsyncSession, product_id: int, data: AlertCreate
) -> None:
    if data.target_price is not None:
        return
    in_stock = await session.scalar(
        select(ProductListing.id)
        .where(
            ProductListing.product_id == product_id,
            ProductListing.is_active.is_(True),
            ProductListing.is_available.is_(True),
            ProductListing.currency == data.currency,
        )
        .limit(1)
    )
    if in_stock is not None:
        raise ConflictError("This phone is in stock now; set a target price instead")


def _product_response(product: Product) -> ProductResponse:
    return ProductResponse(
        id=product.id,
        brand=product.brand,
        model=product.model,
        storage=product.storage,
        color=product.color,
    )


async def track_product(
    session: AsyncSession,
    *,
    user_id: int,
    product_id: int,
) -> TrackedProduct:
    await require_active_product(session, product_id)
    tracked = TrackedProduct(user_id=user_id, product_id=product_id)
    try:
        async with session.begin_nested():
            session.add(tracked)
            await session.flush()
    except IntegrityError as error:
        raise ConflictError("Product is already tracked") from error
    return tracked


async def list_tracked_products(
    session: AsyncSession,
    *,
    user_id: int,
    limit: int,
    offset: int,
) -> Page[TrackedProductResponse]:
    predicate = (
        TrackedProduct.user_id == user_id,
        Product.is_active.is_(True),
    )
    total = int(
        await session.scalar(
            select(func.count(TrackedProduct.id))
            .join(Product, Product.id == TrackedProduct.product_id)
            .where(*predicate)
        )
        or 0
    )
    alert_lowest = _lowest_price(Product.id, PriceAlert.currency)
    # Same summary as the catalog, so the watchlist shows the same prices and stock.
    rows = (
        await session.execute(
            product_summary_select()
            .add_columns(TrackedProduct, PriceAlert, alert_lowest.label("alert_lowest"))
            .join(TrackedProduct, TrackedProduct.product_id == Product.id)
            .outerjoin(
                PriceAlert,
                (PriceAlert.product_id == Product.id)
                & (PriceAlert.user_id == user_id),
            )
            .where(*predicate)
            .order_by(TrackedProduct.created_at.desc(), TrackedProduct.id.desc())
            .limit(limit)
            .offset(offset)
        )
    ).all()
    summaries = await with_price_trends(
        session, [product_summary(*row[:-3]) for row in rows]
    )
    items = []
    for summary, (*_, tracked, alert, alert_price) in zip(summaries, rows, strict=True):
        active_alert = None
        if alert is not None:
            active_alert = AlertBrief(
                id=alert.id,
                target_price=alert.target_price,
                currency=alert.currency,
                is_triggered=alert_reached(alert_price, alert.target_price),
            )
        items.append(
            TrackedProductResponse(
                product=summary,
                active_alert=active_alert,
                created_at=tracked.created_at,
            )
        )
    return Page(items=items, total=total, limit=limit, offset=offset)


async def untrack_product(
    session: AsyncSession,
    *,
    user_id: int,
    product_id: int,
) -> None:
    tracked = await session.scalar(
        select(TrackedProduct).where(
            TrackedProduct.user_id == user_id,
            TrackedProduct.product_id == product_id,
        )
    )
    if tracked is None:
        raise NotFoundError("Tracked product not found")
    await session.delete(tracked)
    # An alert outside the watchlist would notify about a product the user dropped.
    await session.execute(
        delete(PriceAlert).where(
            PriceAlert.user_id == user_id,
            PriceAlert.product_id == product_id,
        )
    )
    await session.flush()


async def create_alert(
    session: AsyncSession,
    *,
    user_id: int,
    product_id: int,
    data: AlertCreate,
) -> PriceAlert:
    await require_active_product(session, product_id)
    await _reject_back_in_stock_while_in_stock(session, product_id, data)
    alert = PriceAlert(
        user_id=user_id,
        product_id=product_id,
        target_price=data.target_price,
        currency=data.currency,
    )
    try:
        async with session.begin_nested():
            session.add(alert)
            await session.flush()
    except IntegrityError as error:
        raise ConflictError("An alert already exists for this product") from error
    # The watchlist lists tracked products, so an alert always tracks its product.
    already_tracked = await session.scalar(
        select(TrackedProduct.id).where(
            TrackedProduct.user_id == user_id,
            TrackedProduct.product_id == product_id,
        )
    )
    if already_tracked is None:
        session.add(TrackedProduct(user_id=user_id, product_id=product_id))
        await session.flush()
    return alert


async def get_alert_response(
    session: AsyncSession,
    alert: PriceAlert,
) -> AlertResponse:
    product = await require_active_product(session, alert.product_id)
    current_price = await session.scalar(
        select(ProductListing.current_price)
        .where(
            ProductListing.product_id == product.id,
            ProductListing.is_active.is_(True),
            ProductListing.is_available.is_(True),
            ProductListing.currency == alert.currency,
        )
        .order_by(ProductListing.current_price, ProductListing.id)
        .limit(1)
    )
    return AlertResponse(
        id=alert.id,
        product=_product_response(product),
        target_price=alert.target_price,
        currency=alert.currency,
        current_lowest_price=current_price,
        is_triggered=alert_reached(current_price, alert.target_price),
        created_at=alert.created_at,
    )


async def list_alerts(
    session: AsyncSession,
    *,
    user_id: int,
    limit: int,
    offset: int,
) -> Page[AlertResponse]:
    total = int(
        await session.scalar(
            select(func.count(PriceAlert.id))
            .join(Product, Product.id == PriceAlert.product_id)
            .where(
                PriceAlert.user_id == user_id,
                Product.is_active.is_(True),
            )
        )
        or 0
    )
    current_price = _lowest_price(Product.id, PriceAlert.currency)
    rows = (
        await session.execute(
            select(PriceAlert, Product, current_price.label("current_price"))
            .join(Product, Product.id == PriceAlert.product_id)
            .where(
                PriceAlert.user_id == user_id,
                Product.is_active.is_(True),
            )
            .order_by(PriceAlert.created_at.desc(), PriceAlert.id.desc())
            .limit(limit)
            .offset(offset)
        )
    ).all()
    items = [
        AlertResponse(
            id=alert.id,
            product=_product_response(product),
            target_price=alert.target_price,
            currency=alert.currency,
            current_lowest_price=price,
            is_triggered=alert_reached(price, alert.target_price),
            created_at=alert.created_at,
        )
        for alert, product, price in rows
    ]
    return Page(items=items, total=total, limit=limit, offset=offset)


async def _owned_alert(
    session: AsyncSession,
    *,
    user_id: int,
    alert_id: int,
) -> PriceAlert:
    alert = await session.scalar(
        select(PriceAlert).where(
            PriceAlert.id == alert_id,
            PriceAlert.user_id == user_id,
        )
    )
    if alert is None:
        raise NotFoundError("Alert not found")
    return alert


async def update_alert(
    session: AsyncSession,
    *,
    user_id: int,
    alert_id: int,
    data: AlertCreate,
) -> PriceAlert:
    alert = await _owned_alert(session, user_id=user_id, alert_id=alert_id)
    await _reject_back_in_stock_while_in_stock(session, alert.product_id, data)
    alert.target_price = data.target_price
    alert.currency = data.currency
    # A new target is a new alert: email again when it is reached.
    alert.notified_at = None
    await session.flush()
    return alert


async def delete_alert(
    session: AsyncSession,
    *,
    user_id: int,
    alert_id: int,
) -> None:
    alert = await _owned_alert(session, user_id=user_id, alert_id=alert_id)
    await session.delete(alert)
    await session.flush()


async def check_and_send_alert_notifications(session: AsyncSession) -> None:
    """Email each newly reached alert (price or back in stock) once to its owner's verified address."""
    current_price = _lowest_price(Product.id, PriceAlert.currency)

    rows = (
        await session.execute(
            select(
                PriceAlert,
                Product,
                User.notification_email,
                current_price.label("current_price"),
            )
            .join(Product, Product.id == PriceAlert.product_id)
            .join(User, User.id == PriceAlert.user_id)
            .where(
                Product.is_active.is_(True),
                User.is_active.is_(True),
                User.notification_email.is_not(None),
                User.notification_email_verified_at.is_not(None),
                PriceAlert.notified_at.is_(None),
            )
        )
    ).all()

    for alert, product, email, price in rows:
        if alert_reached(price, alert.target_price):
            listing_row = (
                await session.execute(
                    select(ProductListing, Store.title)
                    .join(Store, Store.id == ProductListing.store_id)
                    .where(
                        ProductListing.product_id == product.id,
                        ProductListing.is_active.is_(True),
                        ProductListing.is_available.is_(True),
                        ProductListing.currency == alert.currency,
                    )
                    .order_by(ProductListing.current_price, ProductListing.id)
                    .limit(1)
                )
            ).one_or_none()
            listing_result = listing_row[0] if listing_row else None
            store_name = listing_row[1] if listing_row else None

            model_includes_brand = product.model.lower().startswith(
                product.brand.lower()
            )
            product_name = (
                product.model
                if model_includes_brand
                else f"{product.brand} {product.model}"
            )
            product_variant = (
                f"{product.storage or ''} {product.color or ''}".strip()
                or "Standard"
            )

            try:
                await send_price_alert_notification(
                    email=email,
                    product_name=product_name,
                    product_variant=product_variant,
                    target_price=alert.target_price,
                    current_price=price,
                    currency=alert.currency,
                    store_name=store_name,
                    product_url=(
                        listing_result.product_url if listing_result else None
                    ),
                )
            except (EmailNotificationError, RuntimeError) as error:
                logger.warning(
                    "Email delivery failed for alert %s: %s",
                    alert.id,
                    error,
                )
                continue

            alert.notified_at = datetime.now(UTC)

    await session.flush()
