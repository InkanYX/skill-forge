import io
import json
import base64
from pathlib import Path
from uuid import uuid4
from zipfile import ZIP_DEFLATED, ZipFile

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent_runtime import AgentError, _chat, _complete, _vision, execute_run
from app.agent_review import CHECKS
from app.database import AgentArtifact, AgentRun, AgentStep, Base, ImageJob, make_engine
from app.main import create_app
from test_image_jobs import png

KEY = 'agent-unit-test-secret'


class FakeResponse:
    def __init__(self, status_code, payload=None):
        self.status_code = status_code
        self._payload = payload or {}
        self.headers = {}

    def json(self):
        return self._payload

    def iter_bytes(self):
        yield json.dumps(self._payload).encode('utf-8')


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
            'model_name': 'gpt-image-2.5-sunburst',
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


def create_run(client, created, max_steps=20, max_images=6, reference=None, **kwargs):
    files = {
        'payload': (None, json.dumps({
            'goal': '为主图做一张干净的白底商品图', 'skill_id': created['id'],
            'config_id': client.get('/api/image-configs').json()['id'],
            'max_steps': max_steps, 'max_images': max_images}))}
    if reference is not None:
        files['reference'] = ('product.png', reference, 'image/png')
    response = client.post('/api/agent/runs', files=files)
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
        (target.parent / 'result.png').write_bytes(png())
        return {'job_id': job_id, 'status': 'succeeded', 'message': '图片已生成'}
    return wait


def review_response(status='passed'):
    return json.dumps({'status': status, 'summary': '结构与要求一致。',
                       'checks': [{'item': item, 'status': status, 'detail': f'{item}：已核对。'}
                                  for item in CHECKS]}, ensure_ascii=False)


class Scripted:
    def __init__(self, steps, vision_text=None):
        self.steps = list(steps)
        self.vision_text = vision_text if vision_text is not None else review_response()
        self.index = 0
        self.seen_system = ''
        self.vision_calls = 0

    def chat(self, base_url, key, model, messages, tools, **kwargs):
        assert base_url == 'https://image.example.com/v1'
        assert key == KEY and model == 'text-model'
        self.seen_system = messages[0]['content']
        step = self.steps[self.index]
        self.index += 1
        return step(messages) if callable(step) else step

    def vision(self, base_url, key, model, image, question, reference=None, **kwargs):
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
        assert json.loads(jobs[0].execution_profile)['parameters'] == {}
        kinds = [item.kind for item in session.scalars(select(AgentStep).where(AgentStep.run_id == run['id']))]
        assert kinds == ['tool'] * 4
        artifacts = list(session.scalars(select(AgentArtifact).where(AgentArtifact.run_id == run['id'])))
        assert {item.kind for item in artifacts} == {'prompt', 'prompt_check', 'review'}
        saved = json.loads(jobs[0].execution_result)['agent_review']
        assert saved['status'] == 'passed' and len(saved['checks']) == 8
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


def test_chat_timeout_reports_its_own_limit(setup, monkeypatch):
    import app.agent_runtime as runtime
    class TimeoutClient(FakeClient):
        def post(self, *args, **kwargs):
            raise runtime.httpx.ReadTimeout('slow')
    monkeypatch.setattr(runtime.httpx, 'Client', TimeoutClient)
    monkeypatch.setattr(runtime, 'pinned_url', lambda value: (value, {}, {}))
    with pytest.raises(AgentError) as error:
        _chat('https://image.example.com/v1', KEY, 'text-model', [{'role': 'user', 'content': 'hi'}], timeout=300)
    assert '超过 300 秒未返回' in error.value.message
    assert '连接失败' not in error.value.message


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
        assert row.status == 'limit_reached'
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
        assert row.status == 'limit_reached' and '出图次数上限' in row.error
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
        assert row.status == 'needs_review' and '待人工审核' in row.summary
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
    assert body['goal'] == run['goal'] and body['instruction'] == '把立柱改细一点'
    assert body['conversation_id'] == run['id'] and body['parent_run_id'] == run['id']
    assert body['history'][0]['summary'] == '第一轮结论'
    assert client.get(f"/api/agent/runs/{body['id']}").status_code == 200
    assert body['skill_version_id'] == run['skill_version_id']


