import hashlib
import io
import json
from uuid import uuid4
from zipfile import ZipFile

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import (CreationProject,CreationDocument,CreationMaterial,ImageJob,TeamProjectShare,CreativeCase,ProductImageExperience)
from app.creation_materials import material_path
from app.image_jobs import artifact,now
from app.team_sharing import backfill
from test_auth import accounts,member
from test_image_jobs import png


def completed(accounts,owner,kind='plan'):
    _,app,engine,directory=accounts
    project_id=str(uuid4());mid=str(uuid4());jid=str(uuid4());analysis=str(uuid4());brief=str(uuid4())
    material=material_path(directory,project_id,mid);material.parent.mkdir(parents=True);material.write_bytes(png())
    artifact(directory,jid,'result.png').parent.mkdir(parents=True);artifact(directory,jid,'result.png').write_bytes(png())
    artifact(directory,jid,'reference.png').write_bytes(png())
    with Session(engine) as session,session.begin():
        session.add(CreationProject(id=project_id,owner_id=owner,title='凉棚完整流程',kind=kind,revision=4,created_at=now(),updated_at=now(),content=json.dumps({
            'analysis_confirmed':True,'goal':'展示连接结构','image_count':1,'active':{'analysis':analysis,'brief':brief},
            'planning_model':'private-planner','image_model':'private-image','batches':[{'execution_id':str(uuid4()),'job_ids':[jid],'created_at':now()}]})))
        session.add(CreationMaterial(id=mid,project_id=project_id,name='实拍.png',kind='产品实拍',media_type='image/png',digest=hashlib.sha256(png()).hexdigest(),size=len(png()),pages=1,created_at=now()))
        for identifier,stage,content in [(analysis,'analysis',{'facts':'同款产品实物','selling_points':'连接可靠','questions':''}),(brief,'brief',{'art_direction':'场景纵深','shots':[{'id':'shot','name':'结构展示','size':'1464x600','reference_ids':[mid]}]})]:
            session.add(CreationDocument(id=identifier,project_id=project_id,stage=stage,version=1,confirmed_at=now(),created_at=now(),content=json.dumps(content)))
        session.add(ImageJob(id=jid,owner_id=owner,task_id=project_id,request_id=jid,fingerprint='f'*64,config_id=str(uuid4()),config_name='PRIVATE-CONFIG',
            base_url='https://private.invalid/v1',encrypted_key='PRIVATE-ENCRYPTED-KEY',model_name='image-model',prompt='Actual final prompt',size='1464x600',mode='edit',status='succeeded',created_at=now(),updated_at=now(),
            shot_name='结构展示',execution_profile=json.dumps({'shot_role':'main','image_type':'listing','api_key':'PRIVATE-KEY','reference_manifest':[{'id':mid,'kind':'产品实拍'}]}),
            execution_result=json.dumps({'native_pixels':[12,8],'diagnostic':{'response_body':'PRIVATE-RESPONSE'},'agent_review':{'status':'passed','summary':'结构核对通过','checks':[]}})))
        session.add(CreativeCase(id=str(uuid4()),owner_id=owner,job_id=jid,title='反馈',experience='保留自然阴影',issues='',outcome='satisfied',requested_change='',updated_at=now()))
        session.add(ProductImageExperience(id=str(uuid4()),owner_id=owner,product_id=project_id,content=json.dumps({'guidance':'场景要有纵深','reuse_scope':'product'}),status='active',revision=1,created_at=now(),updated_at=now()))
    backfill(app.state.image_configs.engine,directory)
    with Session(engine) as session: share=session.scalar(select(TeamProjectShare).where(TeamProjectShare.project_id==project_id));sid=share.id
    return project_id,mid,jid,sid


def test_default_shared_snapshot_is_readable_but_live_work_and_files_are_private(accounts):
    admin,_,_,_=accounts;alice,user=member(accounts,'alice');bob,_=member(accounts,'bob')
    project,material,job,sid=completed(accounts,user['id'])
    for client in (bob,admin):
        assert client.get('/api/creation-projects').json()==[]
        assert client.get('/api/creation-projects/'+project).status_code==404
        assert client.get('/api/creation-projects/'+project+'/materials/'+material).status_code==404
        assert client.get('/api/image-jobs/'+job).status_code==404
        assert client.get('/api/image-jobs/'+job+'/image').status_code==404
        assert client.get('/api/image-jobs/tasks/'+project).status_code==404
        assert client.get('/api/image-jobs/tasks').json()['total']==0
        dashboard=client.get('/api/workspace').json()
        assert not dashboard['recent_images'] and not dashboard['active_jobs']
        shared=client.get('/api/team-shares/'+sid)
        assert shared.status_code==200,shared.text
        assert shared.json()['version']==1 and shared.json()['author']['id']==user['id']
        assert shared.json()['snapshot']['history'] and not shared.json()['can_manage']
        assert client.get('/api/team-shares/'+sid+'/files/materials/'+material).content==png()
        assert client.get('/api/team-shares/'+sid+'/files/images/'+job+'/original.png').content==png()
        for secret in ('PRIVATE-KEY','PRIVATE-ENCRYPTED-KEY','PRIVATE-RESPONSE','private.invalid','PRIVATE-CONFIG'):
            assert secret not in shared.text
        assert client.post('/api/team-shares/'+sid+'/publish',json={'version':1,'visibility':'team'}).status_code==403
    assert alice.get('/api/creation-projects/'+project).status_code==200
    assert len(bob.get('/api/team-shares').json()['items'])==1


