"""Populate warehouses with overlapping demo assortments and varied stock levels."""

import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Rank records instead of assuming IDs from the initial seed. With five warehouses
    # and 10 products, two are shared by all warehouses, plus a rotating assortment.
    # Keep existing balances, reservations, and soft-deleted stock completely unchanged.
    op.execute(
        sa.text("""
        WITH warehouse_catalog AS (
            SELECT id, row_number() OVER (ORDER BY id) - 1 AS position
            FROM warehouses WHERE deleted_at IS NULL
        ), product_catalog AS (
            SELECT id, row_number() OVER (ORDER BY sku, id) - 1 AS position
            FROM products
            WHERE deleted_at IS NULL AND is_active AND currency = 'USD'
        )
        INSERT INTO stock (warehouse_id, product_id, on_hand, reserved)
        SELECT w.id, p.id, (5 + (p.position * 7 + w.position * 13) % 46)::integer, 0
        FROM warehouse_catalog w CROSS JOIN product_catalog p
        WHERE (p.position < 2 OR (p.position + w.position) % 5 < 3)
          AND NOT EXISTS (
              SELECT 1 FROM stock s WHERE s.warehouse_id = w.id AND s.product_id = p.id
          )
        ORDER BY w.id, p.id
        ON CONFLICT (warehouse_id, product_id) DO NOTHING
    """)
    )


def downgrade() -> None:
    raise NotImplementedError(
        "Demo stock cannot be automatically removed after it may have been reserved or adjusted."
    )
