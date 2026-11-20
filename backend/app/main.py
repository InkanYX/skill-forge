"""HTTP application. Health endpoints deliberately require no database."""

from datetime import datetime, timezone
import os
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.model_configs import FileConfigStore, build_router, probe_models

VERSION = "0.1.0"


class HealthResponse(BaseModel):
    status: Literal["ok"]
    service: str
    version: str
    timestamp: datetime


def create_app(data_dir: Path | None = None, probe=probe_models) -> FastAPI:
    application = FastAPI(
        title="Skill Forge API",
        description="车棚、凉棚图片工作台：健康检查与个人模型配置（本机开发阶段）。",
        version=VERSION,
    )
    application.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "testserver"])

    @application.middleware("http")
    async def local_origin_guard(request: Request, call_next):
        if request.url.path.startswith("/api/model-configs"):
            origin = request.headers.get("origin")
            allowed = {f"http://{host}:{port}" for host in ("localhost", "127.0.0.1") for port in (5173, 8000)}
            if origin and origin not in allowed:
                return JSONResponse(status_code=403, content={"detail": "不允许此网页来源访问模型配置。"})
            if request.method in ("POST", "PUT") and request.headers.get("content-type", "").split(";")[0] != "application/json":
                return JSONResponse(status_code=415, content={"detail": "请使用 JSON 请求。"})
        response = await call_next(request)
        if request.url.path.startswith("/api/model-configs"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @application.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        # Pydantic's default error payload includes the rejected input value.
        errors = [{"loc": error["loc"], "msg": error["msg"], "type": error["type"]} for error in exc.errors()]
        return JSONResponse(status_code=422, content={"detail": errors})

    directory = data_dir or Path(os.environ.get("SKILL_FORGE_DATA_DIR", str(Path(__file__).resolve().parents[2] / "data")))
    application.include_router(build_router(FileConfigStore(directory), probe))
    router = APIRouter(prefix="/api")

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
