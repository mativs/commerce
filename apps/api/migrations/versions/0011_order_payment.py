"""Store checkout payment input and provider references on orders."""

import sqlalchemy as sa
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("orders", sa.Column("credit_card_number", sa.String(19)))
    op.add_column("orders", sa.Column("payment_description", sa.String(255)))
    op.add_column("orders", sa.Column("payment_identifier", sa.String(128)))
    op.create_unique_constraint("uq_orders_payment_identifier", "orders", ["payment_identifier"])


def downgrade() -> None:
    op.drop_constraint("uq_orders_payment_identifier", "orders", type_="unique")
    op.drop_column("orders", "payment_identifier")
    op.drop_column("orders", "payment_description")
    op.drop_column("orders", "credit_card_number")
