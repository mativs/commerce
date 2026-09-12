"""Separate client order and server payment idempotency keys."""

from uuid import uuid4

import sqlalchemy as sa
from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("orders", "idempotency_key", new_column_name="order_idempotency_key")
    # Keep both fields nullable while the legacy rows are being migrated.
    op.alter_column("orders", "order_idempotency_key", nullable=True)
    op.add_column(
        "orders", sa.Column("payment_idempotency_key", sa.String(128), nullable=True)
    )
    connection = op.get_bind()
    # Data migration: legacy orders receive independent backend-generated keys.
    order_ids = connection.execute(
        sa.text("SELECT id FROM orders WHERE order_idempotency_key IS NULL")
    ).scalars().all()
    for order_id in order_ids:
        connection.execute(
            sa.text(
                "UPDATE orders SET order_idempotency_key = :order_key WHERE id = :order_id"
            ),
            {
                "order_key": f"legacy-order:{uuid4()}",
                "order_id": order_id,
            },
        )
    payment_order_ids = connection.execute(
        sa.text("SELECT id FROM orders WHERE payment_idempotency_key IS NULL")
    ).scalars().all()
    for order_id in payment_order_ids:
        connection.execute(
            sa.text(
                "UPDATE orders SET payment_idempotency_key = :payment_key WHERE id = :order_id"
            ),
            {"payment_key": f"payment:{uuid4()}", "order_id": order_id},
        )
    # Schema migration: all current and future orders must have both identities.
    op.alter_column("orders", "order_idempotency_key", nullable=False)
    op.alter_column("orders", "payment_idempotency_key", nullable=False)
    op.create_unique_constraint(
        "uq_orders_payment_idempotency_key", "orders", ["payment_idempotency_key"]
    )


def downgrade() -> None:
    op.drop_constraint("uq_orders_payment_idempotency_key", "orders", type_="unique")
    op.drop_column("orders", "payment_idempotency_key")
    op.alter_column("orders", "order_idempotency_key", nullable=True)
    op.alter_column("orders", "order_idempotency_key", new_column_name="idempotency_key")
