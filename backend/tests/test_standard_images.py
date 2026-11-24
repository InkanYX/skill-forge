import hashlib
import io
import json
import os
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4
import httpx
import openai
import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.database import ImageJob, ImageConfiguration, Base, make_engine
from app.main import create_app
from app.image_jobs import process_one
from app.image_provider import GenerationError
from app.standard_image_worker import process_standard_one
from app.standard_image_executor import execute_cli
from test_image_jobs import png

KEY = 'standard-image-unit-test-secret'

@pytest.fixture
def standard(tmp_path):
    engine = make_engine(f"sqlite:///{(tmp_path/'standard.db').as_posix()}")
    Base.metadata.create_all(engine)
    app = create_app(tmp_path/'data', db_url=str(engine.url), enable_standard=True, start_image_worker=False)
    with TestClient(app) as client:
        yield client, app.state.image_configs, engine, tmp_path/'data'
    engine.dispose()


def save(client, key=KEY):
    response = client.put('/api/image-configs',json={'base_url':'https://image.example.com/v1','api_key':key})
    assert response.status_code==200,response.text
    assert KEY not in response.text
    return response.json()


def verify(client, kind='generate', identifier=None):
    fields={'request_id':(None,identifier or str(uuid4())),'authorized':(None,'yes')}
    if kind=='edit': fields['reference']=('ref.png',png(),'image/png')
    response=client.post('/api/image-configs/verify/'+kind,files=fields)
    assert response.status_code==202,response.text
    return response.json()


def fake_executor(directory,profile,key,prompt,reference):
    assert key == KEY and profile['model']=='gpt-image-2.5-sunburst'
    directory.mkdir(parents=True,exist_ok=True)
    (directory/'result.png').write_bytes(png())
    return {'native_pixels':[12,8],'review':{'status':'pending'}}


def test_runtime_secret_isolated_not_persisted_and_verification_is_optional(standard):
    client, store, engine, directory=standard
    config=save(client)
    assert config['has_api_key'] and config['generation']['status']=='unverified'
    values={'config_id':config['id'],'request_id':str(uuid4()),'prompt':'garden','count':'1'}
    def submit(): return client.post('/api/image-jobs/batch',files={k:(None,v) for k,v in values.items()})
    assert submit().status_code==202
    assert process_standard_one(store,fake_executor)
    assert client.get('/api/image-configs').json()['generation']['status']=='unverified'
    with TestClient(create_app(directory,db_url=str(engine.url),enable_standard=True,start_image_worker=False)) as other:
        assert other.get('/api/image-configs').json() is None
        assert other.post('/api/image-jobs/batch',files={k:(None,v) for k,v in values.items()}).status_code==404
    check=verify(client)
    assert not process_one(engine,directory,lambda *args:pytest.fail('legacy worker claimed standard task'))
    assert process_standard_one(store,fake_executor)
    assert client.get('/api/image-configs').json()['generation']['status']=='succeeded'
    values['request_id']=str(uuid4())
    created=submit()
    assert created.status_code==202,created.text
    assert 'encrypted_key' not in created.json()[0]
    with Session(engine) as session:
        jobs=list(session.scalars(select(ImageJob)))
        assert all(row.encrypted_key=='' for row in jobs)
        assert all(KEY not in json.dumps({c.name:getattr(row,c.name) for c in ImageJob.__table__.columns}) for row in jobs)
        row=session.scalar(select(ImageConfiguration))
        assert 'key' not in ImageConfiguration.__table__.columns
    assert not (directory/'config-encryption.key').exists()
    assert all(KEY.encode() not in file.read_bytes() for file in directory.rglob('*') if file.is_file())
    store.keys.clear()
    assert not client.get('/api/image-configs').json()['has_api_key']
    assert not process_standard_one(store,lambda *args:pytest.fail('missing credentials must not call provider'))


def test_reference_edit_verified_separately_and_config_changes_invalidate(standard):
    client,store,engine,directory=standard
    config=save(client); verify(client); process_standard_one(store,fake_executor)
    values={'config_id':config['id'],'request_id':str(uuid4()),'prompt':'change green'}
    fields={k:(None,v) for k,v in values.items()};fields['reference']=('ref.png',png(),'image/png')
    assert client.post('/api/image-jobs/batch',files=fields).status_code==202
    assert process_standard_one(store,fake_executor)
    assert client.get('/api/image-configs').json()['edit']['status']=='unverified'
    check=verify(client,'edit'); duplicate=verify(client,'edit')
    assert duplicate==check
    assert process_standard_one(store,fake_executor)
    assert client.post('/api/image-jobs/batch',files=fields).status_code==202
    config=save(client,KEY+'new')
    assert config['edit']['status']==config['generation']['status']=='unverified'
    assert client.post('/api/image-configs/verify/edit',files={'request_id':(None,str(uuid4())),'authorized':(None,'yes')}).status_code==422


