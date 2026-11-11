"""P05 : références et réservation persistante des transcriptions."""

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade():
    """Préserve les jobs existants ; refuse les doublons actifs à résoudre explicitement."""
    op.add_column("jobs", sa.Column("media_id", sa.UUID(), nullable=True))
    op.create_foreign_key("fk_jobs_media", "jobs", "media", ["media_id"], ["id"],
                          ondelete="RESTRICT")
    op.add_column("jobs", sa.Column("expected_text_version", sa.Integer(), nullable=True))
    op.add_column("jobs", sa.Column("claim_token", sa.UUID(), nullable=True))
    op.add_column("jobs", sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True))
    op.add_column("jobs", sa.Column("created_at", sa.DateTime(timezone=True),
                                   nullable=False, server_default=sa.func.now()))
    op.add_column("jobs", sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("uq_active_stt_dream", "jobs", ["dream_id"], unique=True,
                    postgresql_where=sa.text("kind = 'stt' AND status IN ('queued','running')"))


def downgrade():
    """Retour pour bases de test uniquement, sans suppression de rêve/média."""
    op.drop_index("uq_active_stt_dream", table_name="jobs")
    op.drop_constraint("fk_jobs_media", "jobs", type_="foreignkey")
    for name in ("finished_at", "created_at", "lease_until", "claim_token",
                 "expected_text_version", "media_id"):
        op.drop_column("jobs", name)
