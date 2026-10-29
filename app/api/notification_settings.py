from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

import jwt
from fastapi import APIRouter, HTTPException, Response, status

from app.conf import settings
from app.db.db_schemas import (
    EmailSettingsResponse,
    EmailSettingsUpdate,
    EmailVerificationRequest,
)
from app.db.models import User
from app.dependencies import CurrentUser, SessionDep
from app.services import email_service
from app.services.auth_service import (
    create_email_verification_token,
    decode_email_verification_token,
)
from app.services.email_service import EmailNotificationError

# Stops one account from using us to flood an inbox with confirmation emails.
VERIFICATION_EMAIL_COOLDOWN = timedelta(seconds=60)

router = APIRouter(
    prefix="/notification-settings",
    tags=["notification settings"],
)


def _response(user: CurrentUser) -> EmailSettingsResponse:
    return EmailSettingsResponse(
        notification_email=user.notification_email,
        email_verified=user.notification_email_verified_at is not None,
        delivery_configured=email_service.email_configured(),
    )


def _require_delivery_configured() -> None:
    if not email_service.email_configured():
        raise HTTPException(status_code=503, detail="Email delivery is not configured on the server")


def _as_utc(value: datetime) -> datetime:
    # SQLite returns naive datetimes; Postgres returns aware ones.
    return value if value.tzinfo else value.replace(tzinfo=UTC)


@router.get("/email", response_model=EmailSettingsResponse)
async def get_email_settings(user: CurrentUser) -> EmailSettingsResponse:
    return _response(user)


@router.put("/email", response_model=EmailSettingsResponse)
async def update_email_settings(
    data: EmailSettingsUpdate,
    session: SessionDep,
    user: CurrentUser,
) -> EmailSettingsResponse:
    if data.notification_email != user.notification_email:
        user.notification_email = data.notification_email
        user.notification_email_verified_at = None
        await session.flush()
    return _response(user)


@router.post("/email/verification", status_code=status.HTTP_204_NO_CONTENT)
async def send_verification_email(session: SessionDep, user: CurrentUser) -> Response:
    if user.notification_email is None:
        raise HTTPException(status_code=409, detail="Save an email address first")
    if user.notification_email_verified_at is not None:
        raise HTTPException(status_code=409, detail="This email address is already verified")
    _require_delivery_configured()
    now = datetime.now(UTC)
    if user.verification_email_sent_at is not None:
        retry_at = _as_utc(user.verification_email_sent_at) + VERIFICATION_EMAIL_COOLDOWN
        if retry_at > now:
            wait = int((retry_at - now).total_seconds()) + 1
            raise HTTPException(
                status_code=429,
                detail=f"A confirmation email was just sent. Try again in {wait} seconds.",
                headers={"Retry-After": str(wait)},
            )
    token = create_email_verification_token(user.id, user.notification_email)
    link = f"{settings.public_base_url}/?{urlencode({'verify_email': token})}"
    try:
        await email_service.send_verification_email(user.notification_email, link)
    except EmailNotificationError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
    user.verification_email_sent_at = now
    await session.flush()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# Unauthenticated: the emailed token alone proves the reader owns the address.
@router.post("/email/verify", status_code=status.HTTP_204_NO_CONTENT)
async def verify_email(data: EmailVerificationRequest, session: SessionDep) -> Response:
    invalid = HTTPException(
        status_code=400,
        detail="This confirmation link is invalid or has expired. Send a new one from Email alerts.",
    )
    try:
        user_id, email = decode_email_verification_token(data.token)
    except (jwt.InvalidTokenError, RuntimeError):
        raise invalid from None
    user = await session.get(User, user_id)
    # A link for an address the user has since replaced must not verify the new one.
    if user is None or not user.is_active or user.notification_email != email:
        raise invalid
    if user.notification_email_verified_at is None:
        user.notification_email_verified_at = datetime.now(UTC)
        await session.flush()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/email/test", status_code=status.HTTP_204_NO_CONTENT)
async def send_test_email(user: CurrentUser) -> Response:
    if user.notification_email is None:
        raise HTTPException(status_code=409, detail="Save an email address first")
    if user.notification_email_verified_at is None:
        raise HTTPException(status_code=409, detail="Confirm your email address first")
    _require_delivery_configured()
    try:
        await email_service.send_test_email(user.notification_email)
    except EmailNotificationError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
    return Response(status_code=status.HTTP_204_NO_CONTENT)
