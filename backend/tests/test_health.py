from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app.main import create_app


def test_health_returns_current_utc_time_without_database_configuration():
    with TestClient(create_app()) as client:
        before = datetime.now(timezone.utc)
        response = client.get("/api/health")
        after = datetime.now(timezone.utc)

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["service"] == "skill-forge-api"
    timestamp = datetime.fromisoformat(payload["timestamp"].replace("Z", "+00:00"))
    assert before <= timestamp <= after


def test_openapi_exposes_health_contract():
    with TestClient(create_app()) as client:
        response = client.get("/openapi.json")

    assert response.status_code == 200
    assert "/api/health" in response.json()["paths"]
