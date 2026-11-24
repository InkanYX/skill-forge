"""Recoverable image removal without losing generation provenance."""
from alembic import op
import sqlalchemy as sa

revision = '0023_image_trash'
down_revision = '0022_image_feedback'
branch_labels = depends_on = None


def upgrade():
    op.add_column('image_jobs', sa.Column('deleted_at', sa.String(40), nullable=True))


def downgrade():
    op.drop_column('image_jobs', 'deleted_at')
