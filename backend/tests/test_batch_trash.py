import json
from uuid import uuid4

from sqlalchemy.orm import Session
from app.database import CreationProject, ImageJob
from app.creation_projects import process_creation_one
from app.standard_image_worker import process_standard_one
from app.image_jobs import artifact
from test_creation_projects import project_setup
from test_standard_images import standard
from test_auth import accounts, member
from test_project_delivery import finished, submitted, executor


def versions(setup):
    client, store, *_ = setup
    project = finished(setup)
    for _ in range(2):
        response = client.post('/api/creation-projects/'+project['id']+'/generate', json={
            'revision': project['revision'], 'request_id': str(uuid4()),
            'shot_ids': ['scene', 'detail'], 'image_model': 'image-editor'})
        assert response.status_code == 202, response.text
        assert process_creation_one(store)
        for _ in range(2): assert process_standard_one(store, executor)
        project = client.get('/api/creation-projects/'+project['id']).json()
    return project


def test_bulk_delete_restore_preserves_files_versions_and_individual_trash(project_setup):
    client, _, engine, directory, _ = project_setup
    project = versions(project_setup)
    first, second, latest = project['batches']
    path = '/api/creation-projects/'+project['id']+'/batches/'
    # A previously individually deleted image must remain deleted after undo.
    identifier = first['job_ids'][0]
    assert client.delete('/api/image-jobs/'+identifier).status_code == 200
    body = {'batch_ids': [first['execution_id'], second['execution_id']], 'request_id': str(uuid4())}
    response = client.post(path+'delete', json=body)
    assert response.status_code == 200, response.text
    assert response.json()['count'] == 3
    assert client.post(path+'delete', json=body).status_code == 200
    after = client.get('/api/creation-projects/'+project['id']).json()
    assert [b['execution_id'] for b in after['batches']] == [latest['execution_id']]
    assert after['batches'][0]['version_number'] == 3
    assert len(after['images']) == 2
    task = client.get('/api/image-jobs/tasks/'+project['id']).json()
    assert len(task['batches']) == 1 and len(task['items']) == 2
    assert artifact(directory, identifier, 'result.png').is_file()
    for _ in range(2): assert client.post(path+'restore/'+body['request_id']).status_code == 200
    after = client.get('/api/creation-projects/'+project['id']).json()
    assert len(after['batches']) == 3 and len(after['images']) == 5
    with Session(engine) as s: assert s.get(ImageJob, identifier).deleted_at


def test_batch_validation_is_atomic_and_protects_latest_and_uncertain(project_setup):
    client, _, engine, _, _ = project_setup
    project = versions(project_setup)
    path = '/api/creation-projects/'+project['id']+'/batches/delete'
    ids = [b['execution_id'] for b in project['batches']]
    for selected, status in [([ids[0], str(uuid4())],404), ([ids[0],ids[-1]],409)]:
        assert client.post(path,json={'batch_ids':selected,'request_id':str(uuid4())}).status_code == status
    with Session(engine) as s, s.begin(): s.get(ImageJob,project['batches'][1]['job_ids'][0]).status='unknown'
    assert client.post(path,json={'batch_ids':ids[:2],'request_id':str(uuid4())}).status_code == 409
    after=client.get('/api/creation-projects/'+project['id']).json()
    assert len(after['images']) == 6 and len(after['batches']) == 3


def test_archive_includes_uncertain_history_without_retry(project_setup):
    client, _, engine, _, _ = project_setup
    project = finished(project_setup)
    with Session(engine) as s, s.begin(): s.get(ImageJob,project['images'][0]['id']).status='unknown'
    result=client.post('/api/creation-projects/'+project['id']+'/cases',json={
        'revision':project['revision'],'request_id':str(uuid4()),'title':'含待确认历史的案例'})
    assert result.status_code==201,result.text
    snapshot=client.get('/api/workflow-cases/'+result.json()['id']).json()['snapshot']
    assert {i['status'] for i in snapshot['images']}=={'unknown','succeeded'}


def test_archive_waits_for_active_image_generation(project_setup):
    client,*_=project_setup
    project=submitted(project_setup)
    response=client.post('/api/creation-projects/'+project['id']+'/cases',json={
        'revision':project['revision'],'request_id':str(uuid4()),'title':'进行中的案例'})
    assert response.status_code==409


def test_version_removal_follows_edit_descendants_but_protects_other_versions(project_setup):
    client, _, engine, _, _ = project_setup
    project=versions(project_setup)
    first, second, latest=project['batches']
    root=first['job_ids'][0]
    child_id=str(uuid4())
    with Session(engine) as s,s.begin():
        source=s.get(ImageJob,root)
        fields={column.name:getattr(source,column.name) for column in ImageJob.__table__.columns}
        fields.update(id=child_id,task_id=str(uuid4()),request_id=str(uuid4()),parent_job_id=root,status='failed')
        s.add(ImageJob(**fields))
        # A new persisted version can reference the old version; it stays independent.
        s.get(ImageJob,latest['job_ids'][0]).parent_job_id=root
        row=s.get(CreationProject,project['id']);data=json.loads(row.content)
        data['batches'][0]['retry_history']={root:[first['job_ids'][1]]}
        data['batches'][0]['job_ids']=[root]
        row.content=json.dumps(data)
    token=str(uuid4());path='/api/creation-projects/'+project['id']+'/batches/'
    result=client.post(path+'delete',json={'batch_ids':[first['execution_id']],'request_id':token})
    assert result.status_code==200,result.text
    assert result.json()['count']==3
    with Session(engine) as s:
        assert s.get(ImageJob,child_id).deleted_at
        assert not s.get(ImageJob,latest['job_ids'][0]).deleted_at
    assert client.post(path+'restore/'+token).status_code==200
    with Session(engine) as s: assert s.get(ImageJob,child_id).deleted_at is None


def test_other_account_cannot_remove_or_restore_project_versions(accounts):
    _,_,engine,_=accounts
    owner,owner_id=member(accounts,'version-owner')
    other,_=member(accounts,'version-other')
    identifier=str(uuid4())
    with Session(engine) as s,s.begin():
        s.add(CreationProject(id=identifier,owner_id=owner_id['id'],kind='plan',title='private',revision=1,
            content='{}',created_at='2026-11-25T00:00:00Z',updated_at='2026-11-25T00:00:00Z'))
    path='/api/creation-projects/'+identifier+'/batches/'
    assert other.post(path+'delete',json={'batch_ids':[str(uuid4())],'request_id':str(uuid4())}).status_code==404
    assert other.post(path+'restore/'+str(uuid4())).status_code==404
