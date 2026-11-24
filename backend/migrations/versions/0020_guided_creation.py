"""Model assignments and durable, confirmed creation stages."""
from alembic import op
import sqlalchemy as sa

revision = '0020_guided_creation'
down_revision = '0019_model_registry'
branch_labels = depends_on = None


def upgrade():
    for name in ('planning_model_name', 'image_model_name'):
        op.add_column('image_configurations', sa.Column(name, sa.String(200), nullable=False, server_default=''))
    op.create_table('creation_projects',
        sa.Column('id', sa.String(36), primary_key=True), sa.Column('owner_id', sa.String(36)),
        sa.Column('title', sa.String(120), nullable=False), sa.Column('revision', sa.Integer(), nullable=False),
        sa.Column('content', sa.Text(), nullable=False), sa.Column('created_at', sa.String(40), nullable=False),
        sa.Column('updated_at', sa.String(40), nullable=False))
    op.create_index('ix_creation_projects_owner_id', 'creation_projects', ['owner_id'])
    op.create_index('ix_creation_projects_updated_at', 'creation_projects', ['updated_at'])
    op.create_table('creation_materials',
        sa.Column('id', sa.String(36), primary_key=True), sa.Column('project_id', sa.String(36), nullable=False),
        sa.Column('name', sa.String(200), nullable=False), sa.Column('kind', sa.String(32), nullable=False),
        sa.Column('media_type', sa.String(64), nullable=False), sa.Column('digest', sa.String(64), nullable=False),
        sa.Column('size', sa.Integer(), nullable=False), sa.Column('pages', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.String(40), nullable=False))
    op.create_index('ix_creation_materials_project_id', 'creation_materials', ['project_id'])
    op.create_table('creation_documents',
        sa.Column('id', sa.String(36), primary_key=True), sa.Column('project_id', sa.String(36), nullable=False),
        sa.Column('stage', sa.String(16), nullable=False), sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('content', sa.Text(), nullable=False), sa.Column('confirmed_at', sa.String(40)),
        sa.Column('created_at', sa.String(40), nullable=False),
        sa.UniqueConstraint('project_id', 'stage', 'version', name='uq_creation_document_version'))
    op.create_index('ix_creation_documents_project_id', 'creation_documents', ['project_id'])
    op.create_table('creation_executions',
        sa.Column('id', sa.String(36), primary_key=True), sa.Column('project_id', sa.String(36), nullable=False),
        sa.Column('stage', sa.String(16), nullable=False), sa.Column('status', sa.String(16), nullable=False),
        sa.Column('input', sa.Text(), nullable=False), sa.Column('output', sa.Text(), nullable=False),
        sa.Column('error', sa.Text(), nullable=False), sa.Column('lease_until', sa.Float()),
        sa.Column('created_at', sa.String(40), nullable=False), sa.Column('updated_at', sa.String(40), nullable=False))
    op.create_index('ix_creation_executions_project_id', 'creation_executions', ['project_id'])
    op.create_index('ix_creation_executions_status', 'creation_executions', ['status'])


def downgrade():
    for name in ('creation_executions', 'creation_documents', 'creation_materials', 'creation_projects'):
        op.drop_table(name)
    for name in ('planning_model_name', 'image_model_name'):
        op.drop_column('image_configurations', name)
