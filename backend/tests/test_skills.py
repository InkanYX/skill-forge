import io
import json
from uuid import uuid4
from zipfile import ZipFile

import pytest
from fastapi.testclient import TestClient

from app.image_jobs import process_one
from app.main import create_app
from test_image_jobs import setup, png


def multipart(values):
    return {key: (None, str(value)) for key, value in values.items()}


def test_skill_versions_conflicts_noop_and_markdown_download(setup):
    engine, directory, _ = setup
    with TestClient(create_app(directory, db_url=str(engine.url))) as client:
        original = {'name': '结构保真', 'purpose': '凉棚场景', 'content': '\n保持{{颜色}}和产品结构。\n不增加侧帘。\n'}
        first = client.post('/api/skills', json=original)
        assert first.status_code == 201
        row = first.json()
        assert row['revision'] == 1 and row['content'] == original['content']
        updated = client.put(f"/api/skills/{row['id']}", json={**original, 'revision': 1, 'content': '新版制作要求'}).json()
        assert updated['revision'] == 2
        assert client.put(f"/api/skills/{row['id']}", json={**original, 'revision': 1}).status_code == 409
        assert client.put(f"/api/skills/{row['id']}", json={**original, 'revision': 2, 'content': '新版制作要求'}).json()['revision'] == 2
        assert [version['revision'] for version in client.get(f"/api/skills/{row['id']}/versions").json()] == [2, 1]
        assert client.get(f"/api/skills/{row['id']}?revision=1").json()['content'] == original['content']
        assert client.get(f"/api/skills/{row['id']}").json()['content'] == '新版制作要求'
        download = client.get(f"/api/skills/{row['id']}/download?revision=1")
        assert download.content.decode('utf-8') == original['content']
        assert 'attachment' in download.headers['content-disposition'] and '-v1.md' in download.headers['content-disposition']
        assert download.headers['x-content-type-options'] == 'nosniff'
        assert len(client.get('/api/skills').json()) == 1
        assert client.get(f"/api/skills/{row['id']}?revision=99").status_code == 404
        assert client.get(f"/api/skills/{uuid4()}").status_code == 404


def test_template_pins_verified_skill_version_and_jobs_cases_exports_keep_it(setup):
    engine, directory, config = setup
    with TestClient(create_app(directory, db_url=str(engine.url))) as client:
        original = {'name': '结构保真', 'content': '保持{{颜色}}，不增加侧帘。'}
        skill = client.post('/api/skills', json=original).json()
        template_input = {'name': '庭院模板', 'prompt': '{{产品}}庭院场景', 'skill_id': skill['id'], 'skill_revision': 1, 'skill': '伪造的版本内容'}
        created = client.post('/api/templates', json=template_input)
        assert created.status_code == 201
        template = created.json()
        assert template['skill'] == original['content'] and template['skill_name'] == original['name']
        assert template['variables'] == ['产品', '颜色']
        client.put(f"/api/skills/{skill['id']}", json={**original, 'revision': 1, 'content': '新版方法：检查横梁。'})
        assert client.get('/api/templates').json()[0]['skill_revision'] == 1
        fields = {'config_id': config.id, 'request_id': str(uuid4()), 'count': 1, 'template': json.dumps({'id': template['id'], 'revision': 1, 'variables': {'产品': '凉棚', '颜色': '灰色'}})}
        old_job = client.post('/api/image-jobs/batch', files=multipart(fields)).json()[0]
        assert '保持灰色，不增加侧帘。' in old_job['prompt'] and '新版方法' not in old_job['prompt']
        # Updating another template field keeps the pinned old Skill version.
        pinned = client.put(f"/api/templates/{template['id']}", json={**template_input, 'revision': 1, 'purpose': '新用途'}).json()
        assert pinned['skill_revision'] == 1 and pinned['revision'] == 2
        synced = client.put(f"/api/templates/{template['id']}", json={**template_input, 'revision': 2, 'skill_revision': 2}).json()
        assert synced['skill_revision'] == 2 and synced['revision'] == 3
        fields.update(request_id=str(uuid4()), template=json.dumps({'id': template['id'], 'revision': 3, 'variables': {'产品': '凉棚'}}))
        new_job = client.post('/api/image-jobs/batch', files=multipart(fields)).json()[0]
        assert '新版方法：检查横梁。' in new_job['prompt']
        assert client.get(f"/api/image-jobs/{old_job['id']}").json()['template_snapshot']['skill_revision'] == 1
        assert process_one(engine, directory, lambda *args: png())
        case = client.post('/api/cases', json={'job_id': old_job['id'], 'title': '旧版成功案例', 'experience': '保持结构有效'}).json()
        assert case['template_snapshot']['skill_revision'] == 1
        assert case['template_snapshot']['skill'] == original['content']
        exported = client.post('/api/image-jobs/exports', files=multipart({'job_ids': json.dumps([old_job['id']])}))
        with ZipFile(io.BytesIO(exported.content)) as archive:
            snapshot = json.loads(archive.read('manifest.json'))['items'][0]['template']
            assert snapshot['skill_revision'] == 1 and snapshot['skill_id'] == skill['id']


def test_invalid_skill_reference_does_not_save_a_template(setup):
    engine, directory, _ = setup
    with TestClient(create_app(directory, db_url=str(engine.url))) as client:
        assert client.post('/api/templates', json={'name': '模板', 'prompt': '场景', 'skill_id': str(uuid4()), 'skill_revision': 1}).status_code == 422
        assert client.post('/api/templates', json={'name': '模板', 'prompt': '场景', 'skill_revision': 1}).status_code == 422
        assert client.get('/api/templates').json() == []


@pytest.mark.parametrize('content', ['', '   ', 'x' * 20001])
def test_invalid_skill_content_is_rejected(setup, content):
    engine, directory, _ = setup
    with TestClient(create_app(directory, db_url=str(engine.url))) as client:
        assert client.post('/api/skills', json={'name': 'Skill', 'content': content}).status_code == 422
        assert client.get('/api/skills').json() == []


def test_skill_origin_guard_and_legacy_inline_template_compatibility(setup):
    engine, directory, _ = setup
    with TestClient(create_app(directory, db_url=str(engine.url))) as client:
        assert client.post('/api/skills', json={'name': 'Skill', 'content': '结构要求'}, headers={'Origin': 'https://bad.example'}).status_code == 403
        response = client.post('/api/templates', json={'name': '模板', 'prompt': '场景', 'skill': '原有内联要求'})
        assert response.status_code == 201
        assert response.json()['skill'] == '原有内联要求' and response.json()['skill_id'] is None
