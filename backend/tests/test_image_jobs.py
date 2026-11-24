import base64
import json
import io
import time
from unittest.mock import patch
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import Base, DatabaseConfigStore, ImageJob, make_engine
from app.image_jobs import artifact, create_job, process_one
from app.image_provider import GenerationError, generate_image, normalize_image
from app.main import create_app
from app.model_configs import ConfigInput

KEY = "test-image-key-not-a-real-credential"


def png():
    value = io.BytesIO()
    Image.new("RGB", (12, 8), "blue").save(value, "PNG")
    return value.getvalue()


@pytest.fixture
def setup(tmp_path):
    engine = make_engine(f"sqlite:///{(tmp_path / 'images.db').as_posix()}")
    Base.metadata.create_all(engine)
    directory = tmp_path / "data"
    config = DatabaseConfigStore(directory, engine).save(ConfigInput(name="测试图片接口", base_url="https://images.example.com/v1", model_name="image-test", api_key=KEY))
    yield engine, directory, config
    engine.dispose()


def enqueue(setup, reference=None, request_id=None):
    engine, directory, config = setup
    return create_job(engine, directory, config.id, "image-test", "保留结构，生成庭院场景", "default", request_id or str(uuid4()), reference)


def test_job_runs_and_artifacts_remain_after_api_reopens(setup):
    engine, directory, config = setup
    item = enqueue(setup, png())
    calls = []
    def provider(url, key, model, prompt, size, reference):
        calls.append(key)
        assert key == KEY and reference == png() and model == "image-test"
        return png()
    assert process_one(engine, directory, provider)
    assert not process_one(engine, directory, provider)
    assert len(calls) == 1
    with TestClient(create_app(directory, db_url=str(engine.url))) as client:
        result = client.get(f"/api/image-jobs/{item.id}")
        assert result.json()["status"] == "succeeded"
        assert KEY not in result.text and "encrypted_key" not in result.text
        assert client.get(f"/api/image-jobs/{item.id}/image").content == png()
        assert client.get(f"/api/image-jobs/{item.id}/reference").content == png()
        download = client.get(f"/api/image-jobs/{item.id}/image?download=true")
        assert "attachment" in download.headers["content-disposition"]
        assert len(client.get("/api/image-jobs").json()) == 1
    with Session(engine) as session:
        assert session.get(ImageJob, item.id).encrypted_key == ""


def test_duplicate_submission_reuses_job(setup):
    identifier = str(uuid4())
    first = enqueue(setup, request_id=identifier)
    second = enqueue(setup, request_id=identifier)
    assert first.id == second.id
    with Session(setup[0]) as session:
        assert len(list(session.scalars(select(ImageJob)))) == 1


def test_conflicting_idempotency_key_rejected(setup):
    from fastapi import HTTPException
    engine, directory, config = setup
    identifier = str(uuid4())
    enqueue(setup, request_id=identifier)
    with pytest.raises(HTTPException) as error:
        create_job(engine, directory, config.id, "image-test", "另一个要求", "default", identifier, None)
    assert error.value.status_code == 409


@pytest.mark.parametrize("uncertain,expected", [(True, "unknown"), (False, "failed")])
def test_error_never_requeues_paid_requests(setup, uncertain, expected):
    engine, directory, _ = setup
    job = enqueue(setup)
    def provider(*args):
        raise GenerationError("安全错误提示", uncertain)
    assert process_one(engine, directory, provider)
    assert not process_one(engine, directory, provider)
    with Session(engine) as session:
        assert session.get(ImageJob, job.id).status == expected


def test_expired_running_job_is_not_called_again(setup):
    engine, directory, _ = setup
    job = enqueue(setup)
    with Session(engine) as session, session.begin():
        row = session.get(ImageJob, job.id)
        row.status = "running"
        row.lease_until = time.time() - 1
    def provider(*args):
        pytest.fail("expired job must not be regenerated")
    assert not process_one(engine, directory, provider)
    with Session(engine) as session:
        assert session.get(ImageJob, job.id).status == "unknown"


