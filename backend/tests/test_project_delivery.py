import io
import json
from uuid import uuid4
from zipfile import ZipFile

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.creation_projects import process_creation_one
from app.database import ImageJob, CreationExecution, CreationProject, CreationDocument, WorkflowCase
from app.image_jobs import artifact
from app.image_provider import GenerationError
from app.standard_image_worker import process_standard_one
from test_creation_projects import project_setup, confirmed_project, edit, confirm
from test_standard_images import standard, KEY
from test_image_jobs import png
from test_product_planning import product


def executor(directory,profile,key,prompt,reference):
    directory.mkdir(parents=True,exist_ok=True)
    (directory/'result.png').write_bytes(png())
    (directory/'preview.jpg').write_bytes(png())
    return {'native_pixels':[12,8],'review':{'status':'pending'}}


def submitted(setup):
    client,store,engine,directory,_=setup
    project=confirmed_project(setup)
    shots=project['documents']['brief']['content']['shots']
    for shot in shots:
        shot['size']='1464x600'
        shot['copy']='Headline: Backyard living\nNote: Furniture not included.'
    prompts=project['documents']['prompts']['content']
    project=confirm(client,edit(client,project,'brief',{'shots':shots}),'brief')
    project=confirm(client,edit(client,project,'prompts',prompts),'prompts')
    result=client.post('/api/creation-projects/'+project['id']+'/generate',json={
        'revision':project['revision'],'request_id':str(uuid4()),'shot_ids':['scene','detail'],'image_model':'image-editor'})
    assert result.status_code==202,result.text
    assert process_creation_one(store)
    return client.get('/api/creation-projects/'+project['id']).json()


def finished(setup):
    project=submitted(setup)
    client,store,*_=setup
    for _ in range(2): assert process_standard_one(store,executor)
    return client.get('/api/creation-projects/'+project['id']).json()


def test_mobile_is_idempotent_edit_batch_with_real_references_and_separate_history(project_setup):
    client,store,engine,directory,_=project_setup
    source=finished(project_setup)
    batch=source['batches'][-1]
    body={'revision':source['revision'],'request_id':str(uuid4()),'batch_id':batch['execution_id'],'image_model':'image-editor'}
    path='/api/creation-projects/'+source['id']+'/mobile'
    response=client.post(path,json=body)
    assert response.status_code==202,response.text
    target=response.json()
    assert target['id']!=source['id'] and target['mobile_source']['job_ids']==batch['job_ids']
    assert client.post(path,json=body).json()['id']==target['id']
    assert len(target['materials'])==len(source['materials'])+2
    assert {s['size'] for s in target['documents']['brief']['content']['shots']}=={'1200x900'}
    assert 'Furniture not included' in target['documents']['prompts']['content']['prompts'][0]['prompt']
    assert 'CONFIRMED SCENE EXACT PROMPT' not in target['documents']['prompts']['content']['prompts'][0]['prompt']
    assert process_creation_one(store)
    target=client.get('/api/creation-projects/'+target['id']).json()
    assert len(target['images'])==2
    assert {i['mode'] for i in target['images']}=={'edit'}
    for image in target['images']:
        refs=image['execution_profile']['reference_manifest']
        assert len(refs)==3 and refs[0]['role']=='排版参考'
        assert (artifact(directory,image['id'],'reference-2.png')).is_file()
    original=client.get('/api/creation-projects/'+source['id']).json()
    assert original['batches']==source['batches'] and len(original['images'])==2
    assert not any(i['size']=='1200x900' for i in original['images'])
    for _ in range(2): assert process_standard_one(store,executor)
    archived=client.post('/api/creation-projects/'+source['id']+'/cases',json={
        'revision':original['revision'],'request_id':str(uuid4()),'title':'桌面与手机版完整案例'})
    assert archived.status_code==201,archived.text
    assert archived.json()['image_count']==4
    detail=client.get('/api/workflow-cases/'+archived.json()['id']).json()['snapshot']
    assert len(detail['related_projects'])==1
    assert {i['size'] for i in detail['images']}=={'1464x600','1200x900'}


def test_mobile_rejects_incomplete_batch_without_placing_orders(project_setup):
    client,store,engine,directory,_=project_setup
    source=submitted(project_setup)
    result=client.post('/api/creation-projects/'+source['id']+'/mobile',json={
        'revision':source['revision'],'request_id':str(uuid4()),'batch_id':source['batches'][0]['execution_id']})
    assert result.status_code==409
    with Session(engine) as s:
        assert len(list(s.scalars(select(CreationExecution))))==1


