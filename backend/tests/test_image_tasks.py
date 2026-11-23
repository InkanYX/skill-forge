import json
import os
from uuid import uuid4, uuid5

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import ImageJob, CreativeCase, database_url, make_engine
from app.image_jobs import build_image_router, process_one
from app.main import create_app
from test_image_jobs import setup, png, KEY


def batch(client, config, count=4, **extra):
    values = {'config_id': config.id, 'request_id': str(uuid4()), 'count': count, 'prompt': '庭院场景', **extra}
    reply = client.post('/api/image-jobs/batch', files={key: (None, str(value)) for key, value in values.items()})
    assert reply.status_code == 202, reply.text
    return reply.json()


def test_task_history_groups_submission_not_prompt_or_image(setup):
    engine, directory, config = setup
    with TestClient(create_app(directory, db_url=str(engine.url))) as client:
        root = str(uuid4())
        first = batch(client, config, request_id=root)
        duplicate = batch(client, config, request_id=root)
        second = batch(client, config)
        assert [item['id'] for item in duplicate] == [item['id'] for item in first]
        assert {item['task_id'] for item in first} == {root}
        assert [item['task_index'] for item in first] == [0, 1, 2, 3]
        page = client.get('/api/image-jobs/tasks', params={'page_size': 1}).json()
        assert page['total'] == 2 and len(page['items']) == 1
        assert page['items'][0]['counts']['total'] == 4
        assert client.get('/api/image-jobs/tasks', params={'page_size': 1, 'page': 2}).json()['items'][0]['id'] == root
        detail = client.get(f'/api/image-jobs/tasks/{root}').json()
        assert [item['id'] for item in detail['items']] == [item['id'] for item in first]
        assert detail['status'] == 'queued'
        assert KEY not in json.dumps(detail) and 'encrypted_key' not in json.dumps(detail)
        assert client.get(f"/api/image-jobs/tasks/for-image/{first[2]['id']}").json()['id'] == root
        assert client.get(f'/api/image-jobs/tasks/{uuid4()}').status_code == 404


def test_aggregate_state_and_filter_keep_all_execution_results(setup):
    engine, directory, config = setup
    with TestClient(create_app(directory, db_url=str(engine.url))) as client:
        rows = batch(client, config)
        root = rows[0]['task_id']
        product_id, template_id = str(uuid4()), str(uuid4())
        with Session(engine) as session, session.begin():
            for index, item in enumerate(rows):
                row = session.get(ImageJob, item['id'])
                row.status = 'failed' if index else 'succeeded'
                row.encrypted_key = ''
                row.product_snapshot = json.dumps({'id': product_id, 'sku': 'OLD-SKU'})
                row.template_snapshot = json.dumps({'id': template_id, 'name': '旧模板'})
            row.prompt = '特殊要求 50%_done'
            row.provider_diagnostic = json.dumps({'http_status': 404, 'path': '/v1/images/generations', 'response_body': '{"detail":"Not Found"}', 'recorded_at': '2026-11-23T03:00:00+00:00'})
        filters = [{'q': '%_done'}, {'product_id': product_id}, {'template_id': template_id}, {'q': 'old-sku'}, {'q': root}, {'status': 'partial'}]
        for query in filters:
            reply = client.get('/api/image-jobs/tasks', params=query)
            assert reply.status_code == 200, reply.text
            page = reply.json()
            assert page['total'] == 1 and page['items'][0]['counts']['total'] == 4
        assert client.get('/api/image-jobs/tasks', params={'status': 'failed'}).json()['total'] == 0
        detail = client.get(f'/api/image-jobs/tasks/{root}').json()
        assert len(detail['items']) == 4 and detail['status'] == 'partial'
        assert detail['items'][3]['diagnostic']['http_status'] == 404
        assert detail['completed_job_ids'] == [rows[0]['id']]
        for status, expected in [('running', 'running'), ('queued', 'queued'), ('unknown', 'unknown'), ('failed', 'partial')]:
            with Session(engine) as session, session.begin():
                session.get(ImageJob, rows[3]['id']).status = status
            assert client.get(f'/api/image-jobs/tasks/{root}').json()['status'] == expected
            assert client.get('/api/image-jobs/tasks', params={'status': expected}).json()['total'] == 1


def test_favorite_and_notes_find_task_without_hiding_other_images(setup):
    engine, directory, config = setup
    with TestClient(create_app(directory, db_url=str(engine.url))) as client:
        rows = batch(client, config, 2)
        with Session(engine) as session, session.begin():
            session.get(ImageJob, rows[1]['id']).status = 'succeeded'
        assert client.post(f"/api/image-jobs/{rows[1]['id']}/favorite", files={'favorite': (None, 'true')}).status_code == 200
        assert client.post('/api/cases', json={'job_id': rows[1]['id'], 'title': '庭院', 'experience': '保留立柱更准确'}).status_code == 200
        page = client.get('/api/image-jobs/tasks', params={'favorite': True, 'has_notes': True, 'q': '立柱'}).json()
        assert page['total'] == 1 and page['items'][0]['counts']['total'] == 2
        assert len(client.get(f"/api/image-jobs/tasks/{rows[0]['task_id']}").json()['items']) == 2


