"""P11 : budgets et attentes persistants ; historiques sans identité inventée."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("jobs", sa.Column("retry_count", sa.Integer(), nullable=False,
                                   server_default="0"))
    op.add_column("jobs", sa.Column("queued_at", sa.DateTime(timezone=True)))
    op.execute("UPDATE jobs SET queued_at = created_at")
    op.alter_column("jobs", "queued_at", nullable=False, server_default=sa.func.now())
    op.add_column("jobs", sa.Column("cycle_key", sa.String(64)))
    op.add_column("jobs", sa.Column("input_snapshot", JSONB(none_as_null=True)))
    op.create_check_constraint("ck_job_retry_count", "jobs", "retry_count BETWEEN 0 AND 2")
    op.create_check_constraint("ck_job_cycle", "jobs",
        "(cycle_key IS NULL AND input_snapshot IS NULL) OR "
        "(cycle_key IS NOT NULL AND input_snapshot IS NOT NULL "
        "AND cycle_key ~ '^[a-f0-9]{64}$' AND jsonb_typeof(input_snapshot) = 'object')")
    op.create_index("ix_jobs_cycle", "jobs", ["dream_id", "kind", "cycle_key"])


def downgrade():
    op.execute("DO $$ BEGIN IF EXISTS (SELECT 1 FROM jobs WHERE cycle_key IS NOT NULL "
               "OR retry_count <> 0) THEN RAISE EXCEPTION "
               "'Downgrade refuse: donnees P11 presentes'; END IF; END $$")
    op.drop_index("ix_jobs_cycle", table_name="jobs")
    op.drop_constraint("ck_job_cycle", "jobs", type_="check")
    op.drop_constraint("ck_job_retry_count", "jobs", type_="check")
    for name in ["input_snapshot", "cycle_key", "queued_at", "retry_count"]:
        op.drop_column("jobs", name)
