"""store the monthly installment price a store advertises for a listing

Revision ID: a7d3c2b19e44
Revises: e5a1c8d3f902
Create Date: 2026-11-01 16:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a7d3c2b19e44"
down_revision: str | Sequence[str] | None = "e5a1c8d3f902"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Nullable: most stores don't publish a monthly price; the next crawl fills the rest.
    op.add_column(
        "product_listing",
        sa.Column("installment_monthly", sa.Numeric(12, 2), nullable=True),
    )
    op.add_column(
        "product_listing",
        sa.Column("installment_months", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("product_listing", "installment_months")
    op.drop_column("product_listing", "installment_monthly")