def test_unknown_and_auth_denial_never_retried_or_fallback(standard):
    client,store,engine,directory=standard
    save(client);check=verify(client,'edit')
    calls=[]
    def uncertain(*args):
        calls.append(args)
        assert args[-1] is not None
        raise GenerationError('timeout',True,{'http_status':None,'response_body':'timeout'})
    assert process_standard_one(store,uncertain)
    assert not process_standard_one(store,uncertain)
    item=client.get('/api/image-jobs/tasks/'+check['task_id']).json()['items'][0]
    assert item['status']=='unknown' and len(calls)==1
    check=verify(client)
    def denied(*args):
        calls.append(args);raise GenerationError('denied',False,{'http_status':403,'response_body':'permission denied'})
    assert process_standard_one(store,denied)
    assert not process_standard_one(store,denied)
    assert client.get('/api/image-configs').json()['generation']['status']=='failed'
    assert len(calls)==2


@pytest.mark.parametrize('model', ['gpt-image-2.5-sunburst', 'gpt-image-2'])
def test_cli_command_selected_model_env_and_native_bytes_with_preview(tmp_path, model):
    original=png();(tmp_path/'reference.png').write_bytes(original)
    calls=[]
    def subprocess_run(command,**kwargs):
        calls.append(command)
        assert kwargs['env']['OPENAI_API_KEY']==KEY
        assert kwargs['env']['OPENAI_BASE_URL']=='https://image.example.com/v1'
        assert '--no-augment' in command and command[command.index('--model')+1]==model
        assert command[command.index('--size')+1]=='auto' and command[command.index('--n')+1]=='1'
        assert command[command.index('--image')+1]==str(tmp_path/'reference.png')
        assert (tmp_path/'prompt.txt').read_text(encoding='utf-8')=='中文完整提示词'
        (tmp_path/'result.png').write_bytes(original)
        from types import SimpleNamespace
        return SimpleNamespace(returncode=0)
    previous=os.environ.get('OPENAI_API_KEY')
    with patch('app.standard_image_executor.subprocess.run',subprocess_run):
        result=execute_cli(tmp_path,{'base_url':'https://image.example.com/v1', 'model':model},KEY,'中文完整提示词',original)
    assert os.environ.get('OPENAI_API_KEY')==previous
    assert result['native_pixels']==[12,8] and result['references'][0]['role']=='edit_target'
    assert result['rules']['model']==model
    assert (tmp_path/'result.png').read_bytes()==original
    assert (tmp_path/'preview.jpg').is_file() and len(calls)==1
    assert all(KEY.encode() not in p.read_bytes() for p in tmp_path.iterdir() if p.is_file())
    with pytest.raises(GenerationError): execute_cli(tmp_path,{},KEY,'repeat',None)
    source=Path(r'D:/requirements/skill-forge/premium-product-image-workflow-最新版迁移包-20261119/runtime/imagegen/scripts/image_gen.py')
    vendored=Path(__file__).resolve().parents[1]/'vendor/imagegen/image_gen.py'
    if source.exists(): assert source.read_bytes()==vendored.read_bytes()


def test_launcher_sdk_disables_hidden_retries_without_network(monkeypatch,tmp_path):
    import app.image_cli_launcher as launcher
    captured={}
    class Client:
        def __init__(self,**kwargs): captured.update(kwargs)
    def fake_run(*args,**kwargs):
        client=launcher.openai.OpenAI()
        assert captured['max_retries']==0
        captured['http_client'].close()
    monkeypatch.setattr(launcher.openai,'OpenAI',Client)
    monkeypatch.setattr(launcher.runpy,'run_path',fake_run)
    monkeypatch.setattr('sys.argv',['wrapper',str(tmp_path/'diagnostic.json'),'generate'])
    launcher.main()
    assert captured['timeout'].read==300

