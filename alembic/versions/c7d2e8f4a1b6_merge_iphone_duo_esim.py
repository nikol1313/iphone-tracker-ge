"""merge "iPhone Duo eSIM" into "iPhone Duo": the Duo is sold only as eSIM

Revision ID: c7d2e8f4a1b6
Revises: f8c2d6a41b93
Create Date: 2026-11-07 12:00:00

"""

from collections.abc import Sequence

from alembic import op

revision: str = "c7d2e8f4a1b6"
down_revision: str | Sequence[str] | None = "f8c2d6a41b93"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Each "iPhone Duo eSIM" product paired with its "iPhone Duo" twin, if one exists.
TWINS = """
    SELECT esim.id AS old_id, plain.id AS new_id
    FROM products esim
    JOIN products plain
      ON plain.brand = esim.brand
     AND plain.model = 'iPhone Duo'
     AND plain.storage IS NOT DISTINCT FROM esim.storage
     AND plain.color IS NOT DISTINCT FROM esim.color
    WHERE esim.model = 'iPhone Duo eSIM'
"""


def upgrade() -> None:
    # Listings move to the twin unless that store already lists it there.
    op.execute(f"""
        UPDATE product_listing l SET product_id = t.new_id
        FROM ({TWINS}) t
        WHERE l.product_id = t.old_id
          AND NOT EXISTS (
              SELECT 1 FROM product_listing o
              WHERE o.product_id = t.new_id AND o.store_id = l.store_id
          )
    """)
    for table in ("tracked_products", "price_alerts"):
        op.execute(f"""
            UPDATE {table} r SET product_id = t.new_id
            FROM ({TWINS}) t
            WHERE r.product_id = t.old_id
              AND NOT EXISTS (
                  SELECT 1 FROM {table} o
                  WHERE o.product_id = t.new_id AND o.user_id = r.user_id
              )
        """)
    # What could not move duplicates the twin; retire it with the old product.
    op.execute(f"""
        UPDATE product_listing SET is_active = false, external_product_id = NULL
        WHERE product_id IN (SELECT old_id FROM ({TWINS}) t)
    """)
    for table in ("tracked_products", "price_alerts"):
        op.execute(f"DELETE FROM {table} WHERE product_id IN (SELECT old_id FROM ({TWINS}) t)")
    op.execute(f"UPDATE products SET is_active = false WHERE id IN (SELECT old_id FROM ({TWINS}) t)")

    # Without a twin, the product is renamed in place.
    op.execute("""
        UPDATE products
        SET model = 'iPhone Duo',
            identity_key = replace(identity_key, 'iphone duo esim', 'iphone duo')
        WHERE model = 'iPhone Duo eSIM' AND is_active
    """)
    op.execute("""
        DELETE FROM model_specs
        WHERE model = 'iPhone Duo eSIM'
          AND EXISTS (SELECT 1 FROM model_specs WHERE model = 'iPhone Duo')
    """)
    op.execute("UPDATE model_specs SET model = 'iPhone Duo' WHERE model = 'iPhone Duo eSIM'")


def downgrade() -> None:
    # The merge is not undone: nothing tells which rows were eSIM before.
    pass
