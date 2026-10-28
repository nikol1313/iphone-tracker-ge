"""merge products by parsed retailer title

Ingestion used to store each retailer's full title as the product model, so the
same phone from different stores became separate products. Re-parse those titles
into model, storage and color, and merge products that now share an identity.

Revision ID: b7e2d91c4a10
Revises: cc72e50a0b18
Create Date: 2026-10-28 12:00:00

"""

from collections import defaultdict
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.services.normalization import parse_iphone_title, product_identity_key

revision: str = "b7e2d91c4a10"
down_revision: str | Sequence[str] | None = "cc72e50a0b18"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _merge_listing(connection: sa.Connection, survivor_id: int, listing) -> None:
    existing = connection.execute(
        sa.text(
            "SELECT id, last_checked_at FROM product_listing "
            "WHERE product_id = :product_id AND store_id = :store_id"
        ),
        {"product_id": survivor_id, "store_id": listing.store_id},
    ).one_or_none()

    if existing is None:
        connection.execute(
            sa.text("UPDATE product_listing SET product_id = :product_id WHERE id = :id"),
            {"product_id": survivor_id, "id": listing.id},
        )
        return

    # Keep the more recently checked listing and fold the other's history into it.
    keep, drop = (
        (listing.id, existing.id)
        if listing.last_checked_at > existing.last_checked_at
        else (existing.id, listing.id)
    )
    connection.execute(
        sa.text("UPDATE price_history SET listing_id = :keep WHERE listing_id = :drop"),
        {"keep": keep, "drop": drop},
    )
    connection.execute(
        sa.text("DELETE FROM product_listing WHERE id = :drop"),
        {"drop": drop},
    )
    connection.execute(
        sa.text("UPDATE product_listing SET product_id = :product_id WHERE id = :id"),
        {"product_id": survivor_id, "id": keep},
    )


def _move_user_rows(
    connection: sa.Connection,
    table: str,
    survivor_id: int,
    duplicate_id: int,
) -> None:
    # A user who already has the survivor keeps that row; the duplicate is dropped.
    connection.execute(
        sa.text(
            f"DELETE FROM {table} WHERE product_id = :duplicate AND user_id IN "
            f"(SELECT user_id FROM {table} WHERE product_id = :survivor)"
        ),
        {"duplicate": duplicate_id, "survivor": survivor_id},
    )
    connection.execute(
        sa.text(f"UPDATE {table} SET product_id = :survivor WHERE product_id = :duplicate"),
        {"duplicate": duplicate_id, "survivor": survivor_id},
    )


def upgrade() -> None:
    connection = op.get_bind()
    products = connection.execute(
        sa.text(
            "SELECT id, brand, model, storage, color, identity_key, image_url "
            "FROM products ORDER BY id"
        )
    ).all()

    targets: dict[int, tuple[str, str | None, str | None]] = {}
    groups: dict[str, list] = defaultdict(list)
    for product in products:
        target = (product.model, product.storage, product.color)
        # Only ingestion-created rows hold a raw title with no storage or color.
        if product.storage is None and product.color is None:
            parsed = parse_iphone_title(product.model)
            if parsed is not None:
                target = (parsed.model, parsed.storage, parsed.color)
        targets[product.id] = target
        groups[product_identity_key(product.brand, *target)].append(product)

    changed: list[tuple[int, str]] = []
    for identity_key, members in groups.items():
        survivor = next(
            (member for member in members if member.identity_key == identity_key),
            members[0],
        )
        for duplicate in members:
            if duplicate.id == survivor.id:
                continue
            connection.execute(
                sa.text(
                    "UPDATE product_listing SET variant_name = :title "
                    "WHERE product_id = :id AND variant_name IS NULL"
                ),
                {"title": duplicate.model[:100], "id": duplicate.id},
            )
            for listing in connection.execute(
                sa.text(
                    "SELECT id, store_id, last_checked_at FROM product_listing "
                    "WHERE product_id = :id"
                ),
                {"id": duplicate.id},
            ).all():
                _merge_listing(connection, survivor.id, listing)
            _move_user_rows(connection, "tracked_products", survivor.id, duplicate.id)
            _move_user_rows(connection, "price_alerts", survivor.id, duplicate.id)
            if survivor.image_url is None and duplicate.image_url is not None:
                connection.execute(
                    sa.text("UPDATE products SET image_url = :url WHERE id = :id"),
                    {"url": duplicate.image_url, "id": survivor.id},
                )
            connection.execute(
                sa.text("DELETE FROM products WHERE id = :id"),
                {"id": duplicate.id},
            )

        if (
            survivor.identity_key != identity_key
            or targets[survivor.id] != (survivor.model, survivor.storage, survivor.color)
        ):
            connection.execute(
                sa.text(
                    "UPDATE product_listing SET variant_name = :title "
                    "WHERE product_id = :id AND variant_name IS NULL"
                ),
                {"title": survivor.model[:100], "id": survivor.id},
            )
            changed.append((survivor.id, identity_key))

    # Two passes so a survivor never collides with a key another survivor is leaving.
    for product_id, _ in changed:
        connection.execute(
            sa.text("UPDATE products SET identity_key = :key WHERE id = :id"),
            {"key": f"merging:{product_id}", "id": product_id},
        )
    for product_id, identity_key in changed:
        model, storage, color = targets[product_id]
        connection.execute(
            sa.text(
                "UPDATE products SET model = :model, storage = :storage, "
                "color = :color, identity_key = :key WHERE id = :id"
            ),
            {
                "model": model,
                "storage": storage,
                "color": color,
                "key": identity_key,
                "id": product_id,
            },
        )


def downgrade() -> None:
    # Merged products cannot be split again; the next crawl recreates listings.
    pass
