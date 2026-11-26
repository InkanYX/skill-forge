"""Explicit, idempotent retries preserve the failed job and all original inputs."""
import json
from uuid import UUID, uuid5

from fastapi import HTTPException
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from app.authorization import require_edit
from app.database import ImageJob, CreationProject, CreationExecution
from app.image_jobs import artifact, now, view
from app.image_batches import normalize_batches, replace_batch_job


def retry_job(engine, directory, configs, source_id, request_id, owner, provider_checked=False):
    with Session(engine) as session, session.begin():
        source = session.get(ImageJob, source_id, with_for_update=True)
        if source is None or source.deleted_at:
            raise HTTPException(404, '原图片任务不存在。')
        require_edit(source)
        if source.owner_id != owner:
            raise HTTPException(403, '请由原任务创建者重试，使用原服务商连接。')
        previous = session.scalar(select(ImageJob).where(ImageJob.request_id == request_id))
        if previous:
            if json.loads(previous.execution_profile or '{}').get('retry_source_job_id') != source_id:
                raise HTTPException(409, '提交标识已用于其他任务。')
            return view(previous)
        if source.status not in ('failed', 'cancelled', 'unknown'):
            raise HTTPException(409, '仅明确失败、已取消或经核对的结果待确认图片可重试。')
        if source.status == 'unknown' and not provider_checked:
            raise HTTPException(409, '请先核对服务商生成与计费记录，确认未找到可用图片，并确认重新生成可能产生新的费用。')
        profile = json.loads(source.execution_profile or '{}')
        if not profile or configs is None or profile.get('verification'):
            raise HTTPException(409, '此任务请通过原提交或模型检查入口重新提交。')
        source_dir = artifact(directory, source_id, 'result.png').parent
        if any((source_dir / ('result.' + suffix)).exists() for suffix in ('png', 'jpg', 'webp')):
            raise HTTPException(409, '任务目录已有返回图片，请先核对结果及计费，未重复下单。')
        project_id = profile.get('creation_project_id')
        project = session.get(CreationProject, project_id, with_for_update=True) if project_id else None
        if project_id and project is None:
            raise HTTPException(409, '来源方案已不存在，请先核对任务。')
        data = json.loads(project.content) if project else None
        batches = normalize_batches(data.get('batches', [])) if project else []
        source_batch = next((batch for batch in batches if source_id in batch['job_ids']), None)
        task_id = (source.task_id or source.request_id) if project else request_id
        # Serialize on the source row; double clicks with different request IDs reuse the pending retry.
        for item in session.scalars(select(ImageJob).where(ImageJob.owner_id == source.owner_id, ImageJob.status.in_(['queued', 'running', 'unknown']))):
            if json.loads(item.execution_profile or '{}').get('retry_source_job_id') == source_id:
                if item.status == 'unknown':
                    raise HTTPException(409, '已有重试结果待确认，请先核对该次记录和服务商计费，未重复下单。')
                return view(item)
        if project and source_batch is None:
            raise HTTPException(409, '此图片已有后续重试或缺少来源版本，请从原版本当前图片入口重试。')
        current = configs.snapshot(owner, source.config_id)
        if any(current.get(key) != profile.get(key) for key in ('base_url', 'generation_path', 'edit_path')):
            raise HTTPException(409, '服务商地址或接口路径已改变，请确认后重新提交，不能自动更换接口重试。')
        if source.model_name not in current['models']:
            raise HTTPException(409, '原生图模型已从配置移除，请先恢复该模型后重试。')
        references = []
        if source.mode == 'edit':
            count = max(1, len(profile.get('reference_manifest', [])))
            for index in range(1, count + 1):
                path = source_dir / ('reference.png' if index == 1 else f'reference-{index}.png')
                if not path.is_file():
                    raise HTTPException(409, '原始参考图缺失，未改成无参考重画。')
                references.append((path.name, path.read_bytes()))
        profile.update(revision=current['revision'], retry_source_job_id=source_id)
        # Preserve the human acknowledgement without rewriting the uncertain record.
        profile.pop('retry_confirmation', None)
        if source.status == 'unknown':
            profile['retry_confirmation'] = {'source_job_id': source_id, 'source_status': 'unknown',
                'provider_checked': True, 'acknowledged_by': owner, 'acknowledged_at': now()}
        # An image call proves preparation completed. Reuse the exact final prompt instead of rewriting it.
        reused = bool(json.loads(source.execution_result or '{}').get('attempts'))
        if reused:
            profile['prepared_by_agent'] = True
            if profile.get('skill_execution'):
                profile['skill_execution'] = {**profile['skill_execution'], 'reused_preparation': True}
        if project:
            profile['creation_execution_id'] = source_batch['execution_id']
            profile['retry_execution_id'] = request_id
        identifier = str(uuid5(UUID(request_id), 'retry-image'))
        target_dir = artifact(directory, identifier, 'result.png').parent
        target_dir.mkdir(parents=True, exist_ok=True)
        for name, content in references:
            (target_dir / name).write_bytes(content)
        for name in ('skill-workflow.json', 'skill-read-log.json', 'skill-context.md', 'revision-analysis.json', 'material-read-log.json', 'prompt.txt'):
            path = source_dir / name
            if path.is_file():
                if name.endswith('.json') and reused:
                    record = json.loads(path.read_text(encoding='utf-8'))
                    if isinstance(record, dict):
                        record.update(reused_preparation=True, retry_source_job_id=source_id)
                    (target_dir / name).write_text(json.dumps(record, ensure_ascii=False), encoding='utf-8')
                else:
                    (target_dir / name).write_bytes(path.read_bytes())
        row = ImageJob(id=identifier, request_id=request_id, fingerprint=source.fingerprint,
            config_id=source.config_id, config_name=source.config_name, base_url=source.base_url,
            encrypted_key='', model_name=source.model_name, prompt=source.prompt, size=source.size,
            mode=source.mode, status='queued', message='单张重试已排队，最多尝试 3 次；原记录保留。',
            created_at=now(), updated_at=now(), owner_id=source.owner_id,
            task_id=task_id, task_index=(session.scalar(select(func.max(ImageJob.task_index)).where(ImageJob.task_id == task_id)) or 0) + 1,
            template_snapshot=source.template_snapshot, product_snapshot=source.product_snapshot,
            parent_job_id=source.parent_job_id, edit_instruction=source.edit_instruction,
            set_id=source.set_id, set_name=source.set_name, shot_name=source.shot_name, shot_index=source.shot_index,
            execution_profile=json.dumps(profile, ensure_ascii=False))
        session.add(row)
        if project:
            index = source_batch['job_ids'].index(source_id)
            shot_ids = [source_batch['shot_ids'][index]] if len(source_batch.get('shot_ids', [])) == len(source_batch['job_ids']) else []
            batch_result = {'job_ids': [identifier], 'shot_ids': shot_ids, 'retry_source_job_id': source_id}
            replace_batch_job(batches, source_id, identifier)
            data['batches'] = batches
            project.content = json.dumps(data, ensure_ascii=False)
            project.revision += 1
            project.updated_at = now()
            session.add(CreationExecution(id=request_id, project_id=project.id, stage='images', status='succeeded',
                input=json.dumps({'owner_id':owner, 'profile':profile, 'retry_source_job_id':source_id}, ensure_ascii=False),
                output=json.dumps({'images':batch_result}, ensure_ascii=False), created_at=now(), updated_at=now()))
        session.flush()
        return view(row)