def image_steps(include_review=True, use_reference=None, **kwargs):
    def generate(messages):
        arguments = {'prompt_id': last_tool(messages)['prompt_id']}
        if use_reference is not None:
            arguments['use_reference'] = use_reference
        return tool_call('generate_image', arguments)

    def view(messages):
        return tool_call('view_image', {'job_id': last_tool(messages)['job_id'], 'question': '核对产品结构'})

    return [tool_call('write_prompt', {'content': '保持产品结构和蓝色，制作白底主图。'}), generate,
            *([view] if include_review else []), tool_call('finish', {'summary': '已完成，自动质检通过。'})]


def test_reference_is_analyzed_before_planning_and_compared_in_review(setup):
    client, store, engine, directory = setup
    save_config(client)
    run = create_run(client, install_skill(client), reference=png())
    script = Scripted(image_steps())
    observations = []

    def vision(base_url, key, model, image, question, reference=None, **kwargs):
        observations.append((question, reference))
        if len(observations) == 1:
            assert image == png() and reference is None
            return '可见蓝色主体；背面连接关系无法确认。'
        assert reference == png()
        assert '制作目标：为主图' in question and '实际图片提示词：保持产品结构和蓝色' in question
        assert '背面连接关系无法确认' in question
        return review_response()

    def chat(*args, **kwargs):
        assert len(observations) >= 1
        assert any('可见蓝色主体' in str(item.get('content')) for item in args[3])
        return script.chat(*args, **kwargs)

    run_now(engine, directory, store, run['id'], chat=chat, vision=vision, wait=fake_wait(engine, directory))
    with Session(engine) as session:
        row = session.get(AgentRun, run['id'])
        assert row.status == 'succeeded', row.error
        image = session.scalar(select(ImageJob).where(ImageJob.agent_run_id == run['id']))
        assert image.mode == 'edit'
        assert (directory / 'image-jobs' / image.id / 'reference.png').read_bytes() == png()
        assert json.loads(image.execution_result)['agent_review']['compared_reference'] is True
        records = list(session.scalars(select(AgentArtifact).where(AgentArtifact.run_id == run['id'])))
        analysis = next(item for item in records if item.kind == 'reference')
        assert '背面连接关系无法确认' in Path(analysis.path).read_text(encoding='utf-8')
    assert len(observations) == 2


def test_provided_reference_cannot_be_disabled_by_model(setup):
    client, store, engine, directory = setup
    save_config(client)
    run = create_run(client, install_skill(client), reference=png())
    script = Scripted(image_steps(use_reference=False))
    run_now(engine, directory, store, run['id'], chat=script.chat, vision=script.vision)
    with Session(engine) as session:
        row = session.get(AgentRun, run['id'])
        assert row.status == 'failed' and '禁止忽略参考图' in row.error
        assert session.scalar(select(ImageJob).where(ImageJob.agent_run_id == run['id'])) is None


def test_vision_receives_labeled_bounded_jpegs_without_changing_original(monkeypatch):
    import app.agent_runtime as runtime
    original = io.BytesIO()
    Image.new('RGBA', (2400, 1600), (0, 0, 255, 100)).save(original, 'PNG')
    content = original.getvalue()
    captured = []

    def chat(base_url, key, model, messages, *args, **kwargs):
        captured.extend(messages[1]['content'])
        return {'content': '观察记录'}

    monkeypatch.setattr(runtime, '_chat', chat)
    assert _vision('https://example.com', KEY, 'vision', content, '对照检查', reference=png()) == '观察记录'
    pictures = [item for item in captured if item['type'] == 'image_url']
    assert len(pictures) == 2
    assert captured[1]['text'] == '产品参考图（身份依据）'
    for picture in pictures:
        encoded = picture['image_url']['url']
        assert encoded.startswith('data:image/jpeg;base64,')
        with Image.open(io.BytesIO(base64.b64decode(encoded.split(',', 1)[1]))) as image:
            assert image.format == 'JPEG' and max(image.size) <= 1280
    with Image.open(io.BytesIO(content)) as source:
        assert source.format == 'PNG' and source.size == (2400, 1600)


