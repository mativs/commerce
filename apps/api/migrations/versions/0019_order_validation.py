"""Persist manually triggered order validation runs and their output."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "order_validation_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("idempotency_key", sa.String(128), nullable=False, unique=True),
        sa.Column("parameters", JSONB(), nullable=False),
        sa.Column("rules_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.clock_timestamp(),
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "status IN ('RUNNING','COMPLETED','PARTIAL','FAILED','INTERRUPTED')",
            name="status_valid",
        ),
    )
    op.create_table(
        "order_validation_check_results",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "run_id", sa.Integer(), sa.ForeignKey("order_validation_runs.id"), nullable=False
        ),
        sa.Column("check_code", sa.String(80), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("finding_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error", sa.String(255)),
        sa.UniqueConstraint("run_id", "check_code"),
        sa.CheckConstraint(
            "status IN ('PENDING','RUNNING','COMPLETED','FAILED','SKIPPED')", name="status_valid"
        ),
    )
    op.create_table(
        "order_validation_findings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "check_result_id",
            sa.Integer(),
            sa.ForeignKey("order_validation_check_results.id"),
            nullable=False,
        ),
        sa.Column("order_id", sa.Integer()),
        sa.Column("warehouse_id", sa.Integer()),
        sa.Column("product_id", sa.Integer()),
        sa.Column("severity", sa.String(20), nullable=False),
        sa.Column("evidence", JSONB(), nullable=False),
        sa.Column(
            "observed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.clock_timestamp(),
        ),
    )
    op.create_index(
        "ix_validation_findings_check", "order_validation_findings", ["check_result_id", "id"]
    )


def downgrade() -> None:
    op.drop_table("order_validation_findings")
    op.drop_table("order_validation_check_results")
    op.drop_table("order_validation_runs")
