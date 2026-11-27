"""Request identity and ownership checks, also enforced for ORM writes."""
from contextvars import ContextVar
from fastapi import HTTPException
from sqlalchemy import event, inspect, select
from sqlalchemy.orm import Session, with_loader_criteria

principal = ContextVar('request_principal', default=None)

def can_edit(row):
    user = principal.get()
    return user is None or getattr(row,'owner_id',None) == user['id'] or (inspect(row).pending and not getattr(row,'owner_id',None))

def require_edit(row):
    if not can_edit(row): raise HTTPException(403, '只能修改自己创建的内容；可以查看或复制团队共享内容。')

def require_private(row):
    user = principal.get()
    if user is not None and row.owner_id != user['id']:
        raise HTTPException(404, '个人模型连接不存在。')

def owner_view(row):
    user = principal.get()
    return {'owner_id': getattr(row,'owner_id',None) or (user['id'] if user and inspect(row).pending else None), 'can_edit': can_edit(row)}


@event.listens_for(Session, 'do_orm_execute')
def hide_deleted_projects(state):
    if not state.is_select or state.execution_options.get('include_deleted_projects'):
        return
    from app.database import CreationProject
    state.statement = state.statement.options(with_loader_criteria(
        CreationProject, lambda row: row.deleted_at.is_(None), include_aliases=True))


@event.listens_for(Session, 'do_orm_execute')
def isolate_personal_reads(state):
    """Apply to entities, counts, nested queries and primary-key/file lookups alike.

    Worker sessions have no request principal. Team sharing reads only its own
    snapshot table, never bypasses this filter to expose live personal records.
    """
    user = principal.get()
    if not user or not state.is_select: return
    from app.database import (OwnedRecord, CreationProject, CreationMaterial, CreationDocument,
        CreationExecution, AgentRun, AgentStep, AgentArtifact, CreativeSkill, SkillRevision, SkillPackage, SkillVersion, SkillFile)
    owner = user['id']
    state.statement = state.statement.options(with_loader_criteria(
        OwnedRecord, lambda row: row.owner_id == owner, include_aliases=True))
    projects = select(CreationProject.id).where(CreationProject.owner_id == owner)
    runs = select(AgentRun.id).where(AgentRun.owner_id == owner)
    skills = select(CreativeSkill.id).where(CreativeSkill.owner_id == owner)
    for model in (CreationMaterial, CreationDocument, CreationExecution):
        state.statement = state.statement.options(with_loader_criteria(model, model.project_id.in_(projects), include_aliases=True))
    for model in (AgentStep, AgentArtifact):
        state.statement = state.statement.options(with_loader_criteria(model, model.run_id.in_(runs), include_aliases=True))
    state.statement = state.statement.options(with_loader_criteria(SkillRevision, SkillRevision.skill_id.in_(skills), include_aliases=True))
    packages=select(SkillPackage.id).where((SkillPackage.owner_id==owner)|(SkillPackage.source=='builtin')|SkillPackage.owner_id.is_(None))
    versions=select(SkillVersion.id).where(SkillVersion.skill_id.in_(packages))
    state.statement = state.statement.options(with_loader_criteria(SkillPackage,
        (SkillPackage.owner_id==owner)|(SkillPackage.source=='builtin')|SkillPackage.owner_id.is_(None),include_aliases=True),
        with_loader_criteria(SkillVersion,SkillVersion.skill_id.in_(packages),include_aliases=True),
        with_loader_criteria(SkillFile,SkillFile.version_id.in_(versions),include_aliases=True))

@event.listens_for(Session, 'before_flush')
def protect_writes(session, flush_context, instances):
    from app.database import CreationProject, CreationDocument, CreationMaterial, ImageJob
    pending = session.info.setdefault('team_changed_projects', set())
    for row in set(session.new) | set(session.dirty):
        if isinstance(row, CreationProject): pending.add(row.id)
        elif isinstance(row, (CreationDocument, CreationMaterial)): pending.add(row.project_id)
        elif isinstance(row, ImageJob) and row.task_id: pending.add(row.task_id)
    user = principal.get()
    if user is None: return
    from app.database import OwnedRecord, ModelConfiguration, ProductAsset, Product, CreativeCase, ImageJob
    for row in set(session.new) | set(session.dirty) | set(session.deleted):
        if not isinstance(row, OwnedRecord): continue
        if row in session.new:
            row.owner_id = user['id']
            if isinstance(row, ProductAsset):
                parent = session.get(Product, row.product_id)
                if parent: require_edit(parent)
            if isinstance(row, CreativeCase):
                parent = session.get(ImageJob, row.job_id)
                if parent: require_edit(parent)
        else:
            if isinstance(row, ModelConfiguration): require_private(row)
            else: require_edit(row)
            if inspect(row).attrs.owner_id.history.has_changes():
                raise HTTPException(403, '不能改变内容归属。')


@event.listens_for(Session, 'after_flush_postexec')
def prepare_default_team_share(session, flush_context):
    identifiers = session.info.pop('team_changed_projects', set())
    if not identifiers: return
    from app.team_sharing import ensure_default_shares
    ensure_default_shares(session, identifiers)
