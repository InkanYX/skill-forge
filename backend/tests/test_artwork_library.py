import json
import os
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import CreativeCase, ImageJob, database_url, make_engine
from app.image_jobs import build_image_router
from app.main import create_app
from test_image_jobs import setup, enqueue, KEY


def test_library_paginates_all_jobs_and_keeps_order_for_equal_timestamps(setup):
    engine, directory, _ = setup
    for _ in range(32):
        enqueue(setup)
    with Session(engine) as session, session.begin():
        for row in session.scalars(select(ImageJob)):
            row.created_at = '2026-01-01T00:00:00+00:00'
    with TestClient(create_app(directory, db_url=str(engine.url))) as client:
        first = client.get('/api/image-jobs/library', params={'status': 'all', 'page_size': 12}).json()
        second = client.get('/api/image-jobs/library', params={'status': 'all', 'page_size': 12, 'page': 2}).json()
        third = client.get('/api/image-jobs/library', params={'status': 'all', 'page_size': 12, 'page': 3}).json()
        assert first['total'] == 32 and len(first['items']) == 12 and len(third['items']) == 8
        identifiers = [row['id'] for page in [first, second, third] for row in page['items']]
        assert len(set(identifiers)) == 32 and identifiers == sorted(identifiers, reverse=True)
        assert len(client.get('/api/image-jobs').json()) == 30
        assert client.get('/api/image-jobs/library').json()['total'] == 0
        assert KEY not in str(first) and 'encrypted_key' not in str(first)


def test_library_filters_historical_product_template_and_literal_search(setup):
    engine, directory, _ = setup
    first, second = enqueue(setup), enqueue(setup)
    product_id, template_id = str(uuid4()), str(uuid4())
    with Session(engine) as session, session.begin():
        row = session.get(ImageJob, first.id)
        row.product_snapshot = json.dumps({'id': product_id, 'sku': 'OLD-SKU', 'name': '灰色凉棚'})
        row.template_snapshot = json.dumps({'id': template_id, 'name': '庭院场景'})
        row.prompt = '自然光 50%_done'
        row.status = 'succeeded'
    with TestClient(create_app(directory, db_url=str(engine.url))) as client:
        for filters in [{'product_id': product_id}, {'template_id': template_id}, {'q': 'old-sku'}, {'q': '庭院场景'}, {'q': '灰色凉棚'}, {'q': '%_done'}]:
            response = client.get('/api/image-jobs/library', params=filters)
            assert response.status_code == 200
            assert [row['id'] for row in response.json()['items']] == [first.id]
        assert client.get('/api/image-jobs/library', params={'product_id': str(uuid4())}).json()['total'] == 0
        assert client.get('/api/image-jobs/library', params={'status': 'queued'}).json()['items'][0]['id'] == second.id
        assert client.get('/api/image-jobs/library', params={'q': 'does-not-exist'}).json()['total'] == 0
        saved = client.post('/api/cases', json={'job_id': first.id, 'title': '庭院', 'experience': '有效经验'}).json()
        assert client.get('/api/image-jobs/library').json()['items'][0]['case_id'] == saved['id']


def test_favorites_are_persistent_idempotent_and_independent_of_notes(setup):
    engine, directory, _ = setup
    first, second = enqueue(setup), enqueue(setup)
    with Session(engine) as session, session.begin():
        session.get(ImageJob, first.id).status = 'succeeded'
    with TestClient(create_app(directory, db_url=str(engine.url))) as client:
        before = client.get(f'/api/image-jobs/{first.id}').json()
        assert before['is_favorite'] is False
        for _ in range(2):
            reply = client.post(f'/api/image-jobs/{first.id}/favorite', files={'favorite': (None, 'true')})
            assert reply.status_code == 200 and reply.json()['is_favorite'] is True
            assert reply.json()['updated_at'] == before['updated_at']
            assert KEY not in reply.text
        assert client.get('/api/image-jobs/library', params={'favorite': True}).json()['total'] == 1
        assert client.get('/api/image-jobs/library', params={'favorite': True, 'has_notes': True}).json()['total'] == 0
        assert client.post(f'/api/image-jobs/{second.id}/favorite', files={'favorite': (None, 'true')}).status_code == 409
        assert client.post(f'/api/image-jobs/{uuid4()}/favorite', files={'favorite': (None, 'true')}).status_code == 404
        assert client.post(f'/api/image-jobs/{first.id}/favorite', files={'favorite': (None, 'invalid')}).status_code == 422
    with TestClient(create_app(directory, db_url=str(engine.url))) as reopened:
        assert reopened.get(f'/api/image-jobs/{first.id}').json()['is_favorite'] is True
        assert reopened.post(f'/api/image-jobs/{first.id}/favorite', files={'favorite': (None, 'false')}).json()['is_favorite'] is False
        assert reopened.get('/api/image-jobs/library', params={'favorite': True}).json()['total'] == 0


