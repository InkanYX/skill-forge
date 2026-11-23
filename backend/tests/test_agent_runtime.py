import io
import json
from uuid import uuid4
from zipfile import ZIP_DEFLATED, ZipFile

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent_runtime import AgentError, _chat, execute_run
from app.database import AgentArtifact, AgentRun, AgentStep, Base, ImageJob, make_engine
from app.main import create_app
from test_image_jobs import png

KEY = 'agent-unit-test-secret'


class FakeResponse:
    def __init__(self, status_code, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload


class FakeClient:
    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def post(self, *args, **kwargs):
        return FakeResponse(403)


def tool_call(name, arguments, call_id=None):
    return {'role': 'assistant', 'content': None, 'tool_calls': [{
        'id': call_id or f'call-{uuid4()}', 'type': 'function',
        'function': {'name': name, 'arguments': json.dumps(arguments, ensure_ascii=False)}}]}


def last_tool(messages):
    return json.loads(messages[-1]['content'])


def archive(files):
    payload = io.BytesIO()
    with ZipFile(payload, 'w', ZIP_DEFLATED) as bundle:
        for path, content in files.items():
            bundle.writestr(path, content.encode('utf-8') if isinstance(content, str) else content)
    return payload.getvalue()


def skill_files():
    return {
        'pkg/SKILL.md': '---\nname: agent-demo\ndescription: "Agent 测试技能"\nmetadata:\n  version: "1.0.0"\n---\n\n# 入口\n\n先策划再出图。\n',
        'pkg/references/quality-gate.md': '# 质检\n\n结构不符即返工。\n',
    }


@pytest.fixture
def setup(tmp_path):
    engine = make_engine(f"sqlite:///{(tmp_path / 'agent.db').as_posix()}")
    Base.metadata.create_all(engine)
    directory = tmp_path / 'data'
    app = create_app(directory, db_url=str(engine.url), enable_standard=True, start_image_worker=False)
    with TestClient(app) as client:
        yield client, app.state.image_configs, engine, directory
    engine.dispose()


def save_config(client, vision=True):
    body = {'base_url': 'https://image.example.com/v1', 'api_key': KEY,
            'text_model_name': 'text-model'}
    if vision:
        body['vision_model_name'] = 'vision-model'
    response = client.put('/api/image-configs', json=body)
    assert response.status_code == 200, response.text
    return response.json()


def install_skill(client):
    response = client.post('/api/skill-packages/import', files={
        'archive': ('bundle.zip', archive(skill_files()), 'application/zip')})
    assert response.status_code == 200, response.text
    preview = response.json()
    created = client.post('/api/skill-packages/import/confirm', json={
        'upload_id': preview['upload_id'], 'selections': [{'name': 'agent-demo'}]})
    assert created.status_code == 200, created.text
    return created.json()[0]


def create_run(client, created, max_steps=20, max_images=6):
    response = client.post('/api/agent/runs', files={
        'payload': (None, json.dumps({
            'goal': '为主图做一张干净的白底商品图', 'skill_id': created['id'],
            'config_id': client.get('/api/image-configs').json()['id'],
            'max_steps': max_steps, 'max_images': max_images}))})
    assert response.status_code == 200, response.text
    return response.json()


def start(engine, run_id):
    with Session(engine) as session, session.begin():
        session.get(AgentRun, run_id).status = 'running'


def run_now(engine, directory, store, run_id, **kwargs):
    start(engine, run_id)
    execute_run(engine, directory, store, run_id, **kwargs)


def fake_wait(engine, directory):
    def wait(job_id):
        with Session(engine) as session, session.begin():
            row = session.get(ImageJob, job_id)
            row.status, row.message = 'succeeded', '图片已生成'
        target = directory / 'image-jobs' / job_id / 'preview.jpg'
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(png())
        return {'job_id': job_id, 'status': 'succeeded', 'message': '图片已生成'}
    return wait


class Scripted:
    def __init__(self, steps, vision_text='检查通过，可以交付。'):
        self.steps = list(steps)
        self.vision_text = vision_text
        self.index = 0
        self.seen_system = ''
        self.vision_calls = 0

    def chat(self, base_url, key, model, messages, tools):
        assert base_url == 'https://image.example.com/v1'
        assert key == KEY and model == 'text-model'
        self.seen_system = messages[0]['content']
        step = self.steps[self.index]
        self.index += 1
        return step(messages) if callable(step) else step

    def vision(self, base_url, key, model, image, question):
        self.vision_calls += 1
        assert model == 'vision-model' and image.startswith(b'\x89PNG')
        return self.vision_text


def test_full_agent_loop_generates_views_and_finishes(setup):
    client, store, engine, directory = setup
    save_config(client)
    created = install_skill(client)
    run = create_run(client, created)

    def write(messages):
        return tool_call('write_prompt', {'name': '主图', 'content': 'Task and selling objective: clean product shot.'})

    def generate(messages):
        return tool_call('generate_image', {'prompt_id': last_tool(messages)['prompt_id']})

    def view(messages):
        return tool_call('view_image', {'job_id': last_tool(messages)['job_id'],
                                        'question': '主体结构是否与参考一致？'})

    script = Scripted([write, generate, view, tool_call('finish', {'summary': '已完成，自动质检通过。'})])
    run_now(engine, directory, store, run['id'], chat=script.chat, vision=script.vision,
                wait=fake_wait(engine, directory))

    with Session(engine) as session:
        row = session.get(AgentRun, run['id'])
        assert row.status == 'succeeded', row.error
        assert row.summary == '已完成，自动质检通过。'
        assert row.image_calls == 1 and row.steps_count == 4
        assert 'agent-demo' in script.seen_system and '先策划再出图' in script.seen_system
        jobs = list(session.scalars(select(ImageJob).where(ImageJob.agent_run_id == run['id'])))
        assert len(jobs) == 1 and jobs[0].status == 'succeeded'
        assert jobs[0].model_name == 'gpt-image-2.5-sunburst'
        assert json.loads(jobs[0].execution_profile)['quality'] == 'high'
        kinds = [item.kind for item in session.scalars(select(AgentStep).where(AgentStep.run_id == run['id']))]
        assert kinds == ['tool'] * 4
        assert session.scalars(select(AgentArtifact).where(AgentArtifact.run_id == run['id'])).one().kind == 'prompt'
    assert script.vision_calls == 1


def test_model_403_stops_without_retry(setup, monkeypatch):
    client, store, engine, directory = setup
    save_config(client)
    created = install_skill(client)
    run = create_run(client, created)

    import app.agent_runtime as runtime
    monkeypatch.setattr(runtime.httpx, 'Client', FakeClient)
    monkeypatch.setattr(runtime, 'pinned_url', lambda value: (value, {}, {}))
    with pytest.raises(AgentError) as error:
        _chat('https://image.example.com/v1', KEY, 'text-model', [{'role': 'user', 'content': 'hi'}])
    assert '鉴权或权限校验失败' in error.value.message

    def denied(*args, **kwargs):
        raise AgentError('文字模型鉴权或权限校验失败，任务已停止，未重试。')

    run_now(engine, directory, store, run['id'], chat=denied, wait=fake_wait(engine, directory))
    with Session(engine) as session:
        row = session.get(AgentRun, run['id'])
        assert row.status == 'failed' and '未重试' in row.error
        assert session.scalar(select(ImageJob).where(ImageJob.agent_run_id == run['id'])) is None


def test_step_limit_stops_the_loop(setup):
    client, store, engine, directory = setup
    save_config(client)
    created = install_skill(client)
    run = create_run(client, created, max_steps=5)
    counter = {'value': 0}

    def write(messages):
        counter['value'] += 1
        return tool_call('write_prompt', {'content': f'第 {counter["value"]} 版提示词'})

    run_now(engine, directory, store, run['id'], chat=Scripted([write] * 10).chat,
            wait=fake_wait(engine, directory))
    with Session(engine) as session:
        row = session.get(AgentRun, run['id'])
        assert row.status == 'succeeded'
        assert '步数上限（5）' in row.summary and row.steps_count == 6


def test_image_limit_blocks_further_generation(setup):
    client, store, engine, directory = setup
    save_config(client)
    created = install_skill(client)
    run = create_run(client, created, max_steps=10, max_images=1)

    def write(messages):
        return tool_call('write_prompt', {'content': '主图提示词'})

    def generate(messages):
        return tool_call('generate_image', {'prompt_id': last_tool(messages)['prompt_id']})

    script = Scripted([write, generate, write, generate])
    run_now(engine, directory, store, run['id'], chat=script.chat, vision=script.vision,
                wait=fake_wait(engine, directory))
    with Session(engine) as session:
        row = session.get(AgentRun, run['id'])
        assert row.status == 'failed' and '出图次数上限' in row.error
        assert row.image_calls == 1


def test_repeated_identical_tool_call_is_stopped(setup):
    client, store, engine, directory = setup
    save_config(client)
    created = install_skill(client)
    run = create_run(client, created)
    call = tool_call('write_prompt', {'content': '同一段提示词'})
    run_now(engine, directory, store, run['id'], chat=Scripted([call, call]).chat,
            wait=fake_wait(engine, directory))
    with Session(engine) as session:
        row = session.get(AgentRun, run['id'])
        assert row.status == 'failed' and '重复的相同工具调用' in row.error
        assert row.steps_count == 1


def test_missing_vision_model_degrades_to_manual_review(setup):
    client, store, engine, directory = setup
    save_config(client, vision=False)
    created = install_skill(client)
    run = create_run(client, created)

    def write(messages):
        return tool_call('write_prompt', {'content': '主图提示词'})

    def generate(messages):
        return tool_call('generate_image', {'prompt_id': last_tool(messages)['prompt_id']})

    script = Scripted([write, generate, tool_call('finish', {'summary': '待人工审核。'})])
    run_now(engine, directory, store, run['id'], chat=script.chat, vision=script.vision,
                wait=fake_wait(engine, directory))
    with Session(engine) as session:
        row = session.get(AgentRun, run['id'])
        assert row.status == 'succeeded' and row.summary == '待人工审核。'
        assert row.vision_model_name == ''
        assert '未配置视觉模型' in script.seen_system
    assert script.vision_calls == 0


def test_cancel_and_rework_endpoints(setup):
    client, store, engine, directory = setup
    save_config(client)
    created = install_skill(client)
    run = create_run(client, created)

    cancelled = client.post(f"/api/agent/runs/{run['id']}/cancel")
    assert cancelled.status_code == 200
    assert cancelled.json()['status'] == 'cancelled'

    with Session(engine) as session, session.begin():
        row = session.get(AgentRun, run['id'])
        row.status, row.summary = 'succeeded', '第一轮结论'

    reworked = client.post(f"/api/agent/runs/{run['id']}/rework", json={'instruction': '把立柱改细一点'})
    assert reworked.status_code == 200, reworked.text
    body = reworked.json()
    assert body['id'] != run['id'] and body['status'] == 'queued'
    assert '第一轮结论' in body['goal'] and '把立柱改细一点' in body['goal']
    assert body['skill_version_id'] == run['skill_version_id']
