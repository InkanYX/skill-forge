import json
from uuid import uuid4
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.main import create_app
from app.database import ImageJob
from app.image_jobs import process_one
from test_image_jobs import setup, png


def fields(values):
    return {key: (None, str(value)) for key, value in values.items()}


def test_product_sku_uniqueness_and_revision(setup):
    engine, directory, _ = setup
    with TestClient(create_app(directory, db_url=str(engine.url))) as client:
        data = {'sku': ' gazebo-01 ', 'name': '铝制凉棚', 'color': '深灰', 'dimensions': '3 m × 4 m'}
        first = client.post('/api/products', json=data)
        assert first.status_code == 201
        product = first.json()
        assert product['sku'] == 'GAZEBO-01' and product['revision'] == 1
        assert client.post('/api/products', json=data).status_code == 409
        updated = client.put(f"/api/products/{product['id']}", json={**data, 'revision': 1, 'color': '白色'})
        assert updated.status_code == 200 and updated.json()['revision'] == 2
        assert client.put(f"/api/products/{product['id']}", json={**data, 'revision': 1}).status_code == 409
        assert len(client.get('/api/products').json()) == 1
        assert client.post('/api/products', json={'sku': ' ', 'name': ' '}).status_code == 422
        assert client.post('/api/products', json=data, headers={'Origin': 'https://bad.example'}).status_code == 403


def test_asset_upload_validation_and_idempotency(setup):
    engine, directory, _ = setup
    with TestClient(create_app(directory, db_url=str(engine.url))) as client:
        product = client.post('/api/products', json={'sku': 'test1', 'name': '产品'}).json()
        path = f"/api/products/{product['id']}/assets"
        identifier = str(uuid4())
        def upload(content=png(), kind='产品实拍', origin=None):
            return client.post(path, data={'asset_id': identifier, 'kind': kind}, files={'image': ('photo.png', content, 'image/png')}, headers={'Origin': origin} if origin else {})
        first = upload()
        assert first.status_code == 201
        asset = first.json()
        assert upload().json()['id'] == asset['id']
        assert len(client.get(path).json()) == 1
        assert upload(kind='尺寸图').status_code == 409
        assert upload(b'not-an-image').status_code == 422
        assert upload(origin='https://bad.example').status_code == 403
        assert client.get(asset['image_url']).content == png()
        assert client.get(f"/api/products/{uuid4()}/assets/{asset['id']}/image").status_code == 404


def test_product_job_snapshot_and_case_survive_product_edits(setup):
    engine, directory, config = setup
    with TestClient(create_app(directory, db_url=str(engine.url))) as client:
        data = {'sku': 'pergola-1', 'name': '凉棚', 'color': '深灰', 'dimensions': '3 m × 4 m', 'facts': '四根立柱', 'notes': '不新增侧帘'}
        product = client.post('/api/products', json=data).json()
        asset = client.post(f"/api/products/{product['id']}/assets", data={'asset_id': str(uuid4())}, files={'image': ('product.png', png(), 'image/png')}).json()
        template = client.post('/api/templates', json={'name': '庭院', 'prompt': '{{产品名称}}置于庭院，颜色{{颜色}}'}).json()
        job_fields = {'config_id': config.id, 'request_id': str(uuid4()), 'count': '2', 'product': json.dumps({'id': product['id'], 'revision': 1, 'asset_id': asset['id']}), 'template': json.dumps({'id': template['id'], 'revision': 1, 'variables': {'产品名称': '凉棚', '颜色': '深灰'}})}
        def submit():
            return client.post('/api/image-jobs/batch', files=fields(job_fields))
        response = submit()
        assert response.status_code == 202
        rows = response.json()
        assert rows[0]['mode'] == 'edit'
        assert rows[0]['product_snapshot']['sku'] == 'PERGOLA-1'
        assert '四根立柱' in rows[0]['prompt'] and '3 m × 4 m' in rows[0]['prompt']
        assert client.put(f"/api/products/{product['id']}", json={**data, 'revision': 1, 'color': '白色'}).status_code == 200
        assert [row['id'] for row in submit().json()] == [row['id'] for row in rows]
        job_fields['request_id'] = str(uuid4())
        assert submit().status_code == 409
        def provider(*args):
            assert args[-1] == png()
            assert '深灰' in args[3]
            return png()
        assert process_one(engine, directory, provider)
        case = client.post('/api/cases', json={'job_id': rows[0]['id'], 'title': '成功案例', 'experience': '结构清晰'}).json()
        assert case['product_snapshot']['color'] == '深灰'
        assert case['product_snapshot']['revision'] == 1
        assert client.get(f"/api/image-jobs/{rows[0]['id']}/reference").content == png()
        assert len(client.get('/api/image-jobs').json()) == 2


def test_asset_from_another_product_and_double_reference_are_rejected(setup):
    engine, directory, config = setup
    with TestClient(create_app(directory, db_url=str(engine.url))) as client:
        p1 = client.post('/api/products', json={'sku': 'p1', 'name': '产品一'}).json()
        p2 = client.post('/api/products', json={'sku': 'p2', 'name': '产品二'}).json()
        asset = client.post(f"/api/products/{p1['id']}/assets", data={'asset_id': str(uuid4())}, files={'image': ('photo.png', png(), 'image/png')}).json()
        data = {'config_id': config.id, 'request_id': str(uuid4()), 'prompt': '场景图', 'product': json.dumps({'id': p2['id'], 'revision': 1, 'asset_id': asset['id']})}
        assert client.post('/api/image-jobs/batch', files=fields(data)).status_code == 422
        data['product'] = json.dumps({'id': p1['id'], 'revision': 1, 'asset_id': asset['id']})
        assert client.post('/api/image-jobs/batch', files={**fields(data), 'reference': ('photo.png', png(), 'image/png')}).status_code == 422
        with Session(engine) as session:
            assert not list(session.scalars(select(ImageJob)))


def test_product_can_use_uploaded_reference_or_no_reference(setup):
    engine, directory, config = setup
    with TestClient(create_app(directory, db_url=str(engine.url))) as client:
        product = client.post('/api/products', json={'sku': 'p1', 'name': '产品一'}).json()
        data = {'config_id': config.id, 'request_id': str(uuid4()), 'prompt': '场景图', 'count': '1', 'product': json.dumps({'id': product['id'], 'revision': 1})}
        response = client.post('/api/image-jobs/batch', files=fields(data))
        assert response.status_code == 202 and response.json()[0]['mode'] == 'generate'
        data['request_id'] = str(uuid4())
        response = client.post('/api/image-jobs/batch', files={**fields(data), 'reference': ('photo.png', png(), 'image/png')})
        assert response.status_code == 202 and response.json()[0]['mode'] == 'edit'
