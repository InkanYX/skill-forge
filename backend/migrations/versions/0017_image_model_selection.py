"""Persist selected image models and the model chosen for each Agent run."""
from alembic import op
import sqlalchemy as sa

revision = '0017_image_model_selection'
down_revision = '0016_private_skill_packages'
branch_labels = depends_on = None


def upgrade():
    op.add_column('image_configurations', sa.Column('model_name', sa.String(200), nullable=False, server_default='gpt-image-2.5-sunburst'))
    op.add_column('image_configurations', sa.Column('model_names', sa.Text(), nullable=False, server_default='["gpt-image-2.5-sunburst"]'))
    op.add_column('agent_runs', sa.Column('image_model_name', sa.String(200), nullable=False, server_default='gpt-image-2.5-sunburst'))


def downgrade():
    op.drop_column('agent_runs', 'image_model_name')
    op.drop_column('image_configurations', 'model_names')
    op.drop_column('image_configurations', 'model_name')
