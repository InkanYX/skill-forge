from app.authorization import owner_view, require_edit
"""Natural-language templates only; imported skills are never executed as code."""
import json
import re
from datetime import datetime, timezone
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator, model_validator
from typing import Literal
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.database import CreativeTemplate, CreativeCase, ImageJob, CreationProject
from app.skills import resolve_skill
from app.image_sizes import ImageSize
from app.learning_feedback import LearningFeedback, freeze_learning, read_learning, comparison_candidates

VARIABLE = re.compile(r"\{\{\s*([^{}\n]{1,40}?)\s*\}\}")


class TemplateInput(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    purpose: str = Field(default="", max_length=1000)
    prompt: str = Field(min_length=1, max_length=12000)
    skill: str = Field(default="", max_length=20000)
    skill_id: UUID | None = None
    skill_revision: int = Field(default=0, ge=0)
    notes: str = Field(default="", max_length=2000)
    size: ImageSize = "default"
    count: int = Field(default=4, ge=1, le=16)
    revision: int = Field(default=0, ge=0)

    @field_validator("name", "prompt")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("名称和提示词不能为空。")
        return value.strip()


class CaseInput(BaseModel):
    job_id: UUID
    title: str = Field(min_length=1, max_length=120)
    experience: str = Field(default='', max_length=4000)
    issues: str = Field(default="", max_length=4000)
    outcome: Literal['pending', 'satisfied', 'rework', 'discarded'] = 'pending'
    learning: LearningFeedback | None = None
    requested_change: str = Field(default='', max_length=4000)
    product_id: UUID | None = None
    revision: int | None = Field(default=None, ge=0)

    @field_validator("title")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("请填写标题和有效经验。")
        return value.strip()

    @model_validator(mode='after')
    def meaningful(self):
        if not any(value.strip() for value in (self.experience, self.issues, self.requested_change)) and not (self.learning and (self.learning.reason.strip() or any(self.learning.ratings.model_dump().values()))):
            raise ValueError('请至少填写一项有效做法、问题或修改要求。')
        return self


def timestamp():
    return datetime.now(timezone.utc).isoformat()


def template_view(row):
    data = json.loads(row.content)
    variables = list(dict.fromkeys(match.strip() for match in VARIABLE.findall(data['prompt'] + '\n' + data['skill'] + '\n' + data['notes'])))
    return {**owner_view(row), **data, "id": row.id, "revision": row.revision, "updated_at": row.updated_at, "variables": variables}


def render_template(session, request, extra):
    try:
        identifier = str(UUID(request['id']))
        revision = int(request['revision'])
        values = request['variables']
        if not isinstance(values, dict) or len(values) > 100 or any(not isinstance(v, str) or len(v) > 2000 for v in values.values()):
            raise ValueError()
    except (KeyError, ValueError, TypeError, AttributeError):
        raise HTTPException(422, "模板参数格式无效。") from None
    row = session.get(CreativeTemplate, identifier)
    if row is None:
        raise HTTPException(404, "创作模板不存在。")
    if row.revision != revision:
        raise HTTPException(409, "模板已更新，请重新选择模板后提交。")
    snapshot = template_view(row)
    if any(not values.get(key, '').strip() for key in snapshot['variables']):
        raise HTTPException(422, "请填齐模板中的填写项。")
    def fill(text):
        return VARIABLE.sub(lambda match: values[match.group(1).strip()].strip(), text)
    parts = [fill(snapshot['prompt'])]
    if snapshot['skill'].strip():
        parts.append("制作方法（自然语言 Skill）：\n" + fill(snapshot['skill']))
    if snapshot['notes'].strip():
        parts.append("画面注意事项：\n" + fill(snapshot['notes']))
    if extra.strip():
        parts.append("本次补充要求：\n" + extra.strip())
    prompt = '\n\n'.join(parts)
    if len(prompt) > 32000:
        raise HTTPException(422, "合并后的创作要求超过 32000 字符，请精简模板或 Skill。")
    return prompt, {**snapshot, "values": values, "extra": extra}


def build_creative_router(engine):
    router = APIRouter(prefix="/api", tags=["creative-library"])
    def require_db():
        if engine is None:
            raise HTTPException(503, "请先配置数据库并执行迁移。")

    @router.get('/templates')
    def list_templates():
        require_db()
        with Session(engine) as session:
            return [template_view(row) for row in session.scalars(select(CreativeTemplate).order_by(CreativeTemplate.updated_at.desc()))]

    def save(data, identifier=None):
        require_db()
        with Session(engine) as session, session.begin():
            content = data.model_dump(mode='json', exclude={'revision'})
            if data.skill_id:
                content.update(resolve_skill(session, data.skill_id, data.skill_revision))
            elif data.skill_revision:
                raise HTTPException(422, '请先选择关联的 Skill。')
            if identifier:
                row = session.get(CreativeTemplate, str(identifier), with_for_update=True)
                if row is None:
                    raise HTTPException(404, "模板不存在。")
                require_edit(row)
                if row.revision != data.revision:
                    raise HTTPException(409, "模板已被修改，请重新载入。")
                row.revision += 1
            else:
                row = CreativeTemplate(id=str(uuid4()), revision=1)
                session.add(row)
            row.content = json.dumps(content, ensure_ascii=False)
            row.updated_at = timestamp()
            return template_view(row)

    @router.post('/templates', status_code=201)
    def create_template(data: TemplateInput):
        return save(data)

    @router.put('/templates/{identifier}')
    def update_template(identifier: UUID, data: TemplateInput):
        return save(data, identifier)

    def case_view(row, job, session):
        from app.product_experience import job_product
        product_id = job_product(session, job) or row.product_id
        product = session.get(CreationProject, product_id) if product_id else None
        review = json.loads(job.execution_result or '{}').get('review', {})
        return {**owner_view(job), "id": row.id, "job_id": row.job_id, "title": row.title, "experience": row.experience, "issues": row.issues or review.get('notes', ''),
                'outcome': row.outcome if row.outcome != 'pending' else {'passed': 'satisfied', 'rework': 'rework'}.get(review.get('status'), 'pending'),
                'requested_change': row.requested_change, 'product_id': product_id, 'product_name': product.title if product else '',
                'product_locked': bool(job_product(session, job)),
                'learning': read_learning(job), 'comparison_candidates': comparison_candidates(session, job, product_id),
                'revision': row.revision, 'updated_at': row.updated_at, "image_url": f"/api/image-jobs/{row.job_id}/image", "prompt": job.prompt, "model_name": job.model_name, "product_snapshot": json.loads(job.product_snapshot), "template_snapshot": json.loads(job.template_snapshot)}

    @router.get('/cases')
    def list_cases():
        require_db()
        with Session(engine) as session:
            rows = session.execute(select(CreativeCase, ImageJob).join(ImageJob, ImageJob.id == CreativeCase.job_id).order_by(CreativeCase.updated_at.desc()))
            return [case_view(row, job, session) for row, job in rows]

    @router.post('/cases')
    def save_case(data: CaseInput):
        require_db()
        with Session(engine) as session, session.begin():
            job = session.get(ImageJob, str(data.job_id), with_for_update=True)
            if job is None or job.status != 'succeeded':
                raise HTTPException(422, "只能为已完成的图片记录经验。")
            require_edit(job)
            row = session.scalar(select(CreativeCase).where(CreativeCase.job_id == job.id))
            from app.product_experience import job_product
            inferred_product = job_product(session, job)
            if data.product_id and inferred_product and str(data.product_id) != inferred_product:
                raise HTTPException(409, '这张图片已关联策划产品，不能改为其他产品。')
            product_id = inferred_product or (str(data.product_id) if data.product_id else None)
            if product_id:
                parent = session.get(CreationProject, product_id)
                if not parent or parent.kind != 'product': raise HTTPException(422, '请选择有效产品。')
            if row is None:
                if data.revision: raise HTTPException(409, '反馈不存在，请重新读取。')
                row = CreativeCase(id=str(uuid4()), job_id=job.id, revision=1)
                session.add(row)
            else:
                if data.revision is not None and data.revision != row.revision: raise HTTPException(409, '反馈已更新，请重新读取后保存。')
                row.revision += 1
            row.title, row.experience, row.issues, row.updated_at = data.title, data.experience, data.issues, timestamp()
            row.outcome, row.requested_change, row.product_id = data.outcome, data.requested_change, product_id
            result = json.loads(job.execution_result or '{}')
            if data.learning is not None:
                result['human_feedback'] = freeze_learning(session, job, product_id, data.learning)
            result['review'] = {'status': {'pending': 'pending', 'satisfied': 'passed', 'rework': 'rework', 'discarded': 'rework'}[data.outcome],
                                'notes': '\n'.join(filter(None, [data.issues, data.requested_change])), 'updated_at': row.updated_at}
            job.execution_result = json.dumps(result, ensure_ascii=False)
            session.flush()
            return case_view(row, job, session)

    @router.get('/cases/{job_id}')
    def get_artwork_note(job_id: UUID, feedback: bool = False):
        require_db()
        with Session(engine) as session:
            job = session.get(ImageJob, str(job_id))
            if job is None:
                raise HTTPException(404, '作品不存在。')
            row = session.scalar(select(CreativeCase).where(CreativeCase.job_id == job.id))
            if row: return case_view(row, job, session)
            if not feedback: return None
            from app.product_experience import job_product
            product_id = job_product(session, job)
            product = session.get(CreationProject, product_id) if product_id else None
            review = json.loads(job.execution_result or '{}').get('review', {})
            return {**owner_view(job), 'learning': read_learning(job), 'comparison_candidates': comparison_candidates(session, job, product_id), 'id': '', 'job_id': job.id, 'title': '', 'experience': '',
                    'issues': review.get('notes', ''), 'requested_change': '', 'revision': 0,
                    'outcome': {'passed': 'satisfied', 'rework': 'rework'}.get(review.get('status'), 'pending'),
                    'product_id': product_id, 'product_name': product.title if product else '', 'product_locked': bool(product_id)}
    return router
