"""Per-browser image configuration and ephemeral, revision-bound credentials."""
import io
import json
from datetime import datetime, timezone
from threading import RLock
from uuid import UUID, uuid4
from typing import Annotated, Literal
from PIL import Image
from fastapi import APIRouter, HTTPException, Request, Form, File, UploadFile
from pydantic import BaseModel, SecretStr, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.authorization import require_private
from app.database import ImageConfiguration, ImageJob, ModelConfiguration, DatabaseConfigStore
from app.model_configs import ConfigInput, probe_connection, probe_models

MODEL = 'gpt-image-2.5-sunburst'
RULES = {'backend': 'imagegen-cli', 'model': MODEL, 'quality': 'high', 'size': 'auto', 'output_format': 'png', 'augment': False, 'max_retries': 0}
DEFAULT_URL = 'https://ai-gateway.valsun.cn/v1'

def now(): return datetime.now(timezone.utc).isoformat()

class ImageConfigInput(BaseModel):
    name: str = Field(default='我的模型服务', min_length=1, max_length=80)
    base_url: str
    api_key: SecretStr | None = None
    text_model_name: str = Field(default='', max_length=200)
    vision_model_name: str = Field(default='', max_length=200)
    text_config_id: UUID | None = None

    @field_validator('text_model_name', 'vision_model_name')
    @classmethod
    def validate_text_model(cls, value):
        value = value.strip()
        if any(ord(char) < 32 for char in value):
            raise ValueError('模型 ID 不能包含控制字符。')
        return value

    @field_validator('base_url')
    @classmethod
    def validate_url(cls, value):
        return ConfigInput.normalize_url(value)

    @field_validator('api_key')
    @classmethod
    def validate_key(cls, value):
        return ConfigInput.valid_key(value)

