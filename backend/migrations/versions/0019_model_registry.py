"""One connection with a normal model list and per-model options/evidence."""
from alembic import op
import sqlalchemy as sa

revision = '0019_model_registry'
down_revision = '0018_generic_models'
branch_labels = depends_on = None

def upgrade():
    op.add_column('image_configurations', sa.Column('model_names', sa.Text(), nullable=False, server_default='[]'))
    op.add_column('image_configurations', sa.Column('model_settings', sa.Text(), nullable=False, server_default='{}'))
    op.add_column('image_configurations', sa.Column('auto_review', sa.Boolean(), nullable=False, server_default=sa.false()))

def downgrade():
    for field in ('auto_review', 'model_settings', 'model_names'):
        op.drop_column('image_configurations', field)
