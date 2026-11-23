from app.authorization import owner_view, require_edit
"""Durable queue and image artifact endpoints for local, single-user use."""
import hashlib
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Literal
from uuid import UUID, uuid4, uuid5

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, Query, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, ValidationError, field_validator
from sqlalchemy import select, update, func, or_, cast, JSON
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import ImageJob, ModelConfiguration, DatabaseConfigStore, CreativeCase
from app.image_provider import MAX_IMAGE, GenerationError, generate_image, normalize_image
from app.creative_templates import render_template
from app.products import resolve_product
from app.model_configs import configured_models
from app.image_sizes import ImageSize, normalize_size


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


class JobView(BaseModel):
    id: str
    config_id: str
    config_name: str
    model_name: str
    prompt: str
    size: str
    mode: str
    status: str
    message: str
    created_at: str
    updated_at: str
    image_url: str | None = None
    reference_url: str | None = None
    template_snapshot: dict = {}
    product_snapshot: dict = {}
    parent_job_id: str | None = None
    edit_instruction: str = ''
    case_id: str | None = None
    is_favorite: bool = False
    set_id: str | None = None
    set_name: str = ''
    shot_name: str = ''
    shot_index: int | None = None
    task_id: str = ''
    owner_id: str | None = None
    can_edit: bool = True
    task_index: int = 0
    execution_profile: dict = {}
    execution_result: dict = {}
    preview_url: str | None = None


