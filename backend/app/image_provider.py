"""Bounded Images API adapter. Never retries paid requests automatically."""
import base64
import binascii
import io
import json
import time
import warnings
from urllib.parse import urlsplit

import httpx
from fastapi import HTTPException
from PIL import Image, ImageOps, UnidentifiedImageError

from app.model_configs import public_address
from app.provider_diagnostics import provider_diagnostic, diagnostic_context

MAX_IMAGE = 20 * 1024 * 1024
MAX_PIXELS = 20_000_000


class GenerationError(Exception):
    def __init__(self, message: str, uncertain: bool = False, diagnostic: dict | None = None):
        super().__init__(message)
        self.message = message
        self.uncertain = uncertain
        self.diagnostic = diagnostic or {}


def normalize_image(content: bytes) -> bytes:
    if not content or len(content) > MAX_IMAGE:
        raise GenerationError("图片为空或超过 20 MB。")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(content)) as image:
                if image.format not in ("PNG", "JPEG", "WEBP") or image.width * image.height > MAX_PIXELS:
                    raise GenerationError("请使用不超过 2000 万像素的 PNG、JPEG 或 WebP 图片。")
                image.load()
                image = ImageOps.exif_transpose(image).convert("RGBA" if "A" in image.getbands() else "RGB")
                output = io.BytesIO()
                image.save(output, format="PNG")
                value = output.getvalue()
                if len(value) > MAX_IMAGE:
                    raise GenerationError("图片转换后超过 20 MB，请先缩小图片。")
                return value
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError, Image.DecompressionBombWarning, ValueError):
        raise GenerationError("无法读取图片，请使用有效的 PNG、JPEG 或 WebP。") from None


def pinned_url(value: str):
    try:
        parsed = urlsplit(value)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.port not in (None, 443):
            raise ValueError()
        original = httpx.URL(value)
    except ValueError:
        raise GenerationError("服务商返回了不支持的图片地址；仅支持公开 HTTPS 下载。", True) from None
    return original.copy_with(host=public_address(original.host)), {"Host": original.host}, {"sni_hostname": original.host}


def read_bounded(response, limit: int, deadline: float) -> bytes:
    value = bytearray()
    for chunk in response.iter_bytes():
        value.extend(chunk)
        if len(value) > limit or time.monotonic() > deadline:
            raise GenerationError("服务商响应过大或超时，请核对服务商记录。", True)
    return bytes(value)


def generate_image(base_url: str, api_key: str, model: str, prompt: str, size: str, reference: bytes | None) -> bytes:
    started = time.monotonic()
    endpoint = base_url + ("/images/edits" if reference else "/images/generations")
    phase, path, response_status = ('edit' if reference else 'generate'), urlsplit(endpoint).path, None
    parameters = {"model": model, "prompt": prompt, "n": 1}
    if size != "default":
        parameters["size"] = size
    request_args = {"data": {key: str(value) for key, value in parameters.items()}, "files": {"image": ("reference.png", reference, "image/png")}} if reference else {"json": parameters}
    try:
        target, headers, extensions = pinned_url(endpoint)
        headers["Authorization"] = f"Bearer {api_key}"
        deadline = time.monotonic() + 300
        with httpx.Client(timeout=httpx.Timeout(300, connect=8), follow_redirects=False, trust_env=False) as client:
            with client.stream("POST", target, headers=headers, extensions=extensions, **request_args) as response:
                response_status = response.status_code
                if response.status_code != 200:
                    diagnostic = provider_diagnostic(response, urlsplit(endpoint).path, 'edit' if reference else 'generate', (api_key, prompt), int((time.monotonic() - started) * 1000))
                if response.status_code in (400, 401, 403, 404, 405, 422, 429):
                    messages = {400: "模型、参数或参考图不受支持。", 401: "密钥认证失败。", 403: "接口或模型权限不足。", 404: "服务商返回 HTTP 404：接口路径或模型路由未找到，请查看调用日志核对。", 405: "服务商不支持此请求方式。", 422: "服务商不支持当前参数。", 429: "服务商限流，请稍后手动提交。"}
                    raise GenerationError(messages[response.status_code], diagnostic=diagnostic)
                if response.status_code != 200:
                    raise GenerationError(f"服务商返回 HTTP {response.status_code}，请核对服务商记录；未自动重试。", True, diagnostic)
                payload = json.loads(read_bounded(response, 40 * 1024 * 1024, deadline))
            rows = payload.get("data") if isinstance(payload, dict) else None
            if not isinstance(rows, list) or not rows or not isinstance(rows[0], dict):
                raise GenerationError("服务商未返回同步 Images 图片结果，可能使用其他协议或异步任务；请核对服务商记录。", True)
            first = rows[0]
            if isinstance(first.get("b64_json"), str):
                content = base64.b64decode(first["b64_json"], validate=True)
            elif isinstance(first.get("url"), str):
                # Never forward the provider credential to an image CDN.
                phase, path, response_status = 'download', '[图片下载地址已隐藏]', None
                download, download_headers, download_extensions = pinned_url(first["url"])
                with client.stream("GET", download, headers=download_headers, extensions=download_extensions, timeout=60) as response:
                    response_status = response.status_code
                    if response.status_code != 200:
                        diagnostic = provider_diagnostic(response, '[图片下载地址已隐藏]', 'download', (api_key, prompt), int((time.monotonic() - started) * 1000))
                        raise GenerationError("服务商已返回图片地址，但下载失败；请核对记录，勿直接重复生成。", True, diagnostic)
                    content = read_bounded(response, MAX_IMAGE, time.monotonic() + 60)
            else:
                raise GenerationError("服务商未返回有效图片内容，请核对服务商记录。", True)
        try:
            return normalize_image(content)
        except GenerationError:
            raise GenerationError("服务商返回了无效或过大的图片；请核对服务商记录。", True) from None
    except GenerationError as error:
        if not error.diagnostic:
            error.diagnostic = diagnostic_context(path, phase, (api_key, prompt), int((time.monotonic() - started) * 1000), response_status, 'GenerationError', error.message)
        raise
    except HTTPException:
        message = '服务商已接受请求，但图片下载地址不可用；请核对服务商记录，未自动重试。' if phase == 'download' else '服务商地址验证失败，未发送生图请求。'
        diagnostic = diagnostic_context(path, phase, (api_key, prompt), int((time.monotonic() - started) * 1000), response_status, 'AddressValidationError', message)
        raise GenerationError(message, phase == 'download', diagnostic) from None
    except (httpx.HTTPError, ValueError, binascii.Error) as error:
        message = '连接中断、超时或返回格式异常，结果无法确认；请核对服务商记录，未自动重试。'
        diagnostic = diagnostic_context(path, phase, (api_key, prompt), int((time.monotonic() - started) * 1000), response_status, type(error).__name__, message)
        raise GenerationError(message, True, diagnostic) from None
