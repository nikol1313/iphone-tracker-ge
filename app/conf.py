from pathlib import Path

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ENV_FILE = Path(__file__).resolve().parent.parent / ".env"
# Placeholder secrets that have shipped in this repo; never valid in production.
KNOWN_PLACEHOLDER_SECRETS = frozenset(
    {"local-development-secret-change-me-1234567890"}
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    DEV_DATABASE_URL: str = "postgresql+asyncpg://user:password@db:5432/app"
    DATABASE_URL: str | None = None
    PROD: bool = False
    JWT_SECRET: SecretStr | None = None
    JWT_ACCESS_TOKEN_EXPIRE_SECONDS: int = Field(default=86400, ge=60)
    TELEGRAM_BOT_TOKEN: SecretStr | None = None
    REFRESH_SCHEDULER_ENABLED: bool = True

    @model_validator(mode="after")
    def _require_production_config(self) -> "Settings":
        if not self.PROD:
            return self
        if not self.DATABASE_URL:
            raise ValueError("DATABASE_URL must be configured when PROD=true")
        secret = self.JWT_SECRET.get_secret_value() if self.JWT_SECRET else ""
        if secret in KNOWN_PLACEHOLDER_SECRETS:
            raise ValueError("JWT_SECRET must not be a placeholder when PROD=true")
        return self

    @property
    def database_url(self) -> str:
        return self.DATABASE_URL or self.DEV_DATABASE_URL

    def jwt_secret(self) -> str:
        if self.JWT_SECRET is None:
            raise RuntimeError("JWT_SECRET must be configured")

        secret = self.JWT_SECRET.get_secret_value()
        if len(secret) < 32:
            raise RuntimeError("JWT_SECRET must contain at least 32 characters")
        return secret


settings = Settings()