def test_multipart_submission_and_invalid_upload(setup):
    engine, directory, config = setup
    with TestClient(create_app(directory, db_url=str(engine.url))) as client:
        fields = {"config_id": config.id, "request_id": str(uuid4()), "prompt": "真实产品场景", "model_name": "image-test"}
        response = client.post("/api/image-jobs", data=fields, files={"reference": ("photo.png", png(), "image/png")})
        assert response.status_code == 202
        assert response.json()["mode"] == "edit"
        assert client.get(f"/api/image-jobs/{response.json()['id']}/image").status_code == 404
        fields["request_id"] = str(uuid4())
        response = client.post("/api/image-jobs", data=fields, files={"reference": ("fake.png", b"not-an-image", "image/png")})
        assert response.status_code == 422
        assert client.post("/api/image-jobs", data=fields, files={"reference": ("photo.png", png(), "image/png")}, headers={"Origin": "https://bad.example"}).status_code == 403


def test_invalid_image_and_path_are_rejected():
    with pytest.raises(GenerationError):
        normalize_image(b"not-an-image")
    with pytest.raises(ValueError):
        artifact(__import__('pathlib').Path('.'), '../../secret', 'result.png')


def test_queued_config_snapshot_is_not_changed_by_editing_configuration(setup):
    engine, directory, config = setup
    enqueue(setup)
    DatabaseConfigStore(directory, engine).save(ConfigInput(name="变更接口", base_url="https://another.example.com/v1", model_name="other", api_key="a-different-test-key"), config.id)
    def provider(url, key, model, *args):
        assert url == "https://images.example.com/v1" and key == KEY and model == "image-test"
        return png()
    assert process_one(engine, directory, provider)


@pytest.mark.parametrize("reference", [None, True])
def test_images_protocol_uses_one_post_with_expected_payload(reference):
    real_client = httpx.Client
    calls = []
    def handle(request):
        calls.append(request)
        assert request.headers["authorization"] == f"Bearer {KEY}"
        assert request.url.path == ("/v1/images/edits" if reference else "/v1/images/generations")
        if reference:
            assert 'multipart/form-data' in request.headers['content-type']
            assert b'name="image"' in request.content
        else:
            import json
            assert json.loads(request.content)["n"] == 1
        return httpx.Response(200, json={"data": [{"b64_json": base64.b64encode(png()).decode()}]})
    with patch("app.image_provider.public_address", return_value="8.8.8.8"), patch("app.image_provider.httpx.Client", side_effect=lambda **kwargs: real_client(transport=httpx.MockTransport(handle), **kwargs)):
        output = generate_image("https://images.example.com/v1", KEY, "image-test", "scene", "default", png() if reference else None)
    assert output == png() and len(calls) == 1


def test_image_download_does_not_receive_provider_key():
    real_client = httpx.Client
    def handle(request):
        if request.method == "POST":
            return httpx.Response(200, json={"data": [{"url": "https://cdn.example.com/result.png"}]})
        assert "authorization" not in request.headers
        return httpx.Response(200, content=png())
    with patch("app.image_provider.public_address", return_value="8.8.8.8"), patch("app.image_provider.httpx.Client", side_effect=lambda **kwargs: real_client(transport=httpx.MockTransport(handle), **kwargs)):
        assert generate_image("https://images.example.com/v1", KEY, "image-test", "scene", "default", None) == png()


def test_timeout_does_not_leak_credentials_or_retry():
    real_client = httpx.Client
    calls = []
    def handle(request):
        calls.append(request)
        raise httpx.ReadTimeout(KEY)
    with patch("app.image_provider.public_address", return_value="8.8.8.8"), patch("app.image_provider.httpx.Client", side_effect=lambda **kwargs: real_client(transport=httpx.MockTransport(handle), **kwargs)):
        with pytest.raises(GenerationError) as error:
            generate_image("https://images.example.com/v1", KEY, "image-test", "scene", "default", None)
    assert error.value.uncertain
    assert KEY not in error.value.message
    assert len(calls) == 1


def test_rejected_download_address_preserves_uncertain_outcome():
    from fastapi import HTTPException
    real_client = httpx.Client
    calls = []
    def handle(request):
        calls.append(request)
        return httpx.Response(200, json={"data": [{"url": "https://cdn.example.com/result.png"}]})
    with patch("app.image_provider.public_address", side_effect=["8.8.8.8", HTTPException(400, "blocked")]), patch("app.image_provider.httpx.Client", side_effect=lambda **kwargs: real_client(transport=httpx.MockTransport(handle), **kwargs)):
        with pytest.raises(GenerationError) as error:
            generate_image("https://images.example.com/v1", KEY, "image-test", "scene", "default", None)
    assert error.value.uncertain
    assert len(calls) == 1