def test_archive_freezes_full_workflow_and_reuse_reads_target_product_facts(project_setup):
    client,store,engine,directory,_=project_setup
    source=finished(project_setup)
    body={'revision':source['revision'],'request_id':str(uuid4()),'title':'场景图案例','summary':'适用于庭院类：使用有景深的场景，固定四根立柱。'}
    path='/api/creation-projects/'+source['id']+'/cases'
    response=client.post(path,json=body)
    assert response.status_code==201,response.text
    case=response.json()
    assert client.post(path,json=body).json()['id']==case['id']
    detail=client.get('/api/workflow-cases/'+case['id']).json()
    assert detail['snapshot']['history'] and len(detail['snapshot']['materials'])==2
    assert KEY not in json.dumps(detail)
    bundle=client.get('/api/workflow-cases/'+case['id']+'/download')
    assert bundle.status_code==200,bundle.text[:100] if bundle.status_code!=200 else ''
    with ZipFile(io.BytesIO(bundle.content)) as archive:
        assert archive.testzip() is None
        names=archive.namelist()
        assert 'snapshot.json' in names and any(n.startswith('materials/') for n in names)
        assert any(n.startswith('skills/') for n in names)
        assert any(n.endswith('original.png') for n in names)
        assert KEY.encode() not in archive.read('snapshot.json')
    image=source['images'][0]
    assert client.delete('/api/image-jobs/'+image['id']).status_code==200
    assert client.get('/api/workflow-cases/'+case['id']+'/images/'+image['id']).status_code==200
    assert len(client.get('/api/workflow-cases/'+case['id']).json()['snapshot']['images'])==2
    target_product=product(project_setup)
    reuse={'request_id':str(uuid4()),'title':'案例参考新方案','product_id':target_product['id']}
    response=client.post('/api/workflow-cases/'+case['id']+'/reuse',json=reuse)
    assert response.status_code==201,response.text
    target=response.json()
    assert target['case_reference']['id']==case['id']
    assert target['documents']['analysis']['content']==target_product['documents']['analysis']['content']
    assert not target['images'] and not target['documents']['prompts']
    assert len([m for m in target['materials'] if m['kind']=='风格参考'])==2
    assert client.post('/api/workflow-cases/'+case['id']+'/reuse',json=reuse).json()['id']==target['id']
    queued=client.post('/api/creation-projects/'+target['id']+'/stages/brief',json={
        'revision':target['revision'],'request_id':str(uuid4())})
    assert queued.status_code==202,queued.text
    with Session(engine) as s:
        run=s.scalar(select(CreationExecution).where(CreationExecution.project_id==target['id']))
        assert json.loads(run.input)['template']['case_reference']['guidance']==body['summary']


def test_ordinary_failure_retries_once_and_records_both_attempts(project_setup):
    client,store,*_=project_setup
    source=submitted(project_setup)
    calls=[]
    def flaky(*args):
        calls.append(1)
        if len(calls)==1: raise GenerationError('限流',diagnostic={'http_status':429})
        return executor(*args)
    assert process_standard_one(store,flaky)
    job=client.get('/api/image-jobs/'+source['images'][0]['id']).json()
    assert job['status']=='succeeded' and len(calls)==2
    assert [a['status'] for a in job['execution_result']['attempts']]==['failed','succeeded']


def test_repeat_failure_is_bounded_to_three_calls_and_next_image_runs(project_setup):
    client,store,*_=project_setup
    source=submitted(project_setup); calls=[]
    def fail(*args):
        calls.append(1);raise GenerationError('普通失败')
    assert process_standard_one(store,fail)
    job=client.get('/api/image-jobs/'+source['images'][0]['id']).json()
    assert job['status']=='failed' and len(calls)==3
    assert len(job['execution_result']['attempts'])==3
    assert process_standard_one(store,executor)
    jobs=client.get('/api/creation-projects/'+source['id']).json()['images']
    assert {item['status'] for item in jobs}=={'failed','succeeded'}


def test_permission_denial_is_not_retried_and_leaves_remaining_batch_queued(project_setup):
    client,store,*_=project_setup
    source=submitted(project_setup);calls=[]
    def denied(*args):
        calls.append(1);raise GenerationError('权限拒绝',diagnostic={'http_status':403})
    assert process_standard_one(store,denied)
    jobs=client.get('/api/creation-projects/'+source['id']).json()['images']
    assert len(calls)==1 and {i['status'] for i in jobs}=={'failed','queued'}
    assert process_standard_one(store,executor)
    assert {i['status'] for i in client.get('/api/creation-projects/'+source['id']).json()['images']}=={'failed','succeeded'}


def test_uncertain_timeout_never_retries_paid_call(project_setup):
    client,store,*_=project_setup
    source=submitted(project_setup);calls=[]
    def uncertain(*args):
        calls.append(1);raise GenerationError('响应超时',True,{'error_type':'ReadTimeout'})
    assert process_standard_one(store,uncertain)
    job=client.get('/api/image-jobs/'+source['images'][0]['id']).json()
    assert len(calls)==1 and job['status']=='unknown'


def test_existing_output_prevents_retry(project_setup):
    client,store,*_=project_setup
    source=submitted(project_setup);calls=[]
    def saved(directory,*args):
        calls.append(1);(directory/'result.png').write_bytes(png());raise GenerationError('已有输出')
    assert process_standard_one(store,saved)
    job=client.get('/api/image-jobs/'+source['images'][0]['id']).json()
    assert len(calls)==1 and len(job['execution_result']['attempts'])==1
