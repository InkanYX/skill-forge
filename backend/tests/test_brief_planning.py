import json
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.brief_planning import history_for,review_plan
from app.creation_projects import process_creation_one
from app.database import CreationProject,CreationDocument,CreationExecution,ImageJob
from app.image_jobs import now
from test_creation_projects import project_setup,confirmed_project,edit,confirm
from test_product_planning import product,plan
from test_standard_images import standard


def queue(client,project,**options):
    identifier=str(uuid4())
    response=client.post('/api/creation-projects/'+project['id']+'/stages/brief',json={
        'revision':project['revision'],'request_id':identifier,**options})
    return identifier,response


@pytest.mark.parametrize('mode',['optimize','replan','directed'])
def test_modes_keep_facts_and_treat_old_drafts_differently(project_setup,mode):
    client,store,engine,_,_=project_setup
    project=confirmed_project(project_setup)
    identifier,response=queue(client,project,brief_mode=mode,planning_direction='家庭庭院生活' if mode=='directed' else '')
    assert response.status_code==202,response.text
    with Session(engine) as session:
        payload=json.loads(session.get(CreationExecution,identifier).input)
        assert payload['previous']['analysis']==project['documents']['analysis']['content']
        assert payload['content_planning']['mode']==mode
        assert payload['content_planning']['history'][0]['document_id']==project['documents']['brief']['id']
        assert len(payload['materials'])==2
        if mode=='optimize':assert payload['current_draft']==project['documents']['brief']['content']
        else:
            assert payload['current_draft'] is None
            assert payload['conversation']==[]
        assert not list(session.scalars(select(ImageJob)))
    # A transport retry reuses one execution. Changing intent cannot reuse its ID.
    repeated=client.post('/api/creation-projects/'+project['id']+'/stages/brief',json={
        'revision':project['revision'],'request_id':identifier,'brief_mode':mode,'planning_direction':'家庭庭院生活' if mode=='directed' else ''})
    assert repeated.status_code==202
    changed=client.post('/api/creation-projects/'+project['id']+'/stages/brief',json={
        'revision':project['revision'],'request_id':identifier,'brief_mode':'replan' if mode!='replan' else 'optimize'})
    assert changed.status_code==409


def test_invalid_modes_and_missing_direction_do_not_queue(project_setup):
    client,_,engine,_,_=project_setup;source=product(project_setup);project=plan(client,source).json()
    for body,expected in [({'brief_mode':'optimize'},409),({'brief_mode':'directed','planning_direction':'  '},422),
            ({'brief_mode':'replan','planning_direction':'庭院'},422),({'brief_mode':'unknown'},422)]:
        _,response=queue(client,project,**body);assert response.status_code==expected,response.text
    response=client.post('/api/creation-projects/'+source['id']+'/stages/analysis',json={
        'revision':source['revision'],'request_id':str(uuid4()),'brief_mode':'replan'})
    assert response.status_code==422
    with Session(engine) as session:assert not list(session.scalars(select(CreationExecution)))


def test_history_uses_only_own_same_product_and_includes_other_plans(project_setup):
    client,_,engine,_,_=project_setup;source=product(project_setup)
    a=plan(client,source).json();b=plan(client,source,title='第二套').json()
    a=edit(client,a,'brief',{'shots':[{'id':'a','name':'旧方案','content':'结构实证'}]})
    foreign_id=str(uuid4());foreign_doc=str(uuid4());other_id=str(uuid4())
    with Session(engine) as session,session.begin():
        # Explicit ownership constraints still work in principal-free worker sessions.
        session.add(CreationProject(id=foreign_id,owner_id='someone-else',title='PRIVATE',kind='plan',source_product_id=source['id'],content='{}',created_at=now(),updated_at=now()))
        session.add(CreationDocument(id=foreign_doc,project_id=foreign_id,stage='brief',version=1,content=json.dumps({'shots':[{'id':'private','name':'PRIVATE','content':'PRIVATE'}]}),created_at=now()))
        session.add(CreationProject(id=other_id,owner_id=a['owner_id'],title='OTHER PRODUCT',kind='plan',source_product_id=str(uuid4()),content='{}',created_at=now(),updated_at=now()))
        session.add(CreationDocument(id=str(uuid4()),project_id=other_id,stage='brief',version=1,content=json.dumps({'shots':[{'id':'other','name':'OTHER','content':'OTHER'}]}),created_at=now()))
    with Session(engine) as session:
        summaries=history_for(session,session.get(CreationProject,b['id']))
        assert [s['project_id'] for s in summaries]==[a['id']]
    identifier,response=queue(client,b,brief_mode='replan');assert response.status_code==202,response.text
    with Session(engine) as session:
        text=session.get(CreationExecution,identifier).input
        assert foreign_id not in text and foreign_doc not in text and other_id not in text


