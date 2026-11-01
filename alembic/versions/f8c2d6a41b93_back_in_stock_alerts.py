"""allow alerts without a target price: notify when the phone is back in stock

Revision ID: f8c2d6a41b93
Revises: b3e9f4a27c18
Create Date: 2026-11-01 20:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f8c2d6a41b93"
down_revision: str | Sequence[str] | None = "b3e9f4a27c18"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # NULL target: any in-stock price triggers the alert. The positive-price check
    # still holds for set targets, since a NULL passes a CHECK constraint.
    op.alter_column(
        "price_alerts",
        "target_price",
        existing_type=sa.Numeric(12, 2),
        nullable=True,
    )


def downgrade() -> None:
    # Back-in-stock alerts have no price to keep; drop them before restoring NOT NULL.
    op.execute("DELETE FROM price_alerts WHERE target_price IS NULL")
    op.alter_column(
        "price_alerts",
        "target_price",
        existing_type=sa.Numeric(12, 2),
        nullable=False,
    )
