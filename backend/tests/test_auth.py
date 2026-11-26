import hashlib
import json
import time
from uuid import uuid4
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, update, func
from sqlalchemy.orm import Session
from app.database import Base, make_engine, UserAccount, LoginSession, ImageConfiguration
from app.auth import initialize_admin, verify_password
from app.main import create_app
from app.standard_image_worker import process_standard_one

OLD='temporary-admin-password'
NEW='changed-admin-password'

@pytest.fixture
def accounts(tmp_path):
    engine=make_engine(f"sqlite:///{(tmp_path/'accounts.db').as_posix()}")
    Base.metadata.create_all(engine)
    initialize_admin(engine,'admin',OLD)
    app=create_app(tmp_path/'data',db_url=str(engine.url),enable_auth=True,enable_standard=True,start_image_worker=False)
    with TestClient(app) as admin:
        assert admin.post('/api/auth/login',json={'username':'admin','password':OLD}).status_code==200
        assert admin.post('/api/auth/password',json={'current_password':OLD,'new_password':NEW}).status_code==200
        yield admin,app,engine,tmp_path/'data'
    engine.dispose()

def member(accounts,name='member'):
    admin,app,_,_=accounts
    issued=admin.post('/api/admin/users',json={'username':name,'display_name':name})
    assert issued.status_code==201,issued.text
    data=issued.json();client=TestClient(app)
    assert client.post('/api/auth/login',json={'username':name,'password':data['temporary_password']}).status_code==200
    assert client.post('/api/auth/password',json={'current_password':data['temporary_password'],'new_password':name+'-new-password'}).status_code==200
    return client,data['user']

def test_login_gate_password_rotation_logout_and_no_registration(accounts):
    admin,app,engine,_=accounts
    client=TestClient(app)
    assert client.get('/api/health').status_code==200
    for path in ('products','model-configs','image-configs','image-jobs','admin/users'):
        assert client.get('/api/'+path).status_code==401
    assert client.post('/api/auth/register',json={}).status_code in (401,404)
    issued=admin.post('/api/admin/users',json={'username':'new-person'}).json()
    reply=client.post('/api/auth/login',json={'username':'new-person','password':issued['temporary_password']})
    assert reply.status_code==200 and reply.json()['must_change_password']
    assert 'httponly' in reply.headers['set-cookie'].lower() and 'samesite=strict' in reply.headers['set-cookie'].lower()
    old=client.cookies.get('sf_login')
    assert client.get('/api/products').status_code==403
    assert client.post('/api/auth/password',json={'current_password':issued['temporary_password'],'new_password':'new-person-password'}).status_code==200
    assert client.cookies.get('sf_login')!=old
    expired=TestClient(app);expired.cookies.set('sf_login',old)
    assert expired.get('/api/products').status_code==401
    assert client.get('/api/products').status_code==200
    assert client.post('/api/auth/logout',json={}).status_code==200
    assert client.get('/api/products').status_code==401
    with Session(engine) as session:
        row=session.scalar(select(UserAccount).where(UserAccount.username=='new-person'))
        assert issued['temporary_password'] not in row.password_hash and verify_password('new-person-password',row.password_hash)

def test_member_cannot_escalate_or_administer(accounts):
    admin,app,engine,_=accounts
    client,user=member(accounts)
    assert client.get('/api/admin/users').status_code==403
    assert client.post('/api/admin/users',json={'username':'intruder','role':'admin'}).status_code==403
    assert client.put('/api/admin/users/'+user['id'],json={'display_name':'admin','is_active':True,'role':'admin'}).status_code==403
    assert admin.post('/api/admin/users',json={'username':'not-admin','role':'admin'}).json()['user']['role']=='member'
    actor=admin.get('/api/auth/me').json()['user']
    assert admin.put('/api/admin/users/'+actor['id'],json={'display_name':'admin','is_active':False}).status_code==409
    with pytest.raises(Exception):initialize_admin(engine,'another-admin','password')

def test_personal_content_is_private_even_from_admin(accounts):
    admin,_,_,_=accounts
    first,user=member(accounts,'alice');second,_=member(accounts,'bob')
    product=first.post('/api/products',json={'sku':'AUTH-PRODUCT','name':'pergola'}).json()
    assert product['owner_id']==user['id'] and product['can_edit']
    assert second.get('/api/products').json()==[]
    assert admin.get('/api/products').json()==[]
    assert second.put('/api/products/'+product['id'],json={'sku':'AUTH-PRODUCT','name':'tampered','revision':1}).status_code==404
    assert second.post('/api/products',json={'sku':'MY-COPY','name':'pergola'}).status_code==201
    template=first.post('/api/templates',json={'name':'template','prompt':'same product'}).json()
    assert second.put('/api/templates/'+template['id'],json={'name':'tampered','prompt':'wrong','revision':1}).status_code==404
    assert second.post('/api/templates',json={'name':'copy','prompt':template['prompt']}).status_code==201
    skill=first.post('/api/skills',json={'name':'skill','content':'keep structure'}).json()
    assert second.put('/api/skills/'+skill['id'],json={'name':'tampered','content':'wrong','revision':1}).status_code==404
    assert admin.put('/api/products/'+product['id'],json={'sku':'AUTH-PRODUCT','name':'admin edit','revision':1}).status_code==404
    assert next(p for p in first.get('/api/products').json() if p['id']==product['id'])['owner_id']==user['id']

