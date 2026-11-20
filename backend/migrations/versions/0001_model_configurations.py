"""Persist personal model configurations without storing plaintext secrets."""
from alembic import op
import sqlalchemy as sa

revision = "0001_model_configurations"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "model_configurations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("base_url", sa.String(2048), nullable=False),
        sa.Column("model_name", sa.String(200), nullable=False),
        sa.Column("encrypted_key", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.String(40), nullable=False),
    )


def downgrade():
    op.drop_table("model_configurations")
