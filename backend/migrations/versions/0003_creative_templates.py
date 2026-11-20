"""Creative templates, immutable job snapshots, and reusable cases."""
from alembic import op
import sqlalchemy as sa

revision = "0003_creative_templates"
down_revision = "0002_image_jobs"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("image_jobs", sa.Column("template_snapshot", sa.Text(), nullable=False, server_default="{}"))
    op.create_table("creative_templates", sa.Column("id", sa.String(36), primary_key=True), sa.Column("content", sa.Text(), nullable=False), sa.Column("revision", sa.Integer(), nullable=False), sa.Column("updated_at", sa.String(40), nullable=False))
    op.create_table("creative_cases", sa.Column("id", sa.String(36), primary_key=True), sa.Column("job_id", sa.String(36), nullable=False, unique=True), sa.Column("title", sa.String(120), nullable=False), sa.Column("experience", sa.Text(), nullable=False), sa.Column("issues", sa.Text(), nullable=False), sa.Column("updated_at", sa.String(40), nullable=False))


def downgrade():
    op.drop_table("creative_cases")
    op.drop_table("creative_templates")
    op.drop_column("image_jobs", "template_snapshot")
