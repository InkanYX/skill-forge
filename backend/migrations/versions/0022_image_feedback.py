"""Image feedback and human-confirmed product drawing experience."""
from alembic import op
import sqlalchemy as sa

revision = '0022_image_feedback'
down_revision = '0021_product_planning'
branch_labels = depends_on = None


def upgrade():
    for column in [sa.Column('outcome', sa.String(16), nullable=False, server_default='pending'),
                   sa.Column('requested_change', sa.Text(), nullable=False, server_default=''),
                   sa.Column('product_id', sa.String(36), nullable=True),
                   sa.Column('revision', sa.Integer(), nullable=False, server_default='1')]:
        op.add_column('creative_cases', column)
    op.create_index('ix_creative_cases_product_id', 'creative_cases', ['product_id'])
    op.create_table('product_image_experiences',
        sa.Column('id', sa.String(36), primary_key=True), sa.Column('owner_id', sa.String(36)),
        sa.Column('product_id', sa.String(36), nullable=False), sa.Column('content', sa.Text(), nullable=False),
        sa.Column('status', sa.String(16), nullable=False), sa.Column('revision', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.String(40), nullable=False), sa.Column('updated_at', sa.String(40), nullable=False))
    op.create_index('ix_product_image_experiences_product_id', 'product_image_experiences', ['product_id'])
    op.create_index('ix_product_image_experiences_owner_id', 'product_image_experiences', ['owner_id'])


def downgrade():
    op.drop_table('product_image_experiences')
    op.drop_index('ix_creative_cases_product_id', table_name='creative_cases')
    for column in ('revision', 'product_id', 'requested_change', 'outcome'):
        op.drop_column('creative_cases', column)
