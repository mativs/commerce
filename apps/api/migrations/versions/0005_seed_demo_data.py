"""Populate five warehouses, five shipping addresses and 100 demo products.

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

# Supplied catalog, with only EAN check digits corrected; prices are USD.
PRODUCT_CSV = """\
name,sku,ean,price
EMT Conduit 1/2 in x 10 ft,ELEC-EMT-050-10,8100000000016,8.49
EMT Conduit 3/4 in x 10 ft,ELEC-EMT-075-10,8100000000023,11.75
EMT Conduit 1 in x 10 ft,ELEC-EMT-100-10,8100000000030,17.95
EMT Compression Connector 1/2 in,ELEC-EMTC-050,8100000000047,1.29
EMT Compression Connector 3/4 in,ELEC-EMTC-075,8100000000054,1.69
EMT Compression Coupling 1/2 in,ELEC-EMTCP-050,8100000000061,1.45
EMT Compression Coupling 3/4 in,ELEC-EMTCP-075,8100000000078,1.89
THHN Copper Wire 12 AWG Black 500 ft,ELEC-THHN-12-BLK-500,8100000000085,89.50
THHN Copper Wire 12 AWG White 500 ft,ELEC-THHN-12-WHT-500,8100000000092,89.50
THHN Copper Wire 12 AWG Green 500 ft,ELEC-THHN-12-GRN-500,8100000000108,92.25
THHN Copper Wire 10 AWG Black 500 ft,ELEC-THHN-10-BLK-500,8100000000115,139.00
THHN Copper Wire 10 AWG Red 500 ft,ELEC-THHN-10-RED-500,8100000000122,139.00
NM-B Cable 12/2 with Ground 250 ft,ELEC-NMB-122-250,8100000000139,118.75
NM-B Cable 14/2 with Ground 250 ft,ELEC-NMB-142-250,8100000000146,84.95
Single Pole Circuit Breaker 20A,ELEC-CB-1P-20,8100000000153,12.49
Double Pole Circuit Breaker 30A,ELEC-CB-2P-30,8100000000160,27.95
Double Pole Circuit Breaker 50A,ELEC-CB-2P-50,8100000000177,31.50
Duplex Receptacle 20A 125V White,ELEC-REC-20-WHT,8100000000184,4.25
GFCI Receptacle 20A 125V White,ELEC-GFCI-20-WHT,8100000000191,18.75
4 in Square Steel Electrical Box,ELEC-BOX-4SQ,8100000000207,3.15
PVC Schedule 40 Pipe 1/2 in x 10 ft,PLMB-PVC40-050-10,8100000000214,6.95
PVC Schedule 40 Pipe 3/4 in x 10 ft,PLMB-PVC40-075-10,8100000000221,8.75
PVC Schedule 40 Pipe 1 in x 10 ft,PLMB-PVC40-100-10,8100000000238,12.40
PVC Schedule 40 90 Degree Elbow 1/2 in,PLMB-PVC90-050,8100000000245,0.79
PVC Schedule 40 90 Degree Elbow 3/4 in,PLMB-PVC90-075,8100000000252,1.05
PVC Schedule 40 Tee 1 in,PLMB-PVCT-100,8100000000269,2.25
PVC Schedule 40 Coupling 1 in,PLMB-PVCC-100,8100000000276,1.15
PEX Tubing 1/2 in Red 100 ft,PLMB-PEX-050-RED-100,8100000000283,39.95
PEX Tubing 1/2 in Blue 100 ft,PLMB-PEX-050-BLU-100,8100000000290,39.95
PEX Brass Tee 1/2 in,PLMB-PEX-T-050,8100000000306,4.65
PEX Brass Elbow 1/2 in,PLMB-PEX-E-050,8100000000313,3.75
Ball Valve Brass 1/2 in FNPT,PLMB-BV-050,8100000000320,11.95
Ball Valve Brass 3/4 in FNPT,PLMB-BV-075,8100000000337,15.75
Pipe Thread Seal Tape 1/2 in x 520 in,PLMB-PTFE-050,8100000000344,1.45
Black Steel Pipe Nipple 1/2 in x 6 in,PVF-BSP-050-06,8100000000351,3.95
Black Malleable Iron Elbow 1/2 in 90 Degree,PVF-BMI90-050,8100000000368,2.75
Black Malleable Iron Tee 3/4 in,PVF-BMIT-075,8100000000375,4.95
Stainless Steel Ball Valve 1 in,PVF-SSBV-100,8100000000382,42.50
Carbon Steel Weld Neck Flange 2 in 150 lb,PVF-WNF-200-150,8100000000399,28.95
Carbon Steel Blind Flange 2 in 150 lb,PVF-BLF-200-150,8100000000405,24.75
HVAC Copper Tubing 3/8 in x 50 ft,HVAC-CU-038-50,8100000000412,74.95
HVAC Copper Tubing 3/4 in x 50 ft,HVAC-CU-075-50,8100000000429,149.50
Refrigerant Line Set 1/4 x 3/8 in 25 ft,HVAC-LS-1438-25,8100000000436,64.95
Refrigerant Line Set 3/8 x 3/4 in 50 ft,HVAC-LS-3875-50,8100000000443,139.95
Round Galvanized Duct 6 in x 5 ft,HVAC-DUCT-06-5,8100000000450,18.50
Round Galvanized Duct 8 in x 5 ft,HVAC-DUCT-08-5,8100000000467,24.95
Adjustable Duct Elbow 6 in 90 Degree,HVAC-ELB-06-90,8100000000474,9.25
Adjustable Duct Elbow 8 in 90 Degree,HVAC-ELB-08-90,8100000000481,12.50
Pleated Air Filter 16 x 20 x 1 in MERV 8,HVAC-FLT-16201-M8,8100000000498,8.95
Pleated Air Filter 20 x 25 x 1 in MERV 11,HVAC-FLT-20251-M11,8100000000504,13.75
Programmable Thermostat 24V,HVAC-THERM-PROG,8100000000511,44.95
Condensate Pump 120V,HVAC-COND-PUMP,8100000000528,69.50
HVAC Foil Tape 2 in x 50 yd,HVAC-TAPE-2-50,8100000000535,12.95
Pipe Insulation 3/4 in x 6 ft,HVAC-INS-075-6,8100000000542,5.75
Structural Lumber 2 x 4 x 8 ft SPF,LMBR-SPF-2X4X8,8100000000559,4.85
Structural Lumber 2 x 4 x 10 ft SPF,LMBR-SPF-2X4X10,8100000000566,6.45
Structural Lumber 2 x 6 x 8 ft SPF,LMBR-SPF-2X6X8,8100000000573,7.95
Pressure Treated Lumber 2 x 4 x 8 ft,LMBR-PT-2X4X8,8100000000580,8.75
Pressure Treated Lumber 4 x 4 x 8 ft,LMBR-PT-4X4X8,8100000000597,14.95
OSB Sheathing 7/16 in 4 x 8 ft,LMBR-OSB-716-48,8100000000603,16.75
CDX Plywood 1/2 in 4 x 8 ft,LMBR-CDX-050-48,8100000000610,31.50
Drywall Panel 1/2 in 4 x 8 ft,CONST-DW-050-48,8100000000627,13.25
Construction Adhesive 10 oz,CONST-ADH-10,8100000000634,5.95
Concrete Anchor 3/8 x 3 in 25 Pack,CONST-ANCH-383-25,8100000000641,21.95
Hex Head Lag Screw 3/8 x 4 in 25 Pack,CONST-LAG-384-25,8100000000658,18.75
Galvanized Deck Screw #10 x 3 in 5 lb,CONST-DS-103-5,8100000000665,29.95
Common Nail 16D 5 lb Box,CONST-NAIL-16D-5,8100000000672,14.50
Framing Hammer 22 oz,TOOL-HAM-FRM-22,8100000000689,34.95
Fiberglass Claw Hammer 16 oz,TOOL-HAM-CLW-16,8100000000696,18.50
Adjustable Wrench 10 in,TOOL-WRENCH-ADJ-10,8100000000702,21.95
Combination Wrench Set SAE 8 Piece,TOOL-WRENCH-SAE-8,8100000000719,44.50
Socket Set 3/8 in Drive 40 Piece,TOOL-SOCKET-38-40,8100000000726,69.95
Locking Pliers 10 in,TOOL-PLIER-LOCK-10,8100000000733,16.95
Diagonal Cutting Pliers 8 in,TOOL-PLIER-DIAG-8,8100000000740,19.75
Wire Stripper 10-20 AWG,TOOL-WIRE-STRIP,8100000000757,22.95
Utility Knife Retractable,TOOL-KNIFE-RET,8100000000764,9.95
Tape Measure 25 ft,TOOL-TAPE-25,8100000000771,14.75
Carbide Circular Saw Blade 7-1/4 in 24T,TOOL-SAW-725-24,8100000000788,17.95
Twist Drill Bit Set 1/16-1/2 in 29 Piece,TOOL-DRILL-29,8100000000795,54.95
Angle Grinder Cutting Disc 4-1/2 in 10 Pack,TOOL-DISC-45-10,8100000000801,19.50
Safety Glasses Clear Anti-Fog,SAFE-GLASS-CLR,8100000000818,7.95
Safety Glasses Smoke Anti-Fog,SAFE-GLASS-SMK,8100000000825,8.25
Hard Hat White Class E,SAFE-HH-WHT-E,8100000000832,24.95
Hard Hat Yellow Class E,SAFE-HH-YEL-E,8100000000849,24.95
High Visibility Safety Vest Class 2 Large,SAFE-VEST-C2-L,8100000000856,12.75
Nitrile Coated Work Gloves Large,SAFE-GLOVE-NIT-L,8100000000863,6.95
Cut Resistant Gloves Level A4 Large,SAFE-GLOVE-A4-L,8100000000870,11.95
Hearing Protection Earplugs 100 Pair,SAFE-EAR-100,8100000000887,24.50
Disposable N95 Respirator 20 Pack,SAFE-N95-20,8100000000894,29.95
First Aid Kit 50 Person,SAFE-FAK-50,8100000000900,54.95
ABC Dry Chemical Fire Extinguisher 5 lb,SAFE-FE-ABC-5,8100000000917,49.95
Multipurpose Lithium Grease 14 oz,MRO-GREASE-LI-14,8100000000924,8.95
Penetrating Lubricant 12 oz,MRO-LUBE-PEN-12,8100000000931,9.75
Electrical Contact Cleaner 11 oz,MRO-CLEAN-ELEC-11,8100000000948,12.50
Shop Towels Blue 200 Count,MRO-TOWEL-200,8100000000955,18.95
Cable Tie Black 11 in 100 Pack,MRO-TIE-11-100,8100000000962,9.95
Stainless Steel Hose Clamp 1/2-1-1/4 in 10 Pack,MRO-CLAMP-125-10,8100000000979,13.75
V-Belt A42 Industrial,IND-BELT-A42,8100000000986,17.95
Deep Groove Ball Bearing 6205-2RS,IND-BRG-6205-2RS,8100000000993,14.95
Roller Chain ANSI #40 10 ft,IND-CHAIN-40-10,8100000001006,42.50
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
