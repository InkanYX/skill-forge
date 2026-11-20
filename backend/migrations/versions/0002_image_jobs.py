"""Add durable single-image jobs."""
from alembic import op
import sqlalchemy as sa

revision = "0002_image_jobs"
down_revision = "0001_model_configurations"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "image_jobs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("request_id", sa.String(36), nullable=False, unique=True),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("config_id", sa.String(36), nullable=False),
        sa.Column("config_name", sa.String(80), nullable=False),
        sa.Column("base_url", sa.String(2048), nullable=False),
        sa.Column("encrypted_key", sa.Text(), nullable=False),
        sa.Column("model_name", sa.String(200), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("size", sa.String(32), nullable=False),
        sa.Column("mode", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.Column("updated_at", sa.String(40), nullable=False),
        sa.Column("lease_until", sa.Float(), nullable=True),
    )
    op.create_index("ix_image_jobs_status", "image_jobs", ["status"])
    op.create_index("ix_image_jobs_created_at", "image_jobs", ["created_at"])


def downgrade():
    op.drop_table("image_jobs")
