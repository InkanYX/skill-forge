"""Reusable natural-language skills and immutable versions."""
from alembic import op
import sqlalchemy as sa

revision = '0007_skill_library'
down_revision = '0006_image_sets'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('creative_skills', sa.Column('id', sa.String(36), primary_key=True), sa.Column('content', sa.Text(), nullable=False), sa.Column('revision', sa.Integer(), nullable=False), sa.Column('updated_at', sa.String(40), nullable=False))
    op.create_table('skill_revisions', sa.Column('skill_id', sa.String(36), primary_key=True), sa.Column('revision', sa.Integer(), primary_key=True), sa.Column('content', sa.Text(), nullable=False), sa.Column('updated_at', sa.String(40), nullable=False))


def downgrade():
    op.drop_table('skill_revisions')
    op.drop_table('creative_skills')