@pytest.mark.parametrize('kind', ['generate','edit'])
@pytest.mark.parametrize('model', ['gpt-image-2.5-sunburst', 'gpt-image-2'])
def test_original_cli_through_real_sdk_uses_exact_payload_and_actual_reference(monkeypatch,tmp_path,kind,model):
    import base64
    import app.image_cli_launcher as launcher
    captured=[]
    def handle(request):
        captured.append(request)
        assert request.headers['authorization']=='Bearer '+KEY
        assert str(request.url)=='https://image.example.com/v1/images/'+('edits' if kind=='edit' else 'generations')
        raw=request.read()
        if kind=='edit':
            assert b'reference.png' in raw and png() in raw
            assert b'name="size"' in raw and b'auto' in raw
            assert model.encode() in raw
        else:
            body=json.loads(raw)
            assert body['model']==model and body['prompt']=='exact prompt'
            assert body['size']=='auto' and body['quality']=='high' and body['output_format']=='png' and body['n']==1
        return httpx.Response(200,json={'data':[{'b64_json':base64.b64encode(png()).decode()}]})
    monkeypatch.setattr(launcher,'PublicTransport',lambda:httpx.MockTransport(handle))
    monkeypatch.setattr(launcher.openai,'OpenAI',launcher.openai.OpenAI)
    monkeypatch.setenv('OPENAI_API_KEY',KEY);monkeypatch.setenv('OPENAI_BASE_URL','https://image.example.com/v1')
    (tmp_path/'prompt.txt').write_text('exact prompt',encoding='utf-8')
    args=['wrapper',str(tmp_path/'diagnostic.json'),kind,'--model',model,'--quality','high','--size','auto','--output-format','png','--no-augment','--prompt-file',str(tmp_path/'prompt.txt'),'--out',str(tmp_path/'native.png')]
    if kind=='edit':
        (tmp_path/'reference.png').write_bytes(png());args.extend(['--image',str(tmp_path/'reference.png')])
    monkeypatch.setattr('sys.argv',args)
    launcher.main()
    assert len(captured)==1 and (tmp_path/'native.png').read_bytes()==png()


def test_review_is_separate_from_generation_and_exported(standard):
    client,store,engine,directory=standard
    save(client);check=verify(client);process_standard_one(store,fake_executor)
    before=client.get('/api/image-jobs/'+check['job_id']).json()
    reply=client.post('/api/image-jobs/'+check['job_id']+'/review',files={'status':(None,'rework'),'notes':(None,'立柱数量需核对')})
    assert reply.status_code==200 and reply.json()['status']=='rework'
    after=client.get('/api/image-jobs/'+check['job_id']).json()
    assert after['status']=='succeeded' and after['updated_at']==before['updated_at']
    assert after['execution_result']['review']['notes']=='立柱数量需核对'
    assert not process_standard_one(store,lambda *args:pytest.fail('review must not generate again'))


def test_real_sdk_403_saves_redacted_response_once(monkeypatch,tmp_path):
    import app.image_cli_launcher as launcher
    calls=[]
    def handle(request):
        calls.append(request)
        return httpx.Response(403,headers={'x-request-id':'denied-test-id'},json={'error':{'message':'denied '+KEY}})
    monkeypatch.setattr(launcher,'PublicTransport',lambda:httpx.MockTransport(handle))
    monkeypatch.setattr(launcher.openai,'OpenAI',launcher.openai.OpenAI)
    monkeypatch.setenv('OPENAI_API_KEY',KEY);monkeypatch.setenv('OPENAI_BASE_URL','https://image.example.com/v1')
    (tmp_path/'prompt.txt').write_text('exact prompt',encoding='utf-8')
    diagnostic=tmp_path/'diagnostic.json'
    monkeypatch.setattr('sys.argv',['wrapper',str(diagnostic),'generate','--model','gpt-image-2.5-sunburst','--quality','high','--size','auto','--output-format','png','--no-augment','--prompt-file',str(tmp_path/'prompt.txt'),'--out',str(tmp_path/'native.png')])
    with pytest.raises(SystemExit): launcher.main()
    data=json.loads(diagnostic.read_text(encoding='utf-8'))
    assert len(calls)==1 and not data['uncertain']
    assert data['diagnostic']['http_status']==403 and data['diagnostic']['path']=='/v1/images/generations'
    assert data['diagnostic']['request_id']=='denied-test-id' and KEY not in diagnostic.read_text(encoding='utf-8')