def test_batch_uses_saved_model_and_retries_reuse_all_jobs(setup):
    engine, directory, config = setup
    with TestClient(create_app(directory, db_url=str(engine.url))) as client:
        fields = {"config_id": config.id, "request_id": str(uuid4()), "prompt": "庭院场景", "count": "4"}
        def submit():
            return client.post("/api/image-jobs/batch", data=fields, files={"reference": ("photo.png", png(), "image/png")})
        first = submit()
        assert first.status_code == 202
        rows = first.json()
        assert len(rows) == 4 and len({row['id'] for row in rows}) == 4
        assert all(row['model_name'] == 'image-test' and row['status'] == 'queued' for row in rows)
        assert [row['id'] for row in submit().json()] == [row['id'] for row in rows]
        fields['count'] = '2'
        assert submit().status_code == 409
        calls = []
        def provider(*args):
            calls.append(args)
            assert args[-1] == png()
            if len(calls) == 2:
                raise GenerationError('其中一张未完成')
            return png()
        for _ in range(4):
            assert process_one(engine, directory, provider)
        assert not process_one(engine, directory, provider)
        jobs = client.get('/api/image-jobs').json()
        assert len(jobs) == 4
        assert sum(job['status'] == 'succeeded' for job in jobs) == 3
        assert sum(job['status'] == 'failed' for job in jobs) == 1


@pytest.mark.parametrize('kind', ['batch', 'sets', 'edit'])
def test_all_creation_flows_use_selected_saved_model_and_keep_queued_snapshot(setup, kind):
    engine, directory, config = setup
    source = None
    if kind == 'edit':
        source = enqueue(setup)
        assert process_one(engine, directory, lambda *args: png())
    with TestClient(create_app(directory, db_url=str(engine.url))) as client:
        config_data = {'name': config.name, 'base_url': config.base_url, 'api_key': '', 'model_name': 'image-test', 'model_names': ['image-test', 'image:edit/v2']}
        assert client.put(f'/api/model-configs/{config.id}', json=config_data).status_code == 200
        fields = {'config_id': config.id, 'request_id': str(uuid4()), 'prompt': 'scene', 'count': '1', 'model_name': 'not-saved'}
        if kind == 'sets':
            fields['plan'] = json.dumps({'name': 'set', 'shots': [{'name': 'scene', 'prompt': 'scene'}]})
        if source:
            fields['source_job_id'] = source.id
        path = '/api/image-jobs/sets' if kind == 'sets' else '/api/image-jobs/batch'
        def submit():
            return client.post(path, files={key: (None, value) for key, value in fields.items()})
        rejected = submit()
        assert rejected.status_code == 422 and KEY not in rejected.text
        fields['model_name'] = 'image:edit/v2'
        response = submit()
        assert response.status_code == 202
        item = response.json()[0]
        assert item['model_name'] == 'image:edit/v2' and item['config_id'] == config.id
        assert submit().json()[0]['id'] == item['id']
        fields['model_name'] = 'image-test'
        assert submit().status_code == 409
        # A provider-config change does not alter an accepted job or its retry.
        config_data['model_names'] = ['image-test']
        assert client.put(f'/api/model-configs/{config.id}', json=config_data).status_code == 200
        fields['model_name'] = 'image:edit/v2'
        assert submit().json()[0]['id'] == item['id']
        seen = []
        def provider(*args):
            seen.append(args[2])
            return png()
        assert process_one(engine, directory, provider)
        assert seen == ['image:edit/v2']
        fields['request_id'] = str(uuid4())
        assert submit().status_code == 422


@pytest.mark.parametrize('count', ['0', '17', 'abc'])
def test_invalid_batch_count_creates_no_jobs(setup, count):
    engine, directory, config = setup
    with TestClient(create_app(directory, db_url=str(engine.url))) as client:
        fields = {'config_id': config.id, 'request_id': str(uuid4()), 'prompt': 'scene', 'count': count}
        response = client.post('/api/image-jobs/batch', data=fields, files={'reference': ('photo.png', png(), 'image/png')})
        assert response.status_code == 422
        assert client.get('/api/image-jobs').json() == []