def test_existing_case_notes_can_be_read_edited_and_searched_in_library(setup):
    engine, directory, _ = setup
    first, second = enqueue(setup), enqueue(setup)
    with Session(engine) as session, session.begin():
        session.get(ImageJob, first.id).status = 'succeeded'
        session.get(ImageJob, second.id).status = 'succeeded'
    with TestClient(create_app(directory, db_url=str(engine.url))) as client:
        assert client.get(f'/api/cases/{first.id}').json() is None
        assert client.get(f'/api/cases/{uuid4()}').status_code == 404
        saved = client.post('/api/cases', json={'job_id': first.id, 'title': '连接特写', 'experience': '参考图改善比例', 'issues': '文字存在 50%_偏差'}).json()
        assert client.get(f'/api/cases/{first.id}').json() == saved
        for query in ['连接特写', '改善比例', '%_偏差']:
            result = client.get('/api/image-jobs/library', params={'has_notes': True, 'q': query}).json()
            assert result['total'] == 1 and result['items'][0]['id'] == first.id
        assert client.get('/api/image-jobs/library', params={'has_notes': True, 'page': 2, 'page_size': 1}).json()['items'] == []
        client.post(f'/api/image-jobs/{first.id}/favorite', files={'favorite': (None, 'true')})
        assert client.get('/api/image-jobs/library', params={'favorite': True, 'has_notes': True}).json()['total'] == 1
        updated = client.post('/api/cases', json={'job_id': first.id, 'title': saved['title'], 'experience': '补充结构参考更有效', 'issues': saved['issues']}).json()
        assert updated['id'] == saved['id'] and updated['issues'] == saved['issues']
        assert client.get(f'/api/cases/{first.id}').json()['experience'] == '补充结构参考更有效'
        assert len(client.get('/api/cases').json()) == 1
        assert client.get('/api/image-jobs/library', params={'q': '改善比例'}).json()['total'] == 0


@pytest.mark.parametrize('params', [{'page': 0}, {'page_size': 1000}, {'product_id': 'invalid'}, {'status': 'invalid'}, {'q': 'a' * 201}])
def test_library_rejects_invalid_query_parameters(setup, params):
    engine, directory, _ = setup
    with TestClient(create_app(directory, db_url=str(engine.url))) as client:
        assert client.get('/api/image-jobs/library', params=params).status_code == 422


@pytest.mark.skipif(os.environ.get('SKILL_FORGE_TEST_POSTGRES') != '1', reason='需要显式启用本机 PostgreSQL 集成测试')
def test_library_json_filters_on_postgres_are_rolled_back(tmp_path):
    from sqlalchemy.engine import make_url
    url = database_url()
    assert url and make_url(url).database == 'skill_forge'
    assert make_url(url).host in ('127.0.0.1', 'localhost')
    engine = make_engine(url)
    identifier, product_id = str(uuid4()), str(uuid4())
    try:
        with engine.connect() as connection:
            transaction = connection.begin()
            try:
                with Session(connection) as session:
                    session.add(ImageJob(id=identifier, request_id=str(uuid4()), fingerprint='0' * 64, config_id=str(uuid4()), config_name='测试', base_url='https://example.com/v1', encrypted_key='', model_name='test', prompt='rolled-back-library-test', size='default', mode='generate', status='succeeded', message='test', created_at='2026-01-01', updated_at='2026-01-01', product_snapshot=json.dumps({'id': product_id, 'sku': 'TEST-PG'}), template_snapshot='{}', is_favorite=True))
                    session.add(CreativeCase(id=str(uuid4()), job_id=identifier, title='PG 经验', experience='立柱参考', issues='', updated_at='2026-01-01'))
                    session.commit()
                application = FastAPI()
                application.include_router(build_image_router(connection, tmp_path))
                with TestClient(application) as client:
                    response = client.get('/api/image-jobs/library', params={'product_id': product_id, 'q': 'test-pg'})
                    assert response.status_code == 200 and response.json()['total'] == 1
                    assert response.json()['items'][0]['id'] == identifier
                    filtered = client.get('/api/image-jobs/library', params={'favorite': True, 'has_notes': True, 'q': '立柱参考'})
                    assert filtered.status_code == 200 and filtered.json()['total'] == 1
            finally:
                transaction.rollback()
        with Session(engine) as session:
            assert session.get(ImageJob, identifier) is None
    finally:
        engine.dispose()
