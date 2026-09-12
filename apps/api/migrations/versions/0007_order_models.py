"""Create orders and immutable status history with database wall-clock timestamps."""

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "orders",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("status", sa.String(10), nullable=False, server_default="CREATED"),
        sa.Column(
            "shipping_address_id",
            sa.Integer(),
            sa.ForeignKey("shipping_addresses.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "warehouse_id", sa.Integer(), sa.ForeignKey("warehouses.id", ondelete="RESTRICT")
        ),
        sa.Column("total_amount", sa.Numeric(22, 2), nullable=False, server_default="0"),
        sa.Column("notes", sa.String(2000)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.clock_timestamp(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.clock_timestamp(),
        ),
        sa.CheckConstraint(
            "status IN ('CREATED', 'BOOKED', 'PAID', 'CANCELLED')", name="status_valid"
        ),
        sa.CheckConstraint(
            "total_amount >= 0 AND total_amount < 'Infinity'::numeric", name="total_valid"
        ),
    )
    op.create_index("ix_orders_shipping_address_id", "orders", ["shipping_address_id"])
    op.create_index("ix_orders_warehouse_id", "orders", ["warehouse_id"])
    op.create_table(
        "order_status_history",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "order_id",
            sa.Integer(),
            sa.ForeignKey("orders.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("status", sa.String(10), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.clock_timestamp(),
        ),
        sa.CheckConstraint(
            "status IN ('CREATED', 'BOOKED', 'PAID', 'CANCELLED')", name="status_valid"
        ),
    )
    op.create_index(
        "ix_order_status_history_chronology",
        "order_status_history",
        ["order_id", "created_at", "id"],
    )
    op.execute("""
        CREATE FUNCTION touch_order_timestamp() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            NEW.created_at := OLD.created_at;
            NEW.updated_at := clock_timestamp();
            RETURN NEW;
        END;
        $$
    """)
    op.execute("""
        CREATE TRIGGER order_timestamp BEFORE UPDATE ON orders
        FOR EACH ROW EXECUTE FUNCTION touch_order_timestamp()
    """)
    op.execute("""
        CREATE FUNCTION record_order_status() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'INSERT' THEN
                INSERT INTO order_status_history (order_id, status) VALUES (NEW.id, NEW.status);
            ELSIF NEW.status IS DISTINCT FROM OLD.status THEN
                INSERT INTO order_status_history (order_id, status) VALUES (NEW.id, NEW.status);
            END IF;
            RETURN NEW;
        END;
        $$
    """)
    op.execute("""
        CREATE TRIGGER order_status_record AFTER INSERT OR UPDATE ON orders
        FOR EACH ROW EXECUTE FUNCTION record_order_status()
    """)
    op.execute("""
        CREATE FUNCTION reject_order_removal() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'Orders cannot be deleted; use cancellation.';
        END;
        $$
    """)
    op.execute("""
        CREATE TRIGGER order_no_delete BEFORE DELETE ON orders
        FOR EACH ROW EXECUTE FUNCTION reject_order_removal()
    """)
    op.execute("""
        CREATE FUNCTION protect_order_status_history() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'Order status history is append-only.';
        END;
        $$
    """)
    op.execute("""
        CREATE TRIGGER order_status_history_immutable BEFORE UPDATE OR DELETE
        ON order_status_history
        FOR EACH ROW EXECUTE FUNCTION protect_order_status_history()
    """)


def downgrade() -> None:
    op.drop_table("order_status_history")
    op.drop_table("orders")
    op.execute("DROP FUNCTION protect_order_status_history()")
    op.execute("DROP FUNCTION reject_order_removal()")
    op.execute("DROP FUNCTION record_order_status()")
    op.execute("DROP FUNCTION touch_order_timestamp()")
