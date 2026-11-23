"""Password accounts, revocable sessions, and shared-content ownership."""
from alembic import op
import sqlalchemy as sa
revision = '0014_accounts_permissions'
down_revision = '0013_shared_model_connection'
branch_labels = depends_on = None
OWNED = ('model_configurations','image_jobs','products','product_assets','creative_templates','creative_skills','creative_cases')

def upgrade():
    op.create_table('user_accounts',sa.Column('id',sa.String(36),primary_key=True),sa.Column('username',sa.String(32),nullable=False,unique=True),sa.Column('display_name',sa.String(80),nullable=False),sa.Column('password_hash',sa.Text(),nullable=False),sa.Column('role',sa.String(16),nullable=False),sa.Column('is_active',sa.Boolean(),nullable=False),sa.Column('must_change_password',sa.Boolean(),nullable=False),sa.Column('failed_attempts',sa.Integer(),nullable=False),sa.Column('locked_until',sa.Float(),nullable=False),sa.Column('created_at',sa.String(40),nullable=False))
    op.create_table('login_sessions',sa.Column('token_hash',sa.String(64),primary_key=True),sa.Column('user_id',sa.String(36),nullable=False),sa.Column('expires_at',sa.Float(),nullable=False))
    op.create_index('ix_login_sessions_user_id','login_sessions',['user_id'])
    op.create_index('ix_login_sessions_expires_at','login_sessions',['expires_at'])
    for table in OWNED:
        op.add_column(table,sa.Column('owner_id',sa.String(36),nullable=True))
        op.create_index(f'ix_{table}_owner_id',table,['owner_id'])

def downgrade():
    for table in reversed(OWNED):
        op.drop_index(f'ix_{table}_owner_id',table_name=table)
        op.drop_column(table,'owner_id')
    op.drop_table('login_sessions');op.drop_table('user_accounts')
