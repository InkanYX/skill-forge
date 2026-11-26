import io
import json
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import ImageJob
from app.image_jobs import artifact, process_one
from app.main import create_app
from test_image_jobs import setup, enqueue, png, KEY


def multipart(values):
    return {key: (None, str(value)) for key, value in values.items()}


def complete_source(setup):
    row = enqueue(setup)
    assert process_one(setup[0], setup[1], lambda *args: png())
    return row


def test_revision_preserves_original_snapshot_and_reuses_submission(setup):
    engine, directory, config = setup
    source = complete_source(setup)
    snapshot = {'id': str(uuid4()), 'sku': 'OLD-SKU', 'name': '凉棚', 'category': '凉棚', 'dimensions': '3 m × 4 m', 'color': '灰色', 'facts': '四根立柱', 'notes': '保持结构', 'revision': 1}
    with Session(engine) as session, session.begin():
        parent = session.get(ImageJob, source.id)
        parent.product_snapshot = json.dumps(snapshot)
        parent.template_snapshot = json.dumps({'id': str(uuid4()), 'name': '旧模板', 'revision': 1})
    with TestClient(create_app(directory, db_url=str(engine.url))) as client:
        values = {'config_id': config.id, 'request_id': str(uuid4()), 'prompt': '只将背景改为庭院', 'count': 1, 'source_job_id': source.id}
        first = client.post('/api/image-jobs/batch', files=multipart(values))
        assert first.status_code == 202
        job = first.json()[0]
        assert job['parent_job_id'] == source.id and job['mode'] == 'edit'
        assert job['edit_instruction'] == values['prompt']
        assert job['product_snapshot'] == snapshot
        assert job['template_snapshot']['name'] == '旧模板'
        assert client.post('/api/image-jobs/batch', files=multipart(values)).json()[0]['id'] == job['id']
        values['prompt'] = '不同的修改'
        assert client.post('/api/image-jobs/batch', files=multipart(values)).status_code == 409
        red = io.BytesIO()
        Image.new('RGB', (12, 8), 'red').save(red, 'PNG')
        def provider(*args):
            assert args[-1] == png() and args[1] == KEY
            assert '只将背景改为庭院' in args[3] and '四根立柱' in args[3]
            return red.getvalue()
        assert process_one(engine, directory, provider)
        assert not process_one(engine, directory, provider)
        assert client.get(f'/api/image-jobs/{source.id}/image').content == png()
        assert client.get(f"/api/image-jobs/{job['id']}/reference").content == png()
        assert client.get(f"/api/image-jobs/{job['id']}/image").content == red.getvalue()
        history = client.get(f"/api/image-jobs/{job['id']}/versions").json()
        assert [item['id'] for item in history['ancestors']] == [source.id]
        assert history['children'] == []
        assert KEY not in str(history)


@pytest.mark.parametrize('status', ['queued', 'failed', 'unknown'])
def test_only_completed_images_can_be_revision_sources(setup, status):
    engine, directory, config = setup
    parent = enqueue(setup)
    with Session(engine) as session, session.begin():
        session.get(ImageJob, parent.id).status = status
    with TestClient(create_app(directory, db_url=str(engine.url))) as client:
        values = {'config_id': config.id, 'request_id': str(uuid4()), 'prompt': '改背景', 'source_job_id': parent.id}
        assert client.post('/api/image-jobs/batch', files=multipart(values)).status_code == 422
        assert len(client.get('/api/image-jobs').json()) == 1


def test_revision_reference_is_copied_and_missing_original_is_not_regenerated(setup):
    engine, directory, config = setup
    parent = complete_source(setup)
    with TestClient(create_app(directory, db_url=str(engine.url))) as client:
        values = {'config_id': config.id, 'request_id': str(uuid4()), 'prompt': '改背景', 'count': 1, 'source_job_id': parent.id}
        first = client.post('/api/image-jobs/batch', files=multipart(values)).json()[0]
        artifact(directory, parent.id, 'result.png').unlink()
        assert client.post('/api/image-jobs/batch', files=multipart(values)).json()[0]['id'] == first['id']
        values['request_id'] = str(uuid4())
        assert client.post('/api/image-jobs/batch', files=multipart(values)).status_code == 422
        assert client.get(f"/api/image-jobs/{first['id']}/reference").content == png()
        assert process_one(engine, directory, lambda *args: png())


def test_revision_rejects_other_reference_sources_and_empty_instructions(setup):
    engine, directory, config = setup
    parent = complete_source(setup)
    with TestClient(create_app(directory, db_url=str(engine.url))) as client:
        values = {'config_id': config.id, 'request_id': str(uuid4()), 'prompt': '改背景', 'source_job_id': parent.id}
        assert client.post('/api/image-jobs/batch', files={**multipart(values), 'reference': ('image.png', png(), 'image/png')}).status_code == 422
        assert client.post('/api/image-jobs/batch', files=multipart({**values, 'template': json.dumps({'id': str(uuid4()), 'revision': 1})})).status_code == 422
        assert client.post('/api/image-jobs/batch', files=multipart({**values, 'prompt': ' '})).status_code == 422
        assert client.post('/api/image-jobs/batch', files=multipart({**values, 'source_job_id': str(uuid4())})).status_code == 422


def test_revision_history_preserves_branches(setup):
    engine, directory, config = setup
    root = complete_source(setup)
    with TestClient(create_app(directory, db_url=str(engine.url))) as client:
        values = {'config_id': config.id, 'request_id': str(uuid4()), 'prompt': '改背景', 'count': 2, 'source_job_id': root.id}
        children = client.post('/api/image-jobs/batch', files=multipart(values)).json()
        assert process_one(engine, directory, lambda *args: png())
        assert process_one(engine, directory, lambda *args: png())
        values.update(request_id=str(uuid4()), count=1, source_job_id=children[0]['id'])
        grandchild = client.post('/api/image-jobs/batch', files=multipart(values)).json()[0]
        history = client.get(f"/api/image-jobs/{grandchild['id']}/versions").json()
        assert [item['id'] for item in history['ancestors']] == [root.id, children[0]['id']]
        root_history = client.get(f'/api/image-jobs/{root.id}/versions').json()
        assert {item['id'] for item in root_history['children']} == {item['id'] for item in children}
        assert not root_history['has_more_children']
        inline = client.get(f'/api/image-jobs/{root.id}/revisions').json()
        assert inline['items'][0]['id'] == root.id
        assert {item['id'] for item in inline['items']} == {root.id, children[0]['id'], children[1]['id'], grandchild['id']}
        assert not inline['has_more']
        assert KEY not in str(inline)
        # A deleted intermediate image must not hide its surviving descendants.
        with Session(engine) as session, session.begin():
            session.get(ImageJob,children[0]['id']).deleted_at = 'removed'
            session.get(ImageJob,children[1]['id']).owner_id = 'another-user'
        inline = client.get(f'/api/image-jobs/{root.id}/revisions').json()
        assert {item['id'] for item in inline['items']} == {root.id, grandchild['id']}
        assert client.get(f'/api/image-jobs/{uuid4()}/revisions').status_code == 404