@pytest.mark.parametrize('reply,status', [
    ('检查通过，可以交付。', 'needs_review'),
    (review_response('uncertain'), 'needs_review'),
    (review_response('rework'), 'needs_changes'),
    (json.dumps({'status': 'passed', 'summary': '通过', 'checks': [
        {'item': 'structure', 'status': 'passed', 'detail': '结构一致'}]}), 'needs_review'),
])
def test_model_claim_cannot_override_missing_or_negative_review(setup, reply, status):
    client, store, engine, directory = setup
    save_config(client)
    run = create_run(client, install_skill(client))
    script = Scripted(image_steps(), vision_text=reply)
    run_now(engine, directory, store, run['id'], chat=script.chat, vision=script.vision,
            wait=fake_wait(engine, directory))
    with Session(engine) as session:
        row = session.get(AgentRun, run['id'])
        assert row.status == status
        assert '自动质检通过' not in row.summary
        record = session.scalar(select(AgentArtifact).where(AgentArtifact.run_id == run['id'],
                                                            AgentArtifact.kind == 'review'))
        assert json.loads(Path(record.path).read_text(encoding='utf-8'))['raw_response'] == reply


def test_finish_without_review_is_manual_and_without_images_is_failed(setup):
    client, store, engine, directory = setup
    save_config(client)
    skill = install_skill(client)
    for steps, status in [(image_steps(include_review=False), 'needs_review'),
                          ([tool_call('finish', {'summary': '成功完成'})], 'failed'),
                          ([{'role': 'assistant', 'content': '图片制作成功。'}], 'failed')]:
        run = create_run(client, skill)
        script = Scripted(steps)
        run_now(engine, directory, store, run['id'], chat=script.chat, wait=fake_wait(engine, directory))
        with Session(engine) as session:
            assert session.get(AgentRun, run['id']).status == status


@pytest.mark.parametrize('outcome,expected', [('unknown', 'unknown'), ('failed', 'failed'), ('queued', 'unknown')])
def test_unconfirmed_or_failed_image_stops_before_another_call(setup, outcome, expected):
    client, store, engine, directory = setup
    save_config(client)
    run = create_run(client, install_skill(client))
    steps = image_steps(include_review=False)
    script = Scripted(steps[:2] + steps)  # A second, different prompt must never be reached.

    def wait(job_id):
        with Session(engine) as session, session.begin():
            session.get(ImageJob, job_id).status = outcome
        return {'job_id': job_id, 'status': outcome, 'message': '服务商结果待核对'}

    run_now(engine, directory, store, run['id'], chat=script.chat, wait=wait)
    with Session(engine) as session:
        row = session.get(AgentRun, run['id'])
        assert row.status == expected and row.image_calls == 1
        assert '未重复提交' in row.error
        assert len(list(session.scalars(select(ImageJob).where(ImageJob.agent_run_id == run['id'])))) == 1
        assert session.scalar(select(AgentStep).where(AgentStep.run_id == run['id'],
                                                      AgentStep.tool_name == 'generate_image')) is not None
    assert script.index == 2


def test_late_completion_cannot_overwrite_cancellation(setup):
    client, store, engine, directory = setup
    save_config(client)
    run = create_run(client, install_skill(client))
    start(engine, run['id'])
    assert client.post(f"/api/agent/runs/{run['id']}/cancel").json()['status'] == 'cancelled'
    _complete(engine, run['id'], 'succeeded', '迟到的回复')
    with Session(engine) as session:
        assert session.get(AgentRun, run['id']).status == 'cancelled'


