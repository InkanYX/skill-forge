import json
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.creation_projects import process_creation_one
from app.database import CreationExecution
from app.skill_image_workflow import review
from app.visual_styles import PRESETS, layout_warnings
from test_creation_projects import project_setup, confirmed_project, edit, confirm
from test_product_planning import product, plan
from test_project_delivery import executor
from test_standard_images import standard
from test_image_jobs import png


def test_style_catalog_validation_and_legacy_compatibility(project_setup):
    client, _, _, _, legacy = project_setup
    catalog = client.get('/api/creation-projects/visual-styles').json()
    assert len(catalog['presets']) == 7
    assert legacy['settings']['visual_style'] is None
    assert legacy['visual_style_snapshot'] is None
    source = product(project_setup)
    invalid = plan(client, source, visual_style={'preset': 'unknown'})
    assert invalid.status_code == 422
    invalid = plan(client, source, visual_style={'preset': 'editorial', 'density': 'unlimited'})
    assert invalid.status_code == 422
    result = plan(client, source, visual_style={'preset': 'editorial', 'variation': 'rich', 'density': 'low'}).json()
    assert result['visual_style_snapshot']['version'] == catalog['version']
    assert result['visual_style_snapshot']['selection'] == result['settings']['visual_style']
    assert result['skill']
    assert '不提供产品事实' in result['visual_style_snapshot']['rules']


def test_style_snapshot_reconfirmation_planning_jobs_archive_and_reuse(project_setup, monkeypatch):
    client, store, engine, directory, _ = project_setup
    project = confirmed_project(project_setup)
    old_brief = project['documents']['brief']['content']
    for shot in old_brief['shots']: shot['size']='1464x600'
    old_prompts = project['documents']['prompts']['content']
    old_analysis_id = project['documents']['analysis']['id']
    root = '/api/creation-projects/' + project['id']
    settings = {**project['settings'], 'visual_style': {'preset':'editorial','variation':'rich','density':'low','palette':'品牌绿'},
        'title':project['title'],'revision':project['revision'],'skill':project['skill']}
    updated = client.put(root,json=settings)
    assert updated.status_code == 200, updated.text
    project = updated.json()
    snapshot = project['visual_style_snapshot']
    assert project['documents']['analysis']['id'] == old_analysis_id
    assert project['documents']['brief'] is None and project['documents']['prompts'] is None
    assert len(project['history']) == 3
    # Catalog updates cannot silently replace a plan's frozen art direction.
    monkeypatch.setitem(next(p for p in PRESETS if p['id']=='editorial'),'rules','NEW FUTURE RULE')
    settings.update(revision=project['revision'],title='改标题不改风格')
    project = client.put(root,json=settings).json()
    assert project['visual_style_snapshot'] == snapshot
    captured = []
    def planner(store, execution_id, project_id, payload, stage):
        captured.append(payload)
        assert payload['settings']['visual_style'] == snapshot
        assert payload['skill_snapshot']
        return {**old_brief,'art_direction':'品牌杂志；大标题与非对称构图；各图变化'}, {}
    queued = client.post(root+'/stages/brief',json={'revision':project['revision'],'request_id':str(uuid4())})
    assert queued.status_code == 202, queued.text
    assert process_creation_one(store,planner)
    project = client.get(root).json()
    assert project['documents']['brief']['content']['art_direction'].startswith('品牌杂志')
    project = confirm(client,project,'brief')
    project = confirm(client,edit(client,project,'prompts',old_prompts),'prompts')
    response = client.post(root+'/generate',json={'revision':project['revision'],'request_id':str(uuid4()),'shot_ids':['scene','detail']})
    assert response.status_code == 202
    assert process_creation_one(store)
    project = client.get(root).json()
    for image in project['images']:
        assert image['execution_profile']['visual_style'] == snapshot
        assert image['prompt'].startswith('CONFIRMED')  # No post-confirmation rewriting.
    from app.standard_image_worker import process_standard_one
    for _ in range(2): assert process_standard_one(store,executor)
    project=client.get(root).json()
    mobile=client.post(root+'/mobile',json={'revision':project['revision'],'request_id':str(uuid4()),'batch_id':project['batches'][-1]['execution_id']})
    assert mobile.status_code==202,mobile.text
    mobile=mobile.json()
    assert mobile['visual_style_snapshot']==snapshot
    assert '品牌绿' in mobile['documents']['prompts']['content']['prompts'][0]['prompt']
    assert process_creation_one(store)
    for _ in range(2): assert process_standard_one(store,executor)
    mobile=client.get('/api/creation-projects/'+mobile['id']).json()
    assert all(image['execution_profile']['visual_style']==snapshot for image in mobile['images'])
    case = client.post(root+'/cases',json={'revision':project['revision'],'request_id':str(uuid4()),'title':'杂志风格案例','summary':'非对称构图'}).json()
    detail=client.get('/api/workflow-cases/'+case['id']).json()
    assert detail['snapshot']['visual_style_snapshot'] == snapshot
    source=product(project_setup)
    reused=client.post('/api/workflow-cases/'+case['id']+'/reuse',json={'request_id':str(uuid4()),'title':'新产品视觉参考','product_id':source['id']})
    assert reused.status_code == 201, reused.text
    assert reused.json()['visual_style_snapshot'] == snapshot
    assert reused.json()['documents']['analysis']['content']['facts'] == source['documents']['analysis']['content']['facts']
    with Session(engine) as session:
        execution=session.scalar(select(CreationExecution).where(CreationExecution.project_id==project['id'],CreationExecution.stage=='brief'))
        assert json.loads(execution.output)['trace']['visual_style'] == snapshot


def test_style_review_uses_frozen_rules_and_warns_about_set_scope(project_setup,monkeypatch,tmp_path):
    from app.visual_styles import snapshot_style
    _, store, _, _, _ = project_setup
    profile=next(iter(store.keys))
    # Use the real configured runtime key, but intercept the model call entirely.
    with Session(store.engine) as session:
        from app.database import ImageConfiguration
        row=session.get(ImageConfiguration,profile)
        revision=row.revision
    direction=snapshot_style({'preset':'immersive'})
    (tmp_path/'preview.jpg').write_bytes(png())
    seen=[]
    def vision(url,key,model,image,prompt,**kwargs):
        seen.append(prompt)
        return json.dumps({'status':'uncertain','summary':'待人工复核整套','checks':[{'item':'requirements','status':'uncertain','detail':'需整套检查'}]})
    monkeypatch.setattr('app.agent_runtime._vision',vision)
    result=review(store,None,tmp_path,'原要求','原提示词',None,profile={'id':profile,'revision':revision,'base_url':'https://provider.example/v1','review_model':'planner','visual_style':direction})
    assert result['status']=='uncertain'
    assert json.dumps(direction,ensure_ascii=False) in seen[0]
    assert '单图不能证明整套构图有变化' in seen[0]
    assert '沉浸场景' in seen[0]


def test_layout_warnings_are_reminders_not_visual_approval():
    warnings=layout_warnings([{'name':'图一','layout':'产品左，文字右'},{'name':'图二','layout':'产品左，文字右'},{'name':'图三','layout':''}])
    assert len(warnings)==2
    assert '完全相同' in warnings[0] and '尚未填写' in warnings[1]
