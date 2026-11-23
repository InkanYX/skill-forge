"""Immutable skill packages, compiled snapshots, and agent run records."""
from alembic import op
import sqlalchemy as sa

revision = '0015_skill_packages'
down_revision = '0014_accounts_permissions'
branch_labels = depends_on = None


def upgrade():
    op.create_table(
        'skill_packages',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('name', sa.String(200), nullable=False, unique=True),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('source', sa.String(16), nullable=False),
        sa.Column('owner_id', sa.String(36), nullable=True),
        sa.Column('is_readonly', sa.Boolean(), nullable=False),
        sa.Column('current_version_id', sa.String(36), nullable=True),
        sa.Column('created_at', sa.String(40), nullable=False),
        sa.Column('updated_at', sa.String(40), nullable=False),
    )
    op.create_index('ix_skill_packages_owner_id', 'skill_packages', ['owner_id'])

    op.create_table(
        'skill_versions',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('skill_id', sa.String(36), nullable=False),
        sa.Column('version_label', sa.String(64), nullable=False),
        sa.Column('status', sa.String(16), nullable=False),
        sa.Column('compile_level', sa.String(16), nullable=False),
        sa.Column('content_sha256', sa.String(64), nullable=False),
        sa.Column('compiled_sha256', sa.String(64), nullable=False),
        sa.Column('compiled_chars', sa.Integer(), nullable=False),
        sa.Column('file_count', sa.Integer(), nullable=False),
        sa.Column('total_bytes', sa.Integer(), nullable=False),
        sa.Column('entry_path', sa.String(500), nullable=False),
        sa.Column('created_at', sa.String(40), nullable=False),
        sa.Column('created_by', sa.String(36), nullable=True),
        sa.Column('import_note', sa.Text(), nullable=False),
        sa.UniqueConstraint('skill_id', 'version_label', name='uq_skill_versions_label'),
    )
    op.create_index('ix_skill_versions_skill_id', 'skill_versions', ['skill_id'])

    op.create_table(
        'skill_files',
        sa.Column('version_id', sa.String(36), primary_key=True),
        sa.Column('path', sa.String(500), primary_key=True),
        sa.Column('kind', sa.String(24), nullable=False),
        sa.Column('size', sa.Integer(), nullable=False),
        sa.Column('sha256', sa.String(64), nullable=False),
        sa.Column('is_text', sa.Boolean(), nullable=False),
    )
    op.create_index('ix_skill_files_version_id', 'skill_files', ['version_id'])

    op.create_table(
        'agent_runs',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('owner_id', sa.String(36), nullable=True),
        sa.Column('skill_id', sa.String(36), nullable=False),
        sa.Column('skill_version_id', sa.String(36), nullable=False),
        sa.Column('config_id', sa.String(36), nullable=False),
        sa.Column('status', sa.String(16), nullable=False),
        sa.Column('goal', sa.Text(), nullable=False),
        sa.Column('model_name', sa.String(200), nullable=False),
        sa.Column('vision_model_name', sa.String(200), nullable=False),
        sa.Column('steps_count', sa.Integer(), nullable=False),
        sa.Column('image_calls', sa.Integer(), nullable=False),
        sa.Column('max_steps', sa.Integer(), nullable=False),
        sa.Column('max_images', sa.Integer(), nullable=False),
        sa.Column('error', sa.Text(), nullable=False),
        sa.Column('summary', sa.Text(), nullable=False),
        sa.Column('created_at', sa.String(40), nullable=False),
        sa.Column('updated_at', sa.String(40), nullable=False),
        sa.Column('finished_at', sa.String(40), nullable=True),
    )
    op.create_index('ix_agent_runs_owner_id', 'agent_runs', ['owner_id'])
    op.create_index('ix_agent_runs_status', 'agent_runs', ['status'])

    op.create_table(
        'agent_steps',
        sa.Column('run_id', sa.String(36), primary_key=True),
        sa.Column('step_index', sa.Integer(), primary_key=True),
        sa.Column('kind', sa.String(16), nullable=False),
        sa.Column('tool_name', sa.String(64), nullable=False),
        sa.Column('arguments', sa.Text(), nullable=False),
        sa.Column('result', sa.Text(), nullable=False),
        sa.Column('created_at', sa.String(40), nullable=False),
    )
    op.create_index('ix_agent_steps_run_id', 'agent_steps', ['run_id'])

    op.create_table(
        'agent_artifacts',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('run_id', sa.String(36), nullable=False),
        sa.Column('kind', sa.String(16), nullable=False),
        sa.Column('name', sa.String(200), nullable=False),
        sa.Column('path', sa.String(500), nullable=False),
        sa.Column('sha256', sa.String(64), nullable=False),
        sa.Column('size', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.String(40), nullable=False),
    )
    op.create_index('ix_agent_artifacts_run_id', 'agent_artifacts', ['run_id'])

    op.add_column('image_jobs', sa.Column('agent_run_id', sa.String(36), nullable=True))
    op.create_index('ix_image_jobs_agent_run_id', 'image_jobs', ['agent_run_id'])
    op.add_column('image_configurations', sa.Column('vision_model_name', sa.String(200), nullable=False, server_default=''))


def downgrade():
    op.drop_column('image_configurations', 'vision_model_name')
    op.drop_index('ix_image_jobs_agent_run_id', table_name='image_jobs')
    op.drop_column('image_jobs', 'agent_run_id')
    op.drop_table('agent_artifacts')
    op.drop_table('agent_steps')
    op.drop_table('agent_runs')
    op.drop_table('skill_files')
    op.drop_table('skill_versions')
    op.drop_table('skill_packages')
