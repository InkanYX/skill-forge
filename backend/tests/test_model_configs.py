from unittest.mock import patch
import json

import httpx
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.main import create_app
from app.model_configs import ConfigInput, FileConfigStore, ProbeResult, ConnectionResult, probe_models, probe_connection, public_address


SECRET = "test-only-secret-not-a-real-key"
BASE = {"name": "测试服务", "base_url": "https://api.example.com/v1", "api_key": SECRET, "model_name": "image-test"}


def test_one_provider_saves_multiple_models_and_default_across_restarts(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        response = client.post('/api/model-configs', json={**BASE, 'model_names': [' image-test ', 'image-edit', 'image-test']})
        assert response.status_code == 201
        item = response.json()
        assert item['model_names'] == ['image-test', 'image-edit']
        assert SECRET not in response.text and 'encrypted_key' not in response.text
        updated = client.put(f"/api/model-configs/{item['id']}", json={**BASE, 'api_key': '', 'model_name': 'image-edit', 'model_names': item['model_names']})
        assert updated.status_code == 200 and updated.json()['model_name'] == 'image-edit'
    with TestClient(create_app(tmp_path)) as reopened:
        assert reopened.get('/api/model-configs').json()[0]['model_names'] == ['image-test', 'image-edit']
    store = FileConfigStore(tmp_path)
    assert store.resolve_key(item['id'], ConfigInput(**{**BASE, 'api_key': None})) == SECRET


def test_legacy_file_config_infers_its_single_model(tmp_path):
    store = FileConfigStore(tmp_path)
    item = store.save(ConfigInput(**BASE))
    records = json.loads(store.path.read_text(encoding='utf-8'))
    records[0].pop('model_names')
    store.path.write_text(json.dumps(records), encoding='utf-8')
    restored = FileConfigStore(tmp_path).list()[0]
    assert restored.id == item.id and restored.model_names == ['image-test']
    assert ConfigInput(name='test', base_url=BASE['base_url'], model_names=['a', 'b']).model_name == 'a'


@pytest.mark.parametrize('names,default', [(['a'], 'b'), ([''], ''), (['a' * 201], ''), (['a\nb'], ''), ([str(i) for i in range(51)], '')])
def test_invalid_multiple_models_do_not_replace_saved_config(tmp_path, names, default):
    with TestClient(create_app(tmp_path)) as client:
        item = client.post('/api/model-configs', json=BASE).json()
        response = client.put(f"/api/model-configs/{item['id']}", json={**BASE, 'model_names': names, 'model_name': default})
        assert response.status_code == 422 and SECRET not in response.text
        assert client.get('/api/model-configs').json()[0]['model_names'] == ['image-test']


def test_save_list_update_and_restart_never_expose_key(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        result = client.post("/api/model-configs", json=BASE)
        assert result.status_code == 201
        item = result.json()
        assert item["has_api_key"] is True
        assert SECRET not in result.text
        assert "api_key" not in item
        assert SECRET not in (tmp_path / "model-configs.json").read_text()
        updated = client.put(f"/api/model-configs/{item['id']}", json={**BASE, "name": "已更新", "api_key": ""})
        assert updated.status_code == 200
    with TestClient(create_app(tmp_path)) as client:
        items = client.get("/api/model-configs").json()
        assert len(items) == 1
        assert items[0]["name"] == "已更新"
    store = FileConfigStore(tmp_path)
    assert store.resolve_key(item["id"], ConfigInput(**{**BASE, "api_key": None})) == SECRET


@pytest.mark.parametrize('endpoint', ['test', 'models'])
def test_saved_key_cannot_be_sent_to_changed_endpoint(tmp_path, endpoint):
    called = []
    def probe(url, key):
        called.append(url)
        return ProbeResult(status="ok", message="ok")
    with TestClient(create_app(tmp_path, probe, connection_probe=probe)) as client:
        item = client.post("/api/model-configs", json=BASE).json()
        response = client.post(f"/api/model-configs/{endpoint}", json={**BASE, "config_id": item["id"], "base_url": "https://another.example.com/v1", "api_key": ""})
        assert response.status_code == 422
        assert called == []


def test_model_discovery_does_not_save_configuration(tmp_path):
    def probe(url, key):
        assert url == BASE["base_url"] and key == SECRET
        return ProbeResult(status="ok", message="已读取模型", models=["model-a"])
    with TestClient(create_app(tmp_path, probe)) as client:
        response = client.post("/api/model-configs/models", json=BASE)
        assert response.json()["models"] == ["model-a"]
        assert client.get("/api/model-configs").json() == []
    assert not (tmp_path / "config-encryption.key").exists()


def test_connection_and_discovery_are_independent_and_never_save(tmp_path):
    calls = []
    def connect(url, key):
        assert url == BASE['base_url'] and key == SECRET
        calls.append('connection')
        return ConnectionResult(status='ok', message='responded')
    def discover(url, key):
        assert key == SECRET
        calls.append('models')
        return ProbeResult(status='ok', message='read', models=['a', 'b'])
    with TestClient(create_app(tmp_path, discover, connection_probe=connect)) as client:
        connection = client.post('/api/model-configs/test', json=BASE)
        assert connection.status_code == 200 and connection.json() == {'status': 'ok', 'message': 'responded'}
        assert calls == ['connection']
        models = client.post('/api/model-configs/models', json=BASE)
        assert models.json()['models'] == ['a', 'b'] and calls == ['connection', 'models']
        assert SECRET not in connection.text + models.text
        assert client.get('/api/model-configs').json() == []
    assert not (tmp_path / 'config-encryption.key').exists()


@pytest.mark.parametrize('code,expected', [(200, 'ok'), (401, 'error'), (403, 'error'), (404, 'unsupported'), (405, 'unsupported'), (429, 'error'), (302, 'error'), (500, 'error')])
def test_connection_checks_headers_without_reading_response_or_following_redirects(code, expected):
    class UnreadBody(httpx.SyncByteStream):
        def __iter__(self):
            raise AssertionError('Connection test must not download a model list')
    calls = []
    def handle(request):
        calls.append(request)
        assert request.url.host == '8.8.8.8' and request.url.path == '/v1/models'
        assert request.headers['authorization'] == f'Bearer {SECRET}'
        assert request.headers['host'] == 'api.example.com'
        assert request.extensions['sni_hostname'] == 'api.example.com'
        return httpx.Response(code, stream=UnreadBody(), headers={'Location': 'https://other.example.com'})
    real_client = httpx.Client
    with patch('app.model_configs.public_address', return_value='8.8.8.8'), patch('app.model_configs.httpx.Client', side_effect=lambda **kwargs: real_client(transport=httpx.MockTransport(handle), **kwargs)):
        result = probe_connection(BASE['base_url'], SECRET)
    assert result.status == expected and 'models' not in result.model_dump()
    assert len(calls) == 1 and SECRET not in result.model_dump_json()


@pytest.mark.parametrize('exception', [httpx.ConnectError, httpx.ReadTimeout])
def test_connection_network_errors_do_not_echo_credentials(exception):
    def handle(request):
        raise exception(SECRET, request=request)
    real_client = httpx.Client
    with patch('app.model_configs.public_address', return_value='8.8.8.8'), patch('app.model_configs.httpx.Client', side_effect=lambda **kwargs: real_client(transport=httpx.MockTransport(handle), **kwargs)):
        result = probe_connection(BASE['base_url'], SECRET)
    assert result.status == 'error' and SECRET not in result.model_dump_json()


@pytest.mark.parametrize("url", ["http://api.example.com/v1", "https://127.0.0.1/v1", "https://localhost/v1", "https://10.0.0.1/v1", "https://user:password@api.example.com/v1", "https://api.example.com/v1?token=secret", "https://api.example.com/v1/responses"])
def test_unsafe_urls_rejected_without_echoing_secrets(tmp_path, url):
    with TestClient(create_app(tmp_path)) as client:
        response = client.post("/api/model-configs", json={**BASE, "base_url": url})
        assert response.status_code == 422
        assert SECRET not in response.text
        assert "password@" not in response.text


def test_cross_origin_and_form_requests_are_rejected(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        assert client.get("/api/model-configs", headers={"Origin": "https://untrusted.example"}).status_code == 403
        assert client.post("/api/model-configs", data={"name": "test"}).status_code == 415


def test_missing_encryption_key_does_not_replace_it(tmp_path):
    store = FileConfigStore(tmp_path)
    item = store.save(ConfigInput(**BASE))
    original = (tmp_path / "model-configs.json").read_bytes()
    (tmp_path / "config-encryption.key").unlink()
    with pytest.raises(HTTPException) as error:
        store.resolve_key(item.id, ConfigInput(**{**BASE, "api_key": None}))
    assert error.value.status_code == 503
    assert (tmp_path / "model-configs.json").read_bytes() == original
    assert not (tmp_path / "config-encryption.key").exists()


def test_corrupt_configuration_is_not_overwritten(tmp_path):
    path = tmp_path / "model-configs.json"
    path.write_text("corrupt", encoding="utf-8")
    with pytest.raises(HTTPException):
        FileConfigStore(tmp_path).save(ConfigInput(**BASE))
    assert path.read_text() == "corrupt"


@pytest.mark.parametrize("status,payload,expected", [
    (200, {"data": [{"id": "b"}, {"id": "a"}, {"id": "a"}]}, "ok"),
    (200, {"unexpected": "format"}, "unsupported"),
    (401, {"error": SECRET}, "error"),
    (404, {}, "unsupported"),
    (429, {}, "error"),
    (302, {}, "error"),
])
def test_provider_protocol_and_redacted_errors(status, payload, expected):
    real_client = httpx.Client
    def handle(request):
        assert request.url.host == "8.8.8.8"
        assert request.url.path == "/v1/models"
        assert request.headers["host"] == "api.example.com"
        assert request.extensions["sni_hostname"] == "api.example.com"
        assert request.headers["authorization"] == f"Bearer {SECRET}"
        return httpx.Response(status, json=payload)
    with patch("app.model_configs.public_address", return_value="8.8.8.8"), patch("app.model_configs.httpx.Client", side_effect=lambda **kwargs: real_client(transport=httpx.MockTransport(handle), **kwargs)):
        result = probe_models(BASE["base_url"], SECRET)
    assert result.status == expected
    assert SECRET not in result.model_dump_json()
    if expected == "ok":
        assert result.models == ["a", "b"]


def test_dns_private_address_is_rejected():
    with patch("app.model_configs.socket.getaddrinfo", return_value=[(2, 1, 6, "", ("127.0.0.1", 443))]):
        with pytest.raises(HTTPException) as error:
            public_address("public-looking.example.com")
    assert error.value.status_code == 422


def test_invalid_key_validation_never_returns_key(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        response = client.post("/api/model-configs", json={**BASE, "api_key": SECRET + "\ninvalid"})
    assert response.status_code == 422
    assert SECRET not in response.text


def test_origin_allowed_for_vite_proxy(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        response = client.get("/api/model-configs", headers={"Origin": "http://127.0.0.1:5173"})
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"


def test_provider_timeout_has_safe_message():
    real_client = httpx.Client
    def timeout(request):
        raise httpx.ReadTimeout(SECRET, request=request)
    with patch("app.model_configs.public_address", return_value="8.8.8.8"), patch("app.model_configs.httpx.Client", side_effect=lambda **kwargs: real_client(transport=httpx.MockTransport(timeout), **kwargs)):
        result = probe_models(BASE["base_url"], SECRET)
    assert result.status == "error"
    assert "超时" in result.message
    assert SECRET not in result.model_dump_json()


def test_provider_invalid_json_is_not_returned_to_browser():
    real_client = httpx.Client
    with patch("app.model_configs.public_address", return_value="8.8.8.8"), patch("app.model_configs.httpx.Client", side_effect=lambda **kwargs: real_client(transport=httpx.MockTransport(lambda request: httpx.Response(200, text=SECRET)), **kwargs)):
        result = probe_models(BASE["base_url"], SECRET)
    assert result.status == "unsupported"
    assert SECRET not in result.model_dump_json()
