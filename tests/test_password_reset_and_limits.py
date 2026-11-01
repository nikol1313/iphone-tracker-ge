from email.message import EmailMessage
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from app.conf import settings
from app.services import email_service

PASSWORD = "strong-password"


@pytest.fixture
def smtp_configured(monkeypatch: pytest.MonkeyPatch) -> list[EmailMessage]:
    monkeypatch.setattr(settings, "SMTP_HOST", "smtp.example.com")
    monkeypatch.setattr(settings, "SMTP_FROM", "iPhone Tracker <alerts@example.com>")
    sent: list[EmailMessage] = []
    monkeypatch.setattr(email_service, "_send", sent.append)
    return sent


def reset_token(message: EmailMessage) -> str:
    text = message.get_body(("plain",)).get_content()
    link = next(line for line in text.splitlines() if "reset_password=" in line)
    return parse_qs(urlsplit(link).query)["reset_password"][0]


async def register(client: httpx.AsyncClient, email: str = "user@example.com") -> None:
    response = await client.post("/auth/register", json={"email": email, "password": PASSWORD})
    assert response.status_code == 201


async def login(client: httpx.AsyncClient, password: str, email: str = "user@example.com") -> int:
    response = await client.post("/auth/login", json={"email": email, "password": password})
    return response.status_code


@pytest.mark.asyncio
async def test_reset_link_sets_new_password_and_works_only_once(
    client: httpx.AsyncClient,
    smtp_configured: list[EmailMessage],
) -> None:
    await register(client)
    response = await client.post("/auth/password-reset", json={"email": "USER@example.com"})
    assert response.status_code == 204
    assert smtp_configured[-1]["To"] == "user@example.com"
    token = reset_token(smtp_configured[-1])

    confirm = await client.post(
        "/auth/password-reset/confirm",
        json={"token": token, "password": "brand-new-password"},
    )
    assert confirm.status_code == 204
    assert await login(client, PASSWORD) == 401
    assert await login(client, "brand-new-password") == 200

    reused = await client.post(
        "/auth/password-reset/confirm",
        json={"token": token, "password": "another-password"},
    )
    assert reused.status_code == 400
    assert await login(client, "brand-new-password") == 200


@pytest.mark.asyncio
async def test_reset_request_does_not_reveal_unknown_accounts(
    client: httpx.AsyncClient,
    smtp_configured: list[EmailMessage],
) -> None:
    response = await client.post("/auth/password-reset", json={"email": "nobody@example.com"})
    assert response.status_code == 204
    assert smtp_configured == []


@pytest.mark.asyncio
async def test_reset_rejects_bad_tokens_and_short_passwords(
    client: httpx.AsyncClient,
    smtp_configured: list[EmailMessage],
) -> None:
    await register(client)
    await client.post("/auth/password-reset", json={"email": "user@example.com"})
    token = reset_token(smtp_configured[-1])

    short = await client.post("/auth/password-reset/confirm", json={"token": token, "password": "short"})
    assert short.status_code == 422
    forged = await client.post(
        "/auth/password-reset/confirm",
        json={"token": "not-a-token", "password": "brand-new-password"},
    )
    assert forged.status_code == 400


@pytest.mark.asyncio
async def test_reset_needs_email_delivery(client: httpx.AsyncClient) -> None:
    response = await client.post("/auth/password-reset", json={"email": "user@example.com"})
    assert response.status_code == 503


@pytest.mark.asyncio
async def test_reset_emails_per_account_are_capped_silently(
    client: httpx.AsyncClient,
    smtp_configured: list[EmailMessage],
) -> None:
    await register(client)
    for _ in range(3):
        await client.post("/auth/password-reset", json={"email": "user@example.com"})
    # The fourth request still answers 204, so it reveals nothing, but sends no email.
    fourth = await client.post("/auth/password-reset", json={"email": "user@example.com"})
    assert fourth.status_code == 204
    assert len(smtp_configured) == 3


@pytest.mark.asyncio
async def test_wrong_passwords_lock_the_account_until_a_reset(
    client: httpx.AsyncClient,
    smtp_configured: list[EmailMessage],
) -> None:
    await register(client)
    for _ in range(5):
        assert await login(client, "wrong-password") == 401
    locked = await client.post("/auth/login", json={"email": "user@example.com", "password": PASSWORD})
    assert locked.status_code == 429
    assert int(locked.headers["Retry-After"]) > 0
    # Other accounts are unaffected.
    await register(client, "other@example.com")
    assert await login(client, PASSWORD, "other@example.com") == 200

    await client.post("/auth/password-reset", json={"email": "user@example.com"})
    await client.post(
        "/auth/password-reset/confirm",
        json={"token": reset_token(smtp_configured[-1]), "password": "brand-new-password"},
    )
    assert await login(client, "brand-new-password") == 200


@pytest.mark.asyncio
async def test_too_many_logins_from_one_ip_are_refused(client: httpx.AsyncClient) -> None:
    await register(client)
    for _ in range(20):
        assert await login(client, PASSWORD) == 200
    assert await login(client, PASSWORD) == 429


@pytest.mark.asyncio
async def test_too_many_registrations_from_one_ip_are_refused(client: httpx.AsyncClient) -> None:
    for number in range(20):
        await register(client, f"user{number}@example.com")
    response = await client.post(
        "/auth/register",
        json={"email": "one-more@example.com", "password": PASSWORD},
    )
    assert response.status_code == 429
