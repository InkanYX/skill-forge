"""Persist redacted upstream error details for image jobs."""
from alembic import op
import sqlalchemy as sa

revision = '0010_provider_diagnostics'
down_revision = '0009_config_models'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('image_jobs', sa.Column('provider_diagnostic', sa.Text(), nullable=False, server_default='{}'))


def downgrade():
    op.drop_column('image_jobs', 'provider_diagnostic')