def test_text_only_batch_requires_saved_model(setup):
    engine, directory, config = setup
    with TestClient(create_app(directory, db_url=str(engine.url))) as client:
        fields = {'config_id': config.id, 'request_id': str(uuid4()), 'prompt': 'scene', 'count': '2'}
        # A browser FormData payload remains multipart even without a file.
        response = client.post('/api/image-jobs/batch', files={key: (None, value) for key, value in fields.items()})
        assert response.status_code == 202
        assert len(response.json()) == 2
        assert all(row['mode'] == 'generate' for row in response.json())
        DatabaseConfigStore(directory, engine).save(ConfigInput(name='无模型', base_url='https://images.example.com/v1', model_name='', api_key=''), config.id)
        fields['request_id'] = str(uuid4())
        response = client.post('/api/image-jobs/batch', files={key: (None, value) for key, value in fields.items()})
        assert response.status_code == 422
        assert len(client.get('/api/image-jobs').json()) == 2


def test_template_snapshot_revision_retry_and_case_roundtrip(setup):
    import json
    engine, directory, config = setup
    with TestClient(create_app(directory, db_url=str(engine.url))) as client:
        draft = {'name': '庭院模板', 'prompt': '为{{ 产品 }}制作庭院图', 'skill': '保持{{颜色}}与真实结构', 'notes': '不增加配件', 'count': 2}
        template = client.post('/api/templates', json=draft).json()
        assert template['revision'] == 1 and template['variables'] == ['产品', '颜色']
        fields = {'config_id': config.id, 'request_id': str(uuid4()), 'prompt': '自然光', 'count': '2', 'template': json.dumps({'id': template['id'], 'revision': 1, 'variables': {'产品': '凉棚', '颜色': '深灰'}})}
        def submit():
            return client.post('/api/image-jobs/batch', files={key: (None, value) for key, value in fields.items()})
        response = submit()
        assert response.status_code == 202
        jobs = response.json()
        assert len(jobs) == 2 and '凉棚' in jobs[0]['prompt'] and '深灰' in jobs[0]['prompt']
        assert jobs[0]['template_snapshot']['skill'] == draft['skill']
        changed = client.put(f"/api/templates/{template['id']}", json={**draft, 'revision': 1, 'skill': '新方法'}).json()
        assert changed['revision'] == 2
        assert client.put(f"/api/templates/{template['id']}", json={**draft, 'revision': 1}).status_code == 409
        assert [item['id'] for item in submit().json()] == [item['id'] for item in jobs]
        fields['request_id'] = str(uuid4())
        assert submit().status_code == 409
        case = {'job_id': jobs[0]['id'], 'title': '庭院展示', 'experience': '保留结构有效', 'issues': '还需人工核对颜色'}
        assert client.post('/api/cases', json=case).status_code == 422
        assert process_one(engine, directory, lambda *args: png())
        saved = client.post('/api/cases', json=case)
        assert saved.status_code == 200
        assert client.post('/api/cases', json={**case, 'experience': '更新经验'}).json()['id'] == saved.json()['id']
        cases = client.get('/api/cases').json()
        assert len(cases) == 1 and cases[0]['experience'] == '更新经验'
        assert cases[0]['template_snapshot']['revision'] == 1
        assert cases[0]['template_snapshot']['skill'] == draft['skill']
        assert KEY not in str(cases)


@pytest.mark.parametrize('template_request', [[], {'id': 5, 'revision': 1, 'variables': {}}, {'id': str(uuid4()), 'revision': 1, 'variables': {}}])
def test_invalid_template_request_cannot_create_jobs(setup, template_request):
    import json
    engine, directory, config = setup
    with TestClient(create_app(directory, db_url=str(engine.url))) as client:
        fields = {'config_id': config.id, 'request_id': str(uuid4()), 'prompt': '', 'template': json.dumps(template_request)}
        response = client.post('/api/image-jobs/batch', files={key: (None, value) for key, value in fields.items()})
        assert response.status_code in (404, 422)
        assert client.get('/api/image-jobs').json() == []


def test_template_missing_variables_and_origin_guard(setup):
    import json
    engine, directory, config = setup
    with TestClient(create_app(directory, db_url=str(engine.url))) as client:
        draft = {'name': '模板', 'prompt': '{{产品}}'}
        assert client.post('/api/templates', json=draft, headers={'Origin': 'https://bad.example'}).status_code == 403
        template = client.post('/api/templates', json=draft).json()
        fields = {'config_id': config.id, 'request_id': str(uuid4()), 'template': json.dumps({'id': template['id'], 'revision': 1, 'variables': {}})}
        response = client.post('/api/image-jobs/batch', files={key: (None, value) for key, value in fields.items()})
        assert response.status_code == 422
        assert client.get('/api/image-jobs').json() == []
