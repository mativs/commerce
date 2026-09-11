"""Create products with reserved identifiers and transactional audit history."""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "products",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("sku", sa.String(100), nullable=False),
        sa.Column("ean", sa.String(13)),
        sa.Column("description", sa.String(2000)),
        sa.Column("price", sa.Numeric(12, 2), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("sku"),
        sa.UniqueConstraint("ean"),
        sa.CheckConstraint("price >= 0 AND price < 'Infinity'::numeric", name="price_range"),
        sa.CheckConstraint("sku = upper(btrim(sku)) AND length(sku) > 0", name="sku_normalized"),
        sa.CheckConstraint("currency ~ '^[A-Z]{3}$'", name="currency_format"),
        sa.CheckConstraint("ean IS NULL OR ean ~ '^([0-9]{8}|[0-9]{13})$'", name="ean_format"),
    )
    op.execute("""
        CREATE TRIGGER product_audit BEFORE INSERT OR UPDATE OR DELETE ON products
        FOR EACH ROW EXECUTE FUNCTION audit_record_change()
    """)


def downgrade() -> None:
    op.drop_table("products")
