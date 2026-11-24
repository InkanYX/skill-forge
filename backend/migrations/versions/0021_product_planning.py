"""Separate reusable product analysis, image plans and neutral plan templates."""
from alembic import op
import sqlalchemy as sa

revision = '0021_product_planning'
down_revision = '0020_guided_creation'
branch_labels = depends_on = None


def upgrade():
    op.add_column('creation_projects', sa.Column('kind', sa.String(16), nullable=False, server_default='legacy'))
    op.add_column('creation_projects', sa.Column('source_product_id', sa.String(36), nullable=True))
    op.create_index('ix_creation_projects_kind', 'creation_projects', ['kind'])
    op.create_index('ix_creation_projects_source_product_id', 'creation_projects', ['source_product_id'])
    op.create_table('image_plan_templates',
        sa.Column('id', sa.String(36), primary_key=True), sa.Column('owner_id', sa.String(36)),
        sa.Column('name', sa.String(120), nullable=False), sa.Column('content', sa.Text(), nullable=False),
        sa.Column('created_at', sa.String(40), nullable=False))
    op.create_index('ix_image_plan_templates_owner_id', 'image_plan_templates', ['owner_id'])


def downgrade():
    op.drop_table('image_plan_templates')
    for column in ('source_product_id', 'kind'):
        op.drop_index('ix_creation_projects_' + column, table_name='creation_projects')
        op.drop_column('creation_projects', column)
