"""Team market studies and durable, idempotent MCP query records."""
from alembic import op
import sqlalchemy as sa

revision = '0027_market_insights'
down_revision = '0026_plan_trash'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('market_studies', sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('owner_id', sa.String(36), nullable=False), sa.Column('author', sa.String(80), nullable=False),
        sa.Column('title', sa.String(120), nullable=False), sa.Column('marketplace', sa.String(2), nullable=False),
        sa.Column('notes', sa.Text(), nullable=False), sa.Column('created_at', sa.String(40), nullable=False))
    op.create_table('market_queries', sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('study_id', sa.String(36), nullable=False), sa.Column('owner_id', sa.String(36), nullable=False),
        sa.Column('request_id', sa.String(36), nullable=False, unique=True),
        sa.Column('active_key', sa.String(64), nullable=True, unique=True), sa.Column('cache_key', sa.String(64), nullable=False),
        sa.Column('provider', sa.String(20), nullable=False), sa.Column('section', sa.String(24), nullable=False),
        sa.Column('tool', sa.String(100), nullable=False), sa.Column('arguments', sa.Text(), nullable=False),
        sa.Column('status', sa.String(20), nullable=False), sa.Column('result', sa.Text(), nullable=False),
        sa.Column('error', sa.Text(), nullable=False), sa.Column('created_at', sa.String(40), nullable=False),
        sa.Column('updated_at', sa.String(40), nullable=False))
    for field in ('study_id', 'cache_key', 'status'):
        op.create_index('ix_market_queries_' + field, 'market_queries', [field])


def downgrade():
    op.drop_table('market_queries')
    op.drop_table('market_studies')
