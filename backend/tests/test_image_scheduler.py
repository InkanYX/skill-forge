"""Real parallel workers with mocked image providers; no paid requests."""
import json
import os
import threading
import time
from collections import Counter
from uuid import uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.database import Base, ImageConfiguration, ImageJob, make_engine
from app.image_configurations import ImageConfigStore
from app.image_jobs import now, process_one
from app.image_scheduler import ACCOUNT_IMAGE_LIMIT, GLOBAL_IMAGE_LIMIT
from app.standard_image_worker import StandardWorker, process_standard_one
from test_image_jobs import png


@pytest.fixture(params=['sqlite', 'postgresql'])
def scheduler_store(request, tmp_path):
    admin = None
    schema = 'scheduler_test_' + uuid4().hex
    if request.param == 'postgresql':
        url = os.environ.get('SKILL_FORGE_SCHEDULER_TEST_POSTGRES')
        if not url:
            pytest.skip('Isolated PostgreSQL test URL not configured')
        admin = make_engine(url)
        with admin.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        from sqlalchemy import create_engine
        engine = create_engine(url, hide_parameters=True, pool_size=10,
                               connect_args={'options': '-csearch_path=' + schema, 'connect_timeout': 3})
    else:
        engine = make_engine('sqlite:///' + (tmp_path / 'scheduler.db').as_posix())
    try:
        Base.metadata.create_all(engine)
        store = ImageConfigStore(engine, tmp_path / 'data')
        yield store
    finally:
        engine.dispose()
        if admin is not None:
            with admin.begin() as connection:
                connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
            admin.dispose()


def enqueue(store, owner, count=1, status='queued', legacy=False):
    identifiers = []
    with Session(store.engine) as session, session.begin():
        config = session.scalar(select(ImageConfiguration).where(ImageConfiguration.owner == owner))
        if config is None:
            config = ImageConfiguration(id=str(uuid4()), owner=owner, name='test', base_url='https://image.example/v1',
                                        revision=str(uuid4()), updated_at=now(), model_name='test-image')
            session.add(config)
            session.flush()
            store.keys[config.id] = (config.revision, 'unit-test-key')
        for _ in range(count):
            identifier = str(uuid4())
            profile = {} if legacy else {'revision': config.revision, 'model': 'test-image',
                                        'prepared_by_agent': True, 'test_owner': owner}
            session.add(ImageJob(id=identifier, request_id=identifier, fingerprint='test', config_id=config.id,
                config_name='test', base_url=config.base_url, encrypted_key='', model_name='test-image',
                prompt='test', size='auto', mode='generate', status=status, message='test',
                owner_id=owner, created_at=now(), updated_at=now(), lease_until=time.time() + 900 if status == 'running' else None,
                execution_profile=json.dumps(profile)))
            identifiers.append(identifier)
    return identifiers


def test_parallel_pool_reaches_six_without_exceeding_two_per_account(scheduler_store):
    store = scheduler_store
    owners = [str(uuid4()) for _ in range(3)]
    # A large first-account backlog must not hide other accounts' eligible work.
    for owner in owners:
        enqueue(store, owner, 4)
    lock = threading.Lock()
    release, full, done = threading.Event(), threading.Event(), threading.Event()
    active, peaks, seen, errors = Counter(), Counter(), set(), []
    totals = {'active': 0, 'peak': 0, 'finished': 0}

    def execute(directory, profile, key, prompt, reference):
        owner = profile['test_owner']
        with lock:
            active[owner] += 1
            totals['active'] += 1
            totals['peak'] = max(totals['peak'], totals['active'])
            peaks[owner] = max(peaks[owner], active[owner])
            if directory.name in seen: errors.append('duplicate job')
            seen.add(directory.name)
            if totals['active'] == GLOBAL_IMAGE_LIMIT: full.set()
        try:
            if not release.wait(20): raise RuntimeError('test gate timed out')
            directory.mkdir(parents=True, exist_ok=True)
            (directory / 'result.png').write_bytes(png())
            return {}
        finally:
            with lock:
                active[owner] -= 1
                totals['active'] -= 1
                totals['finished'] += 1
                if totals['finished'] == 12: done.set()

    worker = StandardWorker(store)
    # Exercise the actual six worker loops, replacing only the paid executor.
    from unittest.mock import patch
    with patch('app.standard_image_worker.process_standard_one', lambda actual_store: process_standard_one(actual_store, execute)):
        worker.start()
        try:
            assert full.wait(15), 'Pool did not fill all six global slots'
            with lock:
                assert totals['active'] == 6
                assert all(active[owner] == 2 for owner in owners)
            release.set()
            assert done.wait(20), 'Queued jobs did not resume as slots were released'
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                with Session(store.engine) as session:
                    states = list(session.scalars(select(ImageJob.status)))
                if all(state == 'succeeded' for state in states): break
                time.sleep(.05)
            assert states == ['succeeded'] * 12
        finally:
            release.set()
            worker.stop()
    assert totals['peak'] == GLOBAL_IMAGE_LIMIT and max(peaks.values()) == ACCOUNT_IMAGE_LIMIT
    assert len(seen) == 12 and not errors


def test_both_worker_paths_share_limits_and_busy_owner_does_not_block_others(scheduler_store):
    store = scheduler_store
    first, second, third = [str(uuid4()) for _ in range(3)]
    enqueue(store, first, 2, status='running', legacy=True)
    first_jobs = enqueue(store, first, 110)
    second_job = enqueue(store, second)[0]
    calls = []
    assert process_standard_one(store, lambda directory, *args: calls.append(directory.name) or {})
    assert calls == [second_job]
    with Session(store.engine) as session:
        assert all(session.get(ImageJob, identifier).status == 'queued' for identifier in first_jobs)
    enqueue(store, second, 2, status='running')
    enqueue(store, third, 2, status='running')
    enqueue(store, third, legacy=True)
    assert not process_standard_one(store, lambda *args: pytest.fail('global limit exceeded'))
    assert not process_one(store.engine, store.directory, lambda *args: pytest.fail('legacy worker bypassed global limit'))


def test_paused_jobs_are_not_claimed(scheduler_store):
    store = scheduler_store
    enqueue(store, str(uuid4()), status='paused')
    assert not process_standard_one(store, lambda *args: pytest.fail('paused job executed'))
