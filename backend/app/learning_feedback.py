"""Human evaluations and bounded, explicit preference evidence."""
import difflib
import json
from typing import Literal
from uuid import UUID
from fastapi import HTTPException
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from app.database import ImageJob, CreativeCase


class Ratings(BaseModel):
    fidelity: int | None = Field(default=None, ge=1, le=5)
    composition: int | None = Field(default=None, ge=1, le=5)
    typography: int | None = Field(default=None, ge=1, le=5)
    scene: int | None = Field(default=None, ge=1, le=5)
    style: int | None = Field(default=None, ge=1, le=5)


class LearningFeedback(BaseModel):
    ratings: Ratings = Field(default_factory=Ratings)
    reference_job_id: UUID | None = None
    preference: Literal['unrated', 'current', 'reference', 'tie'] = 'unrated'
    reason: str = Field(default='', max_length=4000)

    @model_validator(mode='after')
    def valid_preference(self):
        if self.preference != 'unrated' and (not self.reference_job_id or not self.reason.strip()):
            raise ValueError('版本偏好需要选择对比图片并说明原因。')
        return self


class LearningSettings(BaseModel):
    enabled: bool = True
    category: str = Field(default='', max_length=120)
    image_type: Literal['any', 'listing', 'a_plus', 'detail'] = 'any'
    device: Literal['any', 'desktop', 'mobile'] = 'any'
    excluded_ids: list[UUID] = Field(default_factory=list, max_length=100)


def comparison_candidates(session, job, product_id):
    from app.product_experience import job_product, feedback_product
    rows = session.scalars(select(ImageJob).where(ImageJob.status == 'succeeded',
        ImageJob.deleted_at.is_(None), ImageJob.id != job.id, ImageJob.owner_id == job.owner_id)
        .order_by(ImageJob.created_at.desc()).limit(300))
    result = []
    for other in rows:
        note = session.scalar(select(CreativeCase).where(CreativeCase.job_id == other.id))
        other_product = feedback_product(session, note, other) if note else job_product(session, other)
        related = bool(product_id and product_id == other_product) or other.id == job.parent_job_id or other.parent_job_id == job.id
        if not related: continue
        result.append({'id': other.id, 'name': other.shot_name or '历史版本', 'created_at': other.created_at,
            'preview_url': f'/api/image-jobs/{other.id}/preview'})
        if len(result) >= 30: break
    return result


def freeze_learning(session, job, product_id, value):
    data = value.model_dump(mode='json')
    if not value.reference_job_id: return data
    if str(value.reference_job_id) not in {item['id'] for item in comparison_candidates(session, job, product_id)}:
        raise HTTPException(422, '对比图必须是同一产品或修改链中本人已完成且未删除的图片。')
    other = session.get(ImageJob, str(value.reference_job_id))
    reference_note=session.scalar(select(CreativeCase).where(CreativeCase.job_id==other.id))
    reference_ratings=read_learning(other).get('ratings',{})
    deltas={name:score-reference_ratings[name] for name,score in data['ratings'].items()
        if score is not None and reference_ratings.get(name) is not None}
    data['comparison'] = {'reference_job_id': other.id, 'reference_prompt': other.prompt,
        'reference_feedback_revision':reference_note.revision if reference_note else None,
        'reference_ratings':reference_ratings,'rating_delta':deltas,
        'current_prompt': job.prompt, 'reference_edit_instruction': other.edit_instruction,
        'current_edit_instruction': job.edit_instruction,
        'prompt_diff': ''.join(difflib.unified_diff(other.prompt.splitlines(keepends=True),
            job.prompt.splitlines(keepends=True), fromfile='reference', tofile='current'))[:32000]}
    return data


def read_learning(job):
    return json.loads(job.execution_result or '{}').get('human_feedback', {})
