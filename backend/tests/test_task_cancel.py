import json
import os
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event
from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.database import Base, DatabaseConfigStore, ImageJob, database_url, make_engine
from app.image_jobs import cancel_job, cancel_set, create_job, process_one
from app.main import create_app
from app.model_configs import ConfigInput
from test_image_jobs import setup, enqueue, png, KEY


def post_cancel(client, path):
    return client.post(path, files={'action': (None, 'cancel')})


def test_cancelled_job_clears_key_keeps_reference_and_is_never_executed(setup):
    engine, directory, config = setup
    request_id = str(uuid4())
    row = enqueue(setup, reference=png(), request_id=request_id)
    with TestClient(create_app(directory, db_url=str(engine.url))) as client:
        response = post_cancel(client, f'/api/image-jobs/{row.id}/cancel')
        assert response.status_code == 200 and response.json()['status'] == 'cancelled'
        assert KEY not in response.text
        assert post_cancel(client, f'/api/image-jobs/{row.id}/cancel').json()['status'] == 'cancelled'
        assert client.get(f'/api/image-jobs/{row.id}/reference').content == png()
        assert client.get(f'/api/image-jobs/{row.id}/image').status_code == 404
        assert client.get('/api/image-jobs/library', params={'status': 'cancelled'}).json()['total'] == 1
        assert client.post('/api/cases', json={'job_id': row.id, 'title': '取消任务', 'experience': '不能保存'}).status_code == 422
    replay = enqueue(setup, reference=png(), request_id=request_id)
    assert replay.id == row.id and replay.status == 'cancelled'
    assert not process_one(engine, directory, lambda *args: pytest.fail('cancelled task must never call provider'))
    with Session(engine) as session:
        saved = session.get(ImageJob, row.id)
        assert saved.encrypted_key == '' and saved.lease_until is None


@pytest.mark.parametrize('status', ['running', 'succeeded', 'failed', 'unknown'])
def test_running_or_finished_tasks_cannot_be_cancelled(setup, status):
    engine, directory, _ = setup
    row = enqueue(setup)
    with Session(engine) as session, session.begin():
        session.get(ImageJob, row.id).status = status
    with TestClient(create_app(directory, db_url=str(engine.url))) as client:
        response = post_cancel(client, f'/api/image-jobs/{row.id}/cancel')
        assert response.status_code == 409
        assert client.get(f'/api/image-jobs/{row.id}').json()['status'] == status
    with Session(engine) as session:
        assert session.get(ImageJob, row.id).encrypted_key != ''


def test_set_cancel_only_affects_queued_members_and_is_repeatable(setup):
    engine, directory, _ = setup
    set_id = str(uuid4())
    rows = [enqueue(setup) for _ in range(7)]
    statuses = ['queued', 'queued', 'running', 'succeeded', 'failed', 'unknown']
    with Session(engine) as session, session.begin():
        for item, status in zip(rows, statuses):
            row = session.get(ImageJob, item.id)
            row.set_id, row.status = set_id, status
    with TestClient(create_app(directory, db_url=str(engine.url))) as client:
        response = post_cancel(client, f'/api/image-jobs/sets/{set_id}/cancel')
        assert response.status_code == 200
        assert response.json()['cancelled_count'] == 2
        assert response.json()['counts']['running'] == 1
        assert response.json()['counts']['cancelled'] == 2
        assert post_cancel(client, f'/api/image-jobs/sets/{set_id}/cancel').json()['cancelled_count'] == 0
        assert post_cancel(client, f'/api/image-jobs/sets/{uuid4()}/cancel').status_code == 404
    with Session(engine) as session:
        assert session.get(ImageJob, rows[-1].id).status == 'queued'
        assert session.get(ImageJob, rows[2].id).status == 'running'
        assert session.get(ImageJob, rows[0].id).encrypted_key == ''


def test_cancel_endpoint_validation_and_origin_guard(setup):
    engine, directory, _ = setup
    row = enqueue(setup)
    with TestClient(create_app(directory, db_url=str(engine.url))) as client:
        assert post_cancel(client, f'/api/image-jobs/{uuid4()}/cancel').status_code == 404
        assert client.post(f'/api/image-jobs/{row.id}/cancel', files={'action': (None, 'wrong')}).status_code == 422
        assert client.post(f'/api/image-jobs/{row.id}/cancel', files={'action': (None, 'cancel')}, headers={'Origin': 'https://bad.example'}).status_code == 403
        assert client.get(f'/api/image-jobs/{row.id}').json()['status'] == 'queued'


@pytest.mark.skipif(os.environ.get('SKILL_FORGE_TEST_POSTGRES') != '1', reason='需要显式启用 PostgreSQL 并发测试')
def test_postgres_cancel_and_worker_claim_are_mutually_exclusive(tmp_path):
    from sqlalchemy.engine import make_url
    url = database_url()
    assert url and make_url(url).database == 'skill_forge'
    assert make_url(url).host in ('127.0.0.1', 'localhost')
    base = make_engine(url)
    schema = 'cancel_test_' + uuid4().hex
    engine = base.execution_options(schema_translate_map={None: schema})
    try:
        with base.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        Base.metadata.create_all(engine)
        config = DatabaseConfigStore(tmp_path, engine).save(ConfigInput(name='模拟接口', base_url='https://example.com/v1', model_name='fake', api_key=KEY))
        # This schema is invisible to the real worker, so all provider calls below
        # are isolated mocks and cannot consume a configured service's quota.
        for index in range(5):
            row = create_job(engine, tmp_path, config.id, '', '测试任务', 'default', str(uuid4()), None)
            set_id = str(uuid4())
            with Session(engine) as session, session.begin():
                session.get(ImageJob, row.id).set_id = set_id
            barrier, called = Barrier(2), Event()
            def provider(*args):
                called.set(); return png()
            def work():
                barrier.wait(timeout=5)
                return process_one(engine, tmp_path, provider)
            def cancel():
                barrier.wait(timeout=5)
                try:
                    if index % 2:
                        return 'cancelled' if cancel_set(engine, set_id)['cancelled_count'] else 'already-started'
                    return cancel_job(engine, row.id).status
                except HTTPException as error:
                    assert error.status_code == 409
                    return 'already-started'
            with ThreadPoolExecutor(max_workers=2) as pool:
                worker, cancellation = pool.submit(work), pool.submit(cancel)
                outcome = cancellation.result(timeout=15)
                worker.result(timeout=15)
            with Session(engine) as session:
                saved = session.get(ImageJob, row.id)
                if outcome == 'cancelled':
                    assert not called.is_set() and saved.status == 'cancelled'
                else:
                    assert called.is_set() and saved.status == 'succeeded'
                assert saved.encrypted_key == ''
    finally:
        Base.metadata.drop_all(engine)
        with base.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}"'))
        base.dispose()
