import json
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import ImageJob, CreationExecution, ProductImageExperience
from app.product_experience import matching_experience
from test_image_feedback import completed_image, feedback, activate
from test_creation_projects import project_setup, confirm, edit
from test_product_planning import product, plan
from test_standard_images import standard, KEY
from test_auth import accounts, member


def test_ratings_preferences_and_prompt_difference_are_frozen(project_setup):
    client, _, engine, _, _=project_setup
    source=product(project_setup)
    before=completed_image(project_setup,source)
    after=completed_image(project_setup,source)
    with Session(engine) as session,session.begin():
        session.get(ImageJob,before['id']).prompt='Product centered\nHeadline above'
        session.get(ImageJob,after['id']).prompt='Product on right\nText follows scene'
    initial=client.get('/api/cases/'+after['id']+'?feedback=true').json()
    assert before['id'] in [item['id'] for item in initial['comparison_candidates']]
    note=feedback(client,after,outcome='satisfied',issues='',experience='',requested_change='',learning={
        'ratings':{'fidelity':5,'composition':4,'typography':5},'reference_job_id':before['id'],
        'preference':'current','reason':'文字没有遮住产品结构'})
    learning=note['learning']
    assert learning['ratings']['typography']==5
    assert 'Headline above' in learning['comparison']['prompt_diff']
    assert learning['comparison']['reference_prompt']=='Product centered\nHeadline above'
    assert client.post('/api/cases',json={'job_id':after['id'],'title':'反馈','issues':'问题','revision':note['revision'],
        'learning':{'ratings':{'fidelity':6}}}).status_code==422
    assert client.post('/api/cases',json={'job_id':after['id'],'title':'反馈','issues':'问题','revision':note['revision'],
        'learning':{'reference_job_id':before['id'],'preference':'current'}}).status_code==422
    other=product(project_setup); unrelated=completed_image(project_setup,other)
    assert client.post('/api/cases',json={'job_id':after['id'],'title':'反馈','issues':'问题','revision':note['revision'],
        'learning':{'reference_job_id':unrelated['id'],'preference':'reference','reason':'不同产品'}}).status_code==422
    # Updating legacy feedback without a new learning field preserves the evaluation.
    updated=client.post('/api/cases',json={'job_id':after['id'],'title':'反馈','experience':'已采用的版式','outcome':'satisfied','revision':note['revision']}).json()
    assert updated['learning']==learning
    exported=client.get('/api/product-experience/'+source['id']+'/export')
    assert exported.status_code==200 and 'attachment' in exported.headers['content-disposition']
    sample=next(item for item in exported.json()['samples'] if item['job_id']==after['id'])
    assert sample['positive_example'] and sample['learning']==learning
    assert KEY not in exported.text and 'api_key' not in exported.text
    feedback(client,before,outcome='discarded',issues='构图不可用',experience='',requested_change='')
    negative=client.get('/api/product-experience/'+source['id']+'/export').json()['samples']
    assert not next(item for item in negative if item['job_id']==before['id'])['positive_example']


def test_scope_ranking_exclusion_and_stale_evidence(project_setup,monkeypatch):
    client, _, engine, _, _=project_setup
    source,target=product(project_setup),product(project_setup)
    global_rule=activate(client,source['id'],guidance='标题顺应场景留白',reuse_scope='global',portable_confirmed=True)
    category_rule=activate(client,source['id'],guidance='特写说明连接位置',reuse_scope='category',category='户外凉棚',image_type='a_plus',device='mobile',portable_confirmed=True)
    own_rule=activate(client,target['id'],guidance='仅当前产品保真经验')
    root='/api/product-experience/'+source['id']
    assert client.post(root,json={'guidance':'跨产品方法','reuse_scope':'global','status':'active'}).status_code==422
    assert client.post(root,json={'guidance':'同品类方法','reuse_scope':'category','portable_confirmed':True,'status':'active'}).status_code==422
    context={'learning':{'category':'户外凉棚','image_type':'a_plus','device':'mobile'}}
    with Session(engine) as session:
        matches=matching_experience(session,target['id'],context)
        assert [r['id'] for r in matches]==[own_rule['id'],category_rule['id'],global_rule['id']]
        assert all(r['match_reason'] for r in matches)
        assert category_rule['id'] not in [r['id'] for r in matching_experience(session,target['id'],{'learning':{'category':'其他','image_type':'a_plus','device':'mobile'}})]
        assert matching_experience(session,target['id'],{'learning':{'enabled':False}})==[]
    image=completed_image(project_setup,target); note=feedback(client,image)
    monkeypatch.setattr('app.agent_runtime._chat',lambda *a,**k:{'content':json.dumps({'rules':[{'guidance':'不要用文字遮挡结构','feedback_ids':[note['id']]}]})})
    candidate=client.post('/api/product-experience/'+target['id']+'/summarize',json={'request_id':str(uuid4()),'feedback':{note['id']:note['revision']}}).json()['experiences'][0]
    assert candidate['status']=='candidate'
    active=client.put('/api/product-experience/'+target['id']+'/'+candidate['id'],json={**candidate,'status':'active'}).json()
    with Session(engine) as session:
        assert active['id'] in [r['id'] for r in matching_experience(session,target['id'],{})]
    feedback(client,image,revision=note['revision'],issues='纠正原反馈：结构其实没有被遮挡')
    with Session(engine) as session:
        assert active['id'] not in [r['id'] for r in matching_experience(session,target['id'],{})]
    details=client.get('/api/product-experience/'+target['id']).json()
    assert next(r for r in details['experiences'] if r['id']==active['id'])['evidence_current'] is False


