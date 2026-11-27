import json
from uuid import uuid4

import pytest
from sqlalchemy import select, text, inspect
from sqlalchemy.orm import Session

from app.database import CreationProject, CreationExecution, ImageJob, TeamProjectShare, CreativeCase
from app.image_jobs import now, artifact
from test_auth import accounts, member
from test_team_sharing import completed


def test_migration_keeps_existing_projects(tmp_path):
    from alembic import command
    from alembic.config import Config
    from app.database import BACKEND_DIR, make_engine
    engine = make_engine('sqlite:///' + (tmp_path/'migration.db').as_posix())
    config = Config(str(BACKEND_DIR/'alembic.ini'))
    config.attributes['database_url'] = str(engine.url)
    command.upgrade(config, '0025_team_sharing')
    identifier = str(uuid4())
    with engine.begin() as connection:
        connection.execute(text('INSERT INTO creation_projects (id,title,kind,revision,content,created_at,updated_at) '
            "VALUES (:id,'existing','plan',1,'{}','now','now')"), {'id': identifier})
    command.upgrade(config, 'head')
    assert next(item for item in inspect(engine).get_columns('creation_projects') if item['name']=='deleted_at')['nullable']
    with Session(engine) as session:
        row = session.get(CreationProject, identifier)
        assert row.title == 'existing' and row.deleted_at is None
    engine.dispose()


def deletion(client, ids, token=None, revisions=None):
    return client.post('/api/creation-projects/batch-delete', json={
        'request_id': token or str(uuid4()),
        'plans': [{'id': identifier, 'revision': (revisions or {}).get(identifier, 4)} for identifier in ids]})


def test_delete_and_undo_preserve_product_originals_cases_and_prior_image_trash(accounts):
    alice, owner = member(accounts, 'alice'); bob, _ = member(accounts, 'bob')
    product, _, _, _ = completed(accounts, owner['id'], 'product')
    plan, material, job, share = completed(accounts, owner['id'])
    second, _, _, _ = completed(accounts, owner['id'])
    _, _, engine, directory = accounts
    prior = str(uuid4())
    with Session(engine) as session, session.begin():
        session.get(CreationProject, plan).source_product_id = product
        original = session.get(ImageJob, job)
        session.add(ImageJob(id=prior, owner_id=owner['id'], task_id=plan, request_id=prior,
            fingerprint='a'*64, config_id=original.config_id, config_name='test', base_url='https://example.invalid',
            encrypted_key='', model_name='test', prompt='old deleted image', size='default', mode='generate',
            status='failed', deleted_at='earlier', created_at=now(), updated_at=now()))
    token = str(uuid4())
    result = deletion(alice, [plan, second], token)
    assert result.status_code == 200, result.text
    assert result.json()['count'] == 2
    assert deletion(alice, [plan, second], token).json() == result.json()
    assert alice.get('/api/creation-projects/'+product).status_code == 200
    assert alice.get('/api/creation-projects?kind=plan&source_product_id='+product).json() == []
    assert not any(item['id'] in (plan, second) for item in alice.get('/api/creation-projects').json())
    for client in (alice, bob):
        assert client.get('/api/team-shares/'+share).status_code == 404
        assert client.get('/api/creation-projects/'+plan).status_code == 404
        assert client.get(f'/api/creation-projects/{plan}/materials/{material}').status_code == 404
        assert client.get('/api/image-jobs/'+job+'/image').status_code == 404
        assert not any(item['project_id'] == plan for item in client.get('/api/team-shares?mine=true').json()['items'])
    with Session(engine) as session:
        assert session.get(CreationProject, plan) is None
        archived = session.get(CreationProject, plan, execution_options={'include_deleted_projects': True})
        assert archived.deleted_at
        assert session.scalar(select(CreativeCase).where(CreativeCase.job_id == job))
        assert artifact(directory, job, 'result.png').is_file()
    assert bob.post('/api/creation-projects/batch-delete/restore', json=result.json()).status_code == 404
    wrong = {**result.json(), 'request_id': str(uuid4())}
    assert alice.post('/api/creation-projects/batch-delete/restore', json=wrong).status_code == 409
    restored = alice.post('/api/creation-projects/batch-delete/restore', json=result.json())
    assert restored.status_code == 200, restored.text
    assert alice.post('/api/creation-projects/batch-delete/restore', json=result.json()).status_code == 200
    assert alice.get('/api/creation-projects/'+plan).status_code == 200
    assert alice.get('/api/image-jobs/'+job+'/image').status_code == 200
    assert bob.get('/api/team-shares/'+share).status_code == 200
    with Session(engine) as session:
        assert session.get(ImageJob, prior).deleted_at == 'earlier'


def test_selection_is_atomic_owner_scoped_and_revision_checked(accounts):
    alice, owner = member(accounts, 'alice'); _, other = member(accounts, 'bob')
    first, _, _, _ = completed(accounts, owner['id'])
    second, _, _, _ = completed(accounts, owner['id'])
    foreign, _, _, _ = completed(accounts, other['id'])
    assert deletion(alice, [first, foreign]).status_code == 404
    assert deletion(alice, [first, second], revisions={second: 1}).status_code == 409
    assert alice.get('/api/creation-projects/'+first).status_code == 200
    assert deletion(alice, []).status_code == 422
    assert deletion(alice, [first, first]).status_code == 422
    product, _, _, _ = completed(accounts, owner['id'], 'product')
    assert deletion(alice, [first, product]).status_code == 409
    assert alice.get('/api/creation-projects/'+first).status_code == 200


@pytest.mark.parametrize('kind,status', [('image', 'queued'), ('image', 'running'), ('image', 'paused'),
                                         ('execution', 'queued'), ('execution', 'running')])
def test_busy_selection_cannot_delete_or_interrupt_any_plan(accounts, kind, status):
    alice, owner = member(accounts, 'alice')
    first, _, _, _ = completed(accounts, owner['id'])
    second, _, job, _ = completed(accounts, owner['id'])
    with Session(accounts[2]) as session, session.begin():
        if kind == 'image':
            session.get(ImageJob, job).status = status
        else:
            session.add(CreationExecution(id=str(uuid4()), project_id=second, stage='brief', status=status,
                input='{}', output='{}', error='', created_at=now(), updated_at=now()))
    assert deletion(alice, [first, second]).status_code == 409
    rows = {item['id']: item for item in alice.get('/api/creation-projects?kind=plan').json()}
    assert first in rows and rows[second]['busy']
    with Session(accounts[2]) as session:
        assert session.get(ImageJob, job).status == (status if kind == 'image' else 'succeeded')
