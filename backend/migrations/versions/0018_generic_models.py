"""User-selected models, optional parameters, independent capability evidence."""
from alembic import op
import sqlalchemy as sa

revision = '0018_generic_models'
down_revision = '0017_creation_conversations'
branch_labels = depends_on = None


def upgrade():
    op.add_column('image_configurations', sa.Column('model_name', sa.String(200), nullable=False, server_default=''))
    for column in ('request_parameters', 'text_parameters', 'vision_parameters', 'capabilities'):
        op.add_column('image_configurations', sa.Column(column, sa.Text(), nullable=False, server_default='{}'))
    for column, default in [('generation_path', '/images/generations'), ('edit_path', '/images/edits')]:
        op.add_column('image_configurations', sa.Column(column, sa.String(300), nullable=False, server_default=default))
    # Preserve existing users' known configuration once; new connections have no default model or parameters.
    op.execute(sa.text("UPDATE image_configurations SET model_name = 'gpt-image-2.5-sunburst', request_parameters = '{\"quality\":\"high\",\"size\":\"auto\",\"output_format\":\"png\"}'"))


def downgrade():
    for column in ('edit_path', 'generation_path', 'capabilities', 'vision_parameters', 'text_parameters', 'request_parameters', 'model_name'):
        op.drop_column('image_configurations', column)