def test_multiple_tools_in_one_reply_share_the_step_limit(setup):
    client, store, engine, directory = setup
    save_config(client)
    run = create_run(client, install_skill(client), max_steps=5)
    calls = [tool_call('write_prompt', {'content': f'提示词{i}'})['tool_calls'][0] for i in range(8)]
    run_now(engine, directory, store, run['id'], chat=Scripted([
        {'role': 'assistant', 'tool_calls': calls}]).chat)
    with Session(engine) as session:
        row = session.get(AgentRun, run['id'])
        assert row.status == 'limit_reached'
        assert len(list(session.scalars(select(AgentArtifact).where(AgentArtifact.run_id == run['id'])))) == 5


def test_no_vision_does_not_block_reference_editing_or_falsely_pass(setup):
    client, store, engine, directory = setup
    save_config(client, vision=False)
    run = create_run(client, install_skill(client), reference=png())
    script = Scripted(image_steps())
    run_now(engine, directory, store, run['id'], chat=script.chat, vision=script.vision,
            wait=fake_wait(engine, directory))
    with Session(engine) as session:
        row = session.get(AgentRun, run['id'])
        assert row.status == 'needs_review', row.error
        image = session.scalar(select(ImageJob).where(ImageJob.agent_run_id == run['id']))
        assert image.mode == 'edit' and image.status == 'succeeded'
        assert json.loads(image.execution_result)['agent_review']['method'] == 'manual_pending'
    assert script.vision_calls == 0


def test_repaired_version_can_pass_without_old_failed_review_blocking_delivery(setup):
    client, store, engine, directory = setup
    save_config(client)
    run = create_run(client, install_skill(client))
    source_id = ''

    def remember_and_review(messages):
        nonlocal source_id
        source_id = last_tool(messages)['job_id']
        return tool_call('view_image', {'job_id': source_id, 'question': '核对结构'})

    def edit(messages):
        return tool_call('edit_image', {'source_job_id': source_id, 'prompt_id': last_tool(messages)['prompt_id']})

    def review_edit(messages):
        return tool_call('view_image', {'job_id': last_tool(messages)['job_id'], 'question': '是否修复结构'})

    script = Scripted(image_steps()[:2] + [remember_and_review,
        tool_call('write_prompt', {'content': '修复立柱数量，保持其他特征'}), edit, review_edit,
        tool_call('finish', {'summary': '修复版通过检查。'})])
    reviews = iter([review_response('rework'), review_response()])
    references = []

    def vision(*args, reference=None, **kwargs):
        references.append(reference)
        return next(reviews)

    run_now(engine, directory, store, run['id'], chat=script.chat, vision=vision, wait=fake_wait(engine, directory))
    with Session(engine) as session:
        row = session.get(AgentRun, run['id'])
        assert row.status == 'succeeded', row.error
        assert row.image_calls == 2
        revised = session.scalar(select(ImageJob).where(ImageJob.parent_job_id == source_id))
        assert revised.mode == 'edit'
    assert references == [None, png()]


def test_cancel_while_waiting_also_cancels_queued_child(setup):
    client, store, engine, directory = setup
    save_config(client)
    run = create_run(client, install_skill(client))
    script = Scripted(image_steps())

    def wait(job_id):
        response = client.post(f"/api/agent/runs/{run['id']}/cancel")
        assert response.json()['status'] == 'cancelled'
        return {'job_id': job_id, 'status': 'succeeded'}  # A stale response must not revive the run.

    run_now(engine, directory, store, run['id'], chat=script.chat, wait=wait)
    with Session(engine) as session:
        assert session.get(AgentRun, run['id']).status == 'cancelled'
        image = session.scalar(select(ImageJob).where(ImageJob.agent_run_id == run['id']))
        assert image.status == 'cancelled'
    assert script.index == 2
