from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.conf import settings

engine = create_async_engine(settings.database_url, pool_pre_ping=True)


class Base(DeclarativeBase):
    pass


SESSION = async_sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


async def get_conn() -> AsyncGenerator[AsyncSession]:
    async with SESSION() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
