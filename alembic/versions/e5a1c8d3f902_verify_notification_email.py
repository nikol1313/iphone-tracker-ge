"""require a verified address before emailing price alerts

Revision ID: e5a1c8d3f902
Revises: d4b9e7a1c205
Create Date: 2026-10-29 15:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e5a1c8d3f902"
down_revision: str | Sequence[str] | None = "d4b9e7a1c205"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Existing addresses start unverified: nobody has proven they own them yet.
    op.add_column(
        "users",
        sa.Column(
            "notification_email_verified_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "verification_email_sent_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "verification_email_sent_at")
    op.drop_column("users", "notification_email_verified_at")
