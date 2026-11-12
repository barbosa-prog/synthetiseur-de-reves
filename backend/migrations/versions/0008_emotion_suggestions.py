"""P08 : suggestions sans attribution automatique et provenance des choix."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_constraint("ck_job_kind", "jobs", type_="check")
    op.create_check_constraint("ck_job_kind", "jobs", "kind IN ('stt','image','tts','emotion')")
    op.create_index(
        "uq_active_emotion_dream",
        "jobs",
        ["dream_id"],
        unique=True,
        postgresql_where=sa.text("kind = 'emotion' AND status IN ('queued','running')"),
    )
    op.create_table(
        "dream_emotions",
        sa.Column(
            "dream_id", sa.UUID(), sa.ForeignKey("dreams.id", ondelete="RESTRICT"), primary_key=True
        ),
        sa.Column("source", sa.String(12), nullable=False, server_default="unset"),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("selected_text_version", sa.Integer()),
        sa.Column("active_request", sa.UUID(), sa.ForeignKey("jobs.id", ondelete="RESTRICT")),
        sa.Column("suggestion_id", sa.UUID(), sa.ForeignKey("jobs.id", ondelete="RESTRICT")),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            "source IN ('unset','manual','accepted','withdrawn','legacy')", name="ck_emotion_source"
        ),
        sa.CheckConstraint("revision >= 0", name="ck_emotion_revision"),
        sa.CheckConstraint(
            "selected_text_version IS NULL OR selected_text_version >= 0",
            name="ck_emotion_selected_version",
        ),
    )
    op.execute(
        "INSERT INTO dream_emotions (dream_id,source) SELECT id, "
        "CASE WHEN emotion IS NULL THEN 'unset' ELSE 'legacy' END FROM dreams"
    )
    op.create_table(
        "emotion_analyses",
        sa.Column(
            "job_id", sa.UUID(), sa.ForeignKey("jobs.id", ondelete="RESTRICT"), primary_key=True
        ),
        sa.Column(
            "user_id", sa.UUID(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("transcript", sa.Text(), nullable=False),
        sa.Column("text_version", sa.Integer(), nullable=False),
        sa.Column("choice_revision", sa.Integer(), nullable=False),
        sa.Column("parameters", JSONB(), nullable=False),
        sa.Column("result", JSONB()),
        sa.CheckConstraint(
            "text_version >= 1 AND choice_revision >= 0", name="ck_analysis_versions"
        ),
        sa.CheckConstraint(
            "length(btrim(transcript)) BETWEEN 1 AND 20000", name="ck_analysis_text"
        ),
        sa.CheckConstraint("jsonb_typeof(parameters) = 'object'", name="ck_analysis_parameters"),
        sa.CheckConstraint(
            "result IS NULL OR jsonb_typeof(result) = 'object'", name="ck_analysis_result"
        ),
    )


def downgrade():
    # Ne supprime jamais des jobs ou résultats P08 pour rendre le rollback possible.
    op.execute(
        "DO $$ BEGIN IF EXISTS (SELECT 1 FROM jobs WHERE kind='emotion') OR EXISTS "
        "(SELECT 1 FROM dream_emotions WHERE revision > 0 OR source IN "
        "('manual','accepted','withdrawn')) THEN "
        "RAISE EXCEPTION 'Downgrade refuse: donnees P08 presentes'; END IF; END $$"
    )
    op.drop_table("emotion_analyses")
    op.drop_table("dream_emotions")
    op.drop_index("uq_active_emotion_dream", table_name="jobs")
    op.drop_constraint("ck_job_kind", "jobs", type_="check")
    op.create_check_constraint("ck_job_kind", "jobs", "kind IN ('stt','image','tts')")
