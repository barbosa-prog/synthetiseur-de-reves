"""P04 : métadonnées audio mesurées, aucun changement des anciens médias."""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Colonnes nullables pour conserver sans supposition les données précédentes."""
    for name in ["duration_ms", "sample_rate_hz", "channels"]:
        op.add_column("media", sa.Column(name, sa.Integer(), nullable=True))
    for name in ["sample_count", "source_size_bytes"]:
        op.add_column("media", sa.Column(name, sa.BigInteger(), nullable=True))
    for name in ["source_format", "audio_source"]:
        op.add_column("media", sa.Column(name, sa.String(12), nullable=True))
    for name, condition in {
        "duration": "duration_ms IS NULL OR duration_ms BETWEEN 1 AND 480000",
        "sample_rate": "sample_rate_hz IS NULL OR sample_rate_hz = 16000",
        "channels": "channels IS NULL OR channels = 1",
        "sample_count": "sample_count IS NULL OR sample_count BETWEEN 1 AND 7680000",
        "source_size": "source_size_bytes IS NULL OR source_size_bytes BETWEEN 1 AND 15728640",
        "source_format": (
            "source_format IS NULL OR source_format IN ('wav','mp3','webm','ogg','mp4')"
        ),
        "audio_source": "audio_source IS NULL OR audio_source IN ('import','microphone')",
    }.items():
        op.create_check_constraint("ck_media_" + name, "media", condition)


def downgrade() -> None:
    """Retour pour bases jetables, sans toucher aux fichiers."""
    for name in ["duration", "sample_rate", "channels", "sample_count", "source_size",
                 "source_format", "audio_source"]:
        op.drop_constraint("ck_media_" + name, "media", type_="check")
    for name in ["duration_ms", "sample_rate_hz", "channels", "sample_count",
                 "source_format", "source_size_bytes", "audio_source"]:
        op.drop_column("media", name)
