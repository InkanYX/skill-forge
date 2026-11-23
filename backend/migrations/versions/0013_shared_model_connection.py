"""Reuse one provider connection across image and text model purposes."""
from alembic import op
import sqlalchemy as sa
revision = '0013_shared_model_connection'
down_revision = '0012_standard_images'
branch_labels = depends_on = None

def upgrade():
    op.add_column('image_configurations', sa.Column('text_model_name', sa.String(200), nullable=False, server_default=''))
    op.add_column('image_configurations', sa.Column('text_config_id', sa.String(36), nullable=True))

def downgrade():
    op.drop_column('image_configurations', 'text_config_id')
    op.drop_column('image_configurations', 'text_model_name')
