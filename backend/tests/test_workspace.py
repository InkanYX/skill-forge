import json
from datetime import datetime, timezone
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.database import ImageJob
from app.main import create_app
from test_image_jobs import setup, enqueue, KEY


def test_workspace_counts_real_records_and_uses_shanghai_day_boundaries(setup):
    engine, directory, _ = setup
    rows = [enqueue(setup) for _ in range(7)]
    data = [
        ('queued', '2026-11-19T16:00:00+00:00', '2026-11-19T16:00:00+00:00'),
        ('succeeded', '2026-11-19T15:59:59+00:00', '2026-11-19T16:10:00+00:00'),
        ('running', '2026-11-19T16:05:00+00:00', '2026-11-19T16:05:00+00:00'),
        ('failed', '2026-11-19T15:00:00+00:00', '2026-11-19T15:00:00+00:00'),
        ('unknown', '2026-11-19T16:20:00+00:00', '2026-11-19T16:20:00+00:00'),
        ('cancelled', '2026-11-19T16:25:00+00:00', '2026-11-19T16:25:00+00:00'),
        ('succeeded', '2026-11-20T16:00:00+00:00', '2026-11-20T16:00:00+00:00'),
    ]
    with Session(engine) as session, session.begin():
        for item, (status, created, updated) in zip(rows, data):
            row = session.get(ImageJob, item.id)
            row.status, row.created_at, row.updated_at = status, created, updated
            row.shot_name = '结构细节'
            row.product_snapshot = json.dumps({'sku': 'SKU-TEST', 'name': '凉棚'})
    with TestClient(create_app(directory, db_url=str(engine.url))) as client:
        client.post('/api/products', json={'sku': 'sku-test', 'name': '凉棚'})
        client.post('/api/templates', json={'name': '庭院', 'prompt': '场景', 'skill': '完整 Skill 内容不应出现在工作台摘要'})
        client.post('/api/skills', json={'name': 'Skill', 'content': '完整 Skill 内容不应出现在工作台摘要'})
        client.post('/api/cases', json={'job_id': rows[1].id, 'title': '案例', 'experience': '结构清晰'})
        client.post('/api/model-configs', json={'name': '未设置模型', 'base_url': 'https://example.com/v1', 'api_key': KEY, 'model_name': ''})
        with patch('app.workspace.datetime') as clock:
            clock.now.return_value = datetime(2026, 11, 19, 16, 30, tzinfo=timezone.utc)
            response = client.get('/api/workspace')
        assert response.status_code == 200
        value = response.json()
        assert value['jobs'] == {'queued': 1, 'running': 1, 'succeeded': 2, 'failed': 1, 'unknown': 1, 'cancelled': 1}
        assert value['today'] == {'date': '2026-11-20', 'timezone': 'Asia/Shanghai', 'submitted': 4, 'completed': 1}
        assert value['resources'] == {'products': 1, 'templates': 1, 'skills': 1, 'cases': 1, 'model_configs': 2, 'available_models': 1}
        assert [item['id'] for item in value['active_jobs']] == [rows[2].id, rows[0].id]
        assert [item['id'] for item in value['attention_jobs']] == [rows[4].id, rows[3].id]
        assert {item['id'] for item in value['recent_images']} == {rows[1].id, rows[6].id}
        assert value['recent_templates'][0]['name'] == '庭院'
        assert value['recent_products'][0]['sku'] == 'SKU-TEST'
        assert value['active_jobs'][0]['title'] == '结构细节'
        assert KEY not in response.text and 'encrypted_key' not in response.text and 'base_url' not in response.text
        assert '完整 Skill 内容不应出现在工作台摘要' not in response.text
        assert response.headers['cache-control'] == 'no-store'


def test_workspace_limits_lists_but_counts_all_jobs_and_does_not_execute(setup):
    engine, directory, _ = setup
    rows = [enqueue(setup) for _ in range(20)]
    with TestClient(create_app(directory, db_url=str(engine.url))) as client:
        value = client.get('/api/workspace').json()
        assert value['jobs']['queued'] == 20 and len(value['active_jobs']) == 6
        assert value['recent_images'] == [] and value['attention_jobs'] == []
        client.get('/api/workspace')
    with Session(engine) as session:
        assert all(session.get(ImageJob, row.id).status == 'queued' for row in rows)


def test_empty_workspace_is_distinct_from_unavailable_database(setup, tmp_path):
    engine, directory, _ = setup
    with TestClient(create_app(directory, db_url=str(engine.url))) as client:
        value = client.get('/api/workspace').json()
        assert all(count == 0 for count in value['jobs'].values())
        assert value['resources']['products'] == 0 and value['resources']['available_models'] == 1
        assert client.get('/api/workspace', headers={'Origin': 'https://bad.example'}).status_code == 403
    with TestClient(create_app(tmp_path / 'file-only')) as client:
        assert client.get('/api/workspace').status_code == 503
        assert client.get('/api/health').status_code == 200