def test_copy_is_independent_owned_idempotent_and_credential_free(accounts):
    alice,user=member(accounts,'alice');bob,other=member(accounts,'bob')
    project,material,job,sid=completed(accounts,user['id'])
    body={'request_id':str(uuid4()),'title':'我的参考方案','version':1}
    response=bob.post('/api/team-shares/'+sid+'/copy',json=body)
    assert response.status_code==201,response.text
    copied=response.json();assert copied['id']!=project and copied['kind']=='plan'
    assert bob.post('/api/team-shares/'+sid+'/copy',json=body).json()['id']==copied['id']
    details=bob.get('/api/creation-projects/'+copied['id']).json()
    assert details['owner_id']==other['id'] and details['can_edit']
    assert details['team_source']['id']==sid and details['team_source']['version']==1
    assert details['materials'][0]['id']!=material
    assert details['documents']['brief']['confirmed_at'] is None
    assert details['documents']['brief']['content']['shots'][0]['reference_ids']==[details['materials'][0]['id']]
    assert details['images'][0]['id']!=job
    assert alice.get('/api/creation-projects/'+copied['id']).status_code==404
    assert bob.get('/api/image-configs').json() is None
    with Session(accounts[2]) as session:
        imported=session.get(ImageJob,details['images'][0]['id'])
        assert imported.owner_id==other['id'] and imported.encrypted_key=='' and imported.base_url==''
        assert json.loads(imported.execution_profile)['creation_project_id']==copied['id']
        assert json.loads(imported.execution_profile)['shot_role']=='main'
        assert json.loads(imported.execution_profile)['image_type']=='listing'
        assert json.loads(session.get(CreationProject,copied['id']).content)['team_source']['version']==1
    library=bob.get('/api/product-experience/library').json()['experiences']
    assert len(library)==2 and sum(item['can_edit'] for item in library)==1
    # Withdrawal closes every shared endpoint, without deleting an existing independent copy.
    assert alice.put('/api/team-shares/'+sid,json={'version':1,'visibility':'private'}).status_code==200
    for path in ('','/download','/files/materials/'+material):assert bob.get('/api/team-shares/'+sid+path).status_code==404
    assert bob.post('/api/team-shares/'+sid+'/copy',json={**body,'request_id':str(uuid4())}).status_code==404
    assert bob.get('/api/creation-projects/'+copied['id']+'/materials/'+details['materials'][0]['id']).content==png()
    assert bob.get('/api/image-jobs/'+details['images'][0]['id']+'/image').content==png()


def test_versions_freeze_until_published_and_exports_use_only_shared_files(accounts):
    alice,user=member(accounts,'alice');bob,_=member(accounts,'bob')
    project,material,job,sid=completed(accounts,user['id'])
    with Session(accounts[2]) as session,session.begin():
        row=session.get(CreationProject,project);row.title='修改后的标题';row.revision+=1
        session.get(ImageJob,job).prompt='Changed private prompt'
    before=bob.get('/api/team-shares/'+sid).json()
    assert before['title']=='凉棚完整流程' and before['snapshot']['images'][0]['prompt']=='Actual final prompt'
    updated=alice.post('/api/team-shares/'+sid+'/publish',json={'version':1,'visibility':'team'})
    assert updated.status_code==200,updated.text
    assert updated.json()['version']==2 and updated.json()['title']=='修改后的标题'
    assert alice.post('/api/team-shares/'+sid+'/publish',json={'version':1,'visibility':'team'}).status_code==409
    assert bob.post('/api/team-shares/'+sid+'/copy',json={'request_id':str(uuid4()),'title':'过期版本','version':1}).status_code==409
    exported=bob.get('/api/team-shares/'+sid+'/download')
    assert exported.status_code==200
    with ZipFile(io.BytesIO(exported.content)) as archive:
        snapshot=json.loads(archive.read('snapshot.json'))
        assert snapshot['images'][0]['prompt']=='Changed private prompt'
        assert archive.read('materials/'+material)==png()
        assert all('execution.json' not in name for name in archive.namelist())