class ShotInput(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    prompt: str = Field(min_length=1, max_length=4000)
    size: ImageSize = 'default'

    @field_validator('name', 'prompt')
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError('每张图片都需填写用途名称和制作要求。')
        return value.strip()


class ImageSetInput(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    shots: list[ShotInput] = Field(min_length=1, max_length=8)

    @field_validator('name')
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError('请填写套图名称。')
        return value.strip()


class LibraryJobView(JobView):
    case_id: str | None = None


class LibraryPage(BaseModel):
    items: list[LibraryJobView]
    total: int
    page: int
    page_size: int


def view(row: ImageJob) -> JobView:
    fields = {name: getattr(row, name) for name in ("id", "config_id", "parent_job_id", "edit_instruction", "set_id", "set_name", "shot_name", "shot_index", "config_name", "model_name", "prompt", "size", "mode", "status", "message", "created_at", "updated_at")}
    return JobView(**fields, **owner_view(row), execution_profile=json.loads(row.execution_profile or '{}'), execution_result=json.loads(row.execution_result or '{}'), preview_url=f'/api/image-jobs/{row.id}/preview' if row.status == 'succeeded' and row.execution_profile != '{}' else None, task_id=row.task_id or row.request_id, task_index=row.task_index, is_favorite=row.is_favorite, product_snapshot=json.loads(row.product_snapshot or '{}'), template_snapshot=json.loads(row.template_snapshot or '{}'), image_url=f"/api/image-jobs/{row.id}/image" if row.status == "succeeded" else None, reference_url=f"/api/image-jobs/{row.id}/reference" if row.mode == "edit" else None)


def artifact(directory: Path, identifier: str, name: str) -> Path:
    return directory / "image-jobs" / str(UUID(identifier)) / name


def create_job(engine, directory, config_id, model_name, prompt, size, request_id, reference):
    return create_jobs(engine, directory, config_id, model_name, prompt, size, request_id, reference, 1)[0]


def create_jobs(engine, directory, config_id, model_name, prompt, size, request_id, reference, count, template_request=None, product_request=None, source_job_id=None, image_set=None, standard_config=None, owner_id=None):
    if not 1 <= count <= 8:
        raise HTTPException(422, "每次请选择 1 至 8 张图片。")
    try:
        size = normalize_size(size)
    except ValueError as error:
        raise HTTPException(422, str(error)) from None
    model_name, prompt = model_name.strip(), prompt.strip()
    if not prompt and not template_request and not image_set:
        raise HTTPException(422, "请填写图片要求。")
    if reference is not None:
        try:
            reference = normalize_image(reference)
        except GenerationError as error:
            raise HTTPException(422, error.message) from None
    inputs = [config_id, model_name, prompt, size, hashlib.sha256(reference).hexdigest() if reference else None]
    if count > 1:
        inputs.append(count)
    if template_request:
        inputs.append(template_request)
    if product_request:
        inputs.append(product_request)
    if image_set:
        if source_job_id or len(image_set['shots']) != count:
            raise HTTPException(422, '套图参数无效。')
        inputs.append(image_set)
    if source_job_id:
        if reference is not None or product_request or template_request:
            raise HTTPException(422, '继续修改时请使用来源作品，不要同时提供其他参考图、产品或模板。')
        inputs.append({'source_job_id': source_job_id})
    fingerprint = hashlib.sha256(json.dumps(inputs, ensure_ascii=False).encode()).hexdigest()
    request_ids = [request_id] + [str(uuid5(UUID(request_id), f"image-{index}")) for index in range(1, count)]
    with Session(engine) as session:
        def existing():
            rows = list(session.scalars(select(ImageJob).where(ImageJob.request_id.in_(request_ids))))
            if not rows:
                return None
            if len(rows) != count or any(row.fingerprint != fingerprint for row in rows):
                raise HTTPException(409, "此提交标识已用于不同任务，请重新提交。")
            lookup = {row.request_id: row for row in rows}
            return [view(lookup[item]) for item in request_ids]
        prior = existing()
        if prior:
            return prior
        snapshot = {}
        product_snapshot = {}
        edit_instruction = ''
        set_meta = {'set_id': request_id if image_set else None, 'set_name': image_set['name'] if image_set else '', 'shot_name': '', 'shot_index': None}
        if source_job_id:
            source = session.get(ImageJob, source_job_id)
            if source is None or source.status != 'succeeded':
                raise HTTPException(422, '只能基于已完成的作品继续修改。')
            path = artifact(directory, source.id, 'result.png')
            try:
                if path.stat().st_size > MAX_IMAGE:
                    raise GenerationError('来源图片过大。')
                reference = normalize_image(path.read_bytes())
            except (OSError, GenerationError):
                raise HTTPException(422, '来源图片文件缺失或不可用，请检查图片目录。') from None
            snapshot = json.loads(source.template_snapshot or '{}')
            product_snapshot = json.loads(source.product_snapshot or '{}')
            edit_instruction = prompt
            set_meta = {key: getattr(source, key) for key in set_meta}
            prompt = '基于参考图进行修改。除本次明确要求的变化外，保持产品结构、材质、比例和其他画面内容。\n\n本次修改要求：\n' + edit_instruction
        if product_request:
            product_snapshot, reference = resolve_product(session, directory, product_request, reference)
        if template_request:
            prompt, snapshot = render_template(session, template_request, prompt)
        if product_snapshot:
            facts = {
                key: product_snapshot[key]
                for key in ('sku', 'name', 'category', 'dimensions', 'color', 'facts', 'notes')
                if str(product_snapshot[key] or '').strip()
                and str(product_snapshot[key]).strip() not in prompt
            }
            if facts:
                prompt += '\n\n产品资料（只使用已提供信息，不推测缺失参数）：\n' + json.dumps(facts, ensure_ascii=False)
        if len(prompt) > 32000:
            raise HTTPException(422, '合并后的创作要求过长，请精简模板或产品资料。')
        plans = [{'prompt': prompt, 'size': size, 'shot_name': set_meta['shot_name'], 'shot_index': set_meta['shot_index']} for _ in range(count)]
        if image_set:
            plans = [{'prompt': f"{prompt}\n\n本张用途：{shot['name']}\n本张制作要求：\n{shot['prompt']}", 'size': shot['size'], 'shot_name': shot['name'], 'shot_index': index} for index, shot in enumerate(image_set['shots'])]
            if any(len(plan['prompt']) > 32000 for plan in plans):
                raise HTTPException(422, '部分图片合并后的要求过长，请精简公共要求或模板。')
        if standard_config:
            from app.image_configurations import MODEL
            if model_name and model_name != MODEL: raise HTTPException(422, '图片模型固定为 ' + MODEL)
            model_name = MODEL
            from types import SimpleNamespace
            config = SimpleNamespace(**{key: standard_config[key] for key in ('name','base_url')}, encrypted_key='')
            for plan in plans:
                if plan['size'] != 'default':
                    width, height = plan['size'].split('x')
                    from math import gcd
                    divisor = gcd(int(width), int(height))
                    plan['prompt'] += f'\n\nOutput composition aspect ratio: {int(width)//divisor}:{int(height)//divisor}. Native size is auto; preserve product proportions.'
        else:
            config = session.get(ModelConfiguration, config_id)
            if config is None:
                raise HTTPException(404, "请先保存模型配置。")
            model_name = model_name or config.model_name
            if not model_name:
                raise HTTPException(422, "请指定支持生图的模型名称。")
            if model_name not in configured_models(config):
                raise HTTPException(422, '所选模型未保存在此接口配置中，请刷新模型选项后重试。')
            # Validate decryptability now, but store only the encrypted snapshot.
            store = DatabaseConfigStore(directory, engine)
            try:
                store._cipher().decrypt(config.encrypted_key.encode())
            except HTTPException:
                raise
            except Exception:
                raise HTTPException(503, "无法解密密钥，请恢复加密文件或重新保存配置。") from None
        rows = []
        for index, (item_request_id, plan) in enumerate(zip(request_ids, plans)):
            identifier = str(uuid4())
            row = ImageJob(id=identifier, request_id=item_request_id, fingerprint=fingerprint, config_id=config_id, config_name=config.name, base_url=config.base_url, encrypted_key=config.encrypted_key, model_name=model_name, prompt=plan['prompt'], size=plan['size'], mode="edit" if reference else "generate", status="queued", message="等待后台 Worker 执行", created_at=now(), updated_at=now(), owner_id=owner_id)
            row.task_id, row.task_index = request_id, index
            if standard_config: row.execution_profile = json.dumps(standard_config, ensure_ascii=False)
            if reference:
                path = artifact(directory, identifier, "reference.png")
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(reference)
            session.add(row)
            row.template_snapshot = json.dumps(snapshot, ensure_ascii=False)
            row.product_snapshot = json.dumps(product_snapshot, ensure_ascii=False)
            row.parent_job_id = source_job_id
            row.edit_instruction = edit_instruction
            row.set_id, row.set_name = set_meta['set_id'], set_meta['set_name']
            row.shot_name, row.shot_index = plan['shot_name'], plan['shot_index']
            rows.append(row)
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
            prior = existing()
            if prior is None:
                raise HTTPException(409, "任务提交冲突，请刷新任务列表核对。") from None
            return prior
        return [view(row) for row in rows]


def process_one(engine, directory: Path, provider=generate_image) -> bool:
    # A timed-out lease is never put back on the paid-request queue.
    with Session(engine) as session, session.begin():
        session.execute(update(ImageJob).where(ImageJob.status == "running", ImageJob.lease_until < time.time()).values(status="unknown", message="Worker 中断或执行超过时限，请核对服务商记录；未自动重试。", updated_at=now(), lease_until=None, encrypted_key=""))
        row = session.scalar(select(ImageJob).where(ImageJob.status == "queued", ImageJob.execution_profile == "{}").order_by(ImageJob.created_at).limit(1).with_for_update(skip_locked=True))
        if row is None:
            return False
        row.status, row.message, row.updated_at = "running", "服务商正在生成图片，请稍候", now()
        row.lease_until = time.time() + 900
        values = {column.name: getattr(row, column.name) for column in ImageJob.__table__.columns}
    identifier = values["id"]
    state, message = "unknown", "执行中断，请核对服务商记录；未自动重试。"
    diagnostic = {}
    try:
        store = DatabaseConfigStore(directory, engine)
        try:
            key = store._cipher().decrypt(values["encrypted_key"].encode()).decode()
        except Exception:
            raise GenerationError("密钥无法解密，未调用服务商；请检查本机加密文件。") from None
        reference = artifact(directory, identifier, "reference.png").read_bytes() if values["mode"] == "edit" else None
        content = provider(values["base_url"], key, values["model_name"], values["prompt"], values["size"], reference)
        path = artifact(directory, identifier, "result.png")
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_bytes(content)
        os.replace(temporary, path)
        state, message = "succeeded", "图片已生成并保存到本机"
    except GenerationError as error:
        state, message = ("unknown" if error.uncertain else "failed"), error.message
        diagnostic = error.diagnostic
    except HTTPException:
        state, message = "failed", "无法连接服务商公开地址，未自动重试。"
    except Exception:
        # Provider bodies, keys, URLs, and arbitrary exception text are not exposed.
        pass
    with Session(engine) as session, session.begin():
        session.execute(update(ImageJob).where(ImageJob.id == identifier, ImageJob.status == "running").values(status=state, message=message, provider_diagnostic=json.dumps(diagnostic, ensure_ascii=False), updated_at=now(), lease_until=None, encrypted_key=""))
    return True


def cancel_job(engine, identifier: str) -> JobView:
    with Session(engine) as session, session.begin():
        # Shares the row lock with the worker's queued -> running claim.
        row = session.get(ImageJob, identifier, with_for_update=True)
        if row is None:
            raise HTTPException(404, '任务不存在。')
        require_edit(row)
        if row.status == 'cancelled':
            return view(row)
        if row.status == 'running':
            raise HTTPException(409, '任务已开始执行，可能已调用服务商，当前无法取消。请等待结果。')
        if row.status != 'queued':
            raise HTTPException(409, '任务已结束，无法取消。结果待确认时请先核对服务商记录。')
        row.status, row.message = 'cancelled', '已取消排队，未调用服务商。'
        row.updated_at, row.lease_until, row.encrypted_key = now(), None, ''
        return view(row)


def cancel_set(engine, identifier: str):
    with Session(engine) as session, session.begin():
        if session.scalar(select(ImageJob.id).where(ImageJob.set_id == identifier).limit(1)) is None:
            raise HTTPException(404, '套图记录不存在。')
        # PostgreSQL rechecks status after waiting for a worker's row lock.
        for item in session.scalars(select(ImageJob).where(ImageJob.set_id == identifier)):
            require_edit(item)
        cancelled = list(session.scalars(update(ImageJob).where(ImageJob.set_id == identifier, ImageJob.status == 'queued').values(status='cancelled', message='已取消排队，未调用服务商。', updated_at=now(), lease_until=None, encrypted_key='').returning(ImageJob.id)))
        counts = dict(session.execute(select(ImageJob.status, func.count()).where(ImageJob.set_id == identifier).group_by(ImageJob.status)).all())
        return {'cancelled_count': len(cancelled), 'counts': counts, 'message': f"已取消 {len(cancelled)} 项排队任务。已有图片保留，已开始执行的任务不会被中止。"}


def build_image_router(engine, directory: Path, image_configs=None):
    router = APIRouter(prefix="/api/image-jobs", tags=["image-jobs"])
    from app.image_tasks import build_task_router
    router.include_router(build_task_router(engine, view))

    def standard_profile(request, identifier):
        if image_configs is None: return None
        return image_configs.snapshot(request.state.image_owner, str(identifier))

    def require_database():
        if engine is None:
            raise HTTPException(503, "生图任务需要配置 PostgreSQL 并执行迁移。")

    @router.get("", response_model=list[JobView])
    def list_jobs():
        require_database()
        with Session(engine) as session:
            return [view(row) for row in session.scalars(select(ImageJob).order_by(ImageJob.created_at.desc()).limit(30))]

    @router.post('/sets', response_model=list[JobView], status_code=202)
    def submit_set(request: Request, config_id: Annotated[UUID, Form()], request_id: Annotated[UUID, Form()], plan: Annotated[str, Form(max_length=80000)], prompt: Annotated[str, Form(max_length=8000)] = '', template: Annotated[str, Form(max_length=240000)] = '', product: Annotated[str, Form(max_length=2000)] = '', reference: Annotated[UploadFile | None, File()] = None, model_name: Annotated[str, Form(max_length=200)] = ''):
        require_database()
        try:
            image_set = ImageSetInput.model_validate_json(plan).model_dump()
            template_request = json.loads(template) if template else None
            product_request = json.loads(product) if product else None
            if any(value is not None and (not isinstance(value, dict) or not value) for value in (template_request, product_request)):
                raise ValueError()
        except (ValueError, ValidationError):
            raise HTTPException(422, '请检查套图清单：每套 1–8 张，名称、用途和要求必填，单张要求最多 4000 字符；尺寸为 default 或正整数宽x高，总像素不超过 2000 万。') from None
        content = reference.file.read(MAX_IMAGE + 1) if reference else None
        return create_jobs(engine, directory, str(config_id), model_name, prompt, 'default', str(request_id), content, len(image_set['shots']), template_request, product_request, image_set=image_set, standard_config=standard_profile(request, config_id))

    @router.get('/sets/{set_id}')
    def get_set(set_id: UUID):
        require_database()
        with Session(engine) as session:
            rows = list(session.scalars(select(ImageJob).where(ImageJob.set_id == str(set_id)).order_by(ImageJob.shot_index, ImageJob.created_at, ImageJob.id).limit(201)))
            if not rows:
                raise HTTPException(404, '套图记录不存在。')
            return {'id': str(set_id), 'name': rows[0].set_name, 'items': [view(row) for row in rows[:200]], 'has_more': len(rows) > 200}

    @router.post('/sets/{set_id}/cancel')
    def cancel_set_tasks(set_id: UUID, action: Annotated[Literal['cancel'], Form()]):
        require_database()
        return cancel_set(engine, str(set_id))

    @router.post('/{job_id}/cancel', response_model=JobView)
    def cancel_single_task(job_id: UUID, action: Annotated[Literal['cancel'], Form()]):
        require_database()
        return cancel_job(engine, str(job_id))

    @router.get('/library', response_model=LibraryPage)
    def library(page: Annotated[int, Query(ge=1, le=100000)] = 1, page_size: Annotated[int, Query(ge=1, le=48)] = 12, status: Literal['all', 'queued', 'running', 'succeeded', 'failed', 'unknown', 'cancelled'] = 'succeeded', q: Annotated[str, Query(max_length=200)] = '', product_id: UUID | None = None, template_id: UUID | None = None, favorite: bool = False, has_notes: bool = False):
        require_database()
        product = cast(ImageJob.product_snapshot, JSON)
        template = cast(ImageJob.template_snapshot, JSON)
        # SQLite interprets CAST(text AS JSON) as numeric. JSON type_coerce keeps
        # JSON extraction portable without changing the stored snapshot format.
        from sqlalchemy import type_coerce
        if engine.dialect.name == 'sqlite':
            product = type_coerce(ImageJob.product_snapshot, JSON)
            template = type_coerce(ImageJob.template_snapshot, JSON)
        conditions = []
        if favorite:
            conditions.append(ImageJob.is_favorite.is_(True))
        if has_notes:
            conditions.append(select(CreativeCase.id).where(CreativeCase.job_id == ImageJob.id).correlate(ImageJob).exists())
        if status != 'all':
            conditions.append(ImageJob.status == status)
        if product_id:
            conditions.append(product['id'].as_string() == str(product_id))
        if template_id:
            conditions.append(template['id'].as_string() == str(template_id))
        if q.strip():
            note_match = select(CreativeCase.id).where(CreativeCase.job_id == ImageJob.id, or_(*(column.icontains(q.strip(), autoescape=True) for column in (CreativeCase.title, CreativeCase.experience, CreativeCase.issues)))).correlate(ImageJob).exists()
            conditions.append(or_(ImageJob.prompt.icontains(q.strip(), autoescape=True), ImageJob.model_name.icontains(q.strip(), autoescape=True), ImageJob.set_name.icontains(q.strip(), autoescape=True), ImageJob.shot_name.icontains(q.strip(), autoescape=True), product['sku'].as_string().icontains(q.strip(), autoescape=True), product['name'].as_string().icontains(q.strip(), autoescape=True), template['name'].as_string().icontains(q.strip(), autoescape=True), note_match))
        with Session(engine) as session:
            total = session.scalar(select(func.count()).select_from(ImageJob).where(*conditions))
            rows = session.execute(select(ImageJob, CreativeCase.id).outerjoin(CreativeCase, CreativeCase.job_id == ImageJob.id).where(*conditions).order_by(ImageJob.created_at.desc(), ImageJob.id.desc()).offset((page - 1) * page_size).limit(page_size))
            return LibraryPage(items=[LibraryJobView(**{**view(row).model_dump(), 'case_id': case_id}) for row, case_id in rows], total=total, page=page, page_size=page_size)

    @router.post('/{job_id}/favorite', response_model=JobView)
    def favorite_artwork(job_id: UUID, favorite: Annotated[bool, Form()]):
        require_database()
        with Session(engine) as session, session.begin():
            row = session.get(ImageJob, str(job_id), with_for_update=True)
            if row is None:
                raise HTTPException(404, '作品不存在。')
            if row.status != 'succeeded':
                raise HTTPException(409, '只能收藏已完成的图片。')
            # Explicit assignment makes repeated requests safe; do not change
            # updated_at, which represents the generation completion time.
            row.is_favorite = favorite
            return view(row).model_copy(update={'case_id': session.scalar(select(CreativeCase.id).where(CreativeCase.job_id == row.id))})

    @router.post("", response_model=JobView, status_code=202)
    def submit(request: Request, config_id: Annotated[UUID, Form()], request_id: Annotated[UUID, Form()], prompt: Annotated[str, Form(min_length=1, max_length=8000)], model_name: Annotated[str, Form(max_length=200)] = "", size: Annotated[ImageSize, Form()] = "default", reference: Annotated[UploadFile | None, File()] = None):
        require_database()
        content = reference.file.read(MAX_IMAGE + 1) if reference else None
        return create_jobs(engine, directory, str(config_id), model_name, prompt, size, str(request_id), content, 1, standard_config=standard_profile(request, config_id))[0]

    @router.post("/batch", response_model=list[JobView], status_code=202)
    def submit_batch(request: Request, config_id: Annotated[UUID, Form()], request_id: Annotated[UUID, Form()], prompt: Annotated[str, Form(max_length=8000)] = "", count: Annotated[int, Form(ge=1, le=8)] = 1, size: Annotated[ImageSize, Form()] = "default", reference: Annotated[UploadFile | None, File()] = None, template: Annotated[str, Form(max_length=240000)] = "", product: Annotated[str, Form(max_length=2000)] = "", source_job_id: Annotated[UUID | None, Form()] = None, model_name: Annotated[str, Form(max_length=200)] = ""):
        require_database()
        content = reference.file.read(MAX_IMAGE + 1) if reference else None
        # The requested model must belong to the saved provider configuration.
        try:
            template_request = json.loads(template) if template else None
            if template and (not isinstance(template_request, dict) or not template_request):
                raise ValueError()
            product_request = json.loads(product) if product else None
            if product and (not isinstance(product_request, dict) or not product_request):
                raise ValueError()
        except ValueError:
            raise HTTPException(422, "模板参数格式无效。") from None
        return create_jobs(engine, directory, str(config_id), model_name, prompt, size, str(request_id), content, count, template_request, product_request, str(source_job_id) if source_job_id else None, standard_config=standard_profile(request, config_id))

    @router.get("/{job_id}", response_model=JobView)
    def get_job(job_id: UUID):
        require_database()
        with Session(engine) as session:
            row = session.get(ImageJob, str(job_id))
            if row is None:
                raise HTTPException(404, "任务不存在。")
            return view(row).model_copy(update={'case_id': session.scalar(select(CreativeCase.id).where(CreativeCase.job_id == row.id))})

    @router.get('/{job_id}/diagnostics')
    def get_diagnostics(job_id: UUID):
        require_database()
        with Session(engine) as session:
            row = session.get(ImageJob, str(job_id))
            if row is None:
                raise HTTPException(404, '生成记录不存在。')
            diagnostic = json.loads(row.provider_diagnostic or '{}')
            return {'job_id': row.id, 'status': row.status, 'model_name': row.model_name, 'summary': row.message, 'diagnostic': diagnostic or None}

    @router.get('/{job_id}/versions')
    def versions(job_id: UUID):
        require_database()
        with Session(engine) as session:
            current = session.get(ImageJob, str(job_id))
            if current is None:
                raise HTTPException(404, '作品不存在。')
            ancestors, seen = [], {current.id}
            parent_id = current.parent_job_id
            while parent_id and parent_id not in seen and len(ancestors) < 50:
                row = session.get(ImageJob, parent_id)
                if row is None:
                    break
                ancestors.append(view(row))
                seen.add(row.id)
                parent_id = row.parent_job_id
            children = list(session.scalars(select(ImageJob).where(ImageJob.parent_job_id == current.id).order_by(ImageJob.created_at.desc(), ImageJob.id.desc()).limit(21)))
            return {'ancestors': list(reversed(ancestors)), 'current': view(current), 'children': [view(row) for row in children[:20]], 'has_more_ancestors': bool(parent_id), 'has_more_children': len(children) > 20}

    @router.post('/{job_id}/review')
    def save_review(job_id: UUID, status: Annotated[Literal['pending','passed','rework'], Form()], notes: Annotated[str, Form(max_length=4000)] = ''):
        require_database()
        with Session(engine) as session, session.begin():
            row = session.get(ImageJob, str(job_id), with_for_update=True)
            if row is None or row.status != 'succeeded' or row.execution_profile == '{}':
                raise HTTPException(409, '只能检查已完成的标准生图结果。')
            require_edit(row)
            result = json.loads(row.execution_result or '{}')
            result['review'] = {'status': status, 'notes': notes, 'method': 'human', 'updated_at': now()}
            row.execution_result = json.dumps(result, ensure_ascii=False)
            return result['review']

    @router.get("/{job_id}/{kind}")
    def get_image(job_id: UUID, kind: Literal["image", "reference", "preview"], download: bool = False):
        row = get_job(job_id)
        if (kind in ("image", "preview") and row.status != "succeeded") or (kind == "reference" and row.mode != "edit"):
            raise HTTPException(404, "图片尚不可用。")
        path = artifact(directory, str(job_id), "preview.jpg" if kind == "preview" else "result.png" if kind == "image" else "reference.png")
        if not path.is_file():
            raise HTTPException(404, "图片文件不存在，请检查数据目录或备份。")
        return FileResponse(path, media_type="image/jpeg" if kind == "preview" else "image/png", filename=f"skill-forge-{job_id}.png" if download else None, headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})

    return router
