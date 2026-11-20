"""Product records, reusable assets and job snapshots."""
from alembic import op
import sqlalchemy as sa

revision = "0004_products"
down_revision = "0003_creative_templates"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('image_jobs', sa.Column('product_snapshot', sa.Text(), nullable=False, server_default='{}'))
    op.create_table('products', sa.Column('id', sa.String(36), primary_key=True), sa.Column('sku', sa.String(100), unique=True, nullable=False), sa.Column('content', sa.Text(), nullable=False), sa.Column('revision', sa.Integer(), nullable=False), sa.Column('updated_at', sa.String(40), nullable=False))
    op.create_table('product_assets', sa.Column('id', sa.String(36), primary_key=True), sa.Column('product_id', sa.String(36), nullable=False), sa.Column('name', sa.String(120), nullable=False), sa.Column('kind', sa.String(32), nullable=False), sa.Column('digest', sa.String(64), nullable=False), sa.Column('created_at', sa.String(40), nullable=False))
    op.create_index('ix_product_assets_product_id', 'product_assets', ['product_id'])


def downgrade():
    op.drop_table('product_assets')
    op.drop_table('products')
    op.drop_column('image_jobs', 'product_snapshot')
