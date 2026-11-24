from sqlalchemy.orm import Session

from app.agent_runtime import _goal_prompt
from app.database import AgentRun, ImageJob
from test_agent_runtime import (Scripted, create_run, fake_wait, image_steps, install_skill,
                                last_tool, review_response, run_now, save_config, setup, tool_call)


def completed(setup):
    client, store, engine, directory = setup
    save_config(client)
    run = create_run(client, install_skill(client))
    script = Scripted(image_steps(include_review=False))
    run_now(engine, directory, store, run['id'], chat=script.chat, wait=fake_wait(engine, directory))
    return client.get(f"/api/agent/runs/{run['id']}").json()


def test_full_new_instruction_is_persisted_and_latest_turn_is_listed(setup):
    client, store, engine, directory = setup
    first = completed(setup)
    original = '必须保留四柱连接结构。' * 500
    instruction = '只修改背景，不改变四柱连接结构。' * 200
    with Session(engine) as session, session.begin():
        session.get(AgentRun, first['id']).goal = original
    response = client.post(f"/api/agent/runs/{first['id']}/rework", json={'instruction': instruction})
    assert response.status_code == 200, response.text
    second = response.json()
    persisted = client.get(f"/api/agent/runs/{second['id']}").json()
    assert persisted['instruction'] == instruction and persisted['goal'] == original
    assert persisted['conversation_id'] == first['id'] and persisted['turn_index'] == 2
    assert persisted['source_job_id'] == first['images'][0]['id']
    assert persisted['previous_images'][0]['id'] == first['images'][0]['id']
    assert [item['id'] for item in client.get('/api/agent/runs?latest=true').json()] == [second['id']]
    assert len(client.get('/api/agent/runs').json()) == 2
    with Session(engine) as session:
        prompt = _goal_prompt(session.get(AgentRun, second['id']), False)
        assert original in prompt and instruction in prompt


def test_selected_image_is_used_for_edit_and_results_share_one_history_task(setup):
    client, store, engine, directory = setup
    first = completed(setup)
    source_id = first['images'][0]['id']
    second = client.post(f"/api/agent/runs/{first['id']}/rework", json={
        'instruction': '只把背景换成庭院，保留主体蓝色。', 'source_job_id': source_id}).json()
    observed = []

    def write(messages):
        all_text = str(messages)
        assert first['goal'] in all_text and '保留主体蓝色' in all_text
        assert source_id in all_text
        return tool_call('write_prompt', {'content': '只把背景换成庭院，保持蓝色主体。'})

    def edit(messages):
        return tool_call('edit_image', {'source_job_id': source_id, 'prompt_id': last_tool(messages)['prompt_id']})

    def view(messages):
        return tool_call('view_image', {'job_id': last_tool(messages)['job_id'], 'question': '主体是否保持蓝色'})

    def vision(base_url, key, model, image, question, reference=None, **kwargs):
        observed.append((image, reference))
        return '可见蓝色主体。' if len(observed) == 1 else review_response()

    script = Scripted([write, edit, view, tool_call('finish', {'summary': '已完成庭院背景修改。'})])
    run_now(engine, directory, store, second['id'], chat=script.chat, vision=vision, wait=fake_wait(engine, directory))
    latest = client.get(f"/api/agent/runs/{second['id']}").json()
    assert latest['status'] == 'succeeded', latest['error']
    assert latest['images'][0]['parent_job_id'] == source_id
    assert latest['images'][0]['task_id'] == first['id']
    page = client.get('/api/image-jobs/tasks').json()
    assert page['total'] == 1
    record = page['items'][0]
    assert record['id'] == first['id'] and record['turn_count'] == 2
    assert record['counts']['total'] == 2 and record['status'] == 'succeeded'
    detail = client.get(f"/api/image-jobs/tasks/{first['id']}").json()
    assert len(detail['items']) == 2 and detail['agent_run_id'] == second['id']
    found = client.get(f'/api/image-jobs/tasks/for-image/{source_id}').json()
    assert found['id'] == first['id']
    assert observed[-1][1] is not None


def test_model_cannot_redraw_when_user_selected_an_existing_version(setup):
    client, store, engine, directory = setup
    first = completed(setup)
    second = client.post(f"/api/agent/runs/{first['id']}/rework", json={'instruction': '修改背景'}).json()
    script = Scripted(image_steps(include_review=False))
    run_now(engine, directory, store, second['id'], chat=script.chat, vision=script.vision)
    result = client.get(f"/api/agent/runs/{second['id']}").json()
    assert result['status'] == 'failed' and '必须使用 edit_image' in result['error']
    assert not result['images']


def test_pending_turn_prevents_duplicate_submission_and_foreign_source_is_rejected(setup):
    client, store, engine, directory = setup
    first = completed(setup)
    other = create_run(client, install_skill(client))
    response = client.post(f"/api/agent/runs/{other['id']}/rework", json={'instruction': '再做一张'})
    assert response.status_code == 409
    wrong = client.post(f"/api/agent/runs/{first['id']}/rework", json={
        'instruction': '修改背景', 'source_job_id': other['id']})
    assert wrong.status_code == 422
    second = client.post(f"/api/agent/runs/{first['id']}/rework", json={'instruction': '修改背景'})
    assert second.status_code == 200
    repeated = client.post(f"/api/agent/runs/{first['id']}/rework", json={'instruction': '重复修改背景'})
    assert repeated.status_code == 409


def test_unresolved_paid_child_blocks_new_turn_even_if_run_has_stopped(setup):
    client, store, engine, directory = setup
    first = completed(setup)
    with Session(engine) as session, session.begin():
        session.get(ImageJob, first['images'][0]['id']).status = 'unknown'
    response = client.post(f"/api/agent/runs/{first['id']}/rework", json={'instruction': '继续制作'})
    assert response.status_code == 409 and '重复下单' in response.json()['detail']


def test_history_includes_failures_before_any_image_and_can_cancel_queued_run(setup):
    client, store, engine, directory = setup
    save_config(client)
    run = create_run(client, install_skill(client))
    page = client.get('/api/image-jobs/tasks', params={'q': run['goal']}).json()
    assert page['total'] == 1
    assert page['items'][0]['counts']['total'] == 0 and page['items'][0]['status'] == 'queued'
    cancelled = client.post(f"/api/image-jobs/tasks/{run['id']}/cancel", files={'action': (None, 'cancel')})
    assert cancelled.status_code == 200
    assert client.get(f"/api/agent/runs/{run['id']}").json()['status'] == 'cancelled'
    detail = client.get(f"/api/image-jobs/tasks/{run['id']}").json()
    assert detail['status'] == 'cancelled' and detail['items'] == []


def test_review_status_filter_uses_execution_result_instead_of_image_success(setup):
    client, store, engine, directory = setup
    first = completed(setup)
    page = client.get('/api/image-jobs/tasks', params={'status': 'needs_review'}).json()
    assert page['total'] == 1 and page['items'][0]['id'] == first['id']
    assert client.get('/api/image-jobs/tasks', params={'status': 'succeeded'}).json()['total'] == 0
