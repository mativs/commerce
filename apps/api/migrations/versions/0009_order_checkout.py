"""Add order checkout snapshots, idempotency, and cancellation reasons."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for column in ("latitude", "longitude"):
        op.alter_column("shipping_addresses", column, nullable=True)
    op.alter_column("orders", "shipping_address_id", nullable=True)
    op.add_column(
        "orders", sa.Column("shipping_address", JSONB, nullable=False, server_default="{}")
    )
    op.add_column("orders", sa.Column("latitude", sa.Float()))
    op.add_column("orders", sa.Column("longitude", sa.Float()))
    op.add_column("orders", sa.Column("idempotency_key", sa.String(128)))
    op.add_column("orders", sa.Column("request_hash", sa.String(64)))
    op.add_column("orders", sa.Column("failure_reason", sa.String(40)))
    op.create_unique_constraint("uq_orders_idempotency_key", "orders", ["idempotency_key"])
    op.create_check_constraint("latitude_range", "orders", "latitude BETWEEN -90 AND 90")
    op.create_check_constraint("longitude_range", "orders", "longitude BETWEEN -180 AND 180")
    op.create_check_constraint(
        "coordinates_pair", "orders", "(latitude IS NULL) = (longitude IS NULL)"
    )
    op.add_column("order_status_history", sa.Column("reason", sa.String(40)))
    op.execute("""
        UPDATE orders o SET shipping_address = jsonb_build_object(
            'recipient_name', a.recipient_name, 'phone', a.phone,
            'address_line1', a.address_line1, 'address_line2', a.address_line2,
            'city', a.city, 'state', a.state, 'postal_code', a.postal_code,
            'country_code', a.country_code, 'delivery_instructions', a.delivery_instructions
        ), latitude=a.latitude, longitude=a.longitude
        FROM shipping_addresses a WHERE a.id=o.shipping_address_id
    """)
    op.execute("""
        CREATE OR REPLACE FUNCTION record_order_status() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'INSERT' THEN
                INSERT INTO order_status_history (order_id, status, reason)
                VALUES (NEW.id, NEW.status, NEW.failure_reason);
            ELSIF NEW.status IS DISTINCT FROM OLD.status THEN
                INSERT INTO order_status_history (order_id, status, reason)
                VALUES (NEW.id, NEW.status, NEW.failure_reason);
            END IF;
            RETURN NEW;
        END;
        $$
    """)


def downgrade() -> None:
    # Orders created from inline addresses cannot be represented by the previous schema.
    # Refuse rather than discard orders or fabricate address coordinates.
    connection = op.get_bind()
    if connection.scalar(
        sa.text("SELECT EXISTS (SELECT 1 FROM orders WHERE shipping_address_id IS NULL)")
    ):
        raise RuntimeError("Cannot downgrade inline shipping addresses to required address IDs.")
    if connection.scalar(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM shipping_addresses "
            "WHERE latitude IS NULL OR longitude IS NULL)"
        )
    ):
        raise RuntimeError("Cannot downgrade addresses without coordinates.")
    op.execute("""
        CREATE OR REPLACE FUNCTION record_order_status() RETURNS trigger LANGUAGE plpgsql AS $$
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
    op.drop_column("order_status_history", "reason")
    for name in ("latitude_range", "longitude_range", "coordinates_pair"):
        op.drop_constraint(op.f(f"ck_orders_{name}"), "orders", type_="check")
    op.drop_constraint("uq_orders_idempotency_key", "orders", type_="unique")
    for column in (
        "shipping_address",
        "latitude",
        "longitude",
        "idempotency_key",
        "request_hash",
        "failure_reason",
    ):
        op.drop_column("orders", column)
    op.alter_column("orders", "shipping_address_id", nullable=False)
    for column in ("latitude", "longitude"):
        op.alter_column("shipping_addresses", column, nullable=False)
