#!/usr/bin/env python3
"""Create an administrator using explicit environment credentials."""
import asyncio
import os

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.db.models import User
from app.db.sess import engine


async def create_admin_user(email: str, password: str) -> None:
    """Create an admin user for local catalog refreshes."""
    async_session = async_sessionmaker(engine, expire_on_commit=False)

    async with async_session() as session:
        result = await session.execute(select(User).where(User.email == email))
        existing = result.scalar_one_or_none()

        if existing:
            print(f"Admin user already exists: {email}")
            return

        from app.services.auth_service import hash_password

        admin = User(
            email=email,
            password_hash=await hash_password(password),
            is_admin=True,
            is_active=True,
        )
        session.add(admin)
        await session.commit()
        print(f"Created admin user: {email}")


async def main():
    email = os.environ.get("ADMIN_EMAIL", "").strip()
    password = os.environ.get("ADMIN_PASSWORD", "")
    if not email or len(password) < 12:
        raise SystemExit("Set ADMIN_EMAIL and ADMIN_PASSWORD (at least 12 characters).")
    try:
        await create_admin_user(email, password)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
