"""Atomic, owner-scoped soft deletion and undo for image plans."""
import json
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.creation_projects import LOCK, check_idle, touch
from app.database import CreationProject, ImageJob, TeamProjectShare
from app.image_jobs import now


class PlanTarget(BaseModel):
    id: UUID
    revision: int = Field(ge=1)


class DeletePlans(BaseModel):
    request_id: UUID
    plans: list[PlanTarget] = Field(min_length=1, max_length=100)

    @model_validator(mode='after')
    def unique_ids(self):
        if len({item.id for item in self.plans}) != len(self.plans):
            raise ValueError('不能重复选择同一策划。')
        return self


class RestorePlans(BaseModel):
    request_id: UUID
    project_ids: list[UUID] = Field(min_length=1, max_length=100)


def build_plan_trash_router(store):
    router = APIRouter(prefix='/api/creation-projects/batch-delete', tags=['plan-trash'])

    def load(session, identifier, owner):
        row = session.get(CreationProject, str(identifier), with_for_update=True,
                          execution_options={'include_deleted_projects': True})
        if row is None or row.owner_id != owner:
            raise HTTPException(404, '所选图片策划不存在，请刷新列表。')
        if row.kind != 'plan':
            raise HTTPException(409, '此入口仅删除图片策划，不删除产品资料或旧版创作任务。')
        return row, json.loads(row.content)

    @router.post('')
    def remove(request: Request, value: DeletePlans):
        store.require_db()
        token = str(value.request_id)
        with LOCK, Session(store.engine) as session, session.begin():
            targets = [(item, *load(session, item.id, request.state.image_owner))
                       for item in sorted(value.plans, key=lambda item: str(item.id))]
            # Validate the entire selection before changing anything.
            for item, row, data in targets:
                if row.deleted_at and data.get('plan_trash', {}).get('request_id') == token:
                    continue
                if row.deleted_at or row.revision != item.revision:
                    raise HTTPException(409, f'「{row.title}」已更新，请刷新列表后重新选择。')
                check_idle(session, row.id)
            stamp = now()
            for _, row, data in targets:
                if row.deleted_at:
                    continue
                jobs = list(session.scalars(select(ImageJob).where(
                    ImageJob.task_id == row.id, ImageJob.deleted_at.is_(None)).with_for_update()))
                share = session.scalar(select(TeamProjectShare).where(
                    TeamProjectShare.project_id == row.id).with_for_update())
                data['plan_trash'] = {'request_id': token, 'deleted_at': stamp,
                    'job_ids': [job.id for job in jobs],
                    'share_visibility': share.visibility if share else None}
                row.deleted_at = stamp
                for job in jobs:
                    job.deleted_at = stamp
                if share:
                    share.visibility = 'deleted'
                touch(row, data)
            return {'request_id': token, 'project_ids': [row.id for _, row, _ in targets],
                    'count': len(targets)}

    @router.post('/restore')
    def restore(request: Request, value: RestorePlans):
        store.require_db()
        token = str(value.request_id)
        with LOCK, Session(store.engine) as session, session.begin():
            targets = [load(session, identifier, request.state.image_owner)
                       for identifier in sorted(set(value.project_ids), key=str)]
            for row, data in targets:
                if data.get('plan_trash', {}).get('request_id') != token:
                    raise HTTPException(409, '删除记录已改变，无法撤销本次操作。')
            for row, data in targets:
                if not row.deleted_at:
                    continue
                record = data['plan_trash']
                jobs = session.scalars(select(ImageJob).where(
                    ImageJob.id.in_(record['job_ids']), ImageJob.task_id == row.id,
                    ImageJob.deleted_at == record['deleted_at']).with_for_update())
                for job in jobs:
                    job.deleted_at = None
                share = session.scalar(select(TeamProjectShare).where(
                    TeamProjectShare.project_id == row.id).with_for_update())
                if share and share.visibility == 'deleted':
                    share.visibility = record['share_visibility'] or 'private'
                row.deleted_at = None
                record['restored_at'] = now()
                touch(row, data)
            return {'request_id': token, 'project_ids': [row.id for row, _ in targets],
                    'count': len(targets)}
    return router
