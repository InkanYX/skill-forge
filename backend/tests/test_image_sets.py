import json
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import ImageJob
from app.image_jobs import process_one
from app.image_provider import GenerationError
from app.main import create_app
from test_image_jobs import setup, png, KEY


def multipart(values):
    return {key: (None, str(value)) for key, value in values.items()}


def plan():
    return {'name': '凉棚展示套图', 'shots': [{'name': '场景展示', 'prompt': '庭院自然光场景', 'size': '1536x1024'}, {'name': '结构细节', 'prompt': '只展示真实连接结构', 'size': '1024x1024'}, {'name': '尺寸说明', 'prompt': '不虚构尺寸', 'size': 'default'}]}


def test_set_uses_individual_briefs_sizes_and_idempotency(setup):
    engine, directory, config = setup
    identifier = str(uuid4())
    with TestClient(create_app(directory, db_url=str(engine.url))) as client:
        values = {'config_id': config.id, 'request_id': identifier, 'prompt': '整套保持灰色产品结构', 'plan': json.dumps(plan())}
        def submit():
            return client.post('/api/image-jobs/sets', files={**multipart(values), 'reference': ('photo.png', png(), 'image/png')})
        response = submit()
        assert response.status_code == 202
        rows = response.json()
        assert len(rows) == 3 and all(row['set_id'] == identifier for row in rows)
        assert [row['shot_index'] for row in rows] == [0, 1, 2]
        assert [row['size'] for row in rows] == [shot['size'] for shot in plan()['shots']]
        assert len({row['prompt'] for row in rows}) == 3
        assert all('整套保持灰色产品结构' in row['prompt'] for row in rows)
        assert [row['id'] for row in submit().json()] == [row['id'] for row in rows]
        modified = plan(); modified['shots'][1]['prompt'] = '另一种结构要求'
        values['plan'] = json.dumps(modified)
        assert submit().status_code == 409
        calls = []
        def provider(*args):
            calls.append(args)
            assert args[-1] == png()
            if len(calls) == 2:
                raise GenerationError('此张未完成')
            return png()
        for _ in range(3):
            assert process_one(engine, directory, provider)
        assert not process_one(engine, directory, provider)
        result = client.get(f'/api/image-jobs/sets/{identifier}').json()
        assert result['name'] == plan()['name'] and len(result['items']) == 3
        assert [row['status'] for row in result['items']] == ['succeeded', 'failed', 'succeeded']
        assert KEY not in str(result)
        assert client.get('/api/image-jobs/library', params={'q': plan()['name']}).json()['total'] == 2
        assert client.get('/api/image-jobs/library', params={'status': 'all', 'q': '结构细节'}).json()['total'] == 1


@pytest.mark.parametrize('invalid', [[], {'name': '套图', 'shots': []}, {'name': '套图', 'shots': [{'name': ' ', 'prompt': 'x'}]}, {'name': '套图', 'shots': [{'name': 'a', 'prompt': 'x'}] * 9}, {'name': '套图', 'shots': [{'name': 'a', 'prompt': 'x', 'size': 'unsupported'}]}])
def test_invalid_plan_creates_no_partial_jobs(setup, invalid):
    engine, directory, config = setup
    with TestClient(create_app(directory, db_url=str(engine.url))) as client:
        values = {'config_id': config.id, 'request_id': str(uuid4()), 'plan': json.dumps(invalid)}
        assert client.post('/api/image-jobs/sets', files=multipart(values)).status_code == 422
        with Session(engine) as session:
            assert not list(session.scalars(select(ImageJob)))


def test_set_template_product_snapshots_and_revisions_remain_grouped(setup):
    engine, directory, config = setup
    with TestClient(create_app(directory, db_url=str(engine.url))) as client:
        product = client.post('/api/products', json={'sku': 'set-product', 'name': '凉棚', 'color': '灰色'}).json()
        template = client.post('/api/templates', json={'name': '模板', 'prompt': '{{产品}}真实场景', 'skill': '保留产品结构'}).json()
        identifier = str(uuid4())
        values = {'config_id': config.id, 'request_id': identifier, 'plan': json.dumps({'name': '单张套图', 'shots': [plan()['shots'][0]]}), 'product': json.dumps({'id': product['id'], 'revision': 1}), 'template': json.dumps({'id': template['id'], 'revision': 1, 'variables': {'产品': '凉棚'}})}
        result = client.post('/api/image-jobs/sets', files=multipart(values))
        assert result.status_code == 202
        parent = result.json()[0]
        assert '保留产品结构' in parent['prompt'] and 'SET-PRODUCT' in parent['prompt']
        assert parent['template_snapshot']['revision'] == 1 and parent['product_snapshot']['revision'] == 1
        assert process_one(engine, directory, lambda *args: png())
        revision = client.post('/api/image-jobs/batch', files=multipart({'config_id': config.id, 'request_id': str(uuid4()), 'source_job_id': parent['id'], 'count': 1, 'prompt': '调整为傍晚'})).json()[0]
        assert revision['set_id'] == identifier and revision['shot_name'] == parent['shot_name']
        group = client.get(f'/api/image-jobs/sets/{identifier}').json()
        assert len(group['items']) == 2 and group['items'][1]['parent_job_id'] == parent['id']
        assert client.get(f'/api/image-jobs/sets/{uuid4()}').status_code == 404


def test_oversize_merged_set_briefs_create_no_partial_jobs(setup):
    engine, directory, config = setup
    with TestClient(create_app(directory, db_url=str(engine.url))) as client:
        template = client.post('/api/templates', json={'name': '大模板', 'prompt': 'x' * 12000, 'skill': 'y' * 17000}).json()
        values = {'config_id': config.id, 'request_id': str(uuid4()), 'plan': json.dumps({'name': '套图', 'shots': [{'name': '短要求', 'prompt': 'x'}, {'name': '过长合并要求', 'prompt': 'z' * 4000}]}), 'template': json.dumps({'id': template['id'], 'revision': 1, 'variables': {}})}
        assert client.post('/api/image-jobs/sets', files=multipart(values)).status_code == 422
        assert client.get('/api/image-jobs').json() == []
