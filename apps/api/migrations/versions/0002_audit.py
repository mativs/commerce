"""Add timestamps, soft deletion and transactional database audit logs."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for name in ("created_at", "updated_at"):
        op.add_column(
            "warehouses",
            sa.Column(
                name, sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
            ),
        )
    op.add_column("warehouses", sa.Column("deleted_at", sa.DateTime(timezone=True)))
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("table_name", sa.String(255), nullable=False),
        sa.Column("record_id", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(10), nullable=False),
        sa.Column("old_values", postgresql.JSONB()),
        sa.Column("new_values", postgresql.JSONB()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
    )
    op.execute("""
        CREATE FUNCTION audit_warehouse_change() RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE change_action text;
        BEGIN
            IF TG_OP = 'UPDATE' THEN
                NEW.created_at := OLD.created_at;
                NEW.updated_at := clock_timestamp();
                change_action := CASE WHEN OLD.deleted_at IS NULL AND NEW.deleted_at IS NOT NULL
                    THEN 'delete' ELSE 'update' END;
                INSERT INTO audit_logs (table_name, record_id, action, old_values, new_values)
                VALUES (TG_TABLE_NAME, NEW.id, change_action, to_jsonb(OLD), to_jsonb(NEW));
                RETURN NEW;
            ELSIF TG_OP = 'INSERT' THEN
                INSERT INTO audit_logs (table_name, record_id, action, new_values)
                VALUES (TG_TABLE_NAME, NEW.id, 'create', to_jsonb(NEW));
                RETURN NEW;
            ELSE
                INSERT INTO audit_logs (table_name, record_id, action, old_values)
                VALUES (TG_TABLE_NAME, OLD.id, 'delete', to_jsonb(OLD));
                RETURN OLD;
            END IF;
        END;
        $$
    """)
    op.execute("""
        CREATE TRIGGER warehouse_audit BEFORE INSERT OR UPDATE OR DELETE ON warehouses
        FOR EACH ROW EXECUTE FUNCTION audit_warehouse_change()
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER warehouse_audit ON warehouses")
    op.execute("DROP FUNCTION audit_warehouse_change()")
    op.drop_table("audit_logs")
    for name in ("deleted_at", "updated_at", "created_at"):
        op.drop_column("warehouses", name)