def test_private_connections_isolated_even_from_admin(accounts):
    admin,_,_,_=accounts
    first,_=member(accounts,'alice');second,_=member(accounts,'bob')
    config=first.put('/api/image-configs',json={'base_url':'https://images.example.com/v1','api_key':'private-image-key'}).json()
    legacy=first.post('/api/model-configs',json={'base_url':'https://text.example.com/v1','api_key':'private-text-key','model_name':'chat-test'}).json()
    for client in (second,admin):
        assert client.get('/api/image-configs').json() is None and client.get('/api/model-configs').json()==[]
        assert client.post('/api/image-configs/models',json={'text_config_id':legacy['id']}).status_code==404
        assert client.put('/api/model-configs/'+legacy['id'],json={'base_url':'https://text.example.com/v1','model_name':'chat-test'}).status_code==404
        assert client.post('/api/image-jobs/batch',files={k:(None,v) for k,v in {'config_id':config['id'],'request_id':str(uuid4()),'prompt':'test'}.items()}).status_code==404
    assert config['has_api_key'] and 'private-image-key' not in json.dumps(config)

def test_disable_revokes_sessions_cancels_queue_and_blocks_other_task_mutations(accounts):
    admin,app,_,_=accounts
    first,user=member(accounts,'alice');second,_=member(accounts,'bob')
    config=first.put('/api/image-configs',json={'base_url':'https://images.example.com/v1','api_key':'private-key','model_name':'image-test'}).json()
    submitted=first.post('/api/image-jobs/batch',files={k:(None,v) for k,v in {'config_id':config['id'],'request_id':str(uuid4()),'prompt':'test'}.items()})
    assert submitted.status_code==202,submitted.text
    job=submitted.json()[0]
    assert job['owner_id']==user['id'] and second.get('/api/image-jobs/'+job['id']).status_code==404
    for path in (job['id'], 'tasks/'+job['task_id']):
        assert second.post('/api/image-jobs/'+path+'/cancel',files={'action':(None,'cancel')}).status_code==404
    assert admin.put('/api/admin/users/'+user['id'],json={'display_name':'alice','is_active':False}).status_code==200
    assert first.get('/api/products').status_code==401
    assert admin.get('/api/image-jobs/'+job['id']).status_code==404
    from app.database import ImageJob
    with Session(accounts[2]) as session: assert session.get(ImageJob,job['id']).status=='cancelled'
    assert not process_standard_one(app.state.image_configs,lambda *args:pytest.fail('disabled user must not generate'))
    assert not app.state.image_configs.keys.get(config['id'])
    assert admin.put('/api/admin/users/'+user['id'],json={'display_name':'alice','is_active':True}).status_code==200
    assert first.get('/api/products').status_code==401

def test_reset_password_revokes_existing_sessions_and_forces_change(accounts):
    admin,_,_,_=accounts
    client,user=member(accounts)
    reset=admin.post('/api/admin/users/'+user['id']+'/reset-password',json={}).json()
    assert client.get('/api/products').status_code==401
    assert client.post('/api/auth/login',json={'username':'member','password':'member-new-password'}).status_code==401
    assert client.post('/api/auth/login',json={'username':'member','password':reset['temporary_password']}).json()['must_change_password']
    assert client.get('/api/products').status_code==403
    assert 'password_hash' not in admin.get('/api/admin/users').text

def test_expired_forged_sessions_and_cross_origin_are_rejected(accounts):
    admin,app,engine,_=accounts
    client,user=member(accounts)
    with Session(engine) as session,session.begin():
        session.execute(update(LoginSession).where(LoginSession.user_id==user['id']).values(expires_at=time.time()-1))
    assert client.get('/api/products').status_code==401
    forged=TestClient(app);forged.cookies.set('sf_login','a'*43)
    assert forged.get('/api/products').status_code==401
    assert forged.post('/api/auth/login',headers={'Origin':'https://untrusted.example'},json={'username':'admin','password':NEW}).status_code==403

def test_legacy_browser_profile_only_binds_to_admin(accounts):
    admin,app,engine,_=accounts
    token='b'*43
    with Session(engine) as session,session.begin():
        session.add(ImageConfiguration(id=str(uuid4()),owner=hashlib.sha256(token.encode()).hexdigest(),name='legacy image',base_url='https://images.example.com/v1',revision=str(uuid4()),updated_at='2026-11-23'))
    admin.cookies.set('sf_image_session',token)
    assert admin.post('/api/auth/login',json={'username':'admin','password':NEW}).status_code==200
    assert admin.get('/api/image-configs').json()['name']=='legacy image'
    client,_=member(accounts)
    client.cookies.set('sf_image_session',token)
    assert client.get('/api/image-configs').json() is None
