"""Populate five warehouses, five shipping addresses and 10 demo products.

Fixed data keeps fresh installations reproducible. Audit triggers remain enabled.
"""

import sqlalchemy as sa
from alembic import op

from app.infrastructure.demo_data import SHIPPING_ADDRESSES, WAREHOUSES, product_rows

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    warehouses = sa.table(
        "warehouses",
        sa.column("name", sa.String()),
        sa.column("latitude", sa.Float()),
        sa.column("longitude", sa.Float()),
    )
    addresses = sa.table(
        "shipping_addresses",
        sa.column("recipient_name", sa.String()),
        sa.column("address_line1", sa.String()),
        sa.column("address_line2", sa.String()),
        sa.column("city", sa.String()),
        sa.column("state", sa.String()),
        sa.column("postal_code", sa.String()),
        sa.column("country_code", sa.String()),
        sa.column("latitude", sa.Float()),
        sa.column("longitude", sa.Float()),
    )
    products = sa.table(
        "products",
        sa.column("name", sa.String()),
        sa.column("sku", sa.String()),
        sa.column("ean", sa.String()),
        sa.column("price", sa.Numeric(12, 2)),
        sa.column("currency", sa.String()),
    )
    # No conflict suppression: an existing SKU/EAN rolls back the entire migration
    # rather than silently omitting products or overwriting user data.
    op.bulk_insert(warehouses, WAREHOUSES)
    op.bulk_insert(
        addresses,
        [
            {
                **address,
                "city": "Mar del Plata",
                "state": "Buenos Aires",
                "postal_code": "B7600",
                "country_code": "AR",
            }
            for address in SHIPPING_ADDRESSES
        ],
    )
    op.bulk_insert(products, product_rows())


def downgrade() -> None:
    raise NotImplementedError(
        "Demo data cannot be automatically removed after it may have been edited or referenced."
    )
