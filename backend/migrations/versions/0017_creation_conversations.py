"""Link skill-assisted creation turns and group their image results."""
from alembic import op
import sqlalchemy as sa

revision = '0017_creation_conversations'
down_revision = '0016_private_skill_packages'
branch_labels = depends_on = None


def upgrade():
    op.add_column('agent_runs', sa.Column('conversation_id', sa.String(36), nullable=True))
    op.add_column('agent_runs', sa.Column('parent_run_id', sa.String(36), nullable=True))
    op.add_column('agent_runs', sa.Column('source_job_id', sa.String(36), nullable=True))
    op.add_column('agent_runs', sa.Column('turn_index', sa.Integer(), nullable=False, server_default='1'))
    op.add_column('agent_runs', sa.Column('instruction', sa.Text(), nullable=False, server_default=''))
    op.create_index('ix_agent_runs_conversation_id', 'agent_runs', ['conversation_id'])
    # Old runs had no reliable parent relation; preserve each as an independent
    # conversation instead of guessing relationships from concatenated text.
    op.execute(sa.text('UPDATE agent_runs SET conversation_id = id'))
    op.create_index('uq_agent_conversation_turn', 'agent_runs', ['conversation_id', 'turn_index'], unique=True)
    op.execute(sa.text('''UPDATE image_jobs SET task_id = agent_run_id
        WHERE agent_run_id IN (SELECT id FROM agent_runs)'''))


def downgrade():
    # Restore legacy submission groups before removing conversation metadata.
    op.execute(sa.text('UPDATE image_jobs SET task_id = request_id WHERE agent_run_id IS NOT NULL'))
    op.drop_index('uq_agent_conversation_turn', table_name='agent_runs')
    op.drop_index('ix_agent_runs_conversation_id', table_name='agent_runs')
    for column in ('instruction', 'turn_index', 'source_job_id', 'parent_run_id', 'conversation_id'):
        op.drop_column('agent_runs', column)
