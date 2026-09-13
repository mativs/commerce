"""Populate five warehouses, five shipping addresses and 10 demo products.

Fixed data keeps fresh installations reproducible. Audit triggers remain enabled.
"""

import csv
from decimal import Decimal
from io import StringIO

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

WAREHOUSES = [
    {"name": "Mar del Plata Central Warehouse", "latitude": -37.991, "longitude": -57.566},
    {"name": "Mar del Plata North Distribution Center", "latitude": -37.991, "longitude": -57.582},
    {"name": "Mar del Plata West Supply Depot", "latitude": -37.995, "longitude": -57.578},
    {"name": "Mar del Plata South Warehouse", "latitude": -38.003, "longitude": -57.574},
    {"name": "Mar del Plata Trade Counter", "latitude": -37.999, "longitude": -57.570},
]

# Fictional recipients and delivery details with mock coordinates, not geocoded addresses.
SHIPPING_ADDRESSES = [
    {
        "recipient_name": "Centro Electrical Supplies",
        "address_line1": "San Martin 2500",
        "address_line2": "Local 1",
        "latitude": -37.990,
        "longitude": -57.565,
    },
    {
        "recipient_name": "Northside Plumbing Workshop",
        "address_line1": "Avenida Luro 4200",
        "address_line2": None,
        "latitude": -37.992,
        "longitude": -57.570,
    },
    {
        "recipient_name": "Westside Construction Depot",
        "address_line1": "Avenida Juan B. Justo 3600",
        "address_line2": "Deposito",
        "latitude": -38.000,
        "longitude": -57.585,
    },
    {
        "recipient_name": "Southside HVAC Service",
        "address_line1": "Avenida Independencia 3100",
        "address_line2": None,
        "latitude": -38.006,
        "longitude": -57.575,
    },
    {
        "recipient_name": "Harbor Maintenance Workshop",
        "address_line1": "12 de Octubre 3300",
        "address_line2": "Taller",
        "latitude": -38.008,
        "longitude": -57.580,
    },
]

# Ten distinct everyday ecommerce products with valid demo EANs; prices are USD.
PRODUCT_CSV = """\
name,sku,ean,price
Wireless Headphones,HEADPHONES,8100000000016,59.99
Coffee Maker,COFFEE-MAKER,8100000000023,79.90
Travel Backpack,BACKPACK,8100000000030,39.50
Yoga Mat,YOGA-MAT,8100000000047,24.99
Desk Lamp,DESK-LAMP,8100000000054,32.00
Stainless Steel Water Bottle,WATER-BOTTLE,8100000000061,18.50
Board Game,BOARD-GAME,8100000000078,29.99
Cotton Bath Towel,BATH-TOWEL,8100000000085,14.90
Nonstick Frying Pan,FRYING-PAN,8100000000092,34.99
Hardcover Notebook,NOTEBOOK,8100000000108,9.99
"""


def product_rows() -> list[dict]:
    return [
        {**row, "price": Decimal(row["price"]), "currency": "USD"}
        for row in csv.DictReader(StringIO(PRODUCT_CSV))
    ]


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
