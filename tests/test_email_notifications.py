from datetime import UTC, datetime, timedelta
from decimal import Decimal
from email.message import EmailMessage
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.conf import settings
from app.db.models import PriceAlert, Product, ProductListing, Store, User
from app.services import alert_service, email_service
from app.services.alert_service import check_and_send_alert_notifications
from app.services.email_service import (
    EmailNotificationError,
    send_price_alert_notification,
)
from tests.helpers import bearer, register_and_login


@pytest.fixture
def smtp_configured(monkeypatch: pytest.MonkeyPatch) -> list[EmailMessage]:
    monkeypatch.setattr(settings, "SMTP_HOST", "smtp.example.com")
    monkeypatch.setattr(settings, "SMTP_FROM", "Price Monitor <alerts@example.com>")
    sent: list[EmailMessage] = []
    monkeypatch.setattr(email_service, "_send", sent.append)
    return sent


def verification_link(message: EmailMessage) -> str:
    text = message.get_body(("plain",)).get_content()
    return next(line for line in text.splitlines() if "verify_email=" in line)


def verification_token(link: str) -> str:
    return parse_qs(urlsplit(link).query)["verify_email"][0]


@pytest.mark.asyncio
async def test_changed_email_needs_new_confirmation_and_old_links_stop_working(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    smtp_configured: list[EmailMessage],
) -> None:
    token = await register_and_login(
        client,
        email="mover@example.com",
        session_factory=session_factory,
    )
    await client.put(
        "/notification-settings/email",
        headers=bearer(token),
        json={"notification_email": "first@example.com"},
    )
    await client.post("/notification-settings/email/verification", headers=bearer(token))
    first_link = verification_link(smtp_configured[-1])
    assert (
        await client.post(
            "/notification-settings/email/verify",
            json={"token": verification_token(first_link)},
        )
    ).status_code == 204

    # Saving the same address keeps it confirmed; a new address starts unconfirmed.
    same = await client.put(
        "/notification-settings/email",
        headers=bearer(token),
        json={"notification_email": "first@example.com"},
    )
    assert same.json()["email_verified"] is True
    changed = await client.put(
        "/notification-settings/email",
        headers=bearer(token),
        json={"notification_email": "second@example.com"},
    )
    assert changed.json()["email_verified"] is False
    assert (
        await client.post(
            "/notification-settings/email/verify",
            json={"token": verification_token(first_link)},
        )
    ).status_code == 400

    async with session_factory() as session:
        user = await session.scalar(select(User).where(User.email == "mover@example.com"))
        assert user is not None
        # Let the resend cooldown lapse.
        user.verification_email_sent_at = datetime.now(UTC) - timedelta(minutes=5)
        await session.commit()
    assert (
        await client.post("/notification-settings/email/verification", headers=bearer(token))
    ).status_code == 204
    assert smtp_configured[-1]["To"] == "second@example.com"


@pytest.mark.asyncio
async def test_price_alert_email_is_escaped_and_uses_decimal_amounts(
    smtp_configured: list[EmailMessage],
) -> None:
    await send_price_alert_notification(
        email="buyer@example.com",
        product_name="iPhone <Pro & Max>",
        product_variant="256GB & Blue",
        target_price=Decimal("2500.10"),
        current_price=Decimal("2399.99"),
        currency="gel",
        store_name='Shop "One"',
        product_url="https://shop.example/phone?a=1&b=2",
    )

    [message] = smtp_configured
    assert message["To"] == "buyer@example.com"
    assert message["Subject"] == "Price alert: iPhone <Pro & Max> is now GEL 2,399.99"
    text = message.get_body(("plain",)).get_content()
    html = message.get_body(("html",)).get_content()
    assert "Below target by: GEL 100.11" in text
    assert "View product: https://shop.example/phone?a=1&b=2" in text
    assert "iPhone &lt;Pro &amp; Max&gt;" in html
    assert "Shop &quot;One&quot;" in html
    assert 'href="https://shop.example/phone?a=1&amp;b=2"' in html


@pytest.mark.asyncio
async def test_unconfigured_smtp_raises_and_smtp_errors_are_wrapped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "SMTP_HOST", None)
    with pytest.raises(RuntimeError):
        await email_service.send_test_email("buyer@example.com")

    monkeypatch.setattr(settings, "SMTP_HOST", "smtp.example.com")
    monkeypatch.setattr(settings, "SMTP_FROM", "alerts@example.com")

    def refuse(_: EmailMessage) -> None:
        raise ConnectionRefusedError("connection refused")

    monkeypatch.setattr(email_service, "_send", refuse)
    with pytest.raises(EmailNotificationError):
        await email_service.send_test_email("buyer@example.com")