def shot(identifier,point):
    return {'id':identifier,'name':point,'selling_point':point,'objective':point,'content':point}


def comparison_payload(old,mode='replan'):
    return {'settings':{'goal':'生成商品套图'},'current_draft':{'shots':old},'content_planning':{
        'mode':mode,'label':mode,'direction':'','history':[{'project_id':'p','project_title':'历史方案','document_id':'d','version':1,'shots':old}]}}


def test_comparison_excludes_main_image_but_catches_title_only_rewrites():
    original=[shot('main','完整展示产品'),shot('shade','庭院遮阳覆盖'),shot('height','立柱调高按钮')]
    renamed=[{**s,'name':'全新标题'} for s in original]
    report=review_plan(comparison_payload(original),{'shots':renamed})
    assert report['protected_slots']==[1]
    assert report['comparisons'][0]['same_slots']==[2,3]
    assert report['warnings']
    reordered=[original[0],original[2],original[1]]
    report=review_plan(comparison_payload(original),{'shots':reordered})
    assert report['comparisons'][0]['reused_theme_count']==2
    assert report['comparisons'][0]['same_slots']==[] and not report['warnings']
    report=review_plan(comparison_payload(original,'optimize'),{'shots':original})
    assert not report['warnings']


def test_aplus_first_module_is_compared_and_empty_history_is_honest():
    original=[shot('hero','庭院遮阳覆盖')];payload=comparison_payload(original)
    payload['settings']={'goal':'Premium A+'}
    report=review_plan(payload,{'shots':original})
    assert report['protected_slots']==[] and report['comparisons'][0]['same_slots']==[1]
    payload['content_planning']['history']=[]
    report=review_plan(payload,{'shots':original})
    assert report['history_count']==0 and not report['warnings']


def test_real_planner_receives_mode_and_saves_review_without_generating_images(project_setup,monkeypatch):
    client,store,engine,_,_=project_setup;project=confirmed_project(project_setup)
    captured=[]
    def planner(_engine,_data,_dir,_snapshot,instructions,brief,_chat,**kwargs):
        captured.append(brief)
        assert '卖点组合' in instructions
        assert brief['content_planning']['mode']=='directed'
        assert brief['content_planning']['direction']=='结构细节'
        assert brief['current_draft'] is None and brief['conversation']==[]
        return json.dumps({'planning_summary':'改为以结构证据与使用步骤为主线。','shots':project['documents']['brief']['content']['shots']}),{}
    monkeypatch.setattr('app.skill_agent.plan_with_skills',planner)
    identifier,response=queue(client,project,brief_mode='directed',planning_direction='结构细节')
    assert response.status_code==202,response.text
    assert process_creation_one(store)
    with Session(engine) as session:
        execution=session.get(CreationExecution,identifier)
        assert execution.status=='succeeded',execution.error
    updated=client.get('/api/creation-projects/'+project['id']).json()
    assert len(captured)==1
    assert updated['documents']['brief']['version']==2 and not updated['documents']['brief']['confirmed_at']
    assert updated['documents']['prompts'] is None
    assert updated['documents']['analysis']['id']==project['documents']['analysis']['id']
    with Session(engine) as session:
        execution=session.get(CreationExecution,identifier)
        assert execution.status=='succeeded',execution.error
        report=json.loads(execution.output)['trace']['brief_planning']
        assert report['warnings'] and report['summary']=='改为以结构证据与使用步骤为主线。'
        assert not list(session.scalars(select(ImageJob)))


def test_optimize_rejects_changed_slots_and_keeps_previous_confirmed_plan(project_setup):
    client,store,engine,_,_=project_setup;project=confirmed_project(project_setup)
    identifier,response=queue(client,project,brief_mode='optimize');assert response.status_code==202
    assert process_creation_one(store,lambda *_:({'shots':[{'id':'different','name':'换主题','content':'其他画面'}]},{}))
    with Session(engine) as session:assert session.get(CreationExecution,identifier).status=='failed'
    updated=client.get('/api/creation-projects/'+project['id']).json()
    assert updated['documents']['brief']['id']==project['documents']['brief']['id']
    assert updated['documents']['prompts']['id']==project['documents']['prompts']['id']