def test_public_transport_pins_address_preserves_single_host_and_tls_name(monkeypatch):
    import app.image_cli_launcher as launcher
    def pinned(value):
        assert value=='https://image.example.com/v1/images/generations'
        return httpx.URL('https://8.8.8.8/v1/images/generations'), {'Host':'image.example.com'}, {'sni_hostname':'image.example.com'}
    monkeypatch.setattr(launcher,'pinned_url',pinned)
    captured=[]
    transport=launcher.PublicTransport()
    transport.transport.close()
    def handle(request):
        captured.append(request)
        assert request.url.host=='8.8.8.8'
        assert request.headers.get_list('host')==['image.example.com']
        assert request.extensions['sni_hostname']=='image.example.com'
        return httpx.Response(200,json={})
    transport.transport=httpx.MockTransport(handle)
    with httpx.Client(transport=transport) as client:
        assert client.post('https://image.example.com/v1/images/generations',json={'prompt':'test'}).status_code==200
    assert len(captured)==1

@pytest.mark.parametrize('change,expected', [({'base_url':'http://localhost:1234/v1'},'HTTPS'),({'api_key':'invalid\ncredential'},'ASCII')])
def test_image_settings_validation_returns_clear_422_without_input_echo(standard,change,expected):
    client,store,engine,directory=standard
    values={'base_url':'https://image.example.com/v1','api_key':KEY,**change}
    response=client.put('/api/image-configs',json=values)
    assert response.status_code==422 and expected in response.text
    assert KEY not in response.text and 'invalid\\ncredential' not in response.text
    assert client.get('/api/image-configs').json() is None

def test_unverified_config_can_create_set_and_source_revision(standard):
    client,store,engine,directory=standard
    config=save(client)
    def submit(path,values):
        return client.post(path,files={key:(None,str(value)) for key,value in {'config_id':config['id'],'request_id':str(uuid4()),**values}.items()})
    parent=submit('/api/image-jobs/batch',{'prompt':'garden'})
    assert parent.status_code==202
    assert process_standard_one(store,fake_executor)
    revision=submit('/api/image-jobs/batch',{'prompt':'change background','source_job_id':parent.json()[0]['id']})
    assert revision.status_code==202 and revision.json()[0]['mode']=='edit'
    plan={'name':'optional check','shots':[{'name':'main','prompt':'full product'},{'name':'detail','prompt':'connection'}]}
    result=submit('/api/image-jobs/sets',{'plan':json.dumps(plan)})
    assert result.status_code==202 and len(result.json())==2
    current=client.get('/api/image-configs').json()
    assert current['generation']['status']==current['edit']['status']=='unverified'


def test_shared_text_and_image_connection_reuses_runtime_key_and_preserves_image_revision(standard):
    client,store,engine,directory=standard
    config=save(client)
    verify(client);assert process_standard_one(store,fake_executor)
    with Session(engine) as session:
        row=session.get(ImageConfiguration,config['id']);revision=row.revision;owner=row.owner
    reply=client.put('/api/image-configs',json={'base_url':config['base_url'],'text_model_name':'text-planner','text_config_id':None})
    assert reply.status_code==200,reply.text
    assert reply.json()['text_model_name']=='text-planner' and reply.json()['text_config_id'] is None
    assert reply.json()['generation']['status']=='succeeded' and KEY not in reply.text
    assert store.resolve_text(owner)==(config['base_url'],KEY,'text-planner')
    with Session(engine) as session:
        assert session.get(ImageConfiguration,config['id']).revision==revision
    assert client.put('/api/image-configs',json={'base_url':config['base_url']}).json()['text_model_name']=='text-planner'
    assert not (directory/'model-configs.json').exists()


def test_other_existing_provider_is_referenced_without_copying_or_replacing_credentials(standard):
    from app.database import DatabaseConfigStore,ModelConfiguration
    from app.model_configs import ConfigInput
    client,store,engine,directory=standard
    config=save(client)
    other_key='other-provider-test-key'
    legacy=DatabaseConfigStore(directory,engine).save(ConfigInput(name='existing text provider',base_url='https://text.example.com/v1',api_key=other_key,model_name='chat-old'))
    with Session(engine) as session:
        before=session.get(ModelConfiguration,legacy.id).as_dict();owner=session.get(ImageConfiguration,config['id']).owner
    reply=client.put('/api/image-configs',json={'base_url':config['base_url'],'text_config_id':legacy.id,'text_model_name':'chat-new'})
    assert reply.status_code==200,reply.text
    assert store.resolve_text(owner)==('https://text.example.com/v1',other_key,'chat-new')
    assert store.resolve_connection(owner)==(config['base_url'],KEY)
    with Session(engine) as session:
        assert session.get(ModelConfiguration,legacy.id).as_dict()==before
    assert other_key not in reply.text and KEY not in reply.text
    assert client.put('/api/image-configs',json={'base_url':config['base_url'],'text_config_id':str(uuid4())}).status_code==422


