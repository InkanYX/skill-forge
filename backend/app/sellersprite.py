"""Shared, server-only SellerSprite credentials and bounded Streamable HTTP MCP."""
import json
import os
import time
from contextlib import AbstractContextManager
from pathlib import Path

import httpx
from dotenv import dotenv_values

ENDPOINT = 'https://mcp.sellersprite.com/v2/mcp'
ALLOWED_TOOLS = frozenset(('asin.detail', 'asin.content.list', 'asin.review.list'))
MAX_RESPONSE_BYTES = 6 * 1024 * 1024


class ResearchError(Exception):
    def __init__(self, message, uncertain=False, auth=False, diagnostic=None):
        super().__init__(message)
        self.message, self.uncertain, self.auth = message, uncertain, auth
        self.diagnostic = diagnostic or {}


def shared_key():
    # Production uses its protected deployment environment; development uses backend/.env.
    path = Path(os.environ.get('SKILL_FORGE_DEPLOYMENT_ENV') or Path(__file__).resolve().parents[1] / '.env')
    return os.environ.get('SELLERSPRITE_MCP_SECRET_KEY') or dotenv_values(path).get('SELLERSPRITE_MCP_SECRET_KEY') or ''


def service_status():
    return {'name': 'ss_mcp', 'configured': bool(shared_key()), 'shared': True,
            'transport': 'streamable_http', 'max_asins': 5, 'max_reviews': 200,
            'review_scope': 'parent', 'tools': sorted(ALLOWED_TOOLS)}


def _decode(response, expected_id=None, partial=False):
    if response.status_code in (401, 403):
        raise ResearchError('卖家精灵鉴权或权限被拒绝，请联系管理员检查公共密钥和额度。', auth=True)
    if response.status_code >= 400:
        raise ResearchError(f'卖家精灵请求失败（HTTP {response.status_code}），未自动重发。',
                            uncertain=response.status_code >= 500)
    if 'text/event-stream' not in response.headers.get('content-type', ''):
        return response.json()
    for event in response.text.replace('\r\n', '\n').split('\n\n'):
        data = '\n'.join(line[5:].lstrip() for line in event.splitlines() if line.startswith('data:'))
        if data:
            value = json.loads(data)
            if ('result' in value or 'error' in value) and (expected_id is None or value.get('id') == expected_id):
                return value
    if partial:
        return None
    raise ResearchError('卖家精灵未返回有效 MCP 结果；未自动重发。', uncertain=True)


