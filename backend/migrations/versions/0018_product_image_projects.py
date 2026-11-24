"""Durable product materials, selling points, plans and approval history."""
from alembic import op
import sqlalchemy as sa

revision = '0018_product_image_projects'
down_revision = '0017_image_model_selection'
branch_labels = depends_on = None


def upgrade():
    op.create_table('product_image_projects',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('owner_id', sa.String(36), nullable=True),
        sa.Column('title', sa.String(120), nullable=False),
        sa.Column('revision', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(24), nullable=False),
        sa.Column('action', sa.String(24), nullable=False),
        sa.Column('state', sa.Text(), nullable=False),
        sa.Column('lease_until', sa.Float(), nullable=True),
        sa.Column('created_at', sa.String(40), nullable=False),
        sa.Column('updated_at', sa.String(40), nullable=False))
    op.create_index('ix_product_image_projects_owner_id', 'product_image_projects', ['owner_id'])
    op.create_index('ix_product_image_projects_status', 'product_image_projects', ['status'])


def downgrade():
    op.drop_table('product_image_projects')
