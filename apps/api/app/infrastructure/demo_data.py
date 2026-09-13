"""Deterministic catalog data used by the initial migration and demo reset."""

import csv
from decimal import Decimal
from io import StringIO

WAREHOUSES = [
    {"name": "Mar del Plata Central Warehouse", "latitude": -37.991, "longitude": -57.566},
    {"name": "Mar del Plata North Distribution Center", "latitude": -37.991, "longitude": -57.582},
    {"name": "Mar del Plata West Supply Depot", "latitude": -37.995, "longitude": -57.578},
    {"name": "Mar del Plata South Warehouse", "latitude": -38.003, "longitude": -57.574},
    {"name": "Mar del Plata Trade Counter", "latitude": -37.999, "longitude": -57.570},
]

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
