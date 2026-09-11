"""Create audited stock balances per warehouse and product."""

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "stock",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "warehouse_id",
            sa.Integer(),
            sa.ForeignKey("warehouses.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "product_id",
            sa.Integer(),
            sa.ForeignKey("products.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("on_hand", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("reserved", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("warehouse_id", "product_id", name="uq_stock_warehouse_product"),
        sa.CheckConstraint("on_hand >= 0", name="on_hand_nonnegative"),
        sa.CheckConstraint("reserved >= 0", name="reserved_nonnegative"),
        sa.CheckConstraint("reserved <= on_hand", name="reserved_within_on_hand"),
    )
    op.create_index("ix_stock_product_id", "stock", ["product_id"])
    op.execute("""
        CREATE TRIGGER stock_audit BEFORE INSERT OR UPDATE OR DELETE ON stock
        FOR EACH ROW EXECUTE FUNCTION audit_record_change()
    """)


def downgrade() -> None:
    op.drop_table("stock")