class SellerSpriteClient(AbstractContextManager):
    endpoint = ENDPOINT
    allowed_tools = ALLOWED_TOOLS
    def __init__(self, key=None, transport=None):
        key = key if key is not None else shared_key()
        if not key:
            raise ResearchError('管理员尚未配置公共卖家精灵 MCP。')
        self.headers = {'secret-key': key, 'Accept': 'application/json, text/event-stream'}
        self.client = httpx.Client(timeout=httpx.Timeout(150, connect=15), follow_redirects=False, transport=transport)
        self.sequence = 0

    def _post(self, payload, notification=False):
        started = time.monotonic()
        business = payload['method'] == 'tools/call'
        phase = 'query' if business else 'initialize' if payload['method'] == 'initialize' else 'handshake'
        status = None
        try:
            with self.client.stream('POST', self.endpoint, headers=self.headers, json=payload) as response:
                status = response.status_code
                if response.headers.get('mcp-session-id'):
                    self.headers['Mcp-Session-Id'] = response.headers['mcp-session-id']
                if notification and response.status_code < 400:
                    return {}
                body = bytearray()
                for chunk in response.iter_bytes():
                    body.extend(chunk)
                    if len(body) > MAX_RESPONSE_BYTES:
                        raise ResearchError('卖家精灵结果超过读取上限，未重复请求。', uncertain=business)
                    # An SSE response may stay open after the matching RPC result.
                    # Stop at that result instead of waiting for the stream to close.
                    if 'text/event-stream' in response.headers.get('content-type', '') and b'\n\n' in body.replace(b'\r\n', b'\n'):
                        complete = body.replace(b'\r\n', b'\n').rsplit(b'\n\n', 1)[0]
                        candidate = _decode(httpx.Response(status, headers={'content-type': 'text/event-stream'}, content=bytes(complete) + b'\n\n'), expected_id=payload.get('id'), partial=True)
                        if candidate is not None:
                            value = candidate
                            break
                else:
                    # iter_bytes already decompresses gzip/deflate. Copying the
                    # Content-Encoding header here would decode the same bytes twice.
                    value = _decode(httpx.Response(status, headers={'content-type': response.headers.get('content-type', '')}, content=bytes(body)), expected_id=payload.get('id'))
        except ResearchError as error:
            error.diagnostic = {'phase': phase, 'http_status': status, 'elapsed_seconds': round(time.monotonic() - started, 2), **error.diagnostic}
            if not business:
                error.uncertain = False
            raise
        except ResearchError as error:
            error.diagnostic = {'phase': phase, 'http_status': status, 'elapsed_seconds': round(time.monotonic() - started, 2), **error.diagnostic}
            if not business:
                error.uncertain = False
            raise
        except (httpx.ConnectTimeout, httpx.ConnectError) as error:
            raise ResearchError('无法连接卖家精灵 MCP，请检查服务器网络、代理和证书；尚未提交本次业务查询。',
                                diagnostic={'phase': phase, 'error_type': type(error).__name__, 'http_status': status}) from None
        except httpx.DecodingError:
            raise ResearchError('卖家精灵压缩响应解析失败，未重复请求。' + ('查询结果待确认。' if business else '尚未开始业务查询。'),
                                uncertain=business, diagnostic={'phase': phase, 'error_type': 'response_decoding', 'http_status': status}) from None
        except httpx.HTTPError as error:
            message = '卖家精灵查询响应超时或连接中断；可能已扣额度，未自动重发。' if business else '卖家精灵握手响应超时或连接中断，尚未开始业务查询。'
            raise ResearchError(message, uncertain=business, diagnostic={'phase': phase, 'error_type': type(error).__name__,
                                'http_status': status, 'elapsed_seconds': round(time.monotonic() - started, 2)}) from None
        except (ValueError, KeyError):
            raise ResearchError('卖家精灵返回格式异常，未自动重发。', uncertain=business,
                                diagnostic={'phase': phase, 'error_type': 'invalid_response', 'http_status': status}) from None
        if not isinstance(value, dict) or value.get('id') != payload.get('id'):
            raise ResearchError('卖家精灵响应未匹配本次请求，未自动重发。', uncertain=business)
        if value.get('error'):
            # Do not reflect provider bodies, URLs or credentials into project records.
            error_text = str(value['error']).lower()
            auth = any(term in error_text for term in ('401', '403', 'unauthorized', 'forbidden', 'permission', '鉴权', '权限'))
            raise ResearchError('卖家精灵 MCP 返回错误，请检查账号权限和查询条件。', auth=auth)
        return value.get('result', {})

    def __enter__(self):
        try:
            result = self._post({'jsonrpc': '2.0', 'id': 0, 'method': 'initialize', 'params': {
                'protocolVersion': '2025-03-26', 'capabilities': {},
                'clientInfo': {'name': 'skill-forge', 'version': '1.0'}}})
            self.headers['MCP-Protocol-Version'] = result.get('protocolVersion', '2025-03-26')
            self._post({'jsonrpc': '2.0', 'method': 'notifications/initialized'}, notification=True)
            return self
        except Exception:
            self.client.close()
            raise

    def call(self, name, arguments):
        if name not in self.allowed_tools:
            raise ResearchError('此调研工具未启用。')
        self.sequence += 1
        result = self._post({'jsonrpc': '2.0', 'id': self.sequence, 'method': 'tools/call',
                             'params': {'name': name, 'arguments': arguments}})
        if result.get('isError'):
            error_text = str(result.get('content', '')).lower()
            auth = any(term in error_text for term in ('401', '403', 'unauthorized', 'forbidden', 'permission', '鉴权', '权限'))
            raise ResearchError('卖家精灵查询未完成，请核对 ASIN、站点和账号额度；未自动重试。', auth=auth)
        if isinstance(result.get('structuredContent'), (dict, list)):
            data = result['structuredContent']
        else:
            text = '\n'.join(item.get('text', '') for item in result.get('content', []) if item.get('type') == 'text')
            try:
                data = json.loads(text)
            except ValueError:
                raise ResearchError('卖家精灵未返回可分析的数据，未自动重试。', uncertain=True) from None
        if isinstance(data, dict) and (data.get('success') is False or data.get('code') in (401, 403, '401', '403')):
            raise ResearchError('卖家精灵业务查询未成功，请检查权限、额度及查询条件。',
                                auth=data.get('code') in (401, 403, '401', '403'))
        return data

    def __exit__(self, *args):
        self.client.close()
