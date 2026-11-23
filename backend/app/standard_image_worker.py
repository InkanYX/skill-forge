"""Single API-process executor: ephemeral secrets never cross a database or file."""
import json
import time
from threading import Thread, Event
from sqlalchemy import select, update
from sqlalchemy.orm import Session
from app.database import ImageJob, ImageConfiguration, UserAccount
from app.image_jobs import artifact, now
from app.image_provider import GenerationError
from app.standard_image_executor import execute_cli


def process_standard_one(store, executor=execute_cli):
    if store.engine is None: return False
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
        row.lease_until = time.time() + 420
        identifier, profile = row.id, json.loads(row.execution_profile)
        prompt, mode = row.prompt, row.mode
    diagnostic, result, status = {}, {}, 'unknown'
    try:
        directory = artifact(store.directory, identifier, 'result.png').parent
        reference = (directory / 'reference.png').read_bytes() if mode == 'edit' else None
        result = executor(directory, profile, key, prompt, reference)
        status, message = 'succeeded', '原生图片和预览已保存，等待人工检查。'
    except GenerationError as error:
        status, message, diagnostic = ('unknown' if error.uncertain else 'failed'), error.message, error.diagnostic
    except Exception:
        message = '执行中断或结果无法确认，请核对已有文件和服务商记录；未重试。'
    with Session(store.engine) as session, session.begin():
        session.execute(update(ImageJob).where(ImageJob.id == identifier, ImageJob.status == 'running').values(status=status, message=message, provider_diagnostic=json.dumps(diagnostic, ensure_ascii=False), execution_result=json.dumps(result, ensure_ascii=False), updated_at=now(), lease_until=None))
    return True


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
