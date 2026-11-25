"""Single API-process executor: ephemeral secrets never cross a database or file."""
import json
import time
from threading import Thread, Event
from sqlalchemy import select, update
from sqlalchemy.orm import Session
from app.database import ImageJob, ImageConfiguration, UserAccount, AgentRun, AgentStep
from app.image_jobs import artifact, now
from app.image_provider import GenerationError
from app.standard_image_executor import execute_cli
from app.skill_image_workflow import prepare, review, identity_reference


class CancelledBeforeImage(Exception):
    pass


def process_standard_one(store, executor=execute_cli, preparer=None, reviewer=None):
    if store.engine is None: return False
    with Session(store.engine) as session:
        pending_runs = list(session.scalars(select(AgentRun.id).where(AgentRun.status == 'waiting_images').limit(100)))
    for pending_run in pending_runs:
        synchronize_creation(store.engine, pending_run)
    with Session(store.engine) as session, session.begin():
        session.execute(update(ImageJob).where(ImageJob.execution_profile != '{}', ImageJob.status == 'running', ImageJob.lease_until < time.time()).values(status='unknown', message='执行中断，结果待确认；未重复提交。', lease_until=None, updated_at=now()))
        rows = session.scalars(select(ImageJob).where(ImageJob.execution_profile != '{}', ImageJob.status == 'queued').order_by(ImageJob.created_at).limit(100).with_for_update(skip_locked=True))
        selected = None
        for row in rows:
            profile = json.loads(row.execution_profile)
            config = session.get(ImageConfiguration, row.config_id)
            if config is None or config.revision != profile['revision']:
                row.status, row.message, row.updated_at = 'cancelled', '图片配置已改变，此排队项未调用服务商，请重新提交。', now()
                continue
            if getattr(store,'auth_enabled',False):
                account = session.get(UserAccount,row.owner_id) if row.owner_id else None
                if not account or not account.is_active:
                    row.status, row.message, row.updated_at = 'cancelled', '所属账号不可用，未调用服务商。', now()
                    continue
            key = store.key(row.config_id, profile['revision'])
            if key:
                selected = row; break
            message = '等待运行时密钥，请在个人模型配置中重新填写密钥。'
            if row.message != message: row.message = message
        if selected is None: return False
        row = selected
        row.status, row.message, row.updated_at = 'running', '正在按标准图片规则执行', now()
        row.lease_until = time.time() + 900
        identifier, profile = row.id, json.loads(row.execution_profile)
        prompt, mode = row.prompt, row.mode
        owner = row.owner_id
        run_id = row.agent_run_id
    diagnostic, result, status = {}, {}, 'unknown'
    phase = 'prepare'
    try:
        directory = artifact(store.directory, identifier, 'result.png').parent
        reference = (directory / 'reference.png').read_bytes() if mode == 'edit' else None
        if profile.get('reference_manifest'):
            reference = [reference] + [(directory / f'reference-{index}.png').read_bytes() for index in range(2, len(profile['reference_manifest']) + 1)]
        requirements = prompt
        apply_skill = bool(profile.get('skill_workflow')) and not profile.get('prepared_by_agent')
        if not apply_skill and not profile.get('prepared_by_agent'):
            experience = profile.get('drawing_experience', {}).get('direct', [])
            if experience:
                prompt += '\n\n人工确认的产品作图经验（仅适用本次用途，不是产品事实，本轮明确要求优先）：\n' + '\n'.join(item['guidance'] for item in experience)
                with Session(store.engine) as session, session.begin():
                    session.execute(update(ImageJob).where(ImageJob.id == identifier).values(prompt=prompt))
        if apply_skill:
            with Session(store.engine) as session, session.begin():
                session.execute(update(ImageJob).where(ImageJob.id == identifier)
                                .values(message='正在按制作技能分析素材并整理完整提示词', updated_at=now()))
            prompt = (preparer or prepare)(store, owner, profile, directory, requirements, reference)
            with Session(store.engine) as session, session.begin():
                session.execute(update(ImageJob).where(ImageJob.id == identifier)
                                .values(prompt=prompt, message='制作方案已准备，正在调用图片接口', updated_at=now()))
        phase = 'image'
        if run_id and apply_skill:
            with Session(store.engine) as session, session.begin():
                active = session.get(AgentRun, run_id, with_for_update=True)
                if active is None or active.status == 'cancelled':
                    raise CancelledBeforeImage()
                # Standard skill submissions have a per-image allowance, including older queued runs.
                active.max_images = max(active.max_images, active.image_calls + 3)
                active.image_calls += 1
        attempts = []
        for attempt in range(3):
            try:
                result = executor(directory, profile, key, prompt, reference)
                attempts.append({'attempt': attempt + 1, 'status': 'succeeded', 'at': now()})
                break
            except GenerationError as error:
                code = error.diagnostic.get('http_status')
                retryable = not error.uncertain and code not in (401, 403)
                # A saved output may already be paid for; never place another order.
                output_exists = any((directory / ('result.' + suffix)).exists() for suffix in ('png', 'jpg', 'webp'))
                if output_exists: error.uncertain = True
                attempts.append({'attempt': attempt + 1, 'status': 'unknown' if error.uncertain else 'failed',
                    'diagnostic': error.diagnostic, 'at': now(), 'retryable': retryable and not output_exists})
                result['attempts'] = attempts
                if attempt >= 2 or not retryable or output_exists:
                    raise
                if run_id:
                    with Session(store.engine) as session, session.begin():
                        active = session.get(AgentRun, run_id, with_for_update=True)
                        if active is None or active.status == 'cancelled': raise CancelledBeforeImage()
                        if active.image_calls >= active.max_images:
                            raise error
                        active.image_calls += 1
                with Session(store.engine) as session, session.begin():
                    session.execute(update(ImageJob).where(ImageJob.id == identifier).values(
                        message=f'本张第 {attempt + 1} 次调用失败，正在尝试第 {attempt + 2} 次（最多 3 次）；不影响其他图片。',
                        execution_result=json.dumps({'attempts': attempts}, ensure_ascii=False),
                        lease_until=time.time() + 900, updated_at=now()))
        result['attempts'] = attempts
        if profile.get('skill_execution'):
            result['skill_execution'] = profile['skill_execution']
        status, message = 'succeeded', '原生图片和预览已保存，等待人工检查。'
        if apply_skill or profile.get('review_model'):
            # A failed review never erases an image that has already been paid for.
            result['skill_workflow'] = profile['skill_workflow']
            try:
                review_reference = reference[0] if isinstance(reference, list) else reference
                checked = (reviewer or review)(store, owner, directory, requirements, prompt, identity_reference(store, profile, review_reference),
                    **({'profile': profile} if profile.get('review_model') else {}))
                if isinstance(reference, list): checked['compared_reference_count'] = 1
            except Exception:
                checked = {'status': 'uncertain', 'summary': '质检执行中断，待人工审核。', 'checks': [],
                           'method': 'vision', 'compared_reference': False}
            result['agent_review'] = {**checked, 'run_id': run_id, 'updated_at': now()}
            message = '图片已保存，' + {'passed': '自动质检通过。', 'rework': '质检发现需要修改的问题。',
                                       'uncertain': '待人工审核。'}[checked['status']]
    except CancelledBeforeImage:
        status, message = 'cancelled', '创作任务已取消，未调用图片接口。'
    except GenerationError as error:
        status, message, diagnostic = ('unknown' if error.uncertain else 'failed'), error.message, error.diagnostic
        if phase == 'prepare' and not diagnostic:
            diagnostic = {'method': '', 'path': '', 'http_status': None, 'error_type': 'skill_preparation',
                          'provider_message': message, 'recorded_at': now()}
    except Exception:
        message = '执行中断或结果无法确认，请核对已有文件和服务商记录；未重试。'
    for filename in ('skill-workflow.json', 'skill-read-log.json'):
        record = directory / filename
        if record.is_file():
            try:
                document = json.loads(record.read_text(encoding='utf-8'))
            except (OSError, ValueError):
                continue
            result['skill_execution'] = {'method': document.get('planning_method', document.get('engine', 'rules')),
                'used_skills': document.get('used_skills', []), 'files': document.get('files', []),
                'reused_preparation': document.get('reused_preparation', False)}
            break
    if phase == 'image' and status in ('succeeded', 'failed', 'unknown'):
        from app.model_capabilities import evidence, save_evidence
        save_evidence(store, owner, 'edit' if mode == 'edit' else 'generate', profile.get('model', ''),
                      evidence(profile.get('model', ''), status == 'succeeded', diagnostic, message), profile['revision'])
    with Session(store.engine) as session, session.begin():
        run = session.get(AgentRun, run_id, with_for_update=True) if run_id else None
        session.execute(update(ImageJob).where(ImageJob.id == identifier, ImageJob.status == 'running').values(status=status, message=message, provider_diagnostic=json.dumps(diagnostic, ensure_ascii=False), execution_result=json.dumps(result, ensure_ascii=False), updated_at=now(), lease_until=None))
        if run_id:
            if run and run.status == 'waiting_images':
                record_path = directory / 'skill-workflow.json'
                if record_path.is_file():
                    run.model_name = json.loads(record_path.read_text(encoding='utf-8')).get('text_model', '')
                run.vision_model_name = result.get('agent_review', {}).get('model', '')
                run.steps_count += 1
                session.add(AgentStep(run_id=run.id, step_index=run.steps_count, kind='tool', tool_name='image_workflow',
                    arguments=json.dumps({'job_id': identifier}, ensure_ascii=False),
                    result=json.dumps({'status': status, 'message': message, 'review': result.get('agent_review')}, ensure_ascii=False), created_at=now()))
    if run_id:
        synchronize_creation(store.engine, run_id)
    return True


def synchronize_creation(engine, run_id):
    from app.agent_runtime import delivery_status
    with Session(engine) as session, session.begin():
        run = session.get(AgentRun, run_id, with_for_update=True)
        if run is None or run.status != 'waiting_images':
            return
        jobs = list(session.scalars(select(ImageJob).where(ImageJob.agent_run_id == run_id)))
        if any(item.status in ('queued', 'running') for item in jobs):
            return
        status, message = delivery_status(engine, run_id, images=jobs)
        run.status, run.summary, run.error = status, message, '' if status == 'succeeded' else message
        run.updated_at, run.finished_at = now(), now()


class StandardWorker:
    def __init__(self, store):
        self.store = store; self.stop_event = Event(); self.thread = Thread(target=self.run, daemon=True)
    def run(self):
        while not self.stop_event.is_set():
            try: worked = process_standard_one(self.store)
            except Exception: worked = False
            if not worked: self.stop_event.wait(2)
    def start(self): self.thread.start()
    def stop(self):
        self.stop_event.set(); self.thread.join(timeout=2)
