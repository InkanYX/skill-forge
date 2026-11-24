"""Read-only business overview. Counts are database records, not mock metrics."""
import json
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import select, func, case
from sqlalchemy.orm import Session
from app.database import ImageJob, Product, CreativeTemplate, CreativeSkill, CreativeCase, ModelConfiguration
from app.model_configs import configured_models


def job_summary(row):
    product = json.loads(row.product_snapshot or '{}')
    template = json.loads(row.template_snapshot or '{}')
    return {
        'id': row.id, 'title': row.shot_name or product.get('name') or template.get('name') or '自由创作',
        'sku': product.get('sku', ''), 'model_name': row.model_name, 'status': row.status,
        'message': row.message, 'brief': row.prompt[:140], 'created_at': row.created_at,
        'image_url': f'/api/image-jobs/{row.id}/image' if row.status == 'succeeded' else None,
        'set_id': row.set_id, 'set_name': row.set_name,
    }


def build_workspace_router(engine, image_store=None):
    router = APIRouter(prefix='/api/workspace', tags=['workspace'])

    @router.get('')
    def overview(request: Request):
        if engine is None:
            raise HTTPException(503, '工作台需要配置数据库；请先完成本机数据库设置。')
        current = datetime.now(timezone.utc)
        shanghai = timezone(timedelta(hours=8))
        local = current.astimezone(shanghai)
        start = local.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc).isoformat()
        end = (local.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)).astimezone(timezone.utc).isoformat()
        with Session(engine) as session:
            counts = {key: 0 for key in ('queued', 'running', 'succeeded', 'failed', 'unknown', 'cancelled')}
            counts.update(dict(session.execute(select(ImageJob.status, func.count()).group_by(ImageJob.status)).all()))
            def count(model, *conditions):
                return session.scalar(select(func.count()).select_from(model).where(*conditions))
            resources = {'products': count(Product), 'templates': count(CreativeTemplate), 'skills': count(CreativeSkill), 'cases': count(CreativeCase), 'model_configs': count(ModelConfiguration), 'available_models': count(ModelConfiguration, func.trim(ModelConfiguration.model_name) != '', ModelConfiguration.encrypted_key != '')}
            resources['available_models'] = sum(len(configured_models(row)) for row in session.scalars(select(ModelConfiguration).where(ModelConfiguration.encrypted_key != '')))
            connection = image_store.get(request.state.image_owner) if image_store else None
            if connection:
                resources['model_configs'] += 1
                if connection['has_api_key']: resources['available_models'] += len(connection['model_names'])
            today = {
                'date': local.date().isoformat(), 'timezone': 'Asia/Shanghai',
                'submitted': count(ImageJob, ImageJob.created_at >= start, ImageJob.created_at < end),
                'completed': count(ImageJob, ImageJob.status == 'succeeded', ImageJob.updated_at >= start, ImageJob.updated_at < end),
            }
            active = session.scalars(select(ImageJob).where(ImageJob.status.in_(['queued', 'running'])).order_by(case((ImageJob.status == 'running', 0), else_=1), ImageJob.created_at, ImageJob.id).limit(6))
            active_jobs = [job_summary(row) for row in active]
            attention = session.scalars(select(ImageJob).where(ImageJob.status.in_(['failed', 'unknown'])).order_by(ImageJob.updated_at.desc(), ImageJob.id.desc()).limit(4))
            attention_jobs = [job_summary(row) for row in attention]
            latest = session.scalars(select(ImageJob).where(ImageJob.status == 'succeeded').order_by(ImageJob.updated_at.desc(), ImageJob.id.desc()).limit(6))
            recent_images = [job_summary(row) for row in latest]
            products = [{'id': row.id, 'sku': row.sku, 'name': json.loads(row.content)['name'], 'updated_at': row.updated_at} for row in session.scalars(select(Product).order_by(Product.updated_at.desc()).limit(4))]
            templates = [{'id': row.id, 'name': json.loads(row.content)['name'], 'purpose': json.loads(row.content).get('purpose', ''), 'revision': row.revision, 'updated_at': row.updated_at} for row in session.scalars(select(CreativeTemplate).order_by(CreativeTemplate.updated_at.desc()).limit(4))]
        return {'updated_at': current.isoformat(), 'jobs': counts, 'resources': resources, 'today': today, 'active_jobs': active_jobs, 'attention_jobs': attention_jobs, 'recent_images': recent_images, 'recent_products': products, 'recent_templates': templates}
    return router
