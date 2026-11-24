"""Database models and a repository matching the existing configuration API."""

import os
import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from dotenv import dotenv_values
from fastapi import HTTPException
from sqlalchemy import String, Text, Float, Boolean, Index, UniqueConstraint, create_engine, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, Session

from app.authorization import principal, require_private

from app.model_configs import ConfigInput, ConfigView, FileConfigStore, configured_models

BACKEND_DIR = Path(__file__).resolve().parents[1]


def database_url() -> str | None:
    return os.environ.get("DATABASE_URL") or dotenv_values(BACKEND_DIR / ".env").get("DATABASE_URL")


def data_directory() -> Path:
    return Path(os.environ.get("SKILL_FORGE_DATA_DIR") or dotenv_values(BACKEND_DIR / ".env").get("SKILL_FORGE_DATA_DIR") or BACKEND_DIR / "data")


def make_engine(url: str) -> Engine:
    options = {"connect_timeout": 3} if url.startswith("postgresql") else {}
    return create_engine(url, pool_pre_ping=True, hide_parameters=True, connect_args=options)


class Base(DeclarativeBase):
    pass


class UserAccount(Base):
    __tablename__ = 'user_accounts'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    username: Mapped[str] = mapped_column(String(32), unique=True)
    display_name: Mapped[str] = mapped_column(String(80))
    password_hash: Mapped[str] = mapped_column(Text)
    role: Mapped[str] = mapped_column(String(16), default='member')
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=True)
    failed_attempts: Mapped[int] = mapped_column(default=0)
    locked_until: Mapped[float] = mapped_column(Float, default=0)
    created_at: Mapped[str] = mapped_column(String(40))


class LoginSession(Base):
    __tablename__ = 'login_sessions'
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(36), index=True)
    expires_at: Mapped[float] = mapped_column(Float, index=True)


class OwnedRecord:
    owner_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)


class ModelConfiguration(OwnedRecord, Base):
    __tablename__ = "model_configurations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(80))
    base_url: Mapped[str] = mapped_column(String(2048))
    model_name: Mapped[str] = mapped_column(String(200))
    model_names: Mapped[str] = mapped_column(Text, default='[]', server_default='[]')
    encrypted_key: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[str] = mapped_column(String(40))

    def as_dict(self) -> dict:
        return {column.name: getattr(self, column.name) for column in self.__table__.columns}


class ImageJob(OwnedRecord, Base):
    __tablename__ = "image_jobs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    request_id: Mapped[str] = mapped_column(String(36), unique=True)
    fingerprint: Mapped[str] = mapped_column(String(64))
    config_id: Mapped[str] = mapped_column(String(36))
    config_name: Mapped[str] = mapped_column(String(80))
    base_url: Mapped[str] = mapped_column(String(2048))
    encrypted_key: Mapped[str] = mapped_column(Text)
    model_name: Mapped[str] = mapped_column(String(200))
    prompt: Mapped[str] = mapped_column(Text)
    size: Mapped[str] = mapped_column(String(32))
    mode: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16), index=True)
    message: Mapped[str] = mapped_column(Text, default="等待后台执行")
    created_at: Mapped[str] = mapped_column(String(40), index=True)
    updated_at: Mapped[str] = mapped_column(String(40))
    lease_until: Mapped[float | None] = mapped_column(Float, nullable=True)
    template_snapshot: Mapped[str] = mapped_column(Text, default="{}")
    product_snapshot: Mapped[str] = mapped_column(Text, default="{}")
    parent_job_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    edit_instruction: Mapped[str] = mapped_column(Text, default="")
    set_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    set_name: Mapped[str] = mapped_column(String(100), default="")
    shot_name: Mapped[str] = mapped_column(String(80), default="")
    shot_index: Mapped[int | None] = mapped_column(nullable=True)
    is_favorite: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text('false'))
    provider_diagnostic: Mapped[str] = mapped_column(Text, default='{}', server_default='{}')
    task_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    task_index: Mapped[int] = mapped_column(default=0, server_default='0')
    execution_profile: Mapped[str] = mapped_column(Text, default='{}', server_default='{}')
    execution_result: Mapped[str] = mapped_column(Text, default='{}', server_default='{}')
    agent_run_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)


class ImageConfiguration(Base):
    __tablename__ = 'image_configurations'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(80))
    base_url: Mapped[str] = mapped_column(String(2048))
    revision: Mapped[str] = mapped_column(String(36))
    generation_job_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    edit_job_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    updated_at: Mapped[str] = mapped_column(String(40))
    text_model_name: Mapped[str] = mapped_column(String(200), default='', server_default='')
    vision_model_name: Mapped[str] = mapped_column(String(200), default='', server_default='')
    text_config_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    model_name: Mapped[str] = mapped_column(String(200), default='gpt-image-2.5-sunburst', server_default='gpt-image-2.5-sunburst')
    model_names: Mapped[str] = mapped_column(Text, default='["gpt-image-2.5-sunburst"]', server_default='["gpt-image-2.5-sunburst"]')


