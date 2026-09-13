"""Allow the shared audit trigger to handle tables without soft deletion."""

from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE OR REPLACE FUNCTION audit_record_change() RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE change_action text;
        BEGIN
            IF TG_OP = 'UPDATE' THEN
                NEW.created_at := OLD.created_at;
                NEW.updated_at := clock_timestamp();
                change_action := CASE
                    WHEN (to_jsonb(OLD)->>'deleted_at') IS NULL
                     AND (to_jsonb(NEW)->>'deleted_at') IS NOT NULL
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


def downgrade() -> None:
    # This function also supports the older soft-delete schema. Keep the fix rather
    # than restore a trigger that breaks stock updates at revision 0016.
    pass
