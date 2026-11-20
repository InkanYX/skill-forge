import csv
import io
import json
from uuid import uuid4
from zipfile import ZipFile
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import ImageJob
from app.image_jobs import artifact, process_one
from app.main import create_app
from app.image_exports import safe_name
from test_image_jobs import setup, enqueue, png, KEY


def export(client, ids=None, set_id=None, records=True):
    values = {'include_records': str(records).lower()}
    if ids is not None:
        values['job_ids'] = json.dumps(ids)
    if set_id:
        values['set_id'] = set_id
    return client.post('/api/image-jobs/exports', files={key: (None, value) for key, value in values.items()})


def completed(setup):
    job = enqueue(setup)
    assert process_one(setup[0], setup[1], lambda *args: png())
    return job


def test_export_preserves_images_and_contains_safe_records_without_credentials(setup):
    engine, directory, _ = setup
    first, second = completed(setup), completed(setup)
    with Session(engine) as session, session.begin():
        row = session.get(ImageJob, first.id)
        row.product_snapshot = json.dumps({'sku': '=HYPERLINK("bad")', 'name': '凉棚'})
        row.shot_name = '../../CON:结构细节?'
        row.prompt = '=1+1'
    with TestClient(create_app(directory, db_url=str(engine.url))) as client:
        assert client.post('/api/cases', json={'job_id': first.id, 'title': '案例', 'experience': '保留结构有效'}).status_code == 200
        response = export(client, [first.id, second.id, first.id])
        assert response.status_code == 200
        assert response.headers['content-type'] == 'application/zip'
        assert int(response.headers['content-length']) == len(response.content)
        assert response.headers['x-export-count'] == '2'
        assert 'attachment' in response.headers['content-disposition']
        with ZipFile(io.BytesIO(response.content)) as archive:
            names = archive.namelist()
            images = [name for name in names if name.endswith('.png')]
            assert len(images) == 2 and len(set(images)) == 2
            assert all(name.startswith('images/') and name.count('/') == 1 and '\\' not in name and ':' not in name and '?' not in name for name in images)
            assert all(archive.read(name) == png() for name in images)
            manifest_text = archive.read('manifest.json').decode('utf-8')
            manifest = json.loads(manifest_text)
            assert [row['job_id'] for row in manifest['items']] == [first.id, second.id]
            assert manifest['image_count'] == 2
            assert manifest['items'][0]['case']['experience'] == '保留结构有效'
            assert 'encrypted_key' not in manifest_text and KEY not in manifest_text
            assert 'https://images.example.com' not in manifest_text
            csv_rows = list(csv.reader(io.StringIO(archive.read('制作记录.csv').decode('utf-8-sig'))))
            assert csv_rows[1][2].startswith("'=") and csv_rows[1][7] == "'=1+1"
            assert archive.testzip() is None
        # Repeated exports never create or modify generation jobs.
        assert export(client, [first.id]).status_code == 200
        assert len(client.get('/api/image-jobs').json()) == 2


def test_export_images_only_and_temporary_file_is_closed(setup):
    import app.image_exports as module
    engine, directory, _ = setup
    job = completed(setup)
    real = module.tempfile.TemporaryFile
    opened = []
    def temporary(*args, **kwargs):
        value = real(*args, **kwargs); opened.append(value); return value
    with TestClient(create_app(directory, db_url=str(engine.url))) as client, patch.object(module.tempfile, 'TemporaryFile', side_effect=temporary):
        response = export(client, [job.id], records=False)
        assert response.status_code == 200
        with ZipFile(io.BytesIO(response.content)) as archive:
            assert len(archive.namelist()) == 1 and archive.namelist()[0].endswith('.png')
    assert opened and all(value.closed for value in opened)


def test_set_export_includes_only_completed_images_and_versions(setup):
    engine, directory, _ = setup
    jobs = [completed(setup), completed(setup), enqueue(setup)]
    identifier = str(uuid4())
    with Session(engine) as session, session.begin():
        for index, item in enumerate(jobs):
            row = session.get(ImageJob, item.id)
            row.set_id, row.set_name, row.shot_index = identifier, '套图', index
        session.get(ImageJob, jobs[1].id).parent_job_id = jobs[0].id
    with TestClient(create_app(directory, db_url=str(engine.url))) as client:
        response = export(client, set_id=identifier)
        assert response.status_code == 200
        with ZipFile(io.BytesIO(response.content)) as archive:
            items = json.loads(archive.read('manifest.json'))['items']
            assert [item['job_id'] for item in items] == [jobs[0].id, jobs[1].id]
            assert items[1]['parent_job_id'] == jobs[0].id
        assert export(client, set_id=str(uuid4())).status_code == 422


@pytest.mark.parametrize('ids', [[], ['not-a-uuid'], [str(uuid4())] * 51, {'unexpected': 'object'}])
def test_invalid_export_selection_is_rejected(setup, ids):
    engine, directory, _ = setup
    with TestClient(create_app(directory, db_url=str(engine.url))) as client:
        assert export(client, ids).status_code == 422


def test_export_rejects_unfinished_missing_or_unavailable_images(setup):
    engine, directory, _ = setup
    job = completed(setup)
    pending = enqueue(setup)
    with TestClient(create_app(directory, db_url=str(engine.url))) as client:
        assert export(client, [pending.id]).status_code == 409
        assert export(client, [str(uuid4())]).status_code == 404
        assert export(client, [job.id], set_id=str(uuid4())).status_code == 422
        artifact(directory, job.id, 'result.png').unlink()
        assert export(client, [job.id]).status_code == 409


def test_export_resource_limit_closes_temporary_archive(setup):
    import app.image_exports as module
    engine, directory, _ = setup
    job = completed(setup)
    real = module.tempfile.TemporaryFile
    opened = []
    def temporary(*args, **kwargs):
        value = real(*args, **kwargs); opened.append(value); return value
    with TestClient(create_app(directory, db_url=str(engine.url))) as client, patch.object(module, 'MAX_EXPORT_BYTES', 8), patch.object(module.tempfile, 'TemporaryFile', side_effect=temporary):
        assert export(client, [job.id]).status_code == 413
    assert opened and all(value.closed for value in opened)


def test_export_origin_guard_and_filename_sanitizing(setup):
    engine, directory, _ = setup
    with TestClient(create_app(directory, db_url=str(engine.url))) as client:
        response = client.post('/api/image-jobs/exports', files={'job_ids': (None, '[]')}, headers={'Origin': 'https://bad.example'})
        assert response.status_code == 403
    assert safe_name('CON') == '_CON'
    assert safe_name('../../a:b?') == '_.._a_b_'
    assert safe_name('   ') == 'image'
