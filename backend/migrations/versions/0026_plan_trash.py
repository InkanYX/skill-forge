"""Recoverable deletion of image plans without removing source product data."""
from alembic import op
import sqlalchemy as sa

revision = '0026_plan_trash'
down_revision = '0025_team_sharing'
branch_labels = depends_on = None


def upgrade():
    op.add_column('creation_projects', sa.Column('deleted_at', sa.String(40), nullable=True))


def downgrade():
    op.drop_column('creation_projects', 'deleted_at')
