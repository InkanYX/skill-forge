from unittest.mock import patch

import httpx
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.main import create_app
from app.model_configs import ConfigInput, FileConfigStore, ProbeResult, probe_models, public_address


SECRET = "test-only-secret-not-a-real-key"
BASE = {"name": "测试服务", "base_url": "https://api.example.com/v1", "api_key": SECRET, "model_name": "image-test"}


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


def test_saved_key_cannot_be_sent_to_changed_endpoint(tmp_path):
    called = []
    def probe(url, key):
        called.append(url)
        return ProbeResult(status="ok", message="ok")
    with TestClient(create_app(tmp_path, probe)) as client:
        item = client.post("/api/model-configs", json=BASE).json()
        response = client.post("/api/model-configs/test", json={**BASE, "config_id": item["id"], "base_url": "https://another.example.com/v1", "api_key": ""})
        assert response.status_code == 422
        assert called == []


def test_connection_test_does_not_save_configuration(tmp_path):
    def probe(url, key):
        assert url == BASE["base_url"] and key == SECRET
        return ProbeResult(status="ok", message="已读取模型", models=["model-a"])
    with TestClient(create_app(tmp_path, probe)) as client:
        response = client.post("/api/model-configs/test", json=BASE)
        assert response.json()["models"] == ["model-a"]
        assert client.get("/api/model-configs").json() == []
    assert not (tmp_path / "config-encryption.key").exists()


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
