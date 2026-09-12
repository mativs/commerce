"""Remove soft-delete state from stock balances."""

import sqlalchemy as sa
from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("stock", "deleted_at")


def downgrade() -> None:
    op.add_column("stock", sa.Column("deleted_at", sa.DateTime(timezone=True)))
