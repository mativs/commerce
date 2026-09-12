"""Add customer records and associate them with orders when payment starts."""

import sqlalchemy as sa
from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "customers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("first_name", sa.String(100), nullable=False),
        sa.Column("last_name", sa.String(100), nullable=False),
        sa.Column("phone", sa.String(50), nullable=False),
        sa.Column("email", sa.String(254), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("email = lower(btrim(email))", name="email_normalized"),
        sa.UniqueConstraint("email", name="uq_customers_email"),
    )
    op.add_column("orders", sa.Column("customer_id", sa.Integer()))
    op.create_foreign_key(
        "fk_orders_customer_id_customers",
        "orders",
        "customers",
        ["customer_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_orders_customer_id", "orders", ["customer_id"])


def downgrade() -> None:
    op.drop_index("ix_orders_customer_id", table_name="orders")
    op.drop_constraint("fk_orders_customer_id_customers", "orders", type_="foreignkey")
    op.drop_column("orders", "customer_id")
    op.drop_table("customers")
