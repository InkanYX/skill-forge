"""Allow multiple saved models on one provider configuration."""
import json
from alembic import op
import sqlalchemy as sa

revision = '0009_config_models'
down_revision = '0008_artwork_favorites'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('model_configurations', sa.Column('model_names', sa.Text(), nullable=False, server_default='[]'))
    configs = sa.table('model_configurations', sa.column('id', sa.String()), sa.column('model_name', sa.String()), sa.column('model_names', sa.Text()))
    connection = op.get_bind()
    for identifier, name in connection.execute(sa.select(configs.c.id, configs.c.model_name)).all():
        connection.execute(configs.update().where(configs.c.id == identifier).values(model_names=json.dumps([name] if name else [])))


def downgrade():
    op.drop_column('model_configurations', 'model_names')
