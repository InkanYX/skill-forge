"""Bounded, redacted diagnostics. Never persist raw request headers or images."""
import html
import json
import re
from datetime import datetime, timezone
from urllib.parse import quote, quote_plus


def redact(value, secrets=(), limit=3000):
    # The first secret is the credential. Short prompts such as "1" must
    # not erase unrelated digits in an error code or response text. Request
    # fields are still removed structurally regardless of their length.
    secrets = tuple(secret for index, secret in enumerate(secrets) if secret and (index == 0 or len(secret) >= 8))
    text = str(value)
    for secret in sorted((value for value in secrets if value), key=len, reverse=True):
        for variant in {secret, json.dumps(secret)[1:-1], quote(secret, safe=''), quote_plus(secret)}:
            text = text.replace(variant, '[已隐藏]')
    text = re.sub(r'(?is)<(?:script|style)\b[^>]*>.*?</(?:script|style)>', '', text)
    text = html.unescape(re.sub(r'<[^>]{0,500}>', ' ', text))
    # Strip links (including signed query strings) and embedded image data.
    text = re.sub(r'https?://[^\s<>"\']+', '[链接已隐藏]', text, flags=re.I)
    text = re.sub(r'(?i)Bearer\s+[^\s,"\'}]+', 'Bearer [已隐藏]', text)
    text = re.sub(r'''(?ix)(["']?(?:api[_-]?key|access[_-]?token|authorization|password|secret|prompt|images?|input)["']?\s*[:=]\s*)("(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|[^\s,;}]+)''', r'\1"[已隐藏]"', text)
    text = re.sub(r'[A-Za-z0-9_+/=-]{160,}', '[长数据已隐藏]', text)
    text = ''.join(char for char in text if char in '\n\t' or ord(char) >= 32)
    # Decode/HTML removal may expose a previously escaped secret.
    for secret in secrets:
        if secret:
            text = text.replace(secret, '[已隐藏]')
    return text.strip().encode('utf-8', errors='replace').decode('utf-8')[:limit]


def diagnostic_context(path, phase, secrets, elapsed_ms, http_status=None, error_type='', message=''):
    return {
        'phase': phase, 'method': 'GET' if phase == 'download' else 'POST',
        'path': redact(path, secrets[:1], 500), 'http_status': http_status,
        'provider_message': redact(message, secrets), 'response_body': '', 'error_type': redact(error_type, secrets[:1], 160),
        'error_code': '', 'request_id': '', 'truncated': False,
        'elapsed_ms': elapsed_ms, 'recorded_at': datetime.now(timezone.utc).isoformat(),
    }


def safe_response_body(raw, secrets):
    sensitive = {'key', 'apikey', 'token', 'accesstoken', 'authorization', 'password', 'secret', 'prompt', 'image', 'images', 'input', 'messages', 'request', 'requestbody', 'headers', 'cookie', 'setcookie'}
    def scrub(value, depth=0):
        if depth > 6:
            return '[嵌套内容已省略]'
        if isinstance(value, dict):
            return {redact(key, secrets, 200): '[已隐藏]' if re.sub(r'[^a-z]', '', str(key).lower()) in sensitive else scrub(item, depth + 1) for key, item in list(value.items())[:50]}
        if isinstance(value, list):
            return [scrub(item, depth + 1) for item in value[:20]]
        return redact(value, secrets) if isinstance(value, str) else value
    try:
        safe = json.dumps(scrub(json.loads(raw)), ensure_ascii=False, indent=2)
        safe = safe.encode('utf-8', errors='replace').decode('utf-8')
    except ValueError:
        safe = redact(raw, secrets, 4001)
    return safe if len(safe) <= 4000 else safe[:4000] + '\n[已截断]'


def provider_diagnostic(response, path, phase, secrets, elapsed_ms):
    """Read only a short error response; successful image bodies are excluded."""
    content = bytearray()
    truncated = False
    try:
        for chunk in response.iter_bytes():
            room = 8192 - len(content)
            content.extend(chunk[:room])
            if len(chunk) > room:
                truncated = True
                break
    except Exception:
        truncated = True
    raw = content.decode('utf-8', errors='replace')
    response_body = safe_response_body(raw, secrets)
    error_type = error_code = ''
    try:
        payload = json.loads(raw)
        error = payload.get('error', payload) if isinstance(payload, dict) else None
        if isinstance(error, dict):
            message = error.get('message') or error.get('detail') or payload.get('message') or payload.get('detail')
            raw = message if isinstance(message, str) else '服务商返回了错误响应，未提供可展示的错误说明。'
            error_type = error.get('type', '')
            error_code = error.get('code', '')
        elif isinstance(error, str):
            raw = error
        else:
            raw = '服务商返回了错误响应，未提供可展示的错误说明。'
    except ValueError:
        pass
    request_id = response.headers.get('x-request-id') or response.headers.get('request-id') or response.headers.get('x-amzn-requestid') or ''
    return {
        'phase': phase, 'method': 'GET' if phase == 'download' else 'POST',
        'path': redact(path, secrets[:1], 500), 'http_status': response.status_code,
        'provider_message': redact(raw, secrets),
        'response_body': response_body,
        'error_type': redact(error_type, secrets[:1], 160), 'error_code': redact(error_code, secrets[:1], 160),
        'request_id': redact(request_id, secrets[:1], 200), 'truncated': truncated,
        'elapsed_ms': elapsed_ms, 'recorded_at': datetime.now(timezone.utc).isoformat(),
    }
