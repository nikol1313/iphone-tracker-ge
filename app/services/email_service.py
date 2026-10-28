import asyncio
import smtplib
import ssl
from decimal import Decimal
from email.message import EmailMessage
from html import escape
from urllib.parse import urlsplit

from app.conf import settings

SMTP_TIMEOUT_SECONDS = 15
# Port 465 speaks TLS from the first byte; other ports upgrade with STARTTLS.
IMPLICIT_TLS_PORT = 465


class EmailNotificationError(Exception):
    """Raised when the mail server rejects a message or cannot be reached."""


def email_configured() -> bool:
    return bool(settings.SMTP_HOST and settings.SMTP_FROM)


def _connect(context: ssl.SSLContext) -> smtplib.SMTP:
    host = settings.SMTP_HOST or ""
    if settings.SMTP_PORT == IMPLICIT_TLS_PORT:
        return smtplib.SMTP_SSL(
            host,
            settings.SMTP_PORT,
            timeout=SMTP_TIMEOUT_SECONDS,
            context=context,
        )
    server = smtplib.SMTP(host, settings.SMTP_PORT, timeout=SMTP_TIMEOUT_SECONDS)
    try:
        server.starttls(context=context)
    except BaseException:
        server.close()
        raise
    return server


def _send(message: EmailMessage) -> None:
    with _connect(ssl.create_default_context()) as server:
        if settings.SMTP_USERNAME and settings.SMTP_PASSWORD:
            server.login(
                settings.SMTP_USERNAME,
                settings.SMTP_PASSWORD.get_secret_value(),
            )
        server.send_message(message)


async def send_email(*, to: str, subject: str, text: str, html: str) -> None:
    if not email_configured():
        raise RuntimeError("SMTP_HOST and SMTP_FROM are not configured")

    message = EmailMessage()
    message["From"] = settings.SMTP_FROM
    message["To"] = to
    message["Subject"] = subject
    message.set_content(text)
    message.add_alternative(html, subtype="html")

    try:
        await asyncio.to_thread(_send, message)
    except (smtplib.SMTPException, OSError) as error:
        raise EmailNotificationError(f"Email delivery failed: {error}") from error


def _price(value: Decimal) -> str:
    return f"{value:,.2f}"


def _safe_link(url: str | None) -> str | None:
    if not url:
        return None
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    return url


async def send_price_alert_notification(
    *,
    email: str,
    product_name: str,
    product_variant: str,
    target_price: Decimal,
    current_price: Decimal,
    currency: str,
    store_name: str | None = None,
    product_url: str | None = None,
) -> None:
    """Format and send a triggered price alert to one email address."""
    currency = currency.upper()
    difference = target_price - current_price
    difference_label = "Below target by" if difference >= 0 else "Above target by"
    link = _safe_link(product_url)
    rows = [
        ("Product", product_name),
        ("Variant", product_variant),
        ("Target price", f"{currency} {_price(target_price)}"),
        ("Current price", f"{currency} {_price(current_price)}"),
        (difference_label, f"{currency} {_price(abs(difference))}"),
    ]
    if store_name:
        rows.append(("Store", store_name))

    text_lines = ["Your price alert was triggered.", ""]
    text_lines += [f"{label}: {value}" for label, value in rows]
    if link:
        text_lines += ["", f"View product: {link}"]

    html_rows = "".join(
        f"<tr><th align='left' style='padding:4px 12px 4px 0'>{escape(label)}</th>"
        f"<td style='padding:4px 0'>{escape(value)}</td></tr>"
        for label, value in rows
    )
    html_link = (
        f'<p><a href="{escape(link, quote=True)}">View product</a></p>' if link else ""
    )
    await send_email(
        to=email,
        subject=f"Price alert: {product_name} is now {currency} {_price(current_price)}",
        text="\n".join(text_lines),
        html=(
            "<p>Your price alert was triggered.</p>"
            f"<table>{html_rows}</table>{html_link}"
        ),
    )


async def send_test_email(email: str) -> None:
    await send_email(
        to=email,
        subject="Price Monitor: email alerts are working",
        text="This test email confirms Price Monitor can send your price alerts.",
        html="<p>This test email confirms Price Monitor can send your price alerts.</p>",
    )