def test_planning_preview_exclusions_and_historical_snapshot(project_setup):
    client, store, engine, _, _=project_setup
    source=product(project_setup)
    rule=activate(client,source['id'],guidance='有效构图规则')
    planned=plan(client,source).json(); root='/api/creation-projects/'+planned['id']
    preview=client.get(root+'/experience-preview').json()['experiences']
    assert preview[0]['id']==rule['id']
    changed=client.put(root,json={**planned['settings'],'kind':'plan','title':planned['title'],'skill':planned['skill'],'revision':planned['revision'],
        'learning':{'enabled':True,'excluded_ids':[rule['id']]}}).json()
    assert client.get(root+'/experience-preview').json()['experiences'][0]['excluded']
    queued=client.post(root+'/stages/brief',json={'revision':changed['revision'],'request_id':str(uuid4())})
    assert queued.status_code==202,queued.text
    assert queued.json()['drawing_experience']['brief']==[]
    with Session(engine) as session:
        execution=session.scalar(select(CreationExecution).where(CreationExecution.project_id==planned['id']))
        assert json.loads(execution.input)['drawing_experience']['brief']==[]
    # Preview is read-only: no additional model execution was scheduled.
    assert len(client.get(root).json()['executions'])==1


def test_summary_receives_scores_and_preferences_without_uploading_images(project_setup,monkeypatch):
    client, _, _, _, _=project_setup
    source=product(project_setup)
    image=completed_image(project_setup,source)
    note=feedback(client,image,learning={'ratings':{'composition':2},'reason':'主体太小'})
    calls=[]
    def chat(url,key,model,messages,**kwargs):
        calls.append(messages)
        return {'content':json.dumps({'rules':[{'guidance':'用足够大的主体呈现关键结构','feedback_ids':[note['id']]}]})}
    monkeypatch.setattr('app.agent_runtime._chat',chat)
    response=client.post('/api/product-experience/'+source['id']+'/summarize',json={'request_id':str(uuid4()),'feedback':{note['id']:note['revision']}})
    assert response.status_code==200,response.text
    assert response.json()['experiences'][0]['status']=='candidate'
    assert '主体太小' in calls[0][-1]['content']
    assert 'composition' in calls[0][-1]['content'] and 'data:image' not in calls[0][-1]['content']


def test_library_shares_rules_but_personal_exports_and_matching_stay_owned(accounts):
    first,user=member(accounts,'learner-one'); second,_=member(accounts,'learner-two')
    source=first.post('/api/creation-projects',json={'kind':'product','title':'甲产品'}).json()
    rule=first.post('/api/product-experience/'+source['id'],json={'guidance':'本人视觉方法','reuse_scope':'global','portable_confirmed':True,'status':'active'})
    assert rule.status_code==201,rule.text
    assert first.get('/api/product-experience/library').json()['experiences'][0]['guidance']=='本人视觉方法'
    shared=second.get('/api/product-experience/library').json()['experiences']
    assert len(shared)==1 and shared[0]['can_edit'] is False and shared[0]['author']['id']==user['id']
    assert second.get('/api/product-experience/'+source['id']+'/export').status_code==404
    target=second.post('/api/creation-projects',json={'kind':'product','title':'乙产品'}).json()
    with Session(accounts[2]) as session:
        assert matching_experience(session,target['id'],{},owner_id=target['owner_id'])==[]
