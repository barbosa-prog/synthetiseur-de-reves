"""P03 : hachage mot de passe, sessions opaques et limiteurs persistants."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Étend P02 sans supprimer ses données ; doublons de casse à résoudre avant migration."""
    op.add_column("users", sa.Column("password_hash", sa.Text(), nullable=True))
    op.create_index("uq_users_email_normalized", "users", [sa.text("lower(email)")], unique=True)
    op.create_table(
        "auth_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("expires_at > created_at", name="ck_session_expiration"),
    )
    op.create_index("ix_auth_sessions_user_id", "auth_sessions", ["user_id"])
    op.create_table(
        "auth_throttles",
        sa.Column("key", sa.String(64), primary_key=True),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.CheckConstraint("attempts >= 0", name="ck_throttle_attempts"),
    )


def downgrade() -> None:
    """Retour P02 ; invalide les sessions et retire les hachages (à ne pas lancer en service)."""
    op.drop_table("auth_throttles")
    op.drop_table("auth_sessions")
    op.drop_index("uq_users_email_normalized", table_name="users")
    op.drop_column("users", "password_hash")
