"""P19 : métadonnées privées et purge récupérable, anciennes références conservées."""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Ne déplace ni ne supprime aucun fichier ou ancienne ligne."""
    op.add_column("media", sa.Column("size_bytes", sa.BigInteger(), nullable=True))
    op.add_column("media", sa.Column("media_type", sa.String(32), nullable=True))
    op.add_column("media", sa.Column("sha256", sa.String(64), nullable=True))
    op.add_column("media", sa.Column("storage_state", sa.String(12), nullable=False,
                                    server_default="legacy"))
    op.add_column("media", sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                                    server_default=sa.func.now()))
    op.add_column("media", sa.Column("purge_requested_at", sa.DateTime(timezone=True)))
    op.add_column("media", sa.Column("purged_at", sa.DateTime(timezone=True)))
    op.create_check_constraint("ck_media_state", "media",
                               "storage_state IN ('legacy','ready','deleting','purged')")
    op.create_check_constraint("ck_media_size", "media",
                               "size_bytes IS NULL OR size_bytes BETWEEN 1 AND 15728640")
    op.create_check_constraint(
        "ck_media_managed", "media",
        "storage_state = 'legacy' OR (size_bytes IS NOT NULL AND media_type IS NOT NULL "
        "AND sha256 IS NOT NULL AND storage_key ~ '^[a-f0-9]{64}$' AND sha256 ~ '^[a-f0-9]{64}$')",
    )
    op.create_check_constraint(
        "ck_media_type", "media",
        "media_type IS NULL OR (kind IN ('audio','sound') AND media_type IN "
        "('audio/wav','audio/mpeg')) OR (kind = 'image' AND media_type IN "
        "('image/png','image/jpeg','image/webp'))",
    )
    op.create_check_constraint(
        "ck_media_purge_request", "media",
        "(storage_state IN ('deleting','purged')) = (purge_requested_at IS NOT NULL)",
    )
    op.create_check_constraint("ck_media_purged", "media",
                               "(storage_state = 'purged') = (purged_at IS NOT NULL)")


def downgrade() -> None:
    """Retour réservé aux bases jetables ; aucun fichier physique supprimé."""
    for name in ["purged", "purge_request", "type", "managed", "size", "state"]:
        op.drop_constraint("ck_media_" + name, "media", type_="check")
    for name in ["purged_at", "purge_requested_at", "created_at", "storage_state",
                 "sha256", "media_type", "size_bytes"]:
        op.drop_column("media", name)
