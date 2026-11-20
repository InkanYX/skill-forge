"""Non-destructive image revision relationships."""
from alembic import op
import sqlalchemy as sa

revision = '0005_image_revisions'
down_revision = '0004_products'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('image_jobs', sa.Column('parent_job_id', sa.String(36), nullable=True))
    op.add_column('image_jobs', sa.Column('edit_instruction', sa.Text(), nullable=False, server_default=''))
    op.create_index('ix_image_jobs_parent_job_id', 'image_jobs', ['parent_job_id'])


def downgrade():
    op.drop_index('ix_image_jobs_parent_job_id', table_name='image_jobs')
    op.drop_column('image_jobs', 'edit_instruction')
    op.drop_column('image_jobs', 'parent_job_id')
