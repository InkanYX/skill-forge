"""Scope skill package names: built-in names are global, personal names are per owner."""
from alembic import op
import sqlalchemy as sa

revision = '0016_private_skill_packages'
down_revision = '0015_skill_packages'
branch_labels = depends_on = None


def upgrade():
    bind = op.get_bind()
    if bind.dialect.name == 'postgresql':
        op.drop_constraint('skill_packages_name_key', 'skill_packages', type_='unique')
    # SQLite cannot drop a column-level UNIQUE constraint in place. Local test
    # databases keep it; the application still enforces owner-scoped names.
    op.create_index('uq_skill_packages_owner_name', 'skill_packages', ['owner_id', 'name'], unique=True,
                    postgresql_where=sa.text('owner_id IS NOT NULL'),
                    sqlite_where=sa.text('owner_id IS NOT NULL'))
    op.create_index('uq_skill_packages_builtin_name', 'skill_packages', ['name'], unique=True,
                    postgresql_where=sa.text("source = 'builtin'"),
                    sqlite_where=sa.text("source = 'builtin'"))


def downgrade():
    op.drop_index('uq_skill_packages_builtin_name', table_name='skill_packages')
    op.drop_index('uq_skill_packages_owner_name', table_name='skill_packages')
    if op.get_bind().dialect.name == 'postgresql':
        op.create_unique_constraint('skill_packages_name_key', 'skill_packages', ['name'])
