"""Database-wide image admission limits shared by standard and legacy workers."""
from sqlalchemy import false, func, or_, select, text, update

from app.database import ImageJob

GLOBAL_IMAGE_LIMIT = 6
ACCOUNT_IMAGE_LIMIT = 2
_CLAIM_LOCK = 0x5346494D414745


def lock_image_claims(session):
    # Serialize only admission, never the provider request. PostgreSQL shares this
    # transaction lock across API processes and standalone workers.
    dialect = session.get_bind().dialect.name
    if dialect == 'postgresql':
        session.execute(text('SELECT pg_advisory_xact_lock(:key)'), {'key': _CLAIM_LOCK})
    elif dialect == 'sqlite':
        # A no-op write obtains SQLite's write lock before reading slot counts.
        session.execute(update(ImageJob).where(false()).values(updated_at=ImageJob.updated_at))
    else:
        raise RuntimeError('Image scheduling requires PostgreSQL or SQLite.')


def eligible_image_jobs(session, standard):
    running = dict(session.execute(select(ImageJob.owner_id, func.count())
                                  .where(ImageJob.status == 'running').group_by(ImageJob.owner_id)).all())
    if sum(running.values()) >= GLOBAL_IMAGE_LIMIT:
        return None
    conditions = [ImageJob.status == 'queued',
                  ImageJob.execution_profile != '{}' if standard else ImageJob.execution_profile == '{}']
    blocked = [owner for owner, count in running.items() if owner is not None and count >= ACCOUNT_IMAGE_LIMIT]
    if blocked:
        conditions.append(or_(ImageJob.owner_id.is_(None), ImageJob.owner_id.not_in(blocked)))
    if running.get(None, 0) >= ACCOUNT_IMAGE_LIMIT:
        conditions.append(ImageJob.owner_id.is_not(None))
    return select(ImageJob).where(*conditions).order_by(ImageJob.created_at, ImageJob.task_index, ImageJob.id)
