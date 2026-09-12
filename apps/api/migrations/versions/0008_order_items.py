"""Add order items with database-captured unit prices."""

import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "order_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "order_id",
            sa.Integer(),
            sa.ForeignKey("orders.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "product_id",
            sa.Integer(),
            sa.ForeignKey("products.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("unit_price", sa.Numeric(12, 2), nullable=False),
        sa.UniqueConstraint("order_id", "product_id", name="uq_order_items_order_product"),
        sa.CheckConstraint("quantity > 0", name="quantity_positive"),
        sa.CheckConstraint(
            "unit_price >= 0 AND unit_price < 'Infinity'::numeric", name="price_valid"
        ),
    )
    op.create_index("ix_order_items_product_id", "order_items", ["product_id"])
    op.execute("""
        CREATE FUNCTION set_order_item_values() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'INSERT' THEN
                SELECT price INTO NEW.unit_price FROM products WHERE id = NEW.product_id;
                IF NOT FOUND THEN
                    RAISE EXCEPTION 'Product % does not exist', NEW.product_id
                        USING ERRCODE = '23503';
                END IF;
            ELSE
                IF NEW.order_id IS DISTINCT FROM OLD.order_id
                    OR NEW.product_id IS DISTINCT FROM OLD.product_id
                    OR NEW.unit_price IS DISTINCT FROM OLD.unit_price THEN
                    RAISE EXCEPTION 'Order item references and captured price cannot be changed.';
                END IF;
            END IF;
            RETURN NEW;
        END;
        $$
    """)
    op.execute("""
        CREATE TRIGGER order_item_values BEFORE INSERT OR UPDATE ON order_items
        FOR EACH ROW EXECUTE FUNCTION set_order_item_values()
    """)


def downgrade() -> None:
    op.drop_table("order_items")
    op.execute("DROP FUNCTION set_order_item_values()")