def test_set_revision_is_new_task_and_cancel_is_submission_scoped(setup):
    engine, directory, config = setup
    with TestClient(create_app(directory, db_url=str(engine.url))) as client:
        root = str(uuid4())
        plan = {'name': '庭院套图', 'shots': [{'name': '主体', 'prompt': '完整结构'}, {'name': '细节', 'prompt': '连接处'}]}
        reply = client.post('/api/image-jobs/sets', files={key: (None, str(value)) for key, value in {'config_id': config.id, 'request_id': root, 'plan': json.dumps(plan)}.items()})
        assert reply.status_code == 202
        parent = reply.json()[0]
        assert process_one(engine, directory, lambda *args: png())
        revision = batch(client, config, 2, source_job_id=parent['id'], prompt='改为傍晚')
        revised_task = revision[0]['task_id']
        assert revised_task != root and revision[0]['set_id'] == root
        assert client.get(f'/api/image-jobs/tasks/{root}').json()['kind'] == 'set'
        assert client.get(f'/api/image-jobs/tasks/{revised_task}').json()['kind'] == 'edit'
        reply = client.post(f'/api/image-jobs/tasks/{root}/cancel', files={'action': (None, 'cancel')})
        assert reply.status_code == 200 and reply.json()['cancelled_count'] == 1
        assert client.get(f'/api/image-jobs/tasks/{revised_task}').json()['counts']['queued'] == 2
        reply = client.post(f'/api/image-jobs/tasks/{revised_task}/cancel', files={'action': (None, 'cancel')})
        assert reply.json()['cancelled_count'] == 2
        detail = client.get(f'/api/image-jobs/tasks/{revised_task}').json()
        assert detail['status'] == 'cancelled'
        assert all(item['updated_at'] >= item['created_at'] for item in detail['items'])
        assert client.post(f'/api/image-jobs/tasks/{revised_task}/cancel', files={'action': (None, 'cancel')}).json()['cancelled_count'] == 0


def test_legacy_migration_uses_original_batch_uuid_and_preserves_independent_requests(tmp_path):
    from alembic import command
    from alembic.config import Config
    from pathlib import Path
    from sqlalchemy import text
    engine = make_engine(f"sqlite:///{(tmp_path / 'migration.db').as_posix()}")
    config = Config(str(Path(__file__).resolve().parents[1] / 'alembic.ini'))
    config.set_main_option('script_location', str(Path(__file__).resolve().parents[1] / 'migrations'))
    config.attributes['database_url'] = str(engine.url)
    connection = engine.connect()
    try:
        command.upgrade(config, '0010_provider_diagnostics')
        # Identical prompts/fingerprints must not combine separate submissions.
        roots = [uuid4(), uuid4()]
        for root in roots:
            for index in range(4):
                request_id = str(root if index == 0 else uuid5(root, f'image-{index}'))
                connection.execute(text("INSERT INTO image_jobs (id,request_id,fingerprint,config_id,config_name,base_url,encrypted_key,model_name,prompt,size,mode,status,message,created_at,updated_at) VALUES (:id,:request_id,:fingerprint,:config_id,'test','https://example.com/v1','','image-test','same prompt','default','generate','failed','error','2026-11-23','2026-11-23')"), {'id': str(uuid4()), 'request_id': request_id, 'fingerprint': 'a' * 64, 'config_id': str(uuid4())})
        connection.commit()
        command.upgrade(config, 'head')
        rows = connection.execute(text('SELECT task_id,task_index FROM image_jobs')).all()
        assert sorted(rows) == sorted((str(root), index) for root in roots for index in range(4))
    finally:
        connection.close(); engine.dispose()


@pytest.mark.skipif(os.environ.get('SKILL_FORGE_TEST_POSTGRES') != '1', reason='需要显式启用本机 PostgreSQL 集成测试')
def test_task_grouped_filters_on_postgres_rollback(tmp_path):
    from sqlalchemy.engine import make_url
    url = database_url()
    assert url and make_url(url).database == 'skill_forge' and make_url(url).host in ('127.0.0.1', 'localhost')
    engine = make_engine(url)
    root, product_id = str(uuid4()), str(uuid4())
    try:
        with engine.connect() as connection:
            transaction = connection.begin()
            try:
                with Session(connection) as session:
                    for index in range(2):
                        identifier = str(uuid4())
                        session.add(ImageJob(id=identifier, task_id=root, task_index=index, request_id=str(uuid4()), fingerprint='0' * 64, config_id=str(uuid4()), config_name='test', base_url='https://example.com/v1', encrypted_key='', model_name='test', prompt='test task filter', size='default', mode='generate', status='succeeded' if index else 'failed', message='test', created_at='2026-01-01', updated_at='2026-01-01', product_snapshot=json.dumps({'id': product_id, 'sku': 'PG-TASK'}), template_snapshot='{}', is_favorite=bool(index)))
                        if index: session.add(CreativeCase(id=str(uuid4()), job_id=identifier, title='PG 经验', experience='参考结构', issues='', updated_at='2026-01-01'))
                    session.commit()
                application = FastAPI(); application.include_router(build_image_router(connection, tmp_path))
                with TestClient(application) as client:
                    for filters in [{'product_id': product_id, 'q': 'PG-TASK'}, {'q': '参考结构', 'favorite': True, 'has_notes': True}]:
                        reply = client.get('/api/image-jobs/tasks', params=filters)
                        assert reply.status_code == 200, reply.text
                        assert reply.json()['total'] == 1 and reply.json()['items'][0]['counts']['total'] == 2
            finally:
                transaction.rollback()
        with Session(engine) as session:
            assert session.scalar(select(ImageJob.id).where(ImageJob.task_id == root)) is None
    finally:
        engine.dispose()
