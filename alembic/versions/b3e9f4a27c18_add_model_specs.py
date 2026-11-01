"""store phone specifications per model for the compare page

Revision ID: b3e9f4a27c18
Revises: a7d3c2b19e44
Create Date: 2026-11-01 20:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b3e9f4a27c18"
down_revision: str | Sequence[str] | None = "a7d3c2b19e44"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Empty at first; the next catalog refresh fetches specs for each model.
    op.create_table(
        "model_specs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("model", sa.String(100), nullable=False, unique=True),
        sa.Column("specs", sa.JSON(), nullable=False),
        sa.Column("source_url", sa.String(500), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("model_specs")
