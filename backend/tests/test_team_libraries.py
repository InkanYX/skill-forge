import json
from uuid import uuid4
from sqlalchemy import select, update
from sqlalchemy.orm import Session
from app.database import CreationProject, ImageJob, TeamProjectShare, ProductImageExperience, CreativeCase
from app.database import CreationDocument
from app.image_jobs import artifact, now
from app.team_sharing import publish_completed_job, backfill
from test_auth import accounts, member
from test_team_sharing import completed
from test_image_jobs import png


def test_team_case_reads_files_and_reuses_without_exposing_live_project(accounts):
    alice,user=member(accounts,'case-author');bob,other=member(accounts,'case-reader')
    project,_,job,_=completed(accounts,user['id'])
    archived=alice.post('/api/creation-projects/'+project+'/cases',json={
        'revision':4,'request_id':str(uuid4()),'title':'团队完整案例'})
    assert archived.status_code==201,archived.text
    identifier=archived.json()['id'];path='/api/workflow-cases/'+identifier
    values=bob.get('/api/workflow-cases').json()
    assert len(values)==1 and values[0]['author']['id']==user['id'] and values[0]['can_edit'] is False
    detail=bob.get(path);assert detail.status_code==200,detail.text
    assert detail.json()['snapshot']['images'][0]['id']==job
    assert bob.get(path+'/images/'+job).content==png()
    assert bob.get(path+'/download').status_code==200
    assert bob.get('/api/creation-projects/'+project).status_code==404
    assert bob.get('/api/image-jobs/'+job).status_code==404
    assert bob.get('/api/image-configs').json() is None
    assert not any(s in detail.text for s in ('PRIVATE-KEY','PRIVATE-ENCRYPTED-KEY','private.invalid'))
    target,_,_,_=completed(accounts,other['id'],kind='product')
    assert bob.put('/api/image-configs',json={'base_url':'https://own-provider.example/v1','api_key':'synthetic-key',
        'model_name':'planner','planning_model_name':'planner','model_names':['planner']}).status_code==200
    response=bob.post(path+'/reuse',json={'request_id':str(uuid4()),'product_id':target,'title':'我的案例参考方案'})
    assert response.status_code==201,response.text
    assert response.json()['owner_id']==other['id'] and response.json()['source_product_id']==target
    assert alice.get('/api/creation-projects/'+response.json()['id']).status_code==404


def test_team_experience_adoption_is_owned_candidate_and_respects_stale_evidence(accounts):
    alice,user=member(accounts,'experience-author');bob,other=member(accounts,'experience-reader')
    project,_,_,_=completed(accounts,user['id'],kind='product')
    target=bob.post('/api/creation-projects',json={'title':'我的目标产品','kind':'product'}).json()['id']
    library=bob.get('/api/product-experience/library').json()['experiences']
    assert len(library)==1 and library[0]['author']['id']==user['id'] and library[0]['can_edit'] is False
    entry=library[0];path='/api/product-experience/library/'+entry['id']+'/adopt'
    body={'request_id':str(uuid4()),'product_id':target,'revision':entry['revision']}
    assert bob.post(path,json={**body,'product_id':project}).status_code==404
    assert bob.post(path,json={**body,'revision':99}).status_code==409
    result=bob.post(path,json=body);assert result.status_code==201,result.text
    assert result.json()['status']=='candidate' and result.json()['owner_id']==other['id']
    assert bob.post(path,json=body).json()['id']==result.json()['id']
    assert bob.put('/api/product-experience/'+project+'/'+entry['id'],json={'guidance':'改别人的经验','revision':1}).status_code==404
    with Session(accounts[2]) as s,s.begin():
        row=s.get(ProductImageExperience,entry['id']);row.status='disabled'
    assert bob.post(path,json={**body,'request_id':str(uuid4())}).status_code==409
    with Session(accounts[2]) as s,s.begin():
        row=s.get(ProductImageExperience,entry['id']);row.status='active'
        row.content=json.dumps({'guidance':'更新后的经验','sources':[{'id':str(uuid4()),'revision':1}]})
    assert bob.get('/api/product-experience/library').json()['experiences'][-1]['evidence_current'] is False
    assert bob.post(path,json={**body,'request_id':str(uuid4())}).status_code==409


