"""Named image sets with individual shot briefs."""
from alembic import op
import sqlalchemy as sa

revision = '0006_image_sets'
down_revision = '0005_image_revisions'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('image_jobs', sa.Column('set_id', sa.String(36), nullable=True))
    op.add_column('image_jobs', sa.Column('set_name', sa.String(100), nullable=False, server_default=''))
    op.add_column('image_jobs', sa.Column('shot_name', sa.String(80), nullable=False, server_default=''))
    op.add_column('image_jobs', sa.Column('shot_index', sa.Integer(), nullable=True))
    op.create_index('ix_image_jobs_set_id', 'image_jobs', ['set_id'])


def downgrade():
    op.drop_index('ix_image_jobs_set_id', table_name='image_jobs')
    for column in ('shot_index', 'shot_name', 'set_name', 'set_id'):
        op.drop_column('image_jobs', column)
