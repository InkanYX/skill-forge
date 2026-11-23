"""HTTP application. Health endpoints deliberately require no database."""

from datetime import datetime, timezone
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.middleware.trustedhost import TrustedHostMiddleware
from sqlalchemy.exc import SQLAlchemyError
from app.database import DatabaseConfigStore, database_url, data_directory, make_engine, storage_status

from app.model_configs import FileConfigStore, build_router, probe_models
from app.image_jobs import build_image_router
from app.creative_templates import build_creative_router
from app.products import build_product_router
from app.image_exports import build_export_router
from app.skills import build_skill_router
from app.workspace import build_workspace_router

VERSION = "0.1.0"


class HealthResponse(BaseModel):
    status: Literal["ok"]
    service: str
    version: str
    timestamp: datetime


def create_app(data_dir: Path | None = None, probe=probe_models, db_url: str | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app):
        yield
        if engine:
            engine.dispose()

    application = FastAPI(
        title="Skill Forge API",
        description="车棚、凉棚图片工作台：健康检查与个人模型配置（本机开发阶段）。",
        version=VERSION,
        lifespan=lifespan,
    )
    application.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "testserver"])

    @application.middleware("http")
    async def local_origin_guard(request: Request, call_next):
        if request.url.path.startswith(("/api/model-configs", "/api/image-jobs", "/api/templates", "/api/cases", "/api/products", "/api/skills", "/api/workspace")):
            origin = request.headers.get("origin")
            allowed = {f"http://{host}:{port}" for host in ("localhost", "127.0.0.1") for port in (5173, 8000)}
            if origin and origin not in allowed:
                return JSONResponse(status_code=403, content={"detail": "不允许此网页来源访问模型配置。"})
            content_type = request.headers.get("content-type", "").split(";")[0]
            length = request.headers.get("content-length", "")
            asset_upload = request.url.path.startswith('/api/products/') and request.url.path.endswith('/assets')
            if (request.url.path.startswith("/api/image-jobs") or asset_upload) and request.method == "POST" and (content_type != "multipart/form-data" or not length.isdecimal() or int(length) > 21 * 1024 * 1024):
                return JSONResponse(status_code=413, content={"detail": "请使用不超过 20 MB 的参考图片提交。"})
            if not asset_upload and request.url.path.startswith(("/api/model-configs", "/api/templates", "/api/cases", "/api/products", "/api/skills")) and request.method in ("POST", "PUT") and (content_type != "application/json" or not length.isdecimal() or int(length) > 256000):
                return JSONResponse(status_code=415, content={"detail": "请使用 JSON 请求。"})
        response = await call_next(request)
        if request.url.path.startswith(("/api/model-configs", "/api/image-jobs", "/api/templates", "/api/cases", "/api/products", "/api/skills", "/api/workspace")):
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
    application.include_router(build_router(store, probe))
    application.include_router(build_image_router(engine, directory))
    application.include_router(build_export_router(engine, directory))
    application.include_router(build_creative_router(engine))
    application.include_router(build_skill_router(engine))
    application.include_router(build_workspace_router(engine))
    application.include_router(build_product_router(engine, directory))
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