def test_completed_new_set_publishes_despite_old_unknown_and_updates_once(accounts):
    _,user=member(accounts,'automatic-author')
    project,_,job,sid=completed(accounts,user['id'])
    app=accounts[1];engine=app.state.image_configs.engine;directory=accounts[3]
    new_id=str(uuid4());new_batch=str(uuid4())
    artifact(directory,new_id,'result.png').parent.mkdir(parents=True);artifact(directory,new_id,'result.png').write_bytes(png())
    with Session(engine) as s,s.begin():
        old=s.get(ImageJob,job)
        fields={c.name:getattr(old,c.name) for c in ImageJob.__table__.columns}
        fields.update(id=new_id,request_id=new_id,status='running',created_at=now(),updated_at=now())
        s.add(ImageJob(**fields));s.execute(update(ImageJob).where(ImageJob.id==job).values(status='unknown'))
        p=s.get(CreationProject,project);data=json.loads(p.content)
        data['batches'].append({'execution_id':new_batch,'job_ids':[new_id],'created_at':now()})
        p.content=json.dumps(data);p.revision+=1
    publish_completed_job(app.state.image_configs,new_id)
    with Session(engine) as s: assert s.get(TeamProjectShare,sid).version==1
    with Session(engine) as s,s.begin(): s.execute(update(ImageJob).where(ImageJob.id==new_id).values(status='succeeded',updated_at=now()))
    publish_completed_job(app.state.image_configs,new_id)
    with Session(engine) as s:
        share=s.get(TeamProjectShare,sid);assert share.version==2
        assert {i['status'] for i in json.loads(share.content)['images']}=={'unknown','succeeded'}
    publish_completed_job(app.state.image_configs,new_id);backfill(engine,directory)
    with Session(engine) as s: assert s.get(TeamProjectShare,sid).version==2
    # A deliberate private setting remains respected.
    with Session(engine) as s,s.begin():
        s.get(TeamProjectShare,sid).visibility='private'
        s.execute(update(ImageJob).where(ImageJob.id==new_id).values(updated_at=now()+'1'))
    publish_completed_job(app.state.image_configs,new_id)
    with Session(engine) as s: assert s.get(TeamProjectShare,sid).version==2


def test_incomplete_batch_waits_but_unselected_planned_shots_do_not_block_sharing(accounts):
    _,user=member(accounts,'partial-author')
    project,_,job,sid=completed(accounts,user['id'])
    engine=accounts[1].state.image_configs.engine
    doc=str(uuid4());pending=str(uuid4())
    with Session(engine) as s,s.begin():
        share=s.get(TeamProjectShare,sid);share.version=0;share.content='{}'
        row=s.get(CreationProject,project);data=json.loads(row.content)
        data['active']['prompts']=doc;data['batches'][0]['shot_ids']=['one','two'];data['batches'][0]['job_ids'].append(pending);row.content=json.dumps(data)
        original=s.get(ImageJob,job)
        fields={c.name:getattr(original,c.name) for c in ImageJob.__table__.columns}
        fields.update(id=pending,request_id=pending,status='queued')
        s.add(ImageJob(**fields))
        s.add(CreationDocument(id=doc,project_id=project,stage='prompts',version=1,created_at=now(),confirmed_at=now(),
            content=json.dumps({'prompts':[{'shot_id':'one'},{'shot_id':'two'},{'shot_id':'unselected'}]})))
    publish_completed_job(accounts[1].state.image_configs,job)
    with Session(engine) as s: assert s.get(TeamProjectShare,sid).version==0
    artifact(accounts[3],pending,'result.png').parent.mkdir(parents=True)
    artifact(accounts[3],pending,'result.png').write_bytes(png())
    with Session(engine) as s,s.begin(): s.execute(update(ImageJob).where(ImageJob.id==pending).values(status='succeeded'))
    publish_completed_job(accounts[1].state.image_configs,pending)
    with Session(engine) as s: assert s.get(TeamProjectShare,sid).version==1
