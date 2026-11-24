import base64
import io
import json
from uuid import uuid4

import httpx
import pytest
from PIL import Image

from app.standard_image_worker import process_standard_one
from test_standard_images import standard, KEY


@pytest.fixture
def registry(standard, monkeypatch):
    client, store, engine, directory = standard
    name = 'provider/any-model-name'
    config = client.put('/api/image-configs', json={'base_url':'https://provider.example/v1','api_key':KEY,
        'model_name':name,'model_names':[name,'another-model']}).json()
    calls=[]
    original=httpx.Client
    buffer=io.BytesIO();Image.new('RGB',(16,12),'green').save(buffer,'JPEG');native=buffer.getvalue()
    behavior={'image_status':200,'image_code':''}
    def handle(request):
        calls.append(request)
        if request.url.path.endswith('/chat/completions'):
            return httpx.Response(200,json={'choices':[{'message':{'role':'assistant','content':'正常文字回复'}}]})
        if behavior['image_status']!=200:
            return httpx.Response(behavior['image_status'],json={'error':{'code':behavior['image_code'],'message':'image operation failed'}})
        return httpx.Response(200,json={'data':[{'b64_json':base64.b64encode(native).decode()}]})
    monkeypatch.setattr('app.image_provider.pinned_url',lambda value:(value,{},{}))
    monkeypatch.setattr('app.agent_runtime.pinned_url',lambda value:(value,{},{}))
    monkeypatch.setattr(httpx,'Client',lambda **kwargs:original(transport=httpx.MockTransport(handle)))
    return client,store,directory,config,calls,behavior,native


def verify(client,kind='generate'):
    response=client.post('/api/image-configs/verify/'+kind,files={'request_id':(None,str(uuid4())),'authorized':(None,'yes')})
    assert response.status_code==202,response.text
    return response.json()


def test_arbitrary_model_optional_parameters_and_native_jpeg(registry):
    client,store,directory,config,calls,behavior,native=registry
    assert config['model_names']==['provider/any-model-name','another-model']
    assert config['request_parameters']=={}
    task=verify(client);assert process_standard_one(store)
    body=json.loads(calls[-1].content)
    assert body['model']=='provider/any-model-name'
    assert set(body)=={'model','prompt'}
    image=client.get('/api/image-jobs/'+task['job_id']+'/image?download=true')
    assert image.status_code==200 and image.content==native
    assert image.headers['content-type'].startswith('image/jpeg') and '.jpg' in image.headers['content-disposition']
    assert (directory/'image-jobs'/task['job_id']/'result.jpg').read_bytes()==native
    assert client.get('/api/image-configs').json()['capabilities']['generate']['state']=='supported'
    text=client.post('/api/image-configs/text',json={'prompt':'hello'})
    assert text.json()['output']=='正常文字回复'
    assert json.loads(calls[-1].content)['model']==body['model']


@pytest.mark.parametrize('status,code,state',[(404,'','error'),(403,'','error'),(429,'','error'),(400,'unsupported_capability','unsupported')])
def test_image_failure_does_not_disable_text_and_only_explicit_unsupported_counts(registry,status,code,state):
    client,store,directory,config,calls,behavior,native=registry
    behavior.update(image_status=status,image_code=code)
    verify(client);assert process_standard_one(store)
    config=client.get('/api/image-configs').json()
    assert config['capabilities']['generate']['state']==state
    assert client.post('/api/image-configs/text',json={'prompt':'继续文本调用'}).json()['capability']['state']=='supported'
    config=client.get('/api/image-configs').json()
    assert config['capabilities']['generate']['state']==state and config['capabilities']['text']['state']=='supported'


def test_parameters_are_passed_and_model_settings_are_independent(registry):
    client,store,directory,config,calls,behavior,native=registry
    updated=client.put('/api/image-configs',json={'base_url':config['base_url'],'model_name':config['model_name'],
        'model_names':config['model_names'],'request_parameters':{'quality':'medium','output_format':'jpeg'},
        'text_parameters':{'temperature':0.7},'generation_path':'/pictures/create'})
    assert updated.status_code==200,updated.text
    task=verify(client);assert process_standard_one(store)
    assert calls[-1].url.path=='/v1/pictures/create'
    assert json.loads(calls[-1].content)['quality']=='medium'
    client.post('/api/image-configs/text',json={'prompt':'hello'})
    assert json.loads(calls[-1].content)['temperature']==0.7
    assert 'quality' not in json.loads(calls[-1].content)
    assert client.put('/api/image-configs',json={'base_url':config['base_url'],'model_name':'another-model','model_names':config['model_names'],
        'request_parameters':{},'text_parameters':{},'vision_parameters':{}}).status_code==200
    client.post('/api/image-configs/text',json={'prompt':'new model'})
    assert json.loads(calls[-1].content)['model']=='another-model'
    current=client.get('/api/image-configs').json()
    assert current['model_settings'][config['model_name']]['capabilities']['generate']['state']=='supported'
    assert current['model_settings']['another-model']['capabilities']['text']['state']=='supported'
    restored=client.put('/api/image-configs',json={'base_url':config['base_url'],'model_name':config['model_name'],
        'model_names':config['model_names'],'request_parameters':{'quality':'medium','output_format':'jpeg'},'text_parameters':{'temperature':0.7}}).json()
    assert restored['capabilities']['generate']['state']=='supported' and restored['capabilities']['text']['state']=='supported'


