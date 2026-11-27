import json
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import ImageJob, AgentRun
from app.image_jobs import artifact
from app.image_provider import GenerationError
from app.standard_image_worker import process_standard_one
from test_project_delivery import submitted, executor
from test_creation_projects import project_setup
from test_standard_images import standard, KEY
from test_creation_skills import workflow, submit


def fail(*args):
    raise GenerationError('普通失败', diagnostic={'http_status': 500})


def retry(client, identifier, request_id=None, provider_checked=False):
    return client.post(f'/api/image-jobs/{identifier}/retry', files={
        'request_id': (None, request_id or str(uuid4())), 'provider_checked': (None, str(provider_checked).lower())})


def test_retry_new_record_exact_edit_inputs_idempotency_and_project_version(project_setup):
    client, store, engine, directory, _ = project_setup
    source = submitted(project_setup)
    first = source['images'][0]
    assert process_standard_one(store, fail)
    original = client.get('/api/image-jobs/' + first['id']).json()
    request_id = str(uuid4())
    response = retry(client, first['id'], request_id)
    assert response.status_code == 202, response.text
    created = response.json()
    assert created['id'] != first['id'] and created['status'] == 'queued'
    assert created['prompt'] == original['prompt'] and created['model_name'] == original['model_name']
    assert created['mode'] == original['mode'] == 'edit'
    assert created['execution_profile']['reference_manifest'] == original['execution_profile']['reference_manifest']
    assert retry(client, first['id'], request_id).json()['id'] == created['id']
    assert retry(client, first['id']).json()['id'] == created['id']
    for name in ('reference.png', 'reference-2.png'):
        assert artifact(directory, created['id'], name).read_bytes() == artifact(directory, first['id'], name).read_bytes()
    current = client.get('/api/creation-projects/' + source['id']).json()
    assert len(current['batches']) == len(source['batches']) == 1
    batch = current['batches'][0]
    assert batch['execution_id'] == source['batches'][0]['execution_id']
    assert batch['created_at'] == source['batches'][0]['created_at']
    assert batch['shot_ids'] == source['batches'][0]['shot_ids']
    assert batch['job_ids'] == [created['id'], source['batches'][0]['job_ids'][1]]
    assert batch['retry_history'] == {created['id']: [first['id']]}
    assert created['execution_profile']['creation_execution_id'] == batch['execution_id']
    assert client.get('/api/image-jobs/tasks/' + source['id']).json()['batches'] == current['batches']
    assert process_standard_one(store, executor)
    assert process_standard_one(store, executor, preparer=lambda *args: pytest.fail('must reuse final prompt'))
    assert retry(client, first['id'], request_id).json()['status'] == 'succeeded'
    assert client.get('/api/image-jobs/' + first['id']).json()['execution_result'] == original['execution_result']
    assert KEY not in json.dumps(created)
    assert not process_standard_one(store, executor)
    assert retry(client, first['id']).status_code == 409  # Old failures cannot replace a successful retry.
    current = client.get('/api/creation-projects/' + source['id']).json()
    mobile = client.post('/api/creation-projects/' + source['id'] + '/mobile', json={
        'revision': current['revision'], 'request_id': str(uuid4()), 'batch_id': batch['execution_id'],
        'image_model': 'image-editor'})
    assert mobile.status_code == 202, mobile.text
    assert mobile.json()['mobile_source']['job_ids'] == batch['job_ids']


def test_chained_and_multiple_shot_retries_preserve_slots(project_setup):
    client, store, *_ = project_setup
    source = submitted(project_setup)
    originals = source['batches'][0]['job_ids']
    assert process_standard_one(store, fail)
    assert process_standard_one(store, fail)
    first = retry(client, originals[0]).json()['id']
    second = retry(client, originals[1]).json()['id']
    assert process_standard_one(store, fail)
    third = retry(client, first).json()['id']
    project = client.get('/api/creation-projects/' + source['id']).json()
    assert len(project['batches']) == 1
    assert project['batches'][0]['job_ids'] == [third, second]
    assert project['batches'][0]['retry_history'] == {third: [originals[0], first], second: [originals[1]]}
    assert project['batches'][0]['shot_ids'] == source['batches'][0]['shot_ids']
    assert retry(client, originals[0]).status_code == 409


@pytest.mark.parametrize('state', ['queued', 'running', 'unknown', 'succeeded'])
def test_nonfailed_state_cannot_be_retried(project_setup, state):
    client, store, engine, directory, _ = project_setup
    source = submitted(project_setup)
    first = source['images'][0]['id']
    with Session(engine) as session, session.begin():
        session.get(ImageJob, first).status = state
    assert retry(client, first).status_code == 409
    if state != 'unknown':
        assert retry(client, first, provider_checked=True).status_code == 409


