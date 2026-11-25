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


def retry(client, identifier, request_id=None):
    return client.post(f'/api/image-jobs/{identifier}/retry', files={'request_id': (None, request_id or str(uuid4()))})


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
    assert current['batches'][0] == source['batches'][0]
    assert current['batches'][-1]['job_ids'] == [created['id']]
    assert current['batches'][-1]['retry_source_job_id'] == first['id']
    assert process_standard_one(store, executor)
    assert process_standard_one(store, executor, preparer=lambda *args: pytest.fail('must reuse final prompt'))
    assert retry(client, first['id'], request_id).json()['status'] == 'succeeded'
    assert client.get('/api/image-jobs/' + first['id']).json()['execution_result'] == original['execution_result']
    assert KEY not in json.dumps(created)
    assert not process_standard_one(store, executor)


@pytest.mark.parametrize('state', ['queued', 'running', 'unknown', 'succeeded'])
def test_nonfailed_state_cannot_be_retried(project_setup, state):
    client, store, engine, directory, _ = project_setup
    source = submitted(project_setup)
    first = source['images'][0]['id']
    with Session(engine) as session, session.begin():
        session.get(ImageJob, first).status = state
    assert retry(client, first).status_code == 409


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
    assert len(calls) == 6
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
