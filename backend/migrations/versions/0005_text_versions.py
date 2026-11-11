"""P06 : version du texte et date de correction, sans modifier les récits existants."""

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Un texte déjà présent reçoit une version de référence 1, sans date inventée."""
    op.add_column("dreams", sa.Column("text_version", sa.Integer(), nullable=False,
                                     server_default="0"))
    op.add_column("dreams", sa.Column("text_updated_at", sa.DateTime(timezone=True), nullable=True))
    op.execute("UPDATE dreams SET text_version = 1 WHERE transcript IS NOT NULL")
    op.create_check_constraint("ck_dream_text_version", "dreams", "text_version >= 0")


def downgrade() -> None:
    """Retour réservé aux bases jetables ; récits et médias restent présents."""
    op.drop_constraint("ck_dream_text_version", "dreams", type_="check")
    op.drop_column("dreams", "text_updated_at")
    op.drop_column("dreams", "text_version")