def test_new_product_defaults_to_team_and_completed_analysis_auto_publishes(accounts):
    alice,_=member(accounts,'alice');bob,_=member(accounts,'bob')
    result=alice.post('/api/creation-projects',json={'title':'新产品','kind':'product'})
    assert result.status_code==201,result.text
    project=result.json()
    share=next(s for s in bob.get('/api/team-shares').json()['items'] if s['project_id']==project['id'])
    assert share['visibility']=='team' and share['version']==0
    # Normal document confirmation occurs in a request-scoped session.
    from app.authorization import principal
    with Session(accounts[1].state.image_configs.engine) as session,session.begin():
        token=principal.set(alice.get('/api/auth/me').json()['user'])
        try:
            row=session.get(CreationProject,project['id']);data=json.loads(row.content);data['analysis_confirmed']=True
            row.content=json.dumps(data)
        finally:principal.reset(token)
    assert bob.get('/api/team-shares/'+share['id']).json()['version']==1


def test_adopt_shared_experience_is_private_candidate_and_idempotent(accounts):
    alice,user=member(accounts,'alice');bob,other=member(accounts,'bob')
    project,_,_,sid=completed(accounts,user['id'],kind='product')
    own=bob.post('/api/creation-projects',json={'title':'我的产品','kind':'product'}).json()['id']
    body={'request_id':str(uuid4()),'product_id':own,'version':1,'index':0}
    endpoint='/api/team-shares/'+sid+'/experiences'
    assert bob.post(endpoint,json={**body,'product_id':project}).status_code==404
    assert bob.post(endpoint,json={**body,'index':5}).status_code==404
    result=bob.post(endpoint,json=body)
    assert result.status_code==201,result.text
    assert bob.post(endpoint,json=body).json()==result.json()
    with Session(accounts[2]) as session:
        row=session.get(ProductImageExperience,body['request_id'])
        assert row.owner_id==other['id'] and row.status=='candidate' and row.product_id==own
        content=json.loads(row.content)
        assert content['sources']==[] and content['team_source']['id']==sid
        assert content['guidance']=='场景要有纵深'
    assert alice.put('/api/team-shares/'+sid,json={'version':1,'visibility':'private'}).status_code==200
    assert bob.post(endpoint,json={**body,'request_id':str(uuid4())}).status_code==404


def test_bulk_worker_completion_publishes_only_after_all_images_finish(accounts):
    from app.team_sharing import publish_completed_job
    from sqlalchemy import update
    _,user=member(accounts,'artist')
    _,_,job,sid=completed(accounts,user['id'])
    engine=accounts[1].state.image_configs.engine
    with Session(engine) as session,session.begin():
        share=session.get(TeamProjectShare,sid);share.version=0;share.content='{}'
        session.execute(update(ImageJob).where(ImageJob.id==job).values(status='running'))
    publish_completed_job(accounts[1].state.image_configs,job)
    with Session(engine) as session: assert session.get(TeamProjectShare,sid).version==0
    with Session(engine) as session,session.begin():
        session.execute(update(ImageJob).where(ImageJob.id==job).values(status='succeeded'))
    publish_completed_job(accounts[1].state.image_configs,job)
    with Session(engine) as session: assert session.get(TeamProjectShare,sid).version==1


def test_copy_before_configuring_models_can_later_plan_with_own_connection(accounts):
    from app.database import CreationExecution
    alice,user=member(accounts,'source-owner');bob,other=member(accounts,'recipient')
    _,_,_,sid=completed(accounts,user['id'])
    result=bob.post('/api/team-shares/'+sid+'/copy',json={'request_id':str(uuid4()),'title':'独立策划副本','version':1})
    assert result.status_code==201,result.text
    copied=bob.get('/api/creation-projects/'+result.json()['id']).json()
    saved=bob.put('/api/image-configs',json={'base_url':'https://own-provider.example/v1','api_key':'synthetic-private-key',
        'model_name':'my-planner','planning_model_name':'my-planner','model_names':['my-planner']})
    assert saved.status_code==200,saved.text
    run=str(uuid4())
    queued=bob.post('/api/creation-projects/'+copied['id']+'/stages/brief',json={'revision':copied['revision'],'request_id':run})
    assert queued.status_code==202,queued.text
    with Session(accounts[2]) as session:
        execution=session.get(CreationExecution,run);payload=json.loads(execution.input)
        assert payload['profile']['model']=='my-planner'
        assert payload['profile']['base_url']=='https://own-provider.example/v1'
        assert payload['skill_snapshot']['primary']['name']=='premium-product-image-workflow'
        assert payload['settings']['style']==''