def test_vision_validation_needs_no_separate_model_and_auto_review_is_optional(registry):
    client,store,directory,config,calls,behavior,native=registry
    assert config['auto_review'] is False
    result=verify(client,'vision')
    assert result['capability']['state']=='supported'
    assert json.loads(calls[-1].content)['model']==config['model_name']


def test_reserved_options_and_external_paths_are_rejected(registry):
    client,store,directory,config,calls,behavior,native=registry
    for changes in ({'request_parameters':{'model':'override'}},{'request_parameters':{'api_key':'do-not-save'}},
                    {'generation_path':'//other.example/path'},{'model_options':{'another-model':{'capabilities':{'text':'supported'}}}}):
        assert client.put('/api/image-configs',json={'base_url':config['base_url'],**changes}).status_code==422
    assert calls==[]


def test_image_only_model_can_create_and_edit_without_a_text_role(registry):
    client,store,directory,config,calls,behavior,native=registry
    from app.model_capabilities import evidence, save_evidence
    from app.database import ImageConfiguration
    from sqlalchemy import select
    from sqlalchemy.orm import Session
    with Session(store.engine) as session:
        owner=session.scalar(select(ImageConfiguration.owner))
    save_evidence(store,owner,'text',config['model_name'],evidence(config['model_name'],False,{'error_code':'unsupported_capability'},'不支持文字'))
    response=client.post('/api/image-jobs/batch',files={key:(None,value) for key,value in {
        'config_id':config['id'],'model_name':config['model_name'],'request_id':str(uuid4()),'prompt':'庭院里的凉棚'}.items()})
    assert response.status_code==202,response.text
    assert process_standard_one(store)
    assert all(not request.url.path.endswith('/chat/completions') for request in calls)
    task_id=response.json()[0]['task_id']
    task=client.get('/api/image-jobs/tasks/'+task_id).json()
    assert task['status']=='needs_review'
    edited=client.post('/api/agent/runs/'+task['agent_run_id']+'/rework',json={'instruction':'只修改背景','source_job_id':response.json()[0]['id']})
    assert edited.status_code==200,edited.text
    assert edited.json()['status']=='waiting_images'
    assert process_standard_one(store)
    assert calls[-1].url.path.endswith('/images/edits')
    assert all(not request.url.path.endswith('/chat/completions') for request in calls)


def test_legacy_model_column_does_not_create_selectable_models(standard):
    client, store, engine, directory = standard
    saved = client.put('/api/image-configs', json={'base_url': 'https://image.example.com/v1', 'api_key': KEY, 'model_name': 'gpt-image-2.5-sunburst'})
    assert saved.status_code == 200 and saved.json()['model_names'] == ['gpt-image-2.5-sunburst']
    from app.database import ImageConfiguration
    from sqlalchemy import select
    from sqlalchemy.orm import Session
    with Session(engine) as session:
        row = session.scalar(select(ImageConfiguration))
        assert row is not None
        row.model_names = '[]'
        session.commit()
    payload = client.get('/api/image-configs').json()
    assert payload['model_names'] == [] and payload['unified_models'] is False
    assert client.put('/api/image-configs', json={'base_url': 'https://image.example.com/v1', 'planning_model_name': 'gpt-image-2.5-sunburst'}).status_code == 422


def test_changing_provider_clears_all_model_evidence(registry):
    client,store,directory,config,calls,behavior,native=registry
    client.post('/api/image-configs/text',json={'prompt':'check'})
    updated=client.put('/api/image-configs',json={'base_url':'https://different.example/v1','api_key':KEY,
        'model_name':config['model_name'],'model_names':config['model_names']})
    assert updated.status_code==200
    assert all(not entry.get('capabilities') for entry in updated.json()['model_settings'].values())


def test_single_model_configuration_requires_no_role_fields(registry):
    client,store,directory,config,calls,behavior,native=registry
    updated=client.put('/api/image-configs',json={'base_url':config['base_url'],'model_name':'plain-model'})
    assert updated.status_code==200 and updated.json()['unified_models']
    result=client.post('/api/image-configs/text',json={'prompt':'hello'})
    assert result.json()['output']=='正常文字回复'
    assert json.loads(calls[-1].content)['model']=='plain-model'