class Product(OwnedRecord, Base):
    __tablename__ = "products"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    sku: Mapped[str] = mapped_column(String(100), unique=True)
    content: Mapped[str] = mapped_column(Text)
    revision: Mapped[int] = mapped_column(default=1)
    updated_at: Mapped[str] = mapped_column(String(40))


class ProductAsset(OwnedRecord, Base):
    __tablename__ = "product_assets"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    product_id: Mapped[str] = mapped_column(String(36), index=True)
    name: Mapped[str] = mapped_column(String(120))
    kind: Mapped[str] = mapped_column(String(32))
    digest: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[str] = mapped_column(String(40))


class CreativeTemplate(OwnedRecord, Base):
    __tablename__ = "creative_templates"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    content: Mapped[str] = mapped_column(Text)
    revision: Mapped[int] = mapped_column(default=1)
    updated_at: Mapped[str] = mapped_column(String(40))


class CreativeSkill(OwnedRecord, Base):
    __tablename__ = 'creative_skills'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    content: Mapped[str] = mapped_column(Text)
    revision: Mapped[int] = mapped_column(default=1)
    updated_at: Mapped[str] = mapped_column(String(40))


class SkillRevision(Base):
    __tablename__ = 'skill_revisions'
    skill_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    revision: Mapped[int] = mapped_column(primary_key=True)
    content: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[str] = mapped_column(String(40))


class SkillPackage(Base):
    __tablename__ = 'skill_packages'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default='')
    source: Mapped[str] = mapped_column(String(16), default='imported')
    owner_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    is_readonly: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text('true'))
    current_version_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[str] = mapped_column(String(40))
    updated_at: Mapped[str] = mapped_column(String(40))
    # Built-in names stay globally unique; personal packages are unique per owner.
    __table_args__ = (
        Index('uq_skill_packages_owner_name', 'owner_id', 'name', unique=True,
              postgresql_where=text('owner_id IS NOT NULL'), sqlite_where=text('owner_id IS NOT NULL')),
        Index('uq_skill_packages_builtin_name', 'name', unique=True,
              postgresql_where=text("source = 'builtin'"), sqlite_where=text("source = 'builtin'")),
    )


class SkillVersion(Base):
    __tablename__ = 'skill_versions'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    skill_id: Mapped[str] = mapped_column(String(36), index=True)
    version_label: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), default='ready')
    compile_level: Mapped[str] = mapped_column(String(16), default='core')
    content_sha256: Mapped[str] = mapped_column(String(64))
    compiled_sha256: Mapped[str] = mapped_column(String(64))
    compiled_chars: Mapped[int] = mapped_column(default=0)
    file_count: Mapped[int] = mapped_column(default=0)
    total_bytes: Mapped[int] = mapped_column(default=0)
    entry_path: Mapped[str] = mapped_column(String(500), default='SKILL.md')
    created_at: Mapped[str] = mapped_column(String(40))
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    import_note: Mapped[str] = mapped_column(Text, default='')
    __table_args__ = (UniqueConstraint('skill_id', 'version_label', name='uq_skill_versions_label'),)


class SkillFile(Base):
    __tablename__ = 'skill_files'
    version_id: Mapped[str] = mapped_column(String(36), primary_key=True, index=True)
    path: Mapped[str] = mapped_column(String(500), primary_key=True)
    kind: Mapped[str] = mapped_column(String(24))
    size: Mapped[int] = mapped_column(default=0)
    sha256: Mapped[str] = mapped_column(String(64))
    is_text: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text('false'))


class AgentRun(OwnedRecord, Base):
    __tablename__ = 'agent_runs'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    skill_id: Mapped[str] = mapped_column(String(36))
    skill_version_id: Mapped[str] = mapped_column(String(36))
    config_id: Mapped[str] = mapped_column(String(36))
    status: Mapped[str] = mapped_column(String(16), index=True)
    goal: Mapped[str] = mapped_column(Text)
    model_name: Mapped[str] = mapped_column(String(200), default='')
    vision_model_name: Mapped[str] = mapped_column(String(200), default='')
    image_model_name: Mapped[str] = mapped_column(String(200), default='gpt-image-2.5-sunburst', server_default='gpt-image-2.5-sunburst')
    steps_count: Mapped[int] = mapped_column(default=0)
    image_calls: Mapped[int] = mapped_column(default=0)
    max_steps: Mapped[int] = mapped_column(default=20)
    max_images: Mapped[int] = mapped_column(default=6)
    error: Mapped[str] = mapped_column(Text, default='')
    summary: Mapped[str] = mapped_column(Text, default='')
    created_at: Mapped[str] = mapped_column(String(40))
    updated_at: Mapped[str] = mapped_column(String(40))
    finished_at: Mapped[str | None] = mapped_column(String(40), nullable=True)


class AgentStep(Base):
    __tablename__ = 'agent_steps'
    run_id: Mapped[str] = mapped_column(String(36), primary_key=True, index=True)
    step_index: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(16))
    tool_name: Mapped[str] = mapped_column(String(64), default='')
    arguments: Mapped[str] = mapped_column(Text, default='')
    result: Mapped[str] = mapped_column(Text, default='')
    created_at: Mapped[str] = mapped_column(String(40))


