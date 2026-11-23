"""Local-development configuration storage and OpenAI-compatible model discovery."""

import ipaddress
import json
import os
import socket
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

import httpx
from cryptography.fernet import Fernet, InvalidToken
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator


class ConfigInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(default="我的模型接口", min_length=1, max_length=80)
    base_url: str = Field(min_length=1, max_length=2048)
    api_key: SecretStr | None = None
    model_name: str = Field(default="", max_length=200)
    model_names: list[str] = Field(default_factory=list, max_length=50)

    @field_validator('model_names')
    @classmethod
    def valid_models(cls, values):
        names = []
        for value in values:
            value = value.strip()
            if not value or len(value) > 200 or any(ord(char) < 32 for char in value):
                raise ValueError('每个模型 ID 需为 1–200 字符，且不能包含换行等控制字符。')
            if value not in names:
                names.append(value)
        return names

    @model_validator(mode='after')
    def default_model(self):
        if not self.model_names:
            self.model_names = [self.model_name] if self.model_name else []
        elif not self.model_name:
            self.model_name = self.model_names[0]
        elif self.model_name not in self.model_names:
            raise ValueError('默认模型必须在已选模型中。')
        return self

    @field_validator("name", "model_name", mode="before")
    @classmethod
    def trim_text(cls, value):
        return value.strip() if isinstance(value, str) else value

    @field_validator("base_url")
    @classmethod
    def normalize_url(cls, value: str) -> str:
        try:
            parsed = urlsplit(value.strip())
            if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
                raise ValueError()
            if parsed.query or parsed.fragment or parsed.port not in (None, 443):
                raise ValueError()
            host = parsed.hostname.encode("idna").decode("ascii").lower()
            try:
                address = ipaddress.ip_address(host)
            except ValueError:
                if host == "localhost" or host.endswith((".localhost", ".local")):
                    raise ValueError()
            else:
                if not address.is_global or address.version != 4:
                    raise ValueError()
            path = parsed.path.rstrip("/") or "/v1"
            if path.endswith(("/models", "/responses", "/completions", "/generations", "/edits")):
                raise ValueError()
            return urlunsplit(("https", host, path, "", ""))
        except (ValueError, UnicodeError):
            raise ValueError("请填写服务商公开的 HTTPS Base URL（443 端口），例如 https://api.example.com/v1；不要填写具体接口路径。") from None

    @field_validator("api_key")
    @classmethod
    def valid_key(cls, value: SecretStr | None) -> SecretStr | None:
        if value is None:
            return None
        raw = value.get_secret_value().strip()
        if not raw:
            return None
        if len(raw) > 4096 or any(ord(char) < 33 or ord(char) > 126 for char in raw):
            raise ValueError("密钥应为不含空白的 ASCII 字符。")
        return SecretStr(raw)


class TestInput(ConfigInput):
    config_id: str | None = None


class ConfigView(BaseModel):
    id: str
    name: str
    base_url: str
    model_name: str
    model_names: list[str] = Field(default_factory=list)
    has_api_key: bool
    updated_at: str


class ConnectionResult(BaseModel):
    status: str
    message: str


class ProbeResult(ConnectionResult):
    models: list[str] = Field(default_factory=list)


def configured_models(row) -> list[str]:
    """Read both legacy single-model records and the persisted model list."""
    value = row.get('model_names', []) if isinstance(row, dict) else row.model_names
    if isinstance(value, str):
        value = json.loads(value)
    default = row.get('model_name', '') if isinstance(row, dict) else row.model_name
    return value or ([default] if default else [])


