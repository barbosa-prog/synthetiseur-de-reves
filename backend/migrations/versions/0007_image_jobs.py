"""P07 : descriptions versionnées et snapshots des jobs image, sans backfill destructif."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "image_descriptions",
        sa.Column("dream_id", sa.UUID(), sa.ForeignKey("dreams.id", ondelete="RESTRICT"),
                  primary_key=True),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("text_version", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.CheckConstraint("version >= 1 AND text_version >= 1",
                           name="ck_image_description_versions"),
        sa.CheckConstraint("length(btrim(description)) BETWEEN 1 AND 500",
                           name="ck_image_description_length"),
    )
    op.create_table(
        "image_generations",
        sa.Column("job_id", sa.UUID(), sa.ForeignKey("jobs.id", ondelete="RESTRICT"),
                  primary_key=True),
        sa.Column("user_id", sa.UUID(), sa.ForeignKey("users.id", ondelete="RESTRICT"),
                  nullable=False),
        sa.Column("transcript", sa.Text(), nullable=False),
        sa.Column("text_version", sa.Integer(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("description_version", sa.Integer(), nullable=False),
        sa.Column("parameters", JSONB(), nullable=False),
        sa.CheckConstraint("text_version >= 1 AND description_version >= 1",
                           name="ck_image_generation_versions"),
        sa.CheckConstraint("length(btrim(description)) BETWEEN 1 AND 500",
                           name="ck_image_generation_description"),
        sa.CheckConstraint("length(btrim(transcript)) BETWEEN 1 AND 20000",
                           name="ck_image_generation_text"),
        sa.CheckConstraint("jsonb_typeof(parameters) = 'object'",
                           name="ck_image_generation_parameters"),
    )
    op.create_index("uq_active_image_dream", "jobs", ["dream_id"], unique=True,
                    postgresql_where=sa.text("kind = 'image' AND status IN ('queued','running')"))


def downgrade():
    op.drop_index("uq_active_image_dream", table_name="jobs")
    op.drop_table("image_generations")
    op.drop_table("image_descriptions")