def test_unknown_retry_requires_acknowledgement_and_preserves_original(project_setup):
    client, store, engine, directory, _ = project_setup
    source = submitted(project_setup)
    first = source['images'][0]['id']
    with Session(engine) as session, session.begin():
        session.get(ImageJob, first).status = 'unknown'
    original = client.get('/api/image-jobs/' + first).json()
    assert retry(client, first).status_code == 409
    request_id = str(uuid4())
    response = retry(client, first, request_id, provider_checked=True)
    assert response.status_code == 202, response.text
    created = response.json()
    assert created['id'] != first and created['status'] == 'queued'
    for key in ('prompt', 'model_name', 'mode', 'size', 'config_id'):
        assert created[key] == original[key]
    audit = created['execution_profile']['retry_confirmation']
    assert audit['provider_checked'] is True and audit['source_job_id'] == first
    assert audit['source_status'] == 'unknown' and audit['acknowledged_at']
    for name in ('reference.png', 'reference-2.png'):
        assert artifact(directory, created['id'], name).read_bytes() == artifact(directory, first, name).read_bytes()
    assert client.get('/api/image-jobs/' + first).json() == original
    assert retry(client, first, request_id).json()['id'] == created['id']
    assert retry(client, first, provider_checked=True).json()['id'] == created['id']


def test_unknown_acknowledgement_does_not_bypass_existing_output(project_setup):
    client, store, engine, directory, _ = project_setup
    first = submitted(project_setup)['images'][0]['id']
    with Session(engine) as session, session.begin():
        session.get(ImageJob, first).status = 'unknown'
    artifact(directory, first, 'result.png').write_bytes(b'already returned')
    assert retry(client, first, provider_checked=True).status_code == 409
    with Session(engine) as session:
        assert len(list(session.scalars(select(ImageJob)))) == 2


def test_retry_missing_reference_and_existing_output_block_duplicates(project_setup):
    client, store, engine, directory, _ = project_setup
    source = submitted(project_setup)
    first = source['images'][0]['id']
    assert process_standard_one(store, fail)
    path = artifact(directory, first, 'reference-2.png')
    content = path.read_bytes()
    path.unlink()
    assert retry(client, first).status_code == 409
    path.write_bytes(content)
    artifact(directory, first, 'result.webp').write_bytes(b'already returned')
    assert retry(client, first).status_code == 409
    with Session(engine) as session:
        assert len(list(session.scalars(select(ImageJob)))) == 2


def test_runtime_key_and_provider_connection_checked_without_switching(project_setup):
    client, store, engine, directory, _ = project_setup
    source = submitted(project_setup)
    first = source['images'][0]['id']
    assert process_standard_one(store, fail)
    keys = store.keys.copy()
    store.keys.clear()
    assert retry(client, first).status_code == 409
    store.keys.update(keys)
    response = client.put('/api/image-configs', json={'base_url':'https://different.example/v1', 'api_key':KEY,
        'model_name':'image-editor', 'model_names':['planner','image-editor']})
    assert response.status_code == 200
    assert retry(client, first).status_code == 409


def test_failure_in_skill_batch_preserves_later_images_and_three_call_allowance(project_setup):
    client, store, engine, directory, _ = project_setup
    source = submitted(project_setup)
    with Session(engine) as session, session.begin():
        run_id = str(uuid4())
        session.add(AgentRun(id=run_id, status='waiting_images', owner_id=None, config_id=source['images'][0]['config_id'],
            goal='batch', model_name='', vision_model_name='', skill_id='', skill_version_id='',
            steps_count=0, image_calls=0, max_steps=20, max_images=6, created_at='2026-11-25', updated_at='2026-11-25'))
        for job in session.scalars(select(ImageJob)):
            job.agent_run_id = run_id
    assert process_standard_one(store, fail)
    with Session(engine) as session:
        assert session.get(AgentRun, run_id).status == 'waiting_images'
        assert sorted(j.status for j in session.scalars(select(ImageJob))) == ['failed', 'queued']
    assert process_standard_one(store, executor)
    with Session(engine) as session:
        assert session.get(AgentRun, run_id).status == 'failed'
        assert sorted(j.status for j in session.scalars(select(ImageJob))) == ['failed', 'succeeded']


def test_real_skill_batch_each_image_can_succeed_on_third_attempt(workflow):
    client, store, engine, directory, config, captured = workflow
    images, _ = submit(workflow, count=2)
    calls = []
    def third_time(directory, profile, key, prompt, reference):
        calls.append(directory.name)
        if calls.count(directory.name) < 3:
            raise GenerationError('temporary failure', diagnostic={'http_status':500})
        return executor(directory, profile, key, prompt, reference)
    assert process_standard_one(store, third_time)
    assert process_standard_one(store, third_time)
    assert len(calls) == 6, [client.get('/api/image-jobs/' + image['id']).json()['message'] for image in images]
    for image in images:
        result = client.get('/api/image-jobs/' + image['id']).json()
        assert result['status'] == 'succeeded'
        assert [a['status'] for a in result['execution_result']['attempts']] == ['failed','failed','succeeded']
    with Session(engine) as session:
        assert session.get(AgentRun, images[0]['task_id']).image_calls == 6


