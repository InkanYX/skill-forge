from uuid import uuid4

from sqlalchemy.orm import Session

from app.database import ImageJob
from app.image_jobs import artifact
from test_standard_images import standard, save
from test_auth import accounts, member


def submit(client, config):
    reply = client.post('/api/image-jobs/batch', files={'_': (None, '1')}, data={
        'config_id': config['id'], 'model_name': config['model_name'],
        'request_id': str(uuid4()), 'prompt': '庭院', 'count': 2})
    assert reply.status_code == 202, reply.text
    return reply.json()


def test_removal_hides_records_preserves_files_and_can_be_restored(standard):
    client, _, engine, directory = standard
    jobs = submit(client, save(client))
    identifier = jobs[0]['id']
    task_id = jobs[0]['task_id']
    assert client.delete('/api/image-jobs/'+identifier).status_code == 409
    with Session(engine) as session, session.begin():
        for job in jobs:
            session.get(ImageJob,job['id']).status = 'succeeded'
    image = artifact(directory, identifier, 'result.png')
    image.parent.mkdir(parents=True, exist_ok=True)
    image.write_bytes(b'original-image-bytes')
    original_time = client.get('/api/image-jobs/'+identifier).json()['updated_at']
    for _ in range(2):
        assert client.delete('/api/image-jobs/'+identifier).status_code == 200
    assert image.read_bytes() == b'original-image-bytes'
    assert client.get('/api/image-jobs/'+identifier).status_code == 404
    assert client.get('/api/image-jobs/'+identifier+'/image').status_code == 404
    assert identifier not in [i['id'] for i in client.get('/api/image-jobs').json()]
    assert client.get('/api/image-jobs/library').json()['total'] == 1
    detail = client.get('/api/image-jobs/tasks/'+task_id).json()
    assert detail['counts']['total'] == 1 and identifier not in detail['completed_job_ids']
    assert client.delete('/api/image-jobs/'+jobs[1]['id']).status_code == 200
    assert client.get('/api/image-jobs/tasks/'+task_id).json()['items'] == []
    history = client.get('/api/image-jobs/tasks').json()
    assert all(item['counts']['total'] == 0 and not item['completed_job_ids'] for item in history['items'])
    for _ in range(2):
        assert client.post('/api/image-jobs/'+identifier+'/restore', files={'action':(None,'restore')}).status_code == 200
    restored = client.get('/api/image-jobs/'+identifier).json()
    assert restored['updated_at'] == original_time
    assert client.get('/api/image-jobs/library').json()['total'] == 1


def test_delete_and_restore_enforce_owner_permissions(accounts):
    _, _, engine, _ = accounts
    owner, _ = member(accounts,'owner')
    other, _ = member(accounts,'other')
    identifier = submit(owner, save(owner))[0]['id']
    with Session(engine) as session, session.begin():
        session.get(ImageJob,identifier).status = 'failed'
    assert other.delete('/api/image-jobs/'+identifier).status_code == 404
    assert owner.delete('/api/image-jobs/'+identifier).status_code == 200
    assert other.post('/api/image-jobs/'+identifier+'/restore', files={'action':(None,'restore')}).status_code == 404
    assert owner.post('/api/image-jobs/'+identifier+'/restore', files={'action':(None,'restore')}).status_code == 200
