import asyncio
import hashlib
from datetime import UTC, datetime, timedelta

import jwt
from pwdlib import PasswordHash
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.conf import settings
from app.db.db_schemas import TokenResponse, UserCredentials
from app.db.models import User
from app.services.errors import ConflictError
from app.services.normalization import normalize_email

PASSWORD_HASH = PasswordHash.recommended()
JWT_ALGORITHM = "HS256"
EMAIL_VERIFICATION_TOKEN_LIFETIME = timedelta(days=1)
PASSWORD_RESET_TOKEN_LIFETIME = timedelta(hours=1)


async def hash_password(password: str) -> str:
    return await asyncio.to_thread(PASSWORD_HASH.hash, password)


async def verify_password(password: str, password_hash: str) -> bool:
    return await asyncio.to_thread(PASSWORD_HASH.verify, password, password_hash)


async def register_user(
    session: AsyncSession,
    credentials: UserCredentials,
) -> User:
    user = User(
        email=normalize_email(str(credentials.email)),
        password_hash=await hash_password(credentials.password),
    )
    try:
        async with session.begin_nested():
            session.add(user)
            await session.flush()
    except IntegrityError as error:
        raise ConflictError("An account with this email already exists") from error
    return user


async def authenticate_user(
    session: AsyncSession,
    credentials: UserCredentials,
) -> User | None:
    email = normalize_email(str(credentials.email))
    user = await session.scalar(select(User).where(User.email == email))
    if user is None:
        # Keep the unknown-user path computationally similar to a bad password.
        await verify_password(
            credentials.password,
            "$argon2id$v=19$m=65536,t=3,p=4$"
            "MDAwMDAwMDAwMDAwMDAwMA$"
            "RqmW6VJfC3Jb2Y6QqNAH3q4QIzP6zSkZ9qXc8D9RjZQ",
        )
        return None
    if not user.is_active:
        return None
    if not await verify_password(credentials.password, user.password_hash):
        return None
    return user


def create_access_token(user: User) -> TokenResponse:
    issued_at = datetime.now(UTC)
    expires_in = settings.JWT_ACCESS_TOKEN_EXPIRE_SECONDS
    payload = {
        "sub": str(user.id),
        "iat": issued_at,
        "exp": issued_at + timedelta(seconds=expires_in),
        "type": "access",
    }
    token = jwt.encode(
        payload,
        settings.jwt_secret(),
        algorithm=JWT_ALGORITHM,
    )
    return TokenResponse(access_token=token, expires_in=expires_in)


def decode_access_token(token: str) -> int:
    payload = jwt.decode(
        token,
        settings.jwt_secret(),
        algorithms=[JWT_ALGORITHM],
        options={"require": ["exp", "iat", "sub", "type"]},
    )
    if payload.get("type") != "access":
        raise jwt.InvalidTokenError("incorrect token type")

    subject = payload.get("sub")
    if not isinstance(subject, str) or not subject.isdigit():
        raise jwt.InvalidTokenError("invalid token subject")
    return int(subject)


def create_email_verification_token(user_id: int, email: str) -> str:
    issued_at = datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "email": email,
        "iat": issued_at,
        "exp": issued_at + EMAIL_VERIFICATION_TOKEN_LIFETIME,
        "type": "email_verification",
    }
    return jwt.encode(payload, settings.jwt_secret(), algorithm=JWT_ALGORITHM)


def decode_email_verification_token(token: str) -> tuple[int, str]:
    """Return the user id and the address the link was sent to."""
    payload = jwt.decode(
        token,
        settings.jwt_secret(),
        algorithms=[JWT_ALGORITHM],
        options={"require": ["exp", "iat", "sub", "type", "email"]},
    )
    if payload.get("type") != "email_verification":
        raise jwt.InvalidTokenError("incorrect token type")
    subject = payload.get("sub")
    email = payload.get("email")
    if not isinstance(subject, str) or not subject.isdigit() or not isinstance(email, str):
        raise jwt.InvalidTokenError("invalid verification token")
    return int(subject), email


def _password_fingerprint(password_hash: str) -> str:
    # Changes with the password, so a reset link stops working once it has been used.
    return hashlib.sha256(password_hash.encode()).hexdigest()[:32]


def create_password_reset_token(user: User) -> str:
    issued_at = datetime.now(UTC)
    payload = {
        "sub": str(user.id),
        "pwd": _password_fingerprint(user.password_hash),
        "iat": issued_at,
        "exp": issued_at + PASSWORD_RESET_TOKEN_LIFETIME,
        "type": "password_reset",
    }
    return jwt.encode(payload, settings.jwt_secret(), algorithm=JWT_ALGORITHM)


async def find_active_user(session: AsyncSession, email: str) -> User | None:
    user = await session.scalar(select(User).where(User.email == normalize_email(email)))
    return user if user is not None and user.is_active else None


async def reset_password(session: AsyncSession, token: str, password: str) -> User:
    """Set a new password from an emailed reset token; raise InvalidTokenError if it is unusable."""
    payload = jwt.decode(
        token,
        settings.jwt_secret(),
        algorithms=[JWT_ALGORITHM],
        options={"require": ["exp", "iat", "sub", "type", "pwd"]},
    )
    subject = payload.get("sub")
    if payload.get("type") != "password_reset" or not isinstance(subject, str) or not subject.isdigit():
        raise jwt.InvalidTokenError("invalid password reset token")
    user = await session.get(User, int(subject))
    if (
        user is None
        or not user.is_active
        or payload.get("pwd") != _password_fingerprint(user.password_hash)
    ):
        raise jwt.InvalidTokenError("password reset token no longer valid")
    user.password_hash = await hash_password(password)
    await session.flush()
    return user
