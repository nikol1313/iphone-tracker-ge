"""replace Telegram alerts with email alerts

Revision ID: d4b9e7a1c205
Revises: c3a8f5e2d117
Create Date: 2026-10-28 15:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d4b9e7a1c205"
down_revision: str | Sequence[str] | None = "c3a8f5e2d117"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("notification_email", sa.String(length=320), nullable=True),
    )
    op.drop_column("users", "telegram_chat_id")


def downgrade() -> None:
    op.add_column(
        "users",
        sa.Column("telegram_chat_id", sa.String(length=32), nullable=True),
    )
    op.drop_column("users", "notification_email")
