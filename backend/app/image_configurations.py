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

RULES = {'backend': 'openai-compatible', 'max_retries': 0}
DEFAULT_URL = ''

def now(): return datetime.now(timezone.utc).isoformat()

class ImageConfigInput(BaseModel):
    name: str = Field(default='我的模型服务', min_length=1, max_length=80)
    base_url: str
    api_key: SecretStr | None = None
    text_model_name: str = Field(default='', max_length=200)
    vision_model_name: str = Field(default='', max_length=200)
    text_config_id: UUID | None = None
    model_name: str = Field(default='', max_length=200)
    request_parameters: dict = Field(default_factory=dict)
    text_parameters: dict = Field(default_factory=dict)
    vision_parameters: dict = Field(default_factory=dict)
    generation_path: str = '/images/generations'
    edit_path: str = '/images/edits'
    model_names: list[str] = Field(default_factory=list, max_length=100)
    auto_review: bool = False
    planning_model_name: str = Field(default='', max_length=200)
    image_model_name: str = Field(default='', max_length=200)
    model_options: dict[str, dict] = Field(default_factory=dict)

    @field_validator('model_options')
    @classmethod
    def validate_options(cls, values):
        if len(values) > 100: raise ValueError('最多配置 100 个模型。')
        for model, options in values.items():
            if not model or len(model) > 200 or any(ord(char) < 32 for char in model): raise ValueError('模型 ID 无效。')
            if set(options) - {'request_parameters', 'text_parameters', 'vision_parameters'}: raise ValueError('模型选项仅允许请求参数，不能设置能力验证结果。')
            for parameters in options.values():
                if not isinstance(parameters, dict): raise ValueError('可选参数需为 JSON 对象。')
                cls.validate_parameters(parameters)
        return values

    @field_validator('model_names')
    @classmethod
    def validate_models(cls, values):
        values = list(dict.fromkeys(value.strip() for value in values if value.strip()))
        if any(len(value) > 200 or any(ord(char) < 32 for char in value) for value in values):
            raise ValueError('模型 ID 最多 200 字符，不能包含控制字符。')
        return values

    @field_validator('text_model_name', 'vision_model_name', 'model_name', 'planning_model_name', 'image_model_name')
    @classmethod
    def validate_text_model(cls, value):
        value = value.strip()
        if any(ord(char) < 32 for char in value):
            raise ValueError('模型 ID 不能包含控制字符。')
        return value

    @field_validator('request_parameters', 'text_parameters', 'vision_parameters')
    @classmethod
    def validate_parameters(cls, value):
        if len(json.dumps(value, ensure_ascii=False, allow_nan=False)) > 16000:
            raise ValueError('请求参数最多 16000 字符。')
        protected = {'model', 'prompt', 'messages', 'image', 'images', 'api_key', 'base_url', 'headers', 'authorization', 'stream', 'n'}
        if set(value) & protected:
            raise ValueError('模型、内容、密钥、stream 与生成数量由任务管理，请勿在可选参数中重复设置。')
        return value

    @field_validator('generation_path', 'edit_path')
    @classmethod
    def validate_path(cls, value):
        if not value.startswith('/') or value.startswith('//') or any(char in value for char in ('?', '#', '\\', ':')) or '..' in value or len(value) > 300:
            raise ValueError('接口路径需为当前服务商下的相对路径，例如 /images/generations。')
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
        return {'id': row.id, 'revision': row.revision, 'name': row.name, 'base_url': row.base_url, 'model_name': row.model_name,
                'model_names': json.loads(row.model_names or '[]'),
                'model_settings': json.loads(row.model_settings or '{}'), 'auto_review': row.auto_review,
                'planning_model_name': row.planning_model_name, 'image_model_name': row.image_model_name,
                'unified_models': bool(json.loads(row.model_names or '[]')),
                'has_api_key': bool(self.key(row.id, row.revision)),
                **{field: json.loads(getattr(row, field) or '{}') for field in ('request_parameters', 'text_parameters', 'vision_parameters', 'capabilities')},
                'generation_path': row.generation_path, 'edit_path': row.edit_path,
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
            image_changed = changed or bool(row and any(field in data.model_fields_set and getattr(row, field) != getattr(data, field) for field in ('model_name', 'generation_path', 'edit_path')))
            image_changed = image_changed or bool(row and 'request_parameters' in data.model_fields_set and json.loads(row.request_parameters or '{}') != data.request_parameters)
            paths_changed = bool(row and any(field in data.model_fields_set and getattr(row, field) != getattr(data, field) for field in ('generation_path', 'edit_path')))
            if not row:
                row = ImageConfiguration(id=str(uuid4()), owner=owner)
                session.add(row)
            if image_changed:
                row.revision = str(uuid4()); row.generation_job_id = row.edit_job_id = None
            capabilities = json.loads(row.capabilities or '{}')
            settings = json.loads(row.model_settings or '{}')
            for entry in settings.values():
                if changed: entry['capabilities'] = {}
                elif paths_changed:
                    for operation in ('generate', 'edit'): entry.get('capabilities', {}).pop(operation, None)
            switching = 'model_name' in data.model_fields_set and row.model_name != data.model_name
            if switching:
                capabilities = dict(settings.get(data.model_name, {}).get('capabilities', {}))
            if changed: capabilities = {}
            elif image_changed and not switching:
                for operation in ('generate', 'edit'): capabilities.pop(operation, None)
            if switching and 'request_parameters' in data.model_fields_set and settings.get(data.model_name, {}).get('request_parameters', {}) != data.request_parameters:
                for operation in ('generate', 'edit'): capabilities.pop(operation, None)
            for role, model_field, params_field in [('text', 'text_model_name', 'text_parameters'), ('vision', 'vision_model_name', 'vision_parameters')]:
                previous_parameters = settings.get(data.model_name, {}).get(params_field, {}) if switching else json.loads(getattr(row, params_field) or '{}')
                if ('text_config_id' in data.model_fields_set and row.text_config_id != text_config_id) or (model_field in data.model_fields_set and getattr(row, model_field) != getattr(data, model_field)) or (params_field in data.model_fields_set and previous_parameters != getattr(data, params_field)):
                    capabilities.pop(role, None)
            row.capabilities = json.dumps(capabilities, ensure_ascii=False)
            if 'model_names' in data.model_fields_set:
                names = list(data.model_names)
                if data.model_name and data.model_name not in names: names.append(data.model_name)
                row.model_names = json.dumps(names, ensure_ascii=False)
            elif {'text_model_name', 'vision_model_name', 'text_config_id'} & data.model_fields_set:
                # Explicit legacy role fields retain the old API contract. The
                # new page sends model_names and never configures these roles.
                row.model_names = '[]'
            elif 'model_name' in data.model_fields_set and not ({'text_model_name', 'vision_model_name', 'text_config_id'} & data.model_fields_set):
                names = json.loads(row.model_names or '[]')
                if data.model_name and data.model_name not in names: names.append(data.model_name)
                row.model_names = json.dumps(names, ensure_ascii=False)
            if 'auto_review' in data.model_fields_set: row.auto_review = data.auto_review
            names = json.loads(row.model_names or '[]')
            for field in ('planning_model_name', 'image_model_name'):
                value = getattr(data, field) if field in data.model_fields_set else getattr(row, field)
                if value and value not in names:
                    raise HTTPException(422, '创作默认模型必须来自已添加的模型列表。')
                if field in data.model_fields_set: setattr(row, field, value)
            for field in ('model_name', 'generation_path', 'edit_path'):
                if field in data.model_fields_set: setattr(row, field, getattr(data, field))
            for field in ('request_parameters', 'text_parameters', 'vision_parameters'):
                if field in data.model_fields_set: setattr(row, field, json.dumps(getattr(data, field), ensure_ascii=False))
            settings[row.model_name] = {field: json.loads(getattr(row, field) or '{}') for field in ('request_parameters', 'text_parameters', 'vision_parameters', 'capabilities')}
            for model, options in data.model_options.items():
                entry = settings.setdefault(model, {})
                caps = entry.setdefault('capabilities', {})
                for field, value in options.items():
                    if entry.get(field, {}) != value:
                        for operation in ({'request_parameters': ('generate', 'edit'), 'text_parameters': ('text', 'tools'), 'vision_parameters': ('vision',)})[field]: caps.pop(operation, None)
                    entry[field] = value
            row.capabilities = json.dumps(settings.get(row.model_name, {}).get('capabilities', {}), ensure_ascii=False)
            for field in ('request_parameters', 'text_parameters', 'vision_parameters'):
                if field in settings.get(row.model_name, {}): setattr(row, field, json.dumps(settings[row.model_name][field], ensure_ascii=False))
            row.model_settings = json.dumps(settings, ensure_ascii=False)
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
        model = (current.get('planning_model_name') or (current['model_name'] if current.get('unified_models') else current.get('text_model_name', ''))) if current else ''
        if not model:
            raise HTTPException(422, '请先设置文字模型。')
        base_url, key = self.resolve_connection(owner, None if current.get('unified_models') else current['text_config_id'])
        return base_url, key, model

    def resolve_vision(self, owner, check=False):
        current = self.get(owner)
        unified = bool(current and current.get('unified_models'))
        if unified and not check and not current.get('auto_review'):
            raise HTTPException(422, '未开启自动质检，图片交由人工审核。')
        vision_caps = current.get('model_settings', {}).get(current.get('planning_model_name') or current.get('model_name'), {}).get('capabilities', {}) if current else {}
        if unified and not check and vision_caps.get('vision', {}).get('state') == 'unsupported':
            raise HTTPException(422, '当前模型不支持图片理解，图片交由人工审核。')
        model = (current.get('planning_model_name') or current['model_name']) if unified else current.get('vision_model_name', '') if current else ''
        if not model:
            raise HTTPException(422, '未配置视觉模型，无法自动质检；请设置视觉模型或改由人工审核。')
        base_url, key = self.resolve_connection(owner, None if unified else current['text_config_id'])
        return base_url, key, model

    def parameters(self, owner, role):
        current = self.get(owner)
        if current and current.get('planning_model_name') and role in ('text', 'vision'):
            return current.get('model_settings', {}).get(current['planning_model_name'], {}).get(role + '_parameters', {})
        return current.get(role + '_parameters', {}) if current else {}

    def call_text(self, owner, prompt, vision=False, model_name=None):
        from app.agent_runtime import _chat, _vision, AgentError
        from app.model_capabilities import evidence, save_evidence
        current = self.get(owner)
        if model_name:
            if not current or model_name not in current['model_names']: raise HTTPException(422, '请从已添加的模型中选择。')
            url, key = self.resolve_connection(owner)
            model = model_name
        else:
            url, key, model = self.resolve_vision(owner, check=True) if vision else self.resolve_text(owner)
        role = 'vision' if vision else 'text'
        parameters = current.get('model_settings', {}).get(model, {}).get(role + '_parameters', {}) if model_name else self.parameters(owner, role)
        try:
            if vision:
                buffer = io.BytesIO(); Image.new('RGB', (16, 16), 'red').save(buffer, 'PNG')
                result = _vision(url, key, model, buffer.getvalue(), prompt, parameters=parameters)
            else:
                result = _chat(url, key, model, [{'role': 'user', 'content': prompt}], parameters=parameters).get('content', '')
            checked = evidence(model, True, message='调用成功。')
        except AgentError as error:
            result = ''
            checked = evidence(model, False, error.diagnostic, error.message)
        save_evidence(self, owner, role, model, checked, current['revision'])
        return {'output': result, 'capability': checked}

    def snapshot(self, owner, identifier):
        self.require_db()
        with Session(self.engine) as session:
            row = session.get(ImageConfiguration, identifier)
            if row is None or row.owner != owner: raise HTTPException(404, '模型服务配置不存在，请在个人模型配置中保存。')
            if not self.key(row.id, row.revision): raise HTTPException(409, '运行时密钥未就绪，请重新填写 API Key。')
            return {'id': row.id, 'name': row.name, 'base_url': row.base_url, 'revision': row.revision,
                    'model': row.model_name, 'parameters': json.loads(row.request_parameters or '{}'),
                    'generation_path': row.generation_path, 'edit_path': row.edit_path,
                    'capabilities': json.loads(row.capabilities or '{}'),
                    'models': json.loads(row.model_names or '[]') or list(dict.fromkeys(value for value in (row.model_name, row.text_model_name, row.vision_model_name) if value)),
                    'model_settings': json.loads(row.model_settings or '{}'),
                    'generation_verified': self.result(session, row.generation_job_id)['status'] == 'succeeded',
                    'edit_verified': self.result(session, row.edit_job_id)['status'] == 'succeeded', **RULES}

    def enqueue_verification(self, owner, kind, request_id, reference=None, model_name=None):
        with self.lock:
            return self._enqueue_verification(owner, kind, request_id, reference, model_name)

    def _enqueue_verification(self, owner, kind, request_id, reference=None, model_name=None):
        from app.image_jobs import create_jobs
        self.require_db()
        current = self.get(owner)
        if not current: raise HTTPException(422, '请先保存服务商连接。')
        profile = self.snapshot(owner, current['id'])
        if model_name:
            if model_name not in current['model_names']: raise HTTPException(422, '请从已添加的模型中选择。')
            profile['model'] = model_name
            settings = current.get('model_settings', {}).get(model_name, {})
            profile['parameters'] = settings.get('request_parameters', {})
            profile['capabilities'] = settings.get('capabilities', {})
        profile['verification'] = kind
        # Reuse the same submission ID while pending; explicit resubmission can verify again after failure.
        field = 'generation_job_id' if kind == 'generate' else 'edit_job_id'
        with Session(self.engine) as session:
            config = self.find(session, owner)
            existing_id = getattr(config, field)
            existing = session.get(ImageJob, existing_id) if existing_id else None
            if existing and existing.model_name == profile['model'] and existing.status in ('queued', 'running'):
                return {'task_id': existing.task_id, 'job_id': existing.id}
        prompt = 'Create a simple red cube on a plain white background. No text or logos.' if kind == 'generate' else 'Edit only the background to light blue. Preserve the product shape, proportions, colour and all existing details. Do not add text or objects.'
        if kind == 'edit' and not reference: raise HTTPException(422, '请明确上传并授权本次编辑验证的参考图。')
        items = create_jobs(self.engine, self.directory, profile['id'], profile['model'], prompt, 'default', request_id, reference, 1, standard_config=profile, owner_id=owner)
        with Session(self.engine) as session, session.begin():
            config = self.find(session, owner)
            if config.revision != profile['revision']: raise HTTPException(409, '配置已改变，请重新验证。')
            setattr(config, field, items[0].id)
        return {'task_id': items[0].task_id, 'job_id': items[0].id}


class ModelListInput(BaseModel):
    text_config_id: UUID | None = None


class TextCallInput(BaseModel):
    prompt: str = Field(min_length=1, max_length=16000)
    model_name: str | None = Field(default=None, max_length=200)


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
    def verify(request: Request, kind: Literal['generate', 'edit', 'text', 'vision', 'tools'], request_id: Annotated[UUID, Form()], authorized: Annotated[Literal['yes'], Form()], reference: Annotated[UploadFile | None, File()] = None, model_name: Annotated[str | None, Form()] = None):
        if kind == 'tools':
            from app.agent_runtime import _chat, AgentError
            from app.model_capabilities import evidence, save_evidence
            owner = request.state.image_owner
            current = store.get(owner)
            if not current or model_name not in current['model_names']: raise HTTPException(422, '请选择已保存的模型。')
            url, key = store.resolve_connection(owner)
            try:
                result = _chat(url, key, model_name, [{'role': 'user', 'content': '请调用 capability_check 工具，value 填 OK，不要仅回复文字。'}],
                    [{'type': 'function', 'function': {'name': 'capability_check', 'description': '检查工具调用能力', 'parameters': {'type': 'object', 'properties': {'value': {'type': 'string'}}, 'required': ['value']}}}],
                    parameters=current.get('model_settings', {}).get(model_name, {}).get('text_parameters', {}))
                supported = any(call.get('function', {}).get('name') == 'capability_check' for call in result.get('tool_calls', []))
                checked = evidence(model_name, supported, message='已收到工具调用。' if supported else '未返回工具调用，能力待确认。')
            except AgentError as error:
                checked = evidence(model_name, False, error.diagnostic, error.message)
            save_evidence(store, owner, 'tools', model_name, checked, current['revision'])
            return {'output': checked['message'], 'capability': checked}
        if kind in ('text', 'vision'):
            return store.call_text(request.state.image_owner, '请简短描述图片中的颜色。' if kind == 'vision' else '请回复 OK。', vision=kind == 'vision', model_name=model_name)
        return store.enqueue_verification(request.state.image_owner, kind, str(request_id), reference.file.read(20 * 1024 * 1024 + 1) if reference else None, model_name)
    @router.post('/text')
    def text(request: Request, data: TextCallInput):
        return store.call_text(request.state.image_owner, data.prompt, model_name=data.model_name)
    return router
