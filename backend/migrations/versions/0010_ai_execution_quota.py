"""P12 : registre d'admission glissant commun aux trois moteurs."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("ai_quota_policy",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("execution_limit", sa.Integer(), nullable=False),
        sa.CheckConstraint("id = 1", name="ck_ai_quota_singleton"),
        sa.CheckConstraint("execution_limit BETWEEN 1 AND 10000", name="ck_ai_quota_limit"))
    op.execute("INSERT INTO ai_quota_policy(id,execution_limit) VALUES (1,20)")
    op.create_table("ai_executions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("job_id", UUID(as_uuid=True), sa.ForeignKey("jobs.id", ondelete="SET NULL")),
        sa.Column("kind", sa.String(12), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("reservation_token", UUID(as_uuid=True), nullable=False),
        sa.Column("admitted_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.clock_timestamp()),
        sa.CheckConstraint("attempt BETWEEN 1 AND 3", name="ck_ai_execution_attempt"),
        sa.CheckConstraint("kind IN ('stt','image','emotion')", name="ck_ai_execution_kind"),
        sa.UniqueConstraint("job_id", "attempt", name="uq_ai_execution_attempt"),
        sa.UniqueConstraint("reservation_token", name="uq_ai_execution_token"))
    op.create_index("ix_ai_execution_owner_time", "ai_executions", ["user_id", "admitted_at"])


def downgrade():
    op.execute("DO $$ BEGIN IF EXISTS (SELECT 1 FROM ai_executions) THEN "
               "RAISE EXCEPTION 'Downgrade refuse: admissions P12 presentes'; END IF; END $$")
    op.drop_index("ix_ai_execution_owner_time", table_name="ai_executions")
    op.drop_table("ai_executions")
    op.drop_table("ai_quota_policy")
