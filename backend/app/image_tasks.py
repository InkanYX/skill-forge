from app.authorization import can_edit, require_edit
"""Submission-level history; image jobs remain the durable execution units."""
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Form
from sqlalchemy import select, func, case, cast, JSON, type_coerce, or_, update, literal, union_all
from sqlalchemy.orm import Session

from app.database import ImageJob, CreativeCase, AgentRun, ImageConfiguration
from app.creation_conversations import conversation_id, conversation_key, latest_turns

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


def summarize(rows, run=None, root=None, config=None):
    first = rows[0] if rows else None
    counts = {state: 0 for state in STATES}
    counts.update(Counter(row.status for row in rows)); counts['total'] = len(rows)
    product = json.loads(first.product_snapshot or '{}') if first else {}
    template = json.loads(first.template_snapshot or '{}') if first else {}
    kind = 'skill' if run else 'edit' if first.parent_job_id else 'set' if first.set_id else 'free'
    if run and first and not json.loads(first.execution_profile or '{}').get('prepared_by_agent'):
        kind = 'edit' if first.parent_job_id else 'set' if first.set_id else 'free'
    title = run.goal if run else first.set_name if kind == 'set' else first.edit_instruction if kind == 'edit' else first.prompt.split('\n', 1)[0]
    return {
        'owner_id': run.owner_id if run else first.owner_id,
        'can_manage': can_edit(run) if run else all(can_edit(row) for row in rows),
        'id': conversation_id(run) if run else first.task_id or first.request_id,
        'kind': kind, 'title': title[:100] or '图片制作',
        'status': task_status(counts) if run and run.status == 'waiting_images' else run.status if run else task_status(counts), 'counts': counts,
        'created_at': (root or run).created_at if run else min(row.created_at for row in rows),
        'updated_at': max([run.updated_at] + [row.updated_at for row in rows]) if run else max(row.updated_at for row in rows),
        'model_name': first.model_name if first else '', 'config_name': first.config_name if first else config.name if config else '',
        'agent_run_id': run.id if run else None, 'turn_count': run.turn_index if run else 1,
        'agent_summary': (run.summary or run.error) if run else '',
        'product_snapshot': product, 'template_snapshot': template,
        'completed_job_ids': [row.id for row in rows if row.status == 'succeeded'],
    }


