"""Versioned text instructions; importing never executes any content."""
import json
from datetime import datetime, timezone
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.database import CreativeSkill, SkillRevision


class SkillInput(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    purpose: str = Field(default='', max_length=1000)
    content: str = Field(min_length=1, max_length=20000)
    revision: int = Field(default=0, ge=0)

    @field_validator('name', 'content')
    @classmethod
    def nonblank(cls, value, info):
        if not value.strip():
            raise ValueError('请填写 Skill 名称和自然语言内容。')
        return value.strip() if info.field_name == 'name' else value


def skill_view(row):
    identifier = row.skill_id if isinstance(row, SkillRevision) else row.id
    return {**json.loads(row.content), 'id': identifier, 'revision': row.revision, 'updated_at': row.updated_at}


def resolve_skill(session, identifier, revision):
    row = session.get(SkillRevision, (str(identifier), revision))
    if row is None:
        raise HTTPException(422, '所选 Skill 版本不存在，请刷新 Skill 列表后重新选择。')
    snapshot = skill_view(row)
    return {'skill_id': snapshot['id'], 'skill_revision': snapshot['revision'], 'skill_name': snapshot['name'], 'skill': snapshot['content']}


def build_skill_router(engine):
    router = APIRouter(prefix='/api/skills', tags=['skills'])
    def require_db():
        if engine is None:
            raise HTTPException(503, '请先配置数据库并执行迁移。')

    @router.get('')
    def list_skills():
        require_db()
        with Session(engine) as session:
            return [skill_view(row) for row in session.scalars(select(CreativeSkill).order_by(CreativeSkill.updated_at.desc()))]

    def save(data, identifier=None):
        require_db()
        with Session(engine) as session, session.begin():
            content = json.dumps(data.model_dump(exclude={'revision'}), ensure_ascii=False)
            if identifier:
                row = session.get(CreativeSkill, str(identifier), with_for_update=True)
                if row is None:
                    raise HTTPException(404, 'Skill 不存在。')
                if row.revision != data.revision:
                    raise HTTPException(409, 'Skill 已更新，请重新载入后再保存。')
                if row.content == content:
                    return skill_view(row)
                row.revision += 1
            else:
                row = CreativeSkill(id=str(uuid4()), revision=1)
                session.add(row)
            row.content, row.updated_at = content, datetime.now(timezone.utc).isoformat()
            session.add(SkillRevision(skill_id=row.id, revision=row.revision, content=content, updated_at=row.updated_at))
            return skill_view(row)

    @router.post('', status_code=201)
    def create_skill(data: SkillInput):
        return save(data)

    @router.put('/{identifier}')
    def update_skill(identifier: UUID, data: SkillInput):
        return save(data, identifier)

    @router.get('/{identifier}')
    def get_skill(identifier: UUID, revision: Annotated[int | None, Query(ge=1)] = None):
        require_db()
        with Session(engine) as session:
            row = session.get(SkillRevision, (str(identifier), revision)) if revision else session.get(CreativeSkill, str(identifier))
            if row is None:
                raise HTTPException(404, 'Skill 或版本不存在。')
            return skill_view(row)

    @router.get('/{identifier}/versions')
    def versions(identifier: UUID):
        require_db()
        with Session(engine) as session:
            if session.get(CreativeSkill, str(identifier)) is None:
                raise HTTPException(404, 'Skill 不存在。')
            rows = session.scalars(select(SkillRevision).where(SkillRevision.skill_id == str(identifier)).order_by(SkillRevision.revision.desc()).limit(100))
            return [{'revision': row.revision, 'name': json.loads(row.content)['name'], 'updated_at': row.updated_at} for row in rows]

    @router.get('/{identifier}/download')
    def download(identifier: UUID, revision: Annotated[int | None, Query(ge=1)] = None):
        data = get_skill(identifier, revision)
        return Response(data['content'].encode('utf-8'), media_type='text/markdown; charset=utf-8', headers={'Content-Disposition': f'attachment; filename="skill-{identifier}-v{data["revision"]}.md"', 'X-Content-Type-Options': 'nosniff'})
    return router
