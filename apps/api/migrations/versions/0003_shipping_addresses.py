"""Create audited shipping addresses with geocoded coordinates."""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The trigger function already uses TG_TABLE_NAME and JSON snapshots for any table.
    # Renaming retains its identity, including the existing warehouse trigger binding.
    op.execute("ALTER FUNCTION audit_warehouse_change() RENAME TO audit_record_change")
    op.create_table(
        "shipping_addresses",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("recipient_name", sa.String(255), nullable=False),
        sa.Column("phone", sa.String(50)),
        sa.Column("address_line1", sa.String(255), nullable=False),
        sa.Column("address_line2", sa.String(255)),
        sa.Column("city", sa.String(100), nullable=False),
        sa.Column("state", sa.String(100), nullable=False),
        sa.Column("postal_code", sa.String(20), nullable=False),
        sa.Column("country_code", sa.String(2), nullable=False),
        sa.Column("delivery_instructions", sa.String(1000)),
        sa.Column("latitude", sa.Double(), nullable=False),
        sa.Column("longitude", sa.Double(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("latitude BETWEEN -90 AND 90", name="latitude_range"),
        sa.CheckConstraint("longitude BETWEEN -180 AND 180", name="longitude_range"),
    )
    op.execute("""
        CREATE TRIGGER shipping_address_audit BEFORE INSERT OR UPDATE OR DELETE
        ON shipping_addresses
        FOR EACH ROW EXECUTE FUNCTION audit_record_change()
    """)


def downgrade() -> None:
    op.drop_table("shipping_addresses")
    op.execute("ALTER FUNCTION audit_record_change() RENAME TO audit_warehouse_change")
