"""Remove the unused product currency field."""

import sqlalchemy as sa
from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("products", "currency")


def downgrade() -> None:
    op.add_column("products", sa.Column("currency", sa.String(3), nullable=True))
    op.execute("UPDATE products SET currency = 'USD'")
    op.alter_column("products", "currency", nullable=False)
    op.create_check_constraint("currency_format", "products", "currency ~ '^[A-Z]{3}$'")
