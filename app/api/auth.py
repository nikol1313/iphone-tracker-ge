import logging
from urllib.parse import urlencode

import jwt
from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, Response, status

from app.conf import settings
from app.db.db_schemas import (
    PasswordResetConfirm,
    PasswordResetRequest,
    TokenResponse,
    UserCredentials,
    UserResponse,
)
from app.dependencies import SessionDep
from app.services import email_service
from app.services.auth_service import (
    authenticate_user,
    create_access_token,
    create_password_reset_token,
    find_active_user,
    register_user,
    reset_password,
)
from app.services.email_service import EmailNotificationError
from app.services.errors import ConflictError
from app.services.normalization import normalize_email
from app.services.rate_limit import RateLimiter

LOGGER = logging.getLogger(__name__)

# Per client IP, to slow password guessing and scripted sign-ups.
LOGIN_IP_LIMIT = RateLimiter(limit=20, window_seconds=5 * 60)
REGISTER_IP_LIMIT = RateLimiter(limit=20, window_seconds=60 * 60)
RESET_REQUEST_IP_LIMIT = RateLimiter(limit=5, window_seconds=60 * 60)
RESET_CONFIRM_IP_LIMIT = RateLimiter(limit=10, window_seconds=15 * 60)
# Per account: wrong passwords only, so a correct login is never blocked by its own count.
LOGIN_FAILURE_EMAIL_LIMIT = RateLimiter(limit=5, window_seconds=15 * 60)
# Per account: caps reset emails one inbox can receive; enforced silently.
RESET_EMAIL_LIMIT = RateLimiter(limit=3, window_seconds=60 * 60)
RATE_LIMITERS = (
    LOGIN_IP_LIMIT,
    REGISTER_IP_LIMIT,
    RESET_REQUEST_IP_LIMIT,
    RESET_CONFIRM_IP_LIMIT,
    LOGIN_FAILURE_EMAIL_LIMIT,
    RESET_EMAIL_LIMIT,
)

router = APIRouter(prefix="/auth", tags=["authentication"])


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _too_many(wait: int) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail=f"Too many attempts. Try again in {wait} seconds.",
        headers={"Retry-After": str(wait)},
    )


def _limit(limiter: RateLimiter, key: str) -> None:
    wait = limiter.hit(key)
    if wait is not None:
        raise _too_many(wait)


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
)
async def register(
    credentials: UserCredentials,
    session: SessionDep,
    request: Request,
) -> UserResponse:
    _limit(REGISTER_IP_LIMIT, _client_ip(request))
    try:
        user = await register_user(session, credentials)
    except ConflictError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return UserResponse.model_validate(user)


@router.post("/login", response_model=TokenResponse)
async def login(
    credentials: UserCredentials,
    session: SessionDep,
    request: Request,
) -> TokenResponse:
    _limit(LOGIN_IP_LIMIT, _client_ip(request))
    email_wait = LOGIN_FAILURE_EMAIL_LIMIT.retry_after(credentials.email)
    if email_wait is not None:
        raise _too_many(email_wait)
    user = await authenticate_user(session, credentials)
    if user is None:
        LOGIN_FAILURE_EMAIL_LIMIT.record(credentials.email)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return create_access_token(user)


async def _send_reset_email(email: str, link: str) -> None:
    try:
        await email_service.send_password_reset_email(email, link)
    except EmailNotificationError:
        LOGGER.exception("Password reset email to an account could not be sent")


# Same answer whether or not the account exists, and the email goes out after the
# response, so neither the status nor the timing reveals who has an account.
@router.post("/password-reset", status_code=status.HTTP_204_NO_CONTENT)
async def request_password_reset(
    data: PasswordResetRequest,
    session: SessionDep,
    request: Request,
    background: BackgroundTasks,
) -> Response:
    if not email_service.email_configured():
        raise HTTPException(status_code=503, detail="Email delivery is not configured on the server")
    _limit(RESET_REQUEST_IP_LIMIT, _client_ip(request))
    email = normalize_email(str(data.email))
    user = await find_active_user(session, email)
    if user is not None and RESET_EMAIL_LIMIT.hit(email) is None:
        token = create_password_reset_token(user)
        link = f"{settings.public_base_url}/?{urlencode({'reset_password': token})}"
        background.add_task(_send_reset_email, user.email, link)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/password-reset/confirm", status_code=status.HTTP_204_NO_CONTENT)
async def confirm_password_reset(
    data: PasswordResetConfirm,
    session: SessionDep,
    request: Request,
) -> Response:
    _limit(RESET_CONFIRM_IP_LIMIT, _client_ip(request))
    try:
        user = await reset_password(session, data.token, data.password)
    except (jwt.InvalidTokenError, RuntimeError):
        raise HTTPException(
            status_code=400,
            detail="This reset link is invalid, expired, or already used. Request a new one.",
        ) from None
    # The owner just proved inbox access; let them sign in now even if guessers locked the account.
    LOGIN_FAILURE_EMAIL_LIMIT.forget(user.email)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
