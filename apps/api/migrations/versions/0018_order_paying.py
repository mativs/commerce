"""Record payment initiation as a durable order status."""

from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table in ("orders", "order_status_history"):
        op.drop_constraint(op.f(f"ck_{table}_status_valid"), table, type_="check")
        op.create_check_constraint(
            op.f(f"ck_{table}_status_valid"),
            table,
            "status IN ('CREATED', 'BOOKED', 'PAYING', 'PAID', 'CANCELLED')",
        )


def downgrade() -> None:
    # Reject downgrade when PAYING exists, preserving append-only history.
    for table in ("orders", "order_status_history"):
        op.drop_constraint(op.f(f"ck_{table}_status_valid"), table, type_="check")
        op.create_check_constraint(
            op.f(f"ck_{table}_status_valid"),
            table,
            "status IN ('CREATED', 'BOOKED', 'PAID', 'CANCELLED')",
        )