def build_task_router(engine, job_view):
    router = APIRouter(prefix='/tasks', tags=['image-tasks'])

    def require_db():
        if engine is None: raise HTTPException(503, '请先配置数据库并执行迁移。')

    def task_rows(session, identifier):
        return list(session.scalars(select(ImageJob).where(task_key() == identifier).order_by(ImageJob.task_index, ImageJob.created_at, ImageJob.id)))

    def summary(session, identifier, rows):
        run = session.scalar(select(AgentRun).where(conversation_key() == identifier)
                             .order_by(AgentRun.turn_index.desc(), AgentRun.created_at.desc(), AgentRun.id.desc()).limit(1))
        if not rows and not run:
            raise HTTPException(404, '生成任务不存在。')
        root = session.get(AgentRun, identifier) if run else None
        config = session.get(ImageConfiguration, run.config_id) if run and not rows else None
        return summarize(rows, run, root, config)

    def detail(session, identifier):
        rows = task_rows(session, identifier)
        cases = dict(session.execute(select(CreativeCase.job_id, CreativeCase.id).where(CreativeCase.job_id.in_([row.id for row in rows]))).all())
        return {**summary(session, identifier, rows), 'items': [{**job_view(row).model_dump(), 'case_id': cases.get(row.id), 'diagnostic': json.loads(row.provider_diagnostic or '{}') or None} for row in rows]}

    @router.get('')
    def list_tasks(page: Annotated[int, Query(ge=1, le=100000)] = 1, page_size: Annotated[int, Query(ge=1, le=24)] = 8,
                   status: Literal['all', 'queued', 'running', 'succeeded', 'partial', 'failed', 'unknown', 'cancelled', 'needs_review', 'needs_changes', 'limit_reached'] = 'all',
                   q: Annotated[str, Query(max_length=200)] = '', product_id: UUID | None = None, template_id: UUID | None = None,
                   favorite: bool = False, has_notes: bool = False):
        require_db()
        columns = [func.count(ImageJob.id).label('total'),
                   *(func.sum(case((ImageJob.status == item, 1), else_=0)).label(item) for item in STATES)]
        orphan = ~select(AgentRun.id).where(AgentRun.id == ImageJob.agent_run_id).correlate(ImageJob).exists()
        direct = select(task_key().label('id'), func.min(ImageJob.created_at).label('created_at'), *columns,
                        literal(None).label('agent_status'), literal('').label('goal')).where(orphan).group_by(task_key())
        heads = select(AgentRun.id.label('run_id'), conversation_key().label('id'), AgentRun.status,
                       AgentRun.goal).where(AgentRun.id.in_(latest_turns())).subquery()
        roots = select(conversation_key().label('id'), func.min(AgentRun.created_at).label('created_at'))\
            .group_by(conversation_key()).subquery()
        assisted = select(heads.c.id, roots.c.created_at, *columns, heads.c.status.label('agent_status'), heads.c.goal)\
            .select_from(heads.join(roots, heads.c.id == roots.c.id).outerjoin(ImageJob, task_key() == heads.c.id))\
            .group_by(heads.c.id, roots.c.created_at, heads.c.status, heads.c.goal)
        grouped = union_all(direct, assisted).subquery()
        state = case((grouped.c.agent_status.is_not(None) & (grouped.c.agent_status != 'waiting_images'), grouped.c.agent_status),
                     (grouped.c.running > 0, 'running'), (grouped.c.queued > 0, 'queued'), (grouped.c.unknown > 0, 'unknown'),
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
            text_match = or_(task_key().icontains(text, autoescape=True), ImageJob.prompt.icontains(text, autoescape=True), ImageJob.model_name.icontains(text, autoescape=True), ImageJob.set_name.icontains(text, autoescape=True), ImageJob.shot_name.icontains(text, autoescape=True), product['sku'].as_string().icontains(text, autoescape=True), product['name'].as_string().icontains(text, autoescape=True), template['name'].as_string().icontains(text, autoescape=True), note)
            conditions.append(or_(grouped.c.goal.icontains(text, autoescape=True), grouped.c.id.icontains(text, autoescape=True),
                                  select(ImageJob.id).where(task_key() == grouped.c.id, text_match).correlate(grouped).exists()))
        if matches:
            conditions.append(select(ImageJob.id).where(task_key() == grouped.c.id, *matches).correlate(grouped).exists())
        with Session(engine) as session:
            total = session.scalar(select(func.count()).select_from(grouped).where(*conditions))
            identifiers = list(session.scalars(select(grouped.c.id).where(*conditions).order_by(grouped.c.created_at.desc(), grouped.c.id.desc()).offset((page - 1) * page_size).limit(page_size)))
            grouped_rows = defaultdict(list)
            if identifiers:
                for row in session.scalars(select(ImageJob).where(task_key().in_(identifiers)).order_by(ImageJob.task_index, ImageJob.created_at, ImageJob.id)):
                    grouped_rows[row.task_id or row.request_id].append(row)
            return {'items': [summary(session, identifier, grouped_rows[identifier]) for identifier in identifiers], 'total': total, 'page': page, 'page_size': page_size}

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
            run = session.scalar(select(AgentRun).where(conversation_key() == str(task_id))
                                 .order_by(AgentRun.turn_index.desc()).limit(1).with_for_update())
            if run:
                require_edit(run)
                if run.status in ('queued', 'running', 'waiting_images'):
                    run.status, run.error, run.updated_at, run.finished_at = (
                        'cancelled', '任务已取消。', datetime.now(timezone.utc).isoformat(), datetime.now(timezone.utc).isoformat())
            if not run and session.scalar(select(ImageJob.id).where(task_key() == str(task_id)).limit(1)) is None:
                raise HTTPException(404, '生成任务不存在。')
            for row in task_rows(session,str(task_id)):
                require_edit(row)
            cancelled = list(session.scalars(update(ImageJob).where(task_key() == str(task_id), ImageJob.status == 'queued').values(status='cancelled', message='已取消排队，未调用服务商。', encrypted_key='', updated_at=datetime.now(timezone.utc).isoformat()).returning(ImageJob.id)))
            return {'cancelled_count': len(cancelled), 'message': f'已取消 {len(cancelled)} 张排队图片。'}
    return router
