import json
from uuid import uuid4

from sqlalchemy.orm import Session

from app.database import CreationProject
from app.creation_materials import material_path
from test_creation_projects import project_setup, upload, edit, confirm
from test_standard_images import standard
from test_auth import accounts, member
from fastapi.testclient import TestClient
from app.main import create_app
from app.database import Base, make_engine
from app.creation_projects import process_creation_one


def product(setup):
    client, _, _, _, _ = setup
    response = client.post('/api/creation-projects', json={'title':'灰色凉棚','kind':'product','planning_model':'planner','goal':'产品有四根立柱'})
    assert response.status_code == 201, response.text
    row = upload(client, response.json())
    return confirm(client, edit(client, row, 'analysis', {'facts':'四根铝合金立柱，规格书依据','selling_points':'遮阳空间','questions':'抗风参数待确认'}), 'analysis')


def plan(client, source, **extra):
    return client.post('/api/creation-projects', json={'title':'美国站商品图','kind':'plan','planning_model':'planner',
        'source_product_id':source['id'],'market':'Amazon US','language':'英语',**extra})


def test_product_and_plan_have_distinct_server_enforced_responsibilities(project_setup):
    client, store, engine, directory, _ = project_setup
    source = product(project_setup)
    assert source['kind'] == 'product' and source['analysis_confirmed']
    root = '/api/creation-projects/' + source['id']
    assert client.post(root+'/stages/brief',json={'revision':source['revision'],'request_id':str(uuid4())}).status_code == 409
    assert client.post(root+'/generate',json={'revision':source['revision'],'request_id':str(uuid4()),'shot_ids':['one']}).status_code == 409
    assert client.post('/api/creation-projects',json={'title':'缺少来源','kind':'plan','planning_model':'planner'}).status_code == 422
    response = plan(client, source)
    assert response.status_code == 201, response.text
    result = response.json()
    assert result['source_product_id'] == source['id'] and result['source']['version'] == 1
    assert result['documents']['analysis']['confirmed_at']
    root = '/api/creation-projects/' + result['id']
    assert client.post(root+'/stages/analysis',json={'revision':result['revision'],'request_id':str(uuid4())}).status_code == 409
    assert client.put(root+'/documents/analysis',json={'revision':result['revision'],'content':{'facts':'改写','selling_points':'改写'}}).status_code == 409
    assert len(client.get('/api/creation-projects?kind=product&ready=true').json()) == 1


def test_one_product_supports_multiple_independent_plans_and_immutable_material_snapshots(project_setup):
    client, store, engine, directory, _ = project_setup
    source = product(project_setup)
    first = plan(client, source).json(); second = plan(client, source, title='德国站 A+').json()
    assert first['id'] != second['id']
    assert first['materials'][0]['id'] != source['materials'][0]['id']
    original = material_path(directory, source['id'], source['materials'][0]['id']).read_bytes()
    assert material_path(directory, first['id'], first['materials'][0]['id']).read_bytes() == original
    source = edit(client, source, 'analysis', {'facts':'更正后的产品事实','selling_points':'新卖点'})
    first_updated = client.get('/api/creation-projects/'+first['id']).json()
    assert first_updated['source_updated']
    assert first_updated['documents']['analysis']['content']['facts'] == '四根铝合金立柱，规格书依据'
    assert client.get('/api/creation-projects?kind=product&ready=true').json() == []
    assert plan(client, source).status_code == 409


def test_plan_goal_and_style_updates_preserve_the_product_analysis(project_setup):
    client, store, engine, directory, _ = project_setup
    current = plan(client, product(project_setup)).json()
    analysis = current['documents']['analysis']['id']
    url = '/api/creation-projects/'+current['id']
    response = client.put(url,json={**current['settings'],'title':current['title'],'skill':current['skill'],
        'revision':current['revision'],'goal':'德国站庭院图','market':'Amazon DE'})
    assert response.status_code == 200, response.text
    result = response.json()
    assert result['documents']['analysis']['id'] == analysis
    assert result['settings']['market'] == 'Amazon DE'
    # Product identity files cannot be silently replaced or removed from a plan.
    assert client.delete(url+'/materials/'+result['materials'][0]['id']+'?revision='+str(result['revision'])).status_code == 409


def test_plan_templates_are_neutral_and_applied_as_planning_input(project_setup):
    client, store, engine, directory, _ = project_setup
    body = {'name':'庭院类图片组合','description':'用于庭院商品','style':'统一留白',
        'shots':[{'name':'主体展示','objective':'主体完整','layout':'居中'}, {'name':'生活场景','layout':'留出文案区'}]}
    for extra in ({'facts':'上一款产品的尺寸'}, {'reference_ids':[str(uuid4())]}, {'prompts':['上一款产品的完整提示词']}):
        assert client.post('/api/creation-projects/templates',json={**body,**extra}).status_code == 422
    response = client.post('/api/creation-projects/templates',json=body)
    assert response.status_code == 201, response.text
    template = response.json()
    source = product(project_setup)
    result = plan(client,source,template_id=template['id']).json()
    assert result['settings']['image_count'] == 2 and result['settings']['style'] == '统一留白'
    with Session(engine) as session:
        content = json.loads(session.get(CreationProject,result['id']).content)
        assert content['template']['name'] == body['name']
        assert 'reference_ids' not in content['template']['shots'][0]


