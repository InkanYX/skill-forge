"""HTTP application. Health endpoints deliberately require no database."""

from datetime import datetime, timezone
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal
import hashlib
import secrets
import re
import os
from app.auth import AuthService, build_auth_router, COOKIE
from app.authorization import principal
from app.image_configurations import ImageConfigStore, build_image_config_router
from app.standard_image_worker import StandardWorker

from fastapi import APIRouter, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.middleware.trustedhost import TrustedHostMiddleware
from sqlalchemy.exc import SQLAlchemyError
from app.database import DatabaseConfigStore, database_url, data_directory, make_engine, storage_status

from app.model_configs import FileConfigStore, build_router, probe_models, probe_connection
from app.image_jobs import build_image_router
from app.creative_templates import build_creative_router
from app.products import build_product_router
from app.image_exports import build_export_router
from app.skills import build_skill_router
from app.skill_packages import build_skill_router as build_package_router, seed_builtin
from app.agent_runtime import AgentWorker, build_agent_router
from app.workspace import build_workspace_router
from app.creation_projects import build_creation_router, CreationWorker

VERSION = "0.1.0"


class HealthResponse(BaseModel):
    status: Literal["ok"]
    service: str
    version: str
    timestamp: datetime


def create_app(data_dir: Path | None = None, probe=probe_models, db_url: str | None = None, connection_probe=probe_connection, enable_standard: bool | None = None, start_image_worker: bool = True, enable_auth: bool | None = None) -> FastAPI:
    auth_enabled = data_dir is None if enable_auth is None else enable_auth
    standard_enabled = data_dir is None if enable_standard is None else enable_standard
    @asynccontextmanager
    async def lifespan(app):
        if engine and data_dir is None:
            try:
                seed_builtin(engine, directory)
            except Exception:
                # Built-in seeding is best effort; a failure must not block the API.
                pass
        worker = StandardWorker(image_store) if standard_enabled and engine and start_image_worker else None
        agent_worker = AgentWorker(engine, directory, image_store) if standard_enabled and engine and start_image_worker else None
        creation_worker = CreationWorker(image_store) if standard_enabled and engine and start_image_worker else None
        if worker: worker.start()
        if agent_worker: agent_worker.start()
        if creation_worker: creation_worker.start()
        yield
        if creation_worker: creation_worker.stop()
        if agent_worker: agent_worker.stop()
        if worker: worker.stop()
        if engine:
            engine.dispose()

    application = FastAPI(
        title="Skill Forge API",
        description="车棚、凉棚图片工作台：健康检查与个人模型配置（本机开发阶段）。",
        version=VERSION,
        lifespan=lifespan,
    )
    application.add_middleware(TrustedHostMiddleware, allowed_hosts=os.environ.get("SKILL_FORGE_ALLOWED_HOSTS", "127.0.0.1,localhost,testserver").split(","))

    @application.middleware("http")
    async def local_origin_guard(request: Request, call_next):
        user = auth_service.current(request.cookies.get(COOKIE)) if auth_enabled and request.url.path.startswith('/api/') else None
        request.state.user = user
        public = request.url.path in ('/api/health','/api/auth/me','/api/auth/login')
        if auth_enabled and request.url.path.startswith('/api/') and not public:
            if not user: return JSONResponse(status_code=401, content={'detail':'请先登录。'})
            if user['must_change_password'] and request.url.path not in ('/api/auth/password','/api/auth/logout'):
                return JSONResponse(status_code=403, content={'detail':'首次登录或密码重置后，请先修改密码。'})
        token = request.cookies.get('sf_image_session', '')
        new_token = not re.fullmatch(r'[A-Za-z0-9_-]{43}', token)
        if new_token: token = secrets.token_urlsafe(32)
        request.state.image_owner = user['id'] if user else hashlib.sha256(token.encode()).hexdigest()
        if request.url.path.startswith(("/api/auth", "/api/admin", "/api/image-configs", "/api/model-configs", "/api/image-jobs", "/api/templates", "/api/cases", "/api/products", "/api/skills", "/api/skill-packages", "/api/agent", "/api/workspace", "/api/creation-projects")):
            origin = request.headers.get("origin")
            allowed = set(filter(None,os.environ.get("SKILL_FORGE_ALLOWED_ORIGINS", "").split(","))) | {f"http://{host}:{port}" for host in ("localhost", "127.0.0.1") for port in (5173, 8000)}
            if origin and origin not in allowed:
                return JSONResponse(status_code=403, content={"detail": "不允许此网页来源访问模型配置。"})
            content_type = request.headers.get("content-type", "").split(";")[0]
            length = request.headers.get("content-length", "")
            image_verification = request.url.path.startswith('/api/image-configs/verify/')
            asset_upload = request.url.path.startswith('/api/products/') and request.url.path.endswith('/assets')
            package_import = request.url.path == '/api/skill-packages/import'
            agent_upload = request.url.path == '/api/agent/runs'
            creation_upload = request.url.path.startswith('/api/creation-projects/') and request.url.path.endswith('/materials')
            if (request.url.path.startswith("/api/image-jobs") or asset_upload or image_verification or package_import or agent_upload or creation_upload) and request.method == "POST" and (content_type != "multipart/form-data" or not length.isdecimal() or int(length) > 21 * 1024 * 1024):
                return JSONResponse(status_code=413, content={"detail": "请使用不超过 20 MB 的参考图片或技能包提交。"})
            bodyless_post = request.method == 'POST' and (not length.isdecimal() or int(length) == 0)
            if not asset_upload and not image_verification and not package_import and not agent_upload and not creation_upload and not bodyless_post and request.url.path.startswith(("/api/auth", "/api/admin", "/api/image-configs", "/api/model-configs", "/api/templates", "/api/cases", "/api/products", "/api/skills", "/api/skill-packages", "/api/agent", "/api/creation-projects")) and request.method in ("POST", "PUT") and (content_type != "application/json" or not length.isdecimal() or int(length) > 512000):
                return JSONResponse(status_code=415, content={"detail": "请使用 JSON 请求。"})
        context_token = principal.set(user if auth_enabled else None)
        try:
            response = await call_next(request)
        finally:
            principal.reset(context_token)
        if not auth_enabled and new_token and request.url.path.startswith(('/api/image-configs', '/api/creation-projects')):
            response.set_cookie('sf_image_session', token, httponly=True, samesite='strict', max_age=31536000)
        if request.url.path.startswith(("/api/auth", "/api/admin", "/api/image-configs", "/api/model-configs", "/api/image-jobs", "/api/templates", "/api/cases", "/api/products", "/api/skills", "/api/skill-packages", "/api/agent", "/api/workspace", "/api/creation-projects")):
            response.headers["Cache-Control"] = "no-store"
        return response

    @application.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        # Pydantic's default error payload includes the rejected input value.
        errors = [{"loc": error["loc"], "msg": error["msg"], "type": error["type"]} for error in exc.errors()]
        return JSONResponse(status_code=422, content={"detail": errors})

    @application.exception_handler(SQLAlchemyError)
    async def database_error(request: Request, exc: SQLAlchemyError):
        return JSONResponse(status_code=503, content={"detail": "数据库暂不可用，请检查连接与表结构。"})

    directory = data_dir or data_directory()
    # Explicit data_dir keeps file-based tests isolated from a developer's .env.
    url = db_url or (database_url() if data_dir is None else None)
    engine = make_engine(url) if url else None
    store = DatabaseConfigStore(directory, engine) if engine else FileConfigStore(directory)
    application.include_router(build_router(store, probe, connection_probe))
    image_store = ImageConfigStore(engine, directory)
    image_store.auth_enabled = auth_enabled
    application.state.image_configs = image_store
    auth_service = AuthService(engine,image_store)
    application.state.auth_service = auth_service
    application.include_router(build_auth_router(auth_service))
    application.include_router(build_image_config_router(image_store))
    application.include_router(build_image_router(engine, directory, image_store if standard_enabled else None))
    application.include_router(build_export_router(engine, directory))
    application.include_router(build_creative_router(engine))
    application.include_router(build_skill_router(engine))
    application.include_router(build_package_router(engine, directory))
    application.include_router(build_agent_router(engine, directory, image_store))
    application.include_router(build_workspace_router(engine, image_store))
    application.include_router(build_product_router(engine, directory))
    application.include_router(build_creation_router(image_store))
    router = APIRouter(prefix="/api")

    @router.get("/system/status", tags=["system"])
    def system_status():
        return storage_status(engine)

    @router.get("/health", response_model=HealthResponse, tags=["system"])
    def health() -> HealthResponse:
        return HealthResponse(
            status="ok",
            service="skill-forge-api",
            version=VERSION,
            timestamp=datetime.now(timezone.utc),
        )

    application.include_router(router)
    return application


app = create_app()
