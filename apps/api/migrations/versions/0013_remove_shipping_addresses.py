"""Remove saved addresses; shipping details remain on each order."""

from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Migration 0009 already copied legacy addresses into order snapshots.
    op.drop_column("orders", "shipping_address_id")
    op.drop_table("shipping_addresses")


def downgrade() -> None:
    raise NotImplementedError("Removed saved addresses cannot be restored automatically.")