def test_old_product_records_can_be_copied_into_analysis_without_overwriting(project_setup):
    client, store, engine, directory, _ = project_setup
    old = client.post('/api/products',json={'sku':'LEGACY-001','name':'旧产品','facts':'已经人工保存的材质'}).json()
    result = client.post('/api/creation-projects/import-product',json={'legacy_product_id':old['id'],'planning_model':'planner'})
    assert result.status_code == 201, result.text
    assert result.json()['kind'] == 'product'
    assert '已经人工保存的材质' in result.json()['settings']['goal']
    assert result.json()['documents']['analysis'] is None
    assert client.get('/api/products').json()[0]['revision'] == old['revision']


def test_shared_product_is_readonly_and_member_plans_use_their_own_connection(accounts):
    admin, app, engine, directory = accounts
    reader, _ = member(accounts, 'planner-member')
    for client in (admin, reader):
        response = client.put('/api/image-configs',json={'base_url':'https://provider.example/v1','api_key':'synthetic-private-key',
            'model_name':'planner','model_names':['planner']})
        assert response.status_code == 200
    source = admin.post('/api/creation-projects',json={'kind':'product','title':'共享产品','planning_model':'planner','goal':'已整理事实'}).json()
    source = confirm(admin,edit(admin,source,'analysis',{'facts':'四根立柱','selling_points':'庭院遮阳'}),'analysis')
    visible = reader.get('/api/creation-projects/'+source['id'])
    assert visible.status_code == 200 and not visible.json()['can_edit']
    assert any(item['id']==source['id'] for item in reader.get('/api/creation-projects?kind=product&ready=true').json())
    assert reader.put('/api/creation-projects/'+source['id']+'/documents/analysis',json={'revision':source['revision'],'content':{'facts':'替换','selling_points':'替换'}}).status_code == 404
    copied = plan(reader,source)
    assert copied.status_code == 201, copied.text
    assert copied.json()['source']['product_id'] == source['id']
    assert copied.json()['owner_id'] != source['owner_id']


def test_product_can_be_saved_uploaded_and_manually_confirmed_without_model_connection(tmp_path):
    engine=make_engine(f"sqlite:///{(tmp_path/'no-model.db').as_posix()}")
    Base.metadata.create_all(engine)
    with TestClient(create_app(tmp_path/'data',db_url=str(engine.url),start_image_worker=False)) as client:
        response=client.post('/api/creation-projects',json={'kind':'product','title':'先保存资料','sku':'NEW-001','goal':'四根立柱'})
        assert response.status_code==201,response.text
        saved=response.json()
        assert client.get('/api/creation-projects/'+saved['id']).status_code==200
        saved=upload(client,saved)
        saved=confirm(client,edit(client,saved,'analysis',{'facts':'人工核对四根立柱','selling_points':'庭院遮阳'}),'analysis')
        assert saved['analysis_confirmed'] and saved['settings']['sku']=='NEW-001'
        assert client.get('/api/image-configs').json() is None
    engine.dispose()


def test_opening_existing_product_reuses_one_analysis_record(project_setup):
    client,_,_,_,_=project_setup
    old=client.post('/api/products',json={'sku':'ONCE-001','name':'旧产品'}).json()
    first=client.post('/api/creation-projects/import-product',json={'legacy_product_id':old['id']})
    second=client.post('/api/creation-projects/import-product',json={'legacy_product_id':old['id']})
    assert first.status_code==201 and second.status_code==201
    assert first.json()['id']==second.json()['id']
    assert first.json()['legacy_product_id']==old['id']


def test_product_analysis_binds_model_and_skill_only_when_requested(project_setup):
    client,store,engine,directory,_=project_setup
    row=client.post('/api/creation-projects',json={'kind':'product','title':'待分析产品','goal':'规格书中的产品'}).json()
    assert row['settings']['planning_model']==''
    response=client.post('/api/creation-projects/'+row['id']+'/stages/analysis',json={
        'revision':row['revision'],'request_id':str(uuid4()),'planning_model':'planner',
        'skill':{'mode':'auto','skills':[],'allow_auto':True}})
    assert response.status_code==202,response.text
    calls=[]
    def planner(store,execution_id,project_id,payload,stage):
        calls.append(payload)
        assert payload['profile']['model']=='planner'
        assert payload['skill_snapshot']['selection_mode']=='auto'
        return {'facts':'资料中的事实','selling_points':'有依据的卖点','questions':''},{}
    assert process_creation_one(store,planner)
    assert len(calls)==1


def test_generation_model_is_execution_input_and_does_not_change_confirmed_plan(project_setup):
    from test_creation_projects import confirmed_project
    client,store,_,_,_=project_setup
    row=confirmed_project(project_setup)
    before={stage:doc['id'] for stage,doc in row['documents'].items()}
    response=client.post('/api/creation-projects/'+row['id']+'/generate',json={
        'revision':row['revision'],'request_id':str(uuid4()),'shot_ids':['scene'],'image_model':'planner'})
    assert response.status_code==202,response.text
    assert process_creation_one(store)
    after=client.get('/api/creation-projects/'+row['id']).json()
    assert after['images'][0]['model_name']=='planner'
    assert after['settings']['image_model']=='image-editor'
    assert {stage:doc['id'] for stage,doc in after['documents'].items()}==before
    assert after['documents']['prompts']['confirmed_at']
