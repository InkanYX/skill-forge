import base64
import json
from unittest.mock import patch
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import ImageJob
from app.image_jobs import process_one
from app.image_provider import generate_image
from app.main import create_app
from test_image_jobs import setup, png, KEY


def multipart(values):
    return {key: (None, str(value)) for key, value in values.items()}


@pytest.mark.parametrize('size', ['0x2000', '-1x2000', '2.5x2000', '2000x', 'auto', '1e3x1000', '5000x4001', '999999999x1'])
def test_invalid_sizes_are_rejected_before_creating_jobs_or_templates(setup, size):
    engine, directory, config = setup
    with TestClient(create_app(directory, db_url=str(engine.url))) as client:
        values = {'config_id': config.id, 'request_id': str(uuid4()), 'prompt': 'scene', 'size': size, 'count': 1}
        for path in ['/api/image-jobs', '/api/image-jobs/batch']:
            assert client.post(path, files=multipart(values)).status_code == 422
        plan = {'name': 'set', 'shots': [{'name': 'valid', 'prompt': 'scene'}, {'name': 'invalid', 'prompt': 'scene', 'size': size}]}
        assert client.post('/api/image-jobs/sets', files=multipart({'config_id': config.id, 'request_id': str(uuid4()), 'plan': json.dumps(plan)})).status_code == 422
        assert client.post('/api/templates', json={'name': 'template', 'prompt': 'scene', 'size': size}).status_code == 422
        assert client.get('/api/templates').json() == []
    with Session(engine) as session:
        assert list(session.scalars(select(ImageJob))) == []


def test_custom_size_survives_template_batch_revision_and_set_flows(setup):
    engine, directory, config = setup
    with TestClient(create_app(directory, db_url=str(engine.url))) as client:
        template = client.post('/api/templates', json={'name': 'custom', 'prompt': 'scene', 'size': '2000 × 2000'}).json()
        assert template['size'] == '2000x2000'
        assert client.get('/api/templates').json()[0]['size'] == '2000x2000'
        fields = {'config_id': config.id, 'request_id': str(uuid4()), 'size': '02000x2000', 'count': 2, 'template': json.dumps({'id': template['id'], 'revision': template['revision'], 'variables': {}})}
        first = client.post('/api/image-jobs/batch', files=multipart(fields))
        assert first.status_code == 202
        jobs = first.json()
        assert all(item['size'] == '2000x2000' for item in jobs)
        fields['size'] = '2000x2000'
        assert [item['id'] for item in client.post('/api/image-jobs/batch', files=multipart(fields)).json()] == [item['id'] for item in jobs]
        fields['size'] = '2500x1600'
        assert client.post('/api/image-jobs/batch', files=multipart(fields)).status_code == 409
        seen = []
        def provider(url, key, model, prompt, size, reference):
            seen.append(size)
            return png()
        assert process_one(engine, directory, provider)
        assert process_one(engine, directory, provider)
        assert seen == ['2000x2000', '2000x2000']
        source = jobs[0]['id']
        revision = client.post('/api/image-jobs/batch', files=multipart({'config_id': config.id, 'request_id': str(uuid4()), 'source_job_id': source, 'prompt': 'evening', 'size': '2500x1600', 'count': 1}))
        assert revision.status_code == 202 and revision.json()[0]['size'] == '2500x1600'
        assert process_one(engine, directory, provider)
        plan = {'name': 'set', 'shots': [{'name': 'custom', 'prompt': 'scene', 'size': '5000x4000'}, {'name': 'auto', 'prompt': 'scene'}]}
        result = client.post('/api/image-jobs/sets', files=multipart({'config_id': config.id, 'request_id': str(uuid4()), 'plan': json.dumps(plan)}))
        assert result.status_code == 202
        assert [item['size'] for item in result.json()] == ['5000x4000', 'default']
        assert process_one(engine, directory, provider)
        assert process_one(engine, directory, provider)
        assert seen[-3:] == ['2500x1600', '5000x4000', 'default']
        assert client.get(f'/api/image-jobs/{source}').json()['size'] == '2000x2000'
        assert client.get(f'/api/image-jobs/{source}/image').content == png()


@pytest.mark.parametrize('reference', [False, True])
@pytest.mark.parametrize('size', ['default', '2000x2000'])
def test_provider_sends_custom_size_and_omits_automatic_size_without_resizing(reference, size):
    def handle(request):
        if reference:
            assert (b'name="size"' in request.content) == (size != 'default')
            if size != 'default':
                assert b'\r\n\r\n2000x2000\r\n' in request.content
        else:
            payload = json.loads(request.content)
            assert ('size' in payload) == (size != 'default')
            if size != 'default':
                assert payload['size'] == size
        return httpx.Response(200, json={'data': [{'b64_json': base64.b64encode(png()).decode()}]})
    real_client = httpx.Client
    with patch('app.image_provider.public_address', return_value='8.8.8.8'), patch('app.image_provider.httpx.Client', side_effect=lambda **kwargs: real_client(transport=httpx.MockTransport(handle), **kwargs)):
        assert generate_image('https://images.example.com/v1', KEY, 'image-test', 'scene', size, png() if reference else None) == png()
