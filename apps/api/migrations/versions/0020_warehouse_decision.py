"""Save the warehouse selection evidence on each order."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("orders", sa.Column("warehouse_decision", JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("orders", "warehouse_decision")
