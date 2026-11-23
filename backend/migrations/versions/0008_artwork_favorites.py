"""Keep artwork favorites separate from experience notes."""
from alembic import op
import sqlalchemy as sa

revision = '0008_artwork_favorites'
down_revision = '0007_skill_library'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('image_jobs', sa.Column('is_favorite', sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade():
    op.drop_column('image_jobs', 'is_favorite')
