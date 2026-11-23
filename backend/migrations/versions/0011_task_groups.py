"""Group image executions by the original submission, including legacy batches."""
from uuid import UUID, uuid5
from alembic import op
import sqlalchemy as sa

revision = '0011_task_groups'
down_revision = '0010_provider_diagnostics'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('image_jobs', sa.Column('task_id', sa.String(36), nullable=True))
    op.add_column('image_jobs', sa.Column('task_index', sa.Integer(), nullable=False, server_default='0'))
    op.create_index('ix_image_jobs_task_id', 'image_jobs', ['task_id'])
    jobs = sa.table('image_jobs', sa.column('id'), sa.column('request_id'), sa.column('fingerprint'), sa.column('task_id'), sa.column('task_index'))
    connection = op.get_bind()
    rows = connection.execute(sa.select(jobs.c.id, jobs.c.request_id, jobs.c.fingerprint)).all()
    lookup = {row.request_id: row for row in rows}
    groups = {row.id: (row.request_id, 0) for row in rows}
    # Old multi-image submissions derived child request UUIDs from their root.
    # Never merge independent submissions merely because their prompts match.
    for row in rows:
        try:
            root = UUID(row.request_id)
        except ValueError:
            continue
        for index in range(1, 8):
            child = lookup.get(str(uuid5(root, f'image-{index}')))
            if child and child.fingerprint == row.fingerprint:
                groups[child.id] = (row.request_id, index)
    for identifier, (task_id, index) in groups.items():
        connection.execute(jobs.update().where(jobs.c.id == identifier).values(task_id=task_id, task_index=index))


def downgrade():
    op.drop_index('ix_image_jobs_task_id', table_name='image_jobs')
    op.drop_column('image_jobs', 'task_index')
    op.drop_column('image_jobs', 'task_id')
