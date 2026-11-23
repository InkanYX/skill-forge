import json
from unittest.mock import patch
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.database import ImageJob
from app.image_jobs import process_one
from app.image_provider import GenerationError, generate_image
from app.main import create_app
from app.provider_diagnostics import redact, provider_diagnostic, diagnostic_context
from test_image_jobs import setup, enqueue, png, KEY


def test_upstream_error_is_saved_redacted_visible_after_restart_and_never_retried(setup):
    engine, directory, _ = setup
    job = enqueue(setup, png())
    calls = []
    def handle(request):
        calls.append(request)
        return httpx.Response(404, headers={'x-request-id': 'trace-example'}, json={'error': {'message': f'Model route not found. Bearer {KEY}; https://example.com/?token=private-token; prompt: 保留结构，生成庭院场景', 'type': 'route_error', 'code': 'model_not_found'}, 'request': {'api_key': KEY, 'image': 'private-image-data'}})
    real_client = httpx.Client
    with patch('app.image_provider.public_address', return_value='8.8.8.8'), patch('app.image_provider.httpx.Client', side_effect=lambda **kwargs: real_client(transport=httpx.MockTransport(handle), **kwargs)):
        assert process_one(engine, directory)
        assert not process_one(engine, directory)
    assert len(calls) == 1
    with Session(engine) as session:
        row = session.get(ImageJob, job.id)
        assert row.status == 'failed' and row.encrypted_key == ''
        assert KEY not in row.provider_diagnostic and 'private-image-data' not in row.provider_diagnostic and 'private-token' not in row.provider_diagnostic
    with TestClient(create_app(directory, db_url=str(engine.url))) as client:
        result = client.get(f'/api/image-jobs/{job.id}/diagnostics')
        assert result.status_code == 200
        log = result.json()['diagnostic']
        assert log['http_status'] == 404 and log['path'] == '/v1/images/edits'
        assert log['method'] == 'POST' and log['phase'] == 'edit'
        assert log['error_code'] == 'model_not_found' and log['request_id'] == 'trace-example'
        assert 'Model route not found' in log['provider_message']
        body = json.loads(log['response_body'])
        assert body['error']['code'] == 'model_not_found' and body['error']['type'] == 'route_error'
        assert body['request'] == '[已隐藏]'
        assert KEY not in result.text and 'private-token' not in result.text
        assert 'diagnostic' not in client.get('/api/image-jobs').json()[0]
        assert client.get(f'/api/image-jobs/{uuid4()}/diagnostics').status_code == 404
        assert client.get(f'/api/image-jobs/{job.id}/diagnostics', headers={'Origin': 'https://bad.example'}).status_code == 403


def test_old_job_without_response_log_remains_readable(setup):
    engine, directory, _ = setup
    job = enqueue(setup)
    with Session(engine) as session, session.begin():
        row = session.get(ImageJob, job.id)
        row.status = 'failed'
        row.message = '旧版错误摘要'
    with TestClient(create_app(directory, db_url=str(engine.url))) as client:
        value = client.get(f'/api/image-jobs/{job.id}/diagnostics').json()
        assert value['summary'] == '旧版错误摘要' and value['diagnostic'] is None


def test_error_body_is_bounded_and_html_is_plain_text():
    real_client = httpx.Client
    def handle(request):
        return httpx.Response(502, text='<html><script>secret script</script><h1>Bad gateway</h1>' + 'x ' * 10000 + KEY)
    with patch('app.image_provider.public_address', return_value='8.8.8.8'), patch('app.image_provider.httpx.Client', side_effect=lambda **kwargs: real_client(transport=httpx.MockTransport(handle), **kwargs)):
        with pytest.raises(GenerationError) as caught:
            generate_image('https://example.com/v1', KEY, 'image-test', 'scene', 'default', None)
    log = caught.value.diagnostic
    assert log['http_status'] == 502 and log['truncated'] and len(log['provider_message']) <= 3000
    assert 'Bad gateway' in log['provider_message'] and '<html>' not in log['provider_message'] and 'secret script' not in log['provider_message']


def test_timeout_diagnostic_has_no_response_status_and_no_exception_credentials():
    real_client = httpx.Client
    def handle(request):
        raise httpx.ReadTimeout(KEY, request=request)
    with patch('app.image_provider.public_address', return_value='8.8.8.8'), patch('app.image_provider.httpx.Client', side_effect=lambda **kwargs: real_client(transport=httpx.MockTransport(handle), **kwargs)):
        with pytest.raises(GenerationError) as caught:
            generate_image('https://example.com/v1', KEY, 'image-test', 'scene', 'default', None)
    assert caught.value.uncertain
    assert caught.value.diagnostic['http_status'] is None
    assert caught.value.diagnostic['error_type'] == 'ReadTimeout'
    assert KEY not in json.dumps(caught.value.diagnostic)


def test_redaction_handles_encoded_keys_embedded_images_and_unsafe_unicode():
    secret = 'a-key<&special>'
    value = 'a-key&lt;&amp;special&gt; Bearer unknown-token api_key="other-key" image="private-image" https://example.com/?token=secret ' + 'A' * 200 + '\ud800'
    safe = redact(value, (secret,))
    assert secret not in safe and 'unknown-token' not in safe and 'other-key' not in safe and 'private-image' not in safe
    assert 'token=secret' not in safe and 'A' * 200 not in safe
    safe.encode('utf-8')


def test_short_prompt_does_not_corrupt_paths_ids_or_error_codes():
    request_id = '4dd11e9bf34ffd9ad0fecc37f80af4ed'
    response = httpx.Response(404, headers={'x-request-id': request_id}, json={'error': {'message': 'route v1 not found', 'code': 'route_v1'}, 'prompt': '1', 'api_key': KEY})
    log = provider_diagnostic(response, '/v1/images/generations', 'generate', (KEY, '1'), 10)
    assert log['path'] == '/v1/images/generations'
    assert log['request_id'] == request_id and log['error_code'] == 'route_v1'
    body = json.loads(log['response_body'])
    assert body['error']['message'] == 'route v1 not found'
    assert body['prompt'] == '[已隐藏]' and body['api_key'] == '[已隐藏]'
    assert KEY not in json.dumps(log)
    context = diagnostic_context('/v1/images/edits', 'edit', (KEY, '1'), 10, error_type='HTTP1Error')
    assert context['path'] == '/v1/images/edits' and context['error_type'] == 'HTTP1Error'
