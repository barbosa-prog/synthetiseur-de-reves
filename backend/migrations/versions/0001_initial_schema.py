"""P02 : users, dreams, media, jobs. Migration initiale explicite et réversible."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def identifier():
    """Colonne UUID générée côté serveur, indépendante du code ORM futur."""
    return sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                     server_default=sa.text("gen_random_uuid()"))


def upgrade() -> None:
    """Crée les quatre tables et leurs contraintes."""
    op.create_table(
        "users", identifier(), sa.Column("email", sa.Text(), unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.CheckConstraint("email IS NULL OR btrim(email) <> ''", name="ck_user_email"),
    )
    op.create_table(
        "dreams", identifier(),
        sa.Column("user_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("transcript", sa.Text()), sa.Column("emotion", sa.String(20)),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "status IN ('draft','processing','transcribing','transcribed','correcting',"
            "'generating','ready','error','deleted')", name="ck_dream_status"),
        sa.CheckConstraint(
            "emotion IS NULL OR emotion IN ('heureux','stressant','neutre','triste','autre')",
            name="ck_dream_emotion"),
        sa.CheckConstraint("transcript IS NULL OR btrim(transcript) <> ''", name="ck_dream_text"),
        sa.CheckConstraint("status <> 'ready' OR transcript IS NOT NULL", name="ck_dream_ready"),
        sa.CheckConstraint("(status = 'deleted') = (deleted_at IS NOT NULL)",
                           name="ck_dream_deleted"),
    )
    op.create_index("ix_dreams_user_created", "dreams", ["user_id", "created_at"])
    op.create_table(
        "media", identifier(),
        sa.Column("dream_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("dreams.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("storage_key", sa.Text(), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("kind IN ('audio','image','sound')", name="ck_media_kind"),
        sa.CheckConstraint("btrim(storage_key) <> ''", name="ck_media_key"),
    )
    op.create_index("ix_media_dream_id", "media", ["dream_id"])
    op.create_table(
        "jobs", identifier(),
        sa.Column("dream_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("dreams.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("kind", sa.String(12), nullable=False),
        sa.Column("status", sa.String(12), nullable=False, server_default="queued"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_code", sa.String(40)),
        sa.CheckConstraint("kind IN ('stt','image','tts')", name="ck_job_kind"),
        sa.CheckConstraint("status IN ('queued','running','done','failed')", name="ck_job_status"),
        sa.CheckConstraint("attempts BETWEEN 0 AND 3", name="ck_job_attempts"),
    )
    op.create_index("ix_jobs_dream_id", "jobs", ["dream_id"])


def downgrade() -> None:
    """Supprime le schéma P02 ; commande destructive à réserver aux bases jetables."""
    op.drop_table("jobs")
    op.drop_table("media")
    op.drop_table("dreams")
    op.drop_table("users")