class ImageConfigStore:
    def __init__(self, engine, directory):
        self.engine, self.directory = engine, directory
        self.keys, self.lock = {}, RLock()

    def require_db(self):
        if self.engine is None: raise HTTPException(503, '请配置数据库并执行迁移。')

    def find(self, session, owner):
        return session.scalar(select(ImageConfiguration).where(ImageConfiguration.owner == owner))

    def key(self, identifier, revision):
        with self.lock:
            entry = self.keys.get(identifier)
            return entry[1] if entry and entry[0] == revision else None

    def result(self, session, identifier):
        row = session.get(ImageJob, identifier) if identifier else None
        return {'status': row.status if row else 'unverified', 'job_id': row.id if row else None,
                'task_id': row.task_id if row else None, 'updated_at': row.updated_at if row else None}

    def view(self, session, row):
        return {'id': row.id, 'name': row.name, 'base_url': row.base_url, 'model_name': MODEL,
                'model_names': [MODEL], 'has_api_key': bool(self.key(row.id, row.revision)),
                'updated_at': row.updated_at, 'rules': RULES,
                'text_model_name': row.text_model_name, 'vision_model_name': row.vision_model_name,
                'text_config_id': row.text_config_id,
                'generation': self.result(session, row.generation_job_id), 'edit': self.result(session, row.edit_job_id)}

    def get(self, owner):
        self.require_db()
        with Session(self.engine) as session:
            row = self.find(session, owner)
            return self.view(session, row) if row else None

    def save(self, owner, data):
        self.require_db()
        validated = ConfigInput(name=data.name, base_url=data.base_url, api_key=data.api_key)
        with self.lock, Session(self.engine) as session, session.begin():
            row = self.find(session, owner)
            text_config_id = str(data.text_config_id) if data.text_config_id else None
            if 'text_config_id' in data.model_fields_set and text_config_id:
                text_config = session.get(ModelConfiguration, text_config_id)
                if text_config is None:
                    raise HTTPException(422, '所选服务商连接不存在，请重新选择。')
                require_private(text_config)
            supplied = validated.api_key.get_secret_value() if validated.api_key else None
            previous = self.key(row.id, row.revision) if row else None
            if not supplied and (not row or validated.base_url != row.base_url or not previous):
                raise HTTPException(422, '请填写此服务商的 API Key；密钥只在当前服务运行期间保管。')
            key = supplied or previous
            changed = not row or row.base_url != validated.base_url or (supplied is not None and supplied != previous)
            if not row:
                row = ImageConfiguration(id=str(uuid4()), owner=owner)
                session.add(row)
            if changed:
                row.revision = str(uuid4()); row.generation_job_id = row.edit_job_id = None
            row.name, row.base_url, row.updated_at = data.name, validated.base_url, now()
            if 'text_model_name' in data.model_fields_set: row.text_model_name = data.text_model_name
            if 'vision_model_name' in data.model_fields_set: row.vision_model_name = data.vision_model_name
            if 'text_config_id' in data.model_fields_set: row.text_config_id = text_config_id
            session.flush()
            identifier, revision = row.id, row.revision
        with self.lock: self.keys[identifier] = (revision, key)
        return self.get(owner)

    def resolve_connection(self, owner, text_config_id=None):
        """Internal only: never return this credential-bearing tuple from an API."""
        self.require_db()
        if text_config_id:
            with Session(self.engine) as session:
                row = session.get(ModelConfiguration, str(text_config_id))
                if row is None: raise HTTPException(404, '服务商连接不存在。')
                require_private(row)
                data = ConfigInput(name=row.name, base_url=row.base_url)
            key = DatabaseConfigStore(self.directory, self.engine).resolve_key(str(text_config_id), data)
            return data.base_url, key
        current = self.get(owner)
        if not current: raise HTTPException(422, '请先保存服务商连接。')
        profile = self.snapshot(owner, current['id'])
        return profile['base_url'], self.key(profile['id'], profile['revision'])

    def resolve_text(self, owner):
        current = self.get(owner)
        if not current or not current['text_model_name']:
            raise HTTPException(422, '请先设置文字模型。')
        base_url, key = self.resolve_connection(owner, current['text_config_id'])
        return base_url, key, current['text_model_name']

    def resolve_vision(self, owner):
        current = self.get(owner)
        if not current or not current['vision_model_name']:
            raise HTTPException(422, '未配置视觉模型，无法自动质检；请设置视觉模型或改由人工审核。')
        base_url, key = self.resolve_connection(owner, current['text_config_id'])
        return base_url, key, current['vision_model_name']

    def snapshot(self, owner, identifier):
        self.require_db()
        with Session(self.engine) as session:
            row = session.get(ImageConfiguration, identifier)
            if row is None or row.owner != owner: raise HTTPException(404, '模型服务配置不存在，请在个人模型配置中保存。')
            if not self.key(row.id, row.revision): raise HTTPException(409, '运行时密钥未就绪，请重新填写 API Key。')
            return {'id': row.id, 'name': row.name, 'base_url': row.base_url, 'revision': row.revision,
                    'generation_verified': self.result(session, row.generation_job_id)['status'] == 'succeeded',
                    'edit_verified': self.result(session, row.edit_job_id)['status'] == 'succeeded', **RULES}

    def enqueue_verification(self, owner, kind, request_id, reference=None):
        with self.lock:
            return self._enqueue_verification(owner, kind, request_id, reference)

    def _enqueue_verification(self, owner, kind, request_id, reference=None):
        from app.image_jobs import create_jobs
        self.require_db()
        current = self.get(owner)
        if not current: raise HTTPException(422, '请先保存服务商连接。')
        profile = self.snapshot(owner, current['id'])
        profile['verification'] = kind
        # Reuse the same submission ID while pending; explicit resubmission can verify again after failure.
        field = 'generation_job_id' if kind == 'generate' else 'edit_job_id'
        with Session(self.engine) as session:
            config = self.find(session, owner)
            existing_id = getattr(config, field)
            existing = session.get(ImageJob, existing_id) if existing_id else None
            if existing and existing.status in ('queued', 'running'):
                return {'task_id': existing.task_id, 'job_id': existing.id}
        prompt = 'Create a simple red cube on a plain white background. No text or logos.' if kind == 'generate' else 'Edit only the background to light blue. Preserve the product shape, proportions, colour and all existing details. Do not add text or objects.'
        if kind == 'edit' and not reference: raise HTTPException(422, '请明确上传并授权本次编辑验证的参考图。')
        items = create_jobs(self.engine, self.directory, profile['id'], MODEL, prompt, 'default', request_id, reference, 1, standard_config=profile)
        with Session(self.engine) as session, session.begin():
            config = self.find(session, owner)
            if config.revision != profile['revision']: raise HTTPException(409, '配置已改变，请重新验证。')
            setattr(config, field, items[0].id)
        return {'task_id': items[0].task_id, 'job_id': items[0].id}


class ModelListInput(BaseModel):
    text_config_id: UUID | None = None


def build_image_config_router(store):
    router = APIRouter(prefix='/api/image-configs', tags=['standard-image-config'])
    @router.get('')
    def get(request: Request): return store.get(request.state.image_owner)
    @router.put('')
    def save(request: Request, data: ImageConfigInput): return store.save(request.state.image_owner, data)
    @router.post('/connection')
    def connection(request: Request):
        current = store.get(request.state.image_owner)
        if not current: raise HTTPException(422, '请先保存服务商连接。')
        profile = store.snapshot(request.state.image_owner, current['id'])
        return probe_connection(profile['base_url'], store.key(profile['id'], profile['revision']))
    @router.post('/models')
    def models(request: Request, data: ModelListInput):
        base_url, key = store.resolve_connection(request.state.image_owner, data.text_config_id)
        return probe_models(base_url, key)
    @router.post('/verify/{kind}', status_code=202)
    def verify(request: Request, kind: Literal['generate', 'edit'], request_id: Annotated[UUID, Form()], authorized: Annotated[Literal['yes'], Form()], reference: Annotated[UploadFile | None, File()] = None):
        return store.enqueue_verification(request.state.image_owner, kind, str(request_id), reference.file.read(20 * 1024 * 1024 + 1) if reference else None)
    return router
