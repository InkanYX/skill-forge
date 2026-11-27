"""Reversible, atomic removal of persisted generation versions."""
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.authorization import require_edit
from app.database import ImageJob
from app.creation_projects import LOCK, load_project, check_idle, touch
from app.image_batches import normalize_batches
from app.image_jobs import now


class BatchRemoval(BaseModel):
    batch_ids: list[UUID] = Field(min_length=1, max_length=100)
    request_id: UUID


def build_batch_trash_router(store):
    router = APIRouter(prefix='/api/creation-projects')

    @router.post('/{project_id}/batches/delete')
    def remove(project_id: UUID, value: BatchRemoval, request: Request):
        if store.engine is None: raise HTTPException(503, '请先配置数据库并执行迁移。')
        with LOCK, Session(store.engine) as session, session.begin():
            project, data = load_project(session, project_id, request.state.image_owner)
            require_edit(project)
            token = str(value.request_id)
            ids = {str(identifier) for identifier in value.batch_ids}
            prior = data.get('batch_trash', {}).get(token)
            if prior:
                if set(prior['batch_ids']) != ids: raise HTTPException(409, '删除标识已被使用。')
                return {'request_id': token, 'count': len(prior['job_ids'])}
            check_idle(session, project.id)
            batches = normalize_batches(data.get('batches', []))
            visible = [b for b in batches if not b.get('deleted_at')]
            if not ids <= {b['execution_id'] for b in visible}: raise HTTPException(404, '版本不存在或已删除。')
            if visible and visible[-1]['execution_id'] in ids: raise HTTPException(409, '请保留最新版本，只能删除旧版本。')
            selected = [b for b in visible if b['execution_id'] in ids]
            members = lambda b: set(b['job_ids']) | {i for values in b.get('retry_history', {}).values() for i in values}
            targets = set().union(*(members(b) for b in selected))
            protected = set().union(*(members(b) for b in batches if b['execution_id'] not in ids))
            jobs = list(session.scalars(select(ImageJob).where(ImageJob.owner_id == project.owner_id).with_for_update()))
            # Include local edit descendants, but never consume another version's root.
            while True:
                children = {j.id for j in jobs if j.parent_job_id in targets and j.id not in protected}
                expanded = targets | children
                if expanded == targets: break
                targets = expanded
            rows = [j for j in jobs if j.id in targets and not j.deleted_at]
            if any(j.status in ('queued', 'running', 'paused', 'unknown') for j in rows):
                raise HTTPException(409, '所选版本含正在执行或结果待确认的图片，请核对结果后删除。')
            stamp = now()
            for job in rows: job.deleted_at = stamp
            for batch in selected: batch['deleted_at'] = stamp
            data['batches'] = batches
            data.setdefault('batch_trash', {})[token] = {'batch_ids': sorted(ids), 'job_ids': [j.id for j in rows], 'deleted_at': stamp}
            touch(project, data)
            return {'request_id': token, 'count': len(rows)}

    @router.post('/{project_id}/batches/restore/{request_id}')
    def restore(project_id: UUID, request_id: UUID, request: Request):
        if store.engine is None: raise HTTPException(503, '请先配置数据库并执行迁移。')
        with LOCK, Session(store.engine) as session, session.begin():
            project, data = load_project(session, project_id, request.state.image_owner)
            require_edit(project)
            record = data.get('batch_trash', {}).get(str(request_id))
            if not record: raise HTTPException(404, '删除记录不存在。')
            for job in session.scalars(select(ImageJob).where(ImageJob.id.in_(record['job_ids'])).with_for_update()):
                if job.deleted_at == record['deleted_at']: job.deleted_at = None
            for batch in data.get('batches', []):
                if batch['execution_id'] in record['batch_ids'] and batch.get('deleted_at') == record['deleted_at']:
                    batch.pop('deleted_at', None)
            touch(project, data)
            return {'restored': True}

    return router
