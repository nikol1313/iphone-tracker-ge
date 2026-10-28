"""track products that have alerts

Alerts used to be creatable without tracking the product, which hid them from the
watchlist. Every alert now implies a tracked product; backfill the missing rows.

Revision ID: c3a8f5e2d117
Revises: b7e2d91c4a10
Create Date: 2026-10-28 14:30:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c3a8f5e2d117"
down_revision: str | Sequence[str] | None = "b7e2d91c4a10"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        sa.text(
            "INSERT INTO tracked_products (user_id, product_id, created_at) "
            "SELECT a.user_id, a.product_id, a.created_at FROM price_alerts a "
            "WHERE NOT EXISTS (SELECT 1 FROM tracked_products t "
            "WHERE t.user_id = a.user_id AND t.product_id = a.product_id)"
        )
    )


def downgrade() -> None:
    # Backfilled rows are indistinguishable from ones users created.
    pass
