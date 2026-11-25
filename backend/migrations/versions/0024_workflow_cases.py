"""Complete workflow case snapshots."""
from alembic import op
import sqlalchemy as sa

revision = '0024_workflow_cases'
down_revision = '0023_image_trash'
branch_labels = depends_on = None


def upgrade():
    op.create_table('workflow_cases',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('owner_id', sa.String(36), nullable=True),
        sa.Column('project_id', sa.String(36), nullable=False),
        sa.Column('title', sa.String(160), nullable=False),
        sa.Column('summary', sa.Text(), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('request_id', sa.String(36), nullable=False, unique=True),
        sa.Column('created_at', sa.String(40), nullable=False))
    op.create_index('ix_workflow_cases_project_id', 'workflow_cases', ['project_id'])
    op.create_index('ix_workflow_cases_owner_id', 'workflow_cases', ['owner_id'])


def downgrade():
    op.drop_table('workflow_cases')