def test_model_discovery_reuses_selected_connection_and_is_explicit(standard):
    from app.model_configs import ProbeResult
    client,store,engine,directory=standard
    config=save(client)
    calls=[]
    def probe(url,key):
        calls.append((url,key));return ProbeResult(status='ok',message='models read',models=['text-planner'])
    assert not calls
    with patch('app.image_configurations.probe_models',probe):
        reply=client.post('/api/image-configs/models',json={})
    assert reply.status_code==200 and reply.json()['models']==['text-planner']
    assert calls==[(config['base_url'],KEY)] and KEY not in reply.text


def test_selected_image_models_persist_and_text_only_save_preserves_them(standard):
    from app.image_configurations import ImageConfigStore
    client,store,engine,directory=standard
    config=save(client)
    assert config['model_name']=='gpt-image-2.5-sunburst'
    verify(client);process_standard_one(store,fake_executor)
    with Session(engine) as session:
        owner=session.get(ImageConfiguration,config['id']).owner
        revision=session.get(ImageConfiguration,config['id']).revision
    payload={'base_url':config['base_url'], 'model_name':'gpt-image-2',
             'model_names':['gpt-image-2.5-sunburst',' gpt-image-2 ','gpt-image-2']}
    reply=client.put('/api/image-configs',json=payload)
    assert reply.status_code==200,reply.text
    current=reply.json()
    assert current['model_name']==current['rules']['model']=='gpt-image-2'
    assert current['model_names']==['gpt-image-2.5-sunburst','gpt-image-2']
    assert current['generation']['status']==current['edit']['status']=='unverified'
    with Session(engine) as session:
        assert session.get(ImageConfiguration,config['id']).revision!=revision
    preserved=client.put('/api/image-configs',json={'base_url':config['base_url'],'text_model_name':'planner'}).json()
    assert preserved['model_name']==current['model_name'] and preserved['model_names']==current['model_names']
    restored=ImageConfigStore(engine,directory).get(owner)
    assert restored['model_names']==current['model_names'] and not restored['has_api_key']
    assert client.put('/api/image-configs',json={**payload,'model_name':''}).status_code==422
    assert client.put('/api/image-configs',json={**payload,'model_names':['gpt-image-1']}).status_code==422
    assert client.put('/api/image-configs',json={**payload,'model_names':['bad\nmodel']}).status_code==422
    assert KEY not in reply.text


@pytest.mark.parametrize('kind', ['generate','edit'])
def test_chosen_image_model_reaches_job_snapshot_and_worker(standard,kind):
    client,store,engine,directory=standard
    config=save(client)
    payload={'base_url':config['base_url'], 'model_names':['gpt-image-2.5-sunburst','gpt-image-2']}
    assert client.put('/api/image-configs',json=payload).status_code==200
    fields={key:(None,value) for key,value in {'config_id':config['id'],'model_name':'gpt-image-2',
            'request_id':str(uuid4()),'prompt':'exact prompt'}.items()}
    if kind=='edit': fields['reference']=('ref.png',png(),'image/png')
    reply=client.post('/api/image-jobs/batch',files=fields)
    assert reply.status_code==202,reply.text
    job=reply.json()[0]
    assert job['model_name']==job['execution_profile']['model']=='gpt-image-2'
    def execute(directory,profile,key,prompt,reference):
        assert profile['model']=='gpt-image-2' and key==KEY
        assert (reference is not None)==(kind=='edit')
        return {'rules':{'model':profile['model']}}
    assert process_standard_one(store,execute)
    assert client.put('/api/image-configs',json={**payload,'model_name':'gpt-image-2'}).status_code==200
    check=verify(client,kind)
    assert client.get('/api/image-jobs/'+check['job_id']).json()['model_name']=='gpt-image-2'
    assert process_standard_one(store,execute)


def test_unconfigured_or_incompatible_image_model_is_rejected_without_fallback(standard):
    client,store,engine,directory=standard
    config=save(client)
    fields={key:(None,value) for key,value in {'config_id':config['id'],'model_name':'gpt-image-other',
            'request_id':str(uuid4()),'prompt':'exact prompt'}.items()}
    assert client.post('/api/image-jobs/batch',files=fields).status_code==422
    assert client.put('/api/image-configs',json={'base_url':config['base_url'],'model_names':['gpt-image-2.5-sunburst','other-model']}).status_code==200
    fields['model_name']=(None,'other-model')
    reply=client.post('/api/image-jobs/batch',files=fields)
    assert reply.status_code==422 and 'imagegen' in reply.text
    with Session(engine) as session:
        assert list(session.scalars(select(ImageJob)))==[]
