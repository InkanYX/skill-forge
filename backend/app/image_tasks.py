"""Submission-level history; image jobs remain the durable execution units."""
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Form
from sqlalchemy import select, func, case, cast, JSON, type_coerce, or_, update
from sqlalchemy.orm import Session

from app.database import ImageJob, CreativeCase

STATES = ('queued', 'running', 'succeeded', 'failed', 'unknown', 'cancelled')


def task_key():
    return func.coalesce(ImageJob.task_id, ImageJob.request_id)


def task_status(counts):
    if counts.get('running'): return 'running'
    if counts.get('queued'): return 'queued'
    if counts.get('unknown'): return 'unknown'
    if counts.get('succeeded') == counts['total']: return 'succeeded'
    if counts.get('cancelled') == counts['total']: return 'cancelled'
    if counts.get('succeeded'): return 'partial'
    return 'failed'


def summarize(rows):
    first = rows[0]
    counts = {state: 0 for state in STATES}
    counts.update(Counter(row.status for row in rows)); counts['total'] = len(rows)
    product = json.loads(first.product_snapshot or '{}')
    template = json.loads(first.template_snapshot or '{}')
    kind = 'edit' if first.parent_job_id else 'set' if first.set_id else 'free'
    title = first.set_name if kind == 'set' else first.edit_instruction if kind == 'edit' else first.prompt.split('\n', 1)[0]
    return {
        'id': first.task_id or first.request_id, 'kind': kind, 'title': title[:100] or '图片制作',
        'status': task_status(counts), 'counts': counts,
        'created_at': min(row.created_at for row in rows), 'updated_at': max(row.updated_at for row in rows),
        'model_name': first.model_name, 'config_name': first.config_name,
        'product_snapshot': product, 'template_snapshot': template,
        'completed_job_ids': [row.id for row in rows if row.status == 'succeeded'],
    }


def build_task_router(engine, job_view):
    router = APIRouter(prefix='/tasks', tags=['image-tasks'])

    def require_db():
        if engine is None: raise HTTPException(503, '请先配置数据库并执行迁移。')

    def task_rows(session, identifier):
        return list(session.scalars(select(ImageJob).where(task_key() == identifier).order_by(ImageJob.task_index, ImageJob.created_at, ImageJob.id)))

    def detail(session, identifier):
        rows = task_rows(session, identifier)
        if not rows: raise HTTPException(404, '生成任务不存在。')
        cases = dict(session.execute(select(CreativeCase.job_id, CreativeCase.id).where(CreativeCase.job_id.in_([row.id for row in rows]))).all())
        return {**summarize(rows), 'items': [{**job_view(row).model_dump(), 'case_id': cases.get(row.id), 'diagnostic': json.loads(row.provider_diagnostic or '{}') or None} for row in rows]}

    @router.get('')
    def list_tasks(page: Annotated[int, Query(ge=1, le=100000)] = 1, page_size: Annotated[int, Query(ge=1, le=24)] = 8,
                   status: Literal['all', 'queued', 'running', 'succeeded', 'partial', 'failed', 'unknown', 'cancelled'] = 'all',
                   q: Annotated[str, Query(max_length=200)] = '', product_id: UUID | None = None, template_id: UUID | None = None,
                   favorite: bool = False, has_notes: bool = False):
        require_db()
        grouped = select(task_key().label('id'), func.min(ImageJob.created_at).label('created_at'), func.count().label('total'),
                         *(func.sum(case((ImageJob.status == state, 1), else_=0)).label(state) for state in STATES)).group_by(task_key()).subquery()
        state = case((grouped.c.running > 0, 'running'), (grouped.c.queued > 0, 'queued'), (grouped.c.unknown > 0, 'unknown'),
                     (grouped.c.succeeded == grouped.c.total, 'succeeded'), (grouped.c.cancelled == grouped.c.total, 'cancelled'),
                     (grouped.c.succeeded > 0, 'partial'), else_='failed')
        conditions = []
        if status != 'all': conditions.append(state == status)
        snapshot = lambda column: type_coerce(column, JSON) if engine.dialect.name == 'sqlite' else cast(column, JSON)
        product, template = snapshot(ImageJob.product_snapshot), snapshot(ImageJob.template_snapshot)
        matches = []
        if product_id: matches.append(product['id'].as_string() == str(product_id))
        if template_id: matches.append(template['id'].as_string() == str(template_id))
        if favorite: matches.append(ImageJob.is_favorite.is_(True))
        if has_notes: matches.append(select(CreativeCase.id).where(CreativeCase.job_id == ImageJob.id).correlate(ImageJob).exists())
        if q.strip():
            text = q.strip()
            note = select(CreativeCase.id).where(CreativeCase.job_id == ImageJob.id, or_(*(column.icontains(text, autoescape=True) for column in (CreativeCase.title, CreativeCase.experience, CreativeCase.issues)))).correlate(ImageJob).exists()
            matches.append(or_(task_key().icontains(text, autoescape=True), ImageJob.prompt.icontains(text, autoescape=True), ImageJob.model_name.icontains(text, autoescape=True), ImageJob.set_name.icontains(text, autoescape=True), ImageJob.shot_name.icontains(text, autoescape=True), product['sku'].as_string().icontains(text, autoescape=True), product['name'].as_string().icontains(text, autoescape=True), template['name'].as_string().icontains(text, autoescape=True), note))
        if matches:
            conditions.append(select(ImageJob.id).where(task_key() == grouped.c.id, *matches).correlate(grouped).exists())
        with Session(engine) as session:
            total = session.scalar(select(func.count()).select_from(grouped).where(*conditions))
            identifiers = list(session.scalars(select(grouped.c.id).where(*conditions).order_by(grouped.c.created_at.desc(), grouped.c.id.desc()).offset((page - 1) * page_size).limit(page_size)))
            grouped_rows = defaultdict(list)
            if identifiers:
                for row in session.scalars(select(ImageJob).where(task_key().in_(identifiers)).order_by(ImageJob.task_index, ImageJob.created_at, ImageJob.id)):
                    grouped_rows[row.task_id or row.request_id].append(row)
            return {'items': [summarize(grouped_rows[identifier]) for identifier in identifiers], 'total': total, 'page': page, 'page_size': page_size}

    @router.get('/for-image/{job_id}')
    def task_for_image(job_id: UUID):
        require_db()
        with Session(engine) as session:
            row = session.get(ImageJob, str(job_id))
            if row is None: raise HTTPException(404, '图片记录不存在。')
            return detail(session, row.task_id or row.request_id)

    @router.get('/{task_id}')
    def get_task(task_id: UUID):
        require_db()
        with Session(engine) as session:
            return detail(session, str(task_id))

    @router.post('/{task_id}/cancel')
    def cancel_task(task_id: UUID, action: Annotated[Literal['cancel'], Form()]):
        require_db()
        with Session(engine) as session, session.begin():
            if session.scalar(select(ImageJob.id).where(task_key() == str(task_id)).limit(1)) is None:
                raise HTTPException(404, '生成任务不存在。')
            cancelled = list(session.scalars(update(ImageJob).where(task_key() == str(task_id), ImageJob.status == 'queued').values(status='cancelled', message='已取消排队，未调用服务商。', encrypted_key='', updated_at=datetime.now(timezone.utc).isoformat()).returning(ImageJob.id)))
            return {'cancelled_count': len(cancelled), 'message': f'已取消 {len(cancelled)} 张排队图片。'}
    return router
