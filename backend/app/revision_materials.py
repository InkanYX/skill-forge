"""Resolve original uploaded evidence through an image's revision ancestry."""
import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import CreationMaterial, CreationProject, ImageJob
from app.image_provider import GenerationError


def revision_materials(engine, source_id):
    with Session(engine) as session:
        source = session.get(ImageJob, source_id)
        if not source:
            raise GenerationError('来源图片不存在，无法核对原始资料。')
        owner, seen = source.owner_id, set()
        project_id = product_id = None
        while source and source.id not in seen and len(seen) < 64:
            if source.owner_id != owner:
                raise GenerationError('来源资料归属不一致，未读取其他账号的资料。')
            seen.add(source.id)
            profile = json.loads(source.execution_profile or '{}')
            project_id = project_id or profile.get('creation_project_id')
            product_id = product_id or profile.get('experience_product_id')
            if project_id:
                break
            source = session.get(ImageJob, source.parent_job_id) if source.parent_job_id else None
        project_id = project_id or product_id
        if not project_id:
            return None, []
        project = session.get(CreationProject, project_id)
        if not project or project.owner_id != owner:
            raise GenerationError('关联产品资料不存在或归属不一致，无法核对原件。')
        rows = list(session.scalars(select(CreationMaterial).where(
            CreationMaterial.project_id == project.id).order_by(CreationMaterial.created_at, CreationMaterial.id)))
        # Plans normally have immutable copies; only legacy plans need product fallback.
        if not rows and project.source_product_id:
            project = session.get(CreationProject, project.source_product_id)
            if not project or project.owner_id != owner:
                raise GenerationError('原始产品资料不存在或归属不一致。')
            rows = list(session.scalars(select(CreationMaterial).where(
                CreationMaterial.project_id == project.id).order_by(CreationMaterial.created_at, CreationMaterial.id)))
        return project.id, [{key: getattr(row, key) for key in
            ('id', 'name', 'kind', 'media_type', 'digest', 'size', 'pages', 'created_at')} for row in rows]
