"""Durable queue and image artifact endpoints for local, single-user use."""
import hashlib
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Literal
from uuid import UUID, uuid4, uuid5

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import ImageJob, ModelConfiguration, DatabaseConfigStore
from app.image_provider import MAX_IMAGE, GenerationError, generate_image, normalize_image
from app.creative_templates import render_template


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


class JobView(BaseModel):
    id: str
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


def view(row: ImageJob) -> JobView:
    fields = {name: getattr(row, name) for name in ("id", "config_name", "model_name", "prompt", "size", "mode", "status", "message", "created_at", "updated_at")}
    return JobView(**fields, template_snapshot=json.loads(row.template_snapshot or '{}'), image_url=f"/api/image-jobs/{row.id}/image" if row.status == "succeeded" else None, reference_url=f"/api/image-jobs/{row.id}/reference" if row.mode == "edit" else None)


def artifact(directory: Path, identifier: str, name: str) -> Path:
    return directory / "image-jobs" / str(UUID(identifier)) / name


def create_job(engine, directory, config_id, model_name, prompt, size, request_id, reference):
    return create_jobs(engine, directory, config_id, model_name, prompt, size, request_id, reference, 1)[0]


def create_jobs(engine, directory, config_id, model_name, prompt, size, request_id, reference, count, template_request=None):
    if not 1 <= count <= 8:
        raise HTTPException(422, "每次请选择 1 至 8 张图片。")
    model_name, prompt = model_name.strip(), prompt.strip()
    if not prompt and not template_request:
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
        if template_request:
            prompt, snapshot = render_template(session, template_request, prompt)
        config = session.get(ModelConfiguration, config_id)
        if config is None:
            raise HTTPException(404, "请先保存模型配置。")
        model_name = model_name or config.model_name
        if not model_name:
            raise HTTPException(422, "请指定支持生图的模型名称。")
        # Validate decryptability now, but store only the encrypted snapshot.
        store = DatabaseConfigStore(directory, engine)
        try:
            store._cipher().decrypt(config.encrypted_key.encode())
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(503, "无法解密密钥，请恢复加密文件或重新保存配置。") from None
        rows = []
        for item_request_id in request_ids:
            identifier = str(uuid4())
            row = ImageJob(id=identifier, request_id=item_request_id, fingerprint=fingerprint, config_id=config_id, config_name=config.name, base_url=config.base_url, encrypted_key=config.encrypted_key, model_name=model_name, prompt=prompt, size=size, mode="edit" if reference else "generate", status="queued", message="等待后台 Worker 执行", created_at=now(), updated_at=now())
            if reference:
                path = artifact(directory, identifier, "reference.png")
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(reference)
            session.add(row)
            row.template_snapshot = json.dumps(snapshot, ensure_ascii=False)
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
        row = session.scalar(select(ImageJob).where(ImageJob.status == "queued").order_by(ImageJob.created_at).limit(1).with_for_update(skip_locked=True))
        if row is None:
            return False
        row.status, row.message, row.updated_at = "running", "服务商正在生成图片，请稍候", now()
        row.lease_until = time.time() + 900
        values = {column.name: getattr(row, column.name) for column in ImageJob.__table__.columns}
    identifier = values["id"]
    state, message = "unknown", "执行中断，请核对服务商记录；未自动重试。"
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
    except HTTPException:
        state, message = "failed", "无法连接服务商公开地址，未自动重试。"
    except Exception:
        # Provider bodies, keys, URLs, and arbitrary exception text are not exposed.
        pass
    with Session(engine) as session, session.begin():
        session.execute(update(ImageJob).where(ImageJob.id == identifier, ImageJob.status == "running").values(status=state, message=message, updated_at=now(), lease_until=None, encrypted_key=""))
    return True


def build_image_router(engine, directory: Path):
    router = APIRouter(prefix="/api/image-jobs", tags=["image-jobs"])

    def require_database():
        if engine is None:
            raise HTTPException(503, "生图任务需要配置 PostgreSQL 并执行迁移。")

    @router.get("", response_model=list[JobView])
    def list_jobs():
        require_database()
        with Session(engine) as session:
            return [view(row) for row in session.scalars(select(ImageJob).order_by(ImageJob.created_at.desc()).limit(30))]

    @router.post("", response_model=JobView, status_code=202)
    def submit(config_id: Annotated[UUID, Form()], request_id: Annotated[UUID, Form()], prompt: Annotated[str, Form(min_length=1, max_length=8000)], model_name: Annotated[str, Form(max_length=200)] = "", size: Annotated[Literal["default", "1024x1024", "1536x1024", "1024x1536"], Form()] = "default", reference: Annotated[UploadFile | None, File()] = None):
        require_database()
        content = reference.file.read(MAX_IMAGE + 1) if reference else None
        return create_job(engine, directory, str(config_id), model_name, prompt, size, str(request_id), content)

    @router.post("/batch", response_model=list[JobView], status_code=202)
    def submit_batch(config_id: Annotated[UUID, Form()], request_id: Annotated[UUID, Form()], prompt: Annotated[str, Form(max_length=8000)] = "", count: Annotated[int, Form(ge=1, le=8)] = 4, size: Annotated[Literal["default", "1024x1024", "1536x1024", "1024x1536"], Form()] = "default", reference: Annotated[UploadFile | None, File()] = None, template: Annotated[str, Form(max_length=240000)] = ""):
        require_database()
        content = reference.file.read(MAX_IMAGE + 1) if reference else None
        # Resolve the model exclusively from its saved configuration.
        try:
            template_request = json.loads(template) if template else None
            if template and (not isinstance(template_request, dict) or not template_request):
                raise ValueError()
        except ValueError:
            raise HTTPException(422, "模板参数格式无效。") from None
        return create_jobs(engine, directory, str(config_id), "", prompt, size, str(request_id), content, count, template_request)

    @router.get("/{job_id}", response_model=JobView)
    def get_job(job_id: UUID):
        require_database()
        with Session(engine) as session:
            row = session.get(ImageJob, str(job_id))
            if row is None:
                raise HTTPException(404, "任务不存在。")
            return view(row)

    @router.get("/{job_id}/{kind}")
    def get_image(job_id: UUID, kind: Literal["image", "reference"], download: bool = False):
        row = get_job(job_id)
        if (kind == "image" and row.status != "succeeded") or (kind == "reference" and row.mode != "edit"):
            raise HTTPException(404, "图片尚不可用。")
        path = artifact(directory, str(job_id), "result.png" if kind == "image" else "reference.png")
        if not path.is_file():
            raise HTTPException(404, "图片文件不存在，请检查数据目录或备份。")
        return FileResponse(path, media_type="image/png", filename=f"skill-forge-{job_id}.png" if download else None, headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})

    return router
