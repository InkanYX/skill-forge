"""Standard image profiles contain metadata only; credentials stay in memory."""
from alembic import op
import sqlalchemy as sa
revision = '0012_standard_images'
down_revision = '0011_task_groups'
branch_labels = depends_on = None


def upgrade():
    op.add_column('image_jobs', sa.Column('execution_profile', sa.Text(), nullable=False, server_default='{}'))
    op.add_column('image_jobs', sa.Column('execution_result', sa.Text(), nullable=False, server_default='{}'))
    op.create_table('image_configurations',
        sa.Column('id', sa.String(36), primary_key=True), sa.Column('owner', sa.String(64), nullable=False, unique=True),
        sa.Column('name', sa.String(80), nullable=False), sa.Column('base_url', sa.String(2048), nullable=False),
        sa.Column('revision', sa.String(36), nullable=False), sa.Column('generation_job_id', sa.String(36)),
        sa.Column('edit_job_id', sa.String(36)), sa.Column('updated_at', sa.String(40), nullable=False))


def downgrade():
    op.drop_table('image_configurations')
    op.drop_column('image_jobs', 'execution_result')
    op.drop_column('image_jobs', 'execution_profile')