class FileConfigStore:
    """Replaceable single-process store. No user key is returned to clients."""

    def __init__(self, directory: Path):
        self.directory = directory
        self.path = directory / "model-configs.json"
        self.key_path = directory / "config-encryption.key"
        self.lock = RLock()

    def _cipher(self) -> Fernet:
        self.directory.mkdir(parents=True, exist_ok=True)
        if not self.key_path.exists():
            if self.path.exists():
                raise HTTPException(503, "加密文件缺失，请恢复原加密文件；不会覆盖已有配置。")
            try:
                with self.key_path.open("xb") as handle:
                    handle.write(Fernet.generate_key())
                self.key_path.chmod(0o600)
            except FileExistsError:
                pass
        try:
            return Fernet(self.key_path.read_bytes())
        except (ValueError, OSError):
            raise HTTPException(503, "无法读取配置加密文件，请检查本机数据目录。") from None

    def _read(self) -> list[dict]:
        if not self.path.exists():
            return []
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(value, list) or any(not isinstance(row, dict) for row in value):
                raise ValueError()
            for row in value:
                ConfigView.model_validate({**row, 'model_names': configured_models(row), "has_api_key": bool(row.get("encrypted_key"))})
                if not isinstance(row.get("encrypted_key"), str):
                    raise ValueError()
            return value
        except (ValueError, OSError):
            raise HTTPException(503, "配置文件无法读取，请检查或恢复备份；原文件未被覆盖。") from None

    @staticmethod
    def view(row: dict) -> ConfigView:
        return ConfigView(**{key: row[key] for key in ("id", "name", "base_url", "model_name", "updated_at")}, model_names=configured_models(row), has_api_key=bool(row["encrypted_key"]))

    def list(self) -> list[ConfigView]:
        with self.lock:
            return [self.view(row) for row in self._read()]

    def _find(self, config_id: str) -> dict:
        for row in self._read():
            if row["id"] == config_id:
                return row
        raise HTTPException(404, "配置不存在，请刷新列表。")

    def resolve_key(self, config_id: str | None, data: ConfigInput) -> str:
        with self.lock:
            row = self._find(config_id) if config_id else None
            if data.api_key:
                return data.api_key.get_secret_value()
            if row is None:
                raise HTTPException(422, "新配置需要填写 API Key。")
            if row["base_url"] != data.base_url:
                raise HTTPException(422, "接口地址已改变，请重新填写密钥，避免向新地址发送原密钥。")
            try:
                return self._cipher().decrypt(row["encrypted_key"].encode()).decode()
            except (InvalidToken, UnicodeError):
                raise HTTPException(503, "无法解密密钥，请恢复对应加密文件或重新填写密钥。") from None

    def save(self, data: ConfigInput, config_id: str | None = None) -> ConfigView:
        with self.lock:
            key = self.resolve_key(config_id, data)
            rows = self._read()
            row = {
                "id": config_id or str(uuid4()),
                "name": data.name,
                "base_url": data.base_url,
                "model_name": data.model_name,
                "model_names": data.model_names,
                "encrypted_key": self._cipher().encrypt(key.encode()).decode(),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
            rows = [item for item in rows if item["id"] != row["id"]] + [row]
            descriptor, temporary = tempfile.mkstemp(dir=self.directory, suffix=".tmp")
            try:
                with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                    json.dump(rows, handle, ensure_ascii=False, indent=2)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary, self.path)
                self.path.chmod(0o600)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
            return self.view(row)


def public_address(host: str) -> str:
    """Resolve before sending credentials and pin the request to a public IPv4."""
    try:
        records = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    except OSError:
        raise HTTPException(502, "无法解析服务商地址，请检查 URL 和网络。") from None
    addresses = [ipaddress.ip_address(record[4][0]) for record in records]
    if not addresses or any(not address.is_global for address in addresses):
        raise HTTPException(422, "接口地址必须指向公网服务，不支持本机或内网地址。")
    for address in addresses:
        if address.version == 4:
            return str(address)
    raise HTTPException(422, "首版连接测试需要服务商提供公网 IPv4 地址。")


