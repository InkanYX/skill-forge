"""Default team project snapshots and private workspace reads."""
from alembic import op
import sqlalchemy as sa

revision='0025_team_sharing'
down_revision='0024_workflow_cases'
branch_labels=depends_on=None


def upgrade():
    op.create_table('team_project_shares',
        sa.Column('id',sa.String(36),primary_key=True),
        sa.Column('project_id',sa.String(36),nullable=False,unique=True),
        sa.Column('owner_id',sa.String(36),nullable=False),
        sa.Column('title',sa.String(120),nullable=False),
        sa.Column('kind',sa.String(16),nullable=False),
        sa.Column('visibility',sa.String(16),nullable=False),
        sa.Column('version',sa.Integer(),nullable=False),
        sa.Column('source_revision',sa.Integer(),nullable=False),
        sa.Column('content',sa.Text(),nullable=False),
        sa.Column('created_at',sa.String(40),nullable=False),
        sa.Column('updated_at',sa.String(40),nullable=False))
    op.create_index('ix_team_project_shares_owner_id','team_project_shares',['owner_id'])
    op.create_index('ix_team_project_shares_project_id','team_project_shares',['project_id'])


def downgrade():
    op.drop_table('team_project_shares')