def test_pending_unknown_retry_prevents_another_paid_submission(project_setup):
    client, store, engine, directory, _ = project_setup
    source = submitted(project_setup)
    first = source['images'][0]['id']
    assert process_standard_one(store, fail)
    created = retry(client, first).json()
    with Session(engine) as session, session.begin():
        session.get(ImageJob, created['id']).status = 'unknown'
    assert retry(client, first).status_code == 409
    assert retry(client, first, provider_checked=True).status_code == 409
    with Session(engine) as session:
        assert len(list(session.scalars(select(ImageJob)))) == 3


def test_other_owner_cannot_retry_private_connection(project_setup):
    client, store, engine, directory, _ = project_setup
    source = submitted(project_setup)
    first = source['images'][0]['id']
    assert process_standard_one(store, fail)
    with Session(engine) as session, session.begin():
        session.get(ImageJob, first).owner_id = str(uuid4())
    assert retry(client, first).status_code == 403


def test_inline_revision_unknown_retry_stays_in_batch_and_unblocks_creation(project_setup, monkeypatch):
    client, store, engine, directory, _ = project_setup
    source = submitted(project_setup)
    assert process_standard_one(store, executor)
    assert process_standard_one(store, executor)
    root = source['images'][0]
    values = {'config_id': root['config_id'], 'model_name': root['model_name'],
        'request_id': str(uuid4()), 'source_job_id': root['id'], 'prompt': '只调整排版', 'count': '1'}
    response = client.post('/api/image-jobs/batch', files={key:(None,value) for key,value in values.items()})
    assert response.status_code == 202, response.text
    edit = response.json()[0]
    monkeypatch.setattr('app.image_revision.prepare_revision', lambda *args: 'Prepared edit prompt')
    def uncertain(*args):
        raise GenerationError('服务商返回 HTTP 500', True, diagnostic={'http_status':500})
    assert process_standard_one(store, uncertain)
    with Session(engine) as session:
        run_id = session.get(ImageJob, edit['id']).agent_run_id
        assert session.get(AgentRun, run_id).status == 'unknown'
    assert retry(client, edit['id']).status_code == 409
    original = client.get('/api/image-jobs/'+edit['id']).json()
    response = retry(client, edit['id'], provider_checked=True)
    assert response.status_code == 202, response.text
    replacement = response.json()
    assert retry(client, edit['id'], provider_checked=True).json()['id'] == replacement['id']
    assert replacement['parent_job_id'] == root['id']
    assert replacement['task_id'] == edit['task_id']
    assert replacement['prompt'] == original['prompt'] == 'Prepared edit prompt'
    assert artifact(directory, replacement['id'], 'reference.png').read_bytes() == artifact(directory, edit['id'], 'reference.png').read_bytes()
    with Session(engine) as session:
        assert session.get(ImageJob, replacement['id']).agent_run_id == run_id
        assert session.get(AgentRun, run_id).status == 'waiting_images'
    assert process_standard_one(store, executor, reviewer=lambda *args, **kwargs: {'status':'passed', 'checks':[], 'summary':'通过'})
    with Session(engine) as session:
        assert session.get(AgentRun, run_id).status == 'needs_review'
        assert session.get(AgentRun, run_id).image_calls == 2
        assert session.get(ImageJob, edit['id']).status == 'unknown'
    assert client.get('/api/image-jobs/'+edit['id']).json() == original
    current = client.get('/api/creation-projects/'+source['id']).json()
    assert current['batches'] == source['batches']
    history = client.get('/api/image-jobs/'+root['id']+'/revisions').json()['items']
    assert {item['id'] for item in history} == {root['id'], edit['id'], replacement['id']}
    assert retry(client, edit['id'], provider_checked=True).status_code == 409
    # A completed replacement unlocks the next modification on this same card.
    values.update(request_id=str(uuid4()), source_job_id=replacement['id'], prompt='继续调整背景')
    response = client.post('/api/image-jobs/batch', files={key:(None,value) for key,value in values.items()})
    assert response.status_code == 202, response.text


def test_skill_retry_failure_can_retry_again_and_sync_latest_attempt(workflow):
    client, store, engine, directory, *_ = workflow
    images, _ = submit(workflow)
    assert process_standard_one(store, fail)
    first = retry(client, images[0]['id'])
    assert first.status_code == 202, first.text
    assert first.json()['task_id'] == images[0]['task_id']
    assert process_standard_one(store, fail)
    assert retry(client, images[0]['id']).status_code == 409
    second = retry(client, first.json()['id'])
    assert second.status_code == 202, second.text
    assert process_standard_one(store, executor)
    with Session(engine) as session:
        run = session.get(AgentRun, images[0]['task_id'])
        assert run.status == 'needs_review'
        assert run.image_calls == 7