def probe_connection(base_url: str, api_key: str) -> ConnectionResult:
    """Check response headers without downloading or parsing a model list."""
    original = httpx.URL(base_url + '/models')
    address = public_address(original.host)
    target = original.copy_with(host=address)
    try:
        with httpx.Client(timeout=httpx.Timeout(15, connect=8), follow_redirects=False, trust_env=False) as client:
            with client.stream('GET', target, headers={'Authorization': f'Bearer {api_key}', 'Host': original.host}, extensions={'sni_hostname': original.host}) as response:
                status = response.status_code
                if status == 200:
                    return ConnectionResult(status='ok', message='接口已响应（HTTP 200）。未读取模型列表，也未验证具体模型的生图或编辑能力。')
                if status in (401, 403):
                    return ConnectionResult(status='error', message='认证或访问权限校验失败，请检查 API Key 及接口权限。')
                if status in (404, 405):
                    return ConnectionResult(status='unsupported', message='服务商已响应，但未提供兼容的 /models 接口，暂时无法通过此方式验证配置；可手动添加模型。')
                if status == 429:
                    return ConnectionResult(status='error', message='服务商请求限流，请稍后重试。')
                return ConnectionResult(status='error', message=f'服务商返回 HTTP {status}，请检查地址和服务状态。')
    except httpx.TimeoutException:
        return ConnectionResult(status='error', message='连接超时，请检查服务商地址与网络。')
    except httpx.HTTPError:
        return ConnectionResult(status='error', message='连接失败，请检查网络、HTTPS 证书与服务商地址。')


def probe_models(base_url: str, api_key: str) -> ProbeResult:
    original = httpx.URL(base_url + "/models")
    address = public_address(original.host)
    # SNI/certificate verification retains the original host; DNS cannot rebind
    # the outbound socket to an internal address between validation and sending.
    target = original.copy_with(host=address)
    try:
        with httpx.Client(timeout=httpx.Timeout(15, connect=8), follow_redirects=False, trust_env=False) as client:
            with client.stream("GET", target, headers={"Authorization": f"Bearer {api_key}", "Host": original.host}, extensions={"sni_hostname": original.host}) as response:
                if response.status_code in (401, 403):
                    return ProbeResult(status="error", message="认证或权限校验失败，请检查密钥及模型列表访问权限。")
                if response.status_code in (404, 405):
                    return ProbeResult(status="unsupported", message="服务商未提供兼容的模型列表接口，可手动填写模型名称并保存；连接与生图能力尚未验证。")
                if response.status_code == 429:
                    return ProbeResult(status="error", message="服务商请求限流，请稍后重试。")
                if response.status_code != 200:
                    return ProbeResult(status="error", message=f"服务商返回 HTTP {response.status_code}，未验证连接；请检查地址和服务状态。")
                content = bytearray()
                for chunk in response.iter_bytes():
                    content.extend(chunk)
                    if len(content) > 2 * 1024 * 1024:
                        return ProbeResult(status="error", message="服务商响应过大，无法读取模型列表。")
                payload = json.loads(content)
        rows = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(rows, list):
            raise ValueError()
        models = sorted({row["id"] for row in rows if isinstance(row, dict) and isinstance(row.get("id"), str) and 0 < len(row["id"]) <= 200})[:1000]
        return ProbeResult(status="ok", message="已成功读取模型列表。此测试不验证具体模型的生图或编辑能力。", models=models)
    except httpx.TimeoutException:
        return ProbeResult(status="error", message="连接超时，请检查服务商地址与网络。")
    except httpx.HTTPError:
        return ProbeResult(status="error", message="连接失败，请检查网络、HTTPS 证书与服务商地址。")
    except (ValueError, UnicodeError):
        return ProbeResult(status="unsupported", message="服务商响应不符合模型列表格式，可手动填写模型名称；连接能力尚未验证。")


def build_router(store: FileConfigStore, probe=probe_models, connection_probe=probe_connection) -> APIRouter:
    router = APIRouter(prefix="/api/model-configs", tags=["model-configs"])

    @router.get("", response_model=list[ConfigView])
    def list_configs():
        return store.list()

    @router.post("/test", response_model=ConnectionResult)
    def test_config(data: TestInput):
        return connection_probe(data.base_url, store.resolve_key(data.config_id, data))

    @router.post('/models', response_model=ProbeResult)
    def read_models(data: TestInput):
        return probe(data.base_url, store.resolve_key(data.config_id, data))

    @router.post("", response_model=ConfigView, status_code=201)
    def create_config(data: ConfigInput):
        return store.save(data)

    @router.put("/{config_id}", response_model=ConfigView)
    def update_config(config_id: str, data: ConfigInput):
        return store.save(data, config_id)

    return router