@pytest.mark.asyncio
async def test_email_settings_are_authenticated_validated_and_testable(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    smtp_configured: list[EmailMessage],
) -> None:
    assert (await client.get("/notification-settings/email")).status_code == 401
    token = await register_and_login(
        client,
        email="owner@example.com",
        session_factory=session_factory,
    )

    assert (
        await client.post("/notification-settings/email/test", headers=bearer(token))
    ).status_code == 409
    invalid = await client.put(
        "/notification-settings/email",
        headers=bearer(token),
        json={"notification_email": "not-an-email"},
    )
    assert invalid.status_code == 422

    saved = await client.put(
        "/notification-settings/email",
        headers=bearer(token),
        json={"notification_email": " Alerts@Example.com "},
    )
    assert saved.json() == {
        "notification_email": "alerts@example.com",
        "email_verified": False,
        "delivery_configured": True,
    }
    # Unconfirmed addresses get no mail except the confirmation link.
    assert (
        await client.post("/notification-settings/email/test", headers=bearer(token))
    ).status_code == 409

    sent = await client.post("/notification-settings/email/verification", headers=bearer(token))
    assert sent.status_code == 204
    assert smtp_configured[-1]["To"] == "alerts@example.com"
    link = verification_link(smtp_configured[-1])
    assert link.startswith(f"{settings.public_base_url}/?verify_email=")
    resent = await client.post("/notification-settings/email/verification", headers=bearer(token))
    assert resent.status_code == 429
    assert int(resent.headers["Retry-After"]) > 0

    assert (
        await client.post("/notification-settings/email/verify", json={"token": "forged"})
    ).status_code == 400
    verified = await client.post(
        "/notification-settings/email/verify",
        json={"token": verification_token(link)},
    )
    assert verified.status_code == 204
    settings_response = await client.get("/notification-settings/email", headers=bearer(token))
    assert settings_response.json()["email_verified"] is True

    tested = await client.post("/notification-settings/email/test", headers=bearer(token))
    assert tested.status_code == 204
    assert smtp_configured[-1]["To"] == "alerts@example.com"

    cleared = await client.put(
        "/notification-settings/email",
        headers=bearer(token),
        json={"notification_email": None},
    )
    assert cleared.json()["notification_email"] is None


@pytest.mark.asyncio
async def test_triggered_alert_routes_to_owner_once_with_correct_listing(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with session_factory() as session:
        gel_store = Store(title="GEL Store", web_url="https://gel.example")
        usd_store = Store(title="USD Store", web_url="https://usd.example")
        product = Product(
            brand="Apple",
            model="iPhone 17 Pro",
            storage="256GB",
            color="Blue",
            identity_key="iphone-17-pro-256-blue",
        )
        configured_user = User(
            email="configured@example.com",
            password_hash="unused",
            notification_email="alerts@example.com",
            notification_email_verified_at=datetime.now(UTC),
        )
        unconfigured_user = User(
            email="unconfigured@example.com",
            password_hash="unused",
        )
        unverified_user = User(
            email="unverified@example.com",
            password_hash="unused",
            notification_email="someone-else@example.com",
        )
        session.add_all(
            [
                gel_store,
                usd_store,
                product,
                configured_user,
                unconfigured_user,
                unverified_user,
            ]
        )
        await session.flush()
        session.add_all(
            [
                ProductListing(
                    store_id=gel_store.id,
                    product_id=product.id,
                    product_url="https://gel.example/phone",
                    current_price=Decimal("2400.00"),
                    currency="GEL",
                ),
                ProductListing(
                    store_id=usd_store.id,
                    product_id=product.id,
                    product_url="https://usd.example/phone",
                    current_price=Decimal("10.00"),
                    currency="USD",
                ),
                PriceAlert(
                    user_id=configured_user.id,
                    product_id=product.id,
                    target_price=Decimal("2500.00"),
                    currency="GEL",
                ),
                PriceAlert(
                    user_id=unconfigured_user.id,
                    product_id=product.id,
                    target_price=Decimal("2500.00"),
                    currency="GEL",
                ),
                PriceAlert(
                    user_id=unverified_user.id,
                    product_id=product.id,
                    target_price=Decimal("2500.00"),
                    currency="GEL",
                ),
            ]
        )
        await session.commit()

    deliveries: list[dict] = []

    async def capture_delivery(**message: object) -> None:
        deliveries.append(message)

    monkeypatch.setattr(
        alert_service,
        "send_price_alert_notification",
        capture_delivery,
    )

    async with session_factory() as session:
        async with session.begin():
            await check_and_send_alert_notifications(session)
        async with session.begin():
            await check_and_send_alert_notifications(session)

        alerts = (
            await session.scalars(
                select(PriceAlert).order_by(PriceAlert.user_id)
            )
        ).all()

    assert len(deliveries) == 1
    assert deliveries[0]["email"] == "alerts@example.com"
    assert deliveries[0]["currency"] == "GEL"
    assert deliveries[0]["current_price"] == Decimal("2400.00")
    assert deliveries[0]["store_name"] == "GEL Store"
    assert alerts[0].notified_at is not None
    assert alerts[1].notified_at is None
    assert alerts[2].notified_at is None


@pytest.mark.asyncio
async def test_failed_delivery_is_left_pending_for_retry(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with session_factory() as session:
        store = Store(title="Store", web_url="https://store.example")
        product = Product(
            brand="Apple",
            model="iPhone 17",
            identity_key="iphone-17",
        )
        user = User(
            email="retry@example.com",
            password_hash="unused",
            notification_email="retry@example.com",
            notification_email_verified_at=datetime.now(UTC),
        )
        session.add_all([store, product, user])
        await session.flush()
        session.add(
            ProductListing(
                store_id=store.id,
                product_id=product.id,
                product_url="https://store.example/phone",
                current_price=Decimal("900.00"),
                currency="GEL",
            )
        )
        session.add(
            PriceAlert(
                user_id=user.id,
                product_id=product.id,
                target_price=Decimal("1000.00"),
                currency="GEL",
            )
        )
        await session.commit()

    attempts = 0

    async def fail_delivery(**_: object) -> None:
        nonlocal attempts
        attempts += 1
        raise EmailNotificationError("temporary failure")

    monkeypatch.setattr(
        alert_service,
        "send_price_alert_notification",
        fail_delivery,
    )

    async with session_factory() as session:
        async with session.begin():
            await check_and_send_alert_notifications(session)
        async with session.begin():
            await check_and_send_alert_notifications(session)
        alert = await session.scalar(select(PriceAlert))

    assert attempts == 2
    assert alert is not None
    assert alert.notified_at is None
