import pytest
from pydantic import ValidationError

from app.conf import Settings

PROD_DB = "postgresql+asyncpg://u:p@db:5432/app"
SECRET = "a-real-production-secret-of-at-least-32-chars"


def make(**values: object) -> Settings:
    return Settings(_env_file=None, **values)


def test_dev_allows_fallback_database_url() -> None:
    settings = make(PROD=False)

    assert settings.database_url == settings.DEV_DATABASE_URL


def test_prod_requires_database_url() -> None:
    with pytest.raises(ValidationError, match="DATABASE_URL"):
        make(PROD=True, JWT_SECRET=SECRET)


def test_prod_rejects_placeholder_jwt_secret() -> None:
    with pytest.raises(ValidationError, match="placeholder"):
        make(
            PROD=True,
            DATABASE_URL=PROD_DB,
            JWT_SECRET="local-development-secret-change-me-1234567890",
        )


def test_prod_accepts_real_config() -> None:
    settings = make(PROD=True, DATABASE_URL=PROD_DB, JWT_SECRET=SECRET)

    assert settings.jwt_secret() == SECRET