class AgentArtifact(Base):
    __tablename__ = 'agent_artifacts'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(36), index=True)
    kind: Mapped[str] = mapped_column(String(16))
    name: Mapped[str] = mapped_column(String(200), default='')
    path: Mapped[str] = mapped_column(String(500))
    sha256: Mapped[str] = mapped_column(String(64))
    size: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[str] = mapped_column(String(40))


class CreativeCase(OwnedRecord, Base):
    __tablename__ = "creative_cases"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    job_id: Mapped[str] = mapped_column(String(36), unique=True)
    title: Mapped[str] = mapped_column(String(120))
    experience: Mapped[str] = mapped_column(Text)
    issues: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[str] = mapped_column(String(40))


class ProductImageProject(OwnedRecord, Base):
    """Durable, versioned human approvals; no credentials in project state."""
    __tablename__ = 'product_image_projects'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    title: Mapped[str] = mapped_column(String(120))
    revision: Mapped[int] = mapped_column(default=1)
    status: Mapped[str] = mapped_column(String(24), index=True)
    action: Mapped[str] = mapped_column(String(24), default='')
    state: Mapped[str] = mapped_column(Text)
    lease_until: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[str] = mapped_column(String(40))
    updated_at: Mapped[str] = mapped_column(String(40))


class DatabaseConfigStore(FileConfigStore):
    """Retains encryption format, response schema, and address-change protection."""

    def __init__(self, directory: Path, engine: Engine):
        super().__init__(directory)
        self.engine = engine

    def _read(self) -> list[dict]:
        with Session(self.engine) as session:
            statement = select(ModelConfiguration).order_by(ModelConfiguration.updated_at)
            user = principal.get()
            if user: statement = statement.where(ModelConfiguration.owner_id == user['id'])
            return [row.as_dict() for row in session.scalars(statement)]

    def _cipher(self):
        with Session(self.engine) as session:
            any_config = session.scalar(select(ModelConfiguration.id).limit(1))
        if not self.key_path.exists() and any_config:
            raise HTTPException(503, "数据库已有配置但本机加密文件缺失，请恢复原加密文件。")
        return super()._cipher()

    def save(self, data: ConfigInput, config_id: str | None = None) -> ConfigView:
        with self.lock:
            key = self.resolve_key(config_id, data)
            cipher = self._cipher()
            with Session(self.engine) as session, session.begin():
                if config_id:
                    row = session.get(ModelConfiguration, config_id, with_for_update=True)
                    if row is None:
                        raise HTTPException(404, "配置不存在，请刷新列表。")
                    require_private(row)
                else:
                    row = ModelConfiguration(id=str(uuid4()))
                    session.add(row)
                row.name = data.name
                row.base_url = data.base_url
                row.model_name = data.model_name
                row.model_names = json.dumps(data.model_names, ensure_ascii=False)
                row.encrypted_key = cipher.encrypt(key.encode()).decode()
                row.updated_at = datetime.now(timezone.utc).isoformat()
                result = self.view(row.as_dict())
            return result


def import_file_configs(directory: Path, engine: Engine) -> int:
    legacy = FileConfigStore(directory)
    rows = legacy._read()
    if not rows:
        return 0
    # Check every ciphertext before writing; missing keys never get regenerated.
    cipher = legacy._cipher()
    for row in rows:
        cipher.decrypt(row["encrypted_key"].encode())
    imported = 0
    with Session(engine) as session, session.begin():
        for values in rows:
            values = {**values, 'model_names': json.dumps(configured_models(values), ensure_ascii=False)}
            row = session.get(ModelConfiguration, values["id"])
            if row is None:
                session.add(ModelConfiguration(**{column.name: values.get(column.name) for column in ModelConfiguration.__table__.columns}))
                imported += 1
            elif {key:value for key,value in row.as_dict().items() if key != 'owner_id'} != values:
                raise ValueError("数据库中已有相同 ID 的不同配置，迁移已取消，不会覆盖。")
    return imported


def storage_status(engine: Engine | None) -> dict:
    if engine is None:
        return {"storage": "file", "status": "ready", "message": "使用本机文件配置存储"}
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
            connection.execute(select(ModelConfiguration.id).limit(0))
            connection.execute(select(ImageJob.id).limit(0))
            connection.execute(select(CreativeTemplate.id).limit(0))
            connection.execute(select(CreativeCase.id).limit(0))
            connection.execute(select(Product.id).limit(0))
            connection.execute(select(ProductAsset.id).limit(0))
            connection.execute(select(CreativeSkill.id).limit(0))
            connection.execute(select(SkillRevision.skill_id).limit(0))
            connection.execute(select(SkillPackage.id).limit(0))
            connection.execute(select(SkillVersion.id).limit(0))
            connection.execute(select(AgentRun.id).limit(0))
            connection.execute(select(ProductImageProject.id).limit(0))
        return {"storage": "postgresql", "status": "ready", "message": "数据库连接、模型配置与生图任务表检查通过"}
    except Exception:
        return {"storage": "postgresql", "status": "unavailable", "message": "数据库未连接或表结构未就绪，请检查数据库并运行迁移。"}
