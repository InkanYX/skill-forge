import io
import json
import re
from uuid import uuid4

import pytest
import httpx
from PIL import Image
from sqlalchemy.orm import Session

from app.database import AgentRun, SkillPackage
from app.standard_image_worker import process_standard_one
from app.agent_runtime import _chat as real_chat
from app.creation_skills import run_snapshot
from test_agent_runtime import review_response
from test_image_jobs import png
from test_standard_images import standard, fake_executor, KEY


@pytest.fixture
def workflow(standard, monkeypatch):
    client, store, engine, directory = standard
    config = client.put('/api/image-configs', json={'base_url': 'https://image.example.com/v1', 'api_key': KEY,
        'model_name': 'gpt-image-2.5-sunburst',
        'text_model_name': 'planning-model', 'vision_model_name': 'vision-model'}).json()
    captured = {'planning': [], 'analysis': [], 'reviews': []}

    def chat(url, key, model, messages, *args, **kwargs):
        assert model == 'planning-model' and key == KEY
        brief = next(json.loads(item['content'])['requirements'] for item in messages
                     if item['role'] == 'user' and isinstance(item['content'], str) and item['content'].startswith('{'))
        tool_messages = [item for item in messages if item['role'] == 'tool']
        if not tool_messages:
            wanted = 'amazon-a-plus' if 'A+' in brief else 'premium-product-image-workflow'
            with Session(engine) as session:
                package = session.query(SkillPackage).filter_by(name=wanted, source='builtin').one()
            return {'tool_calls': [{'id': 'entry', 'type': 'function', 'function': {'name': 'read_file',
                'arguments': json.dumps({'file_path': f'/skills/skill-{package.id}/SKILL.md'})}}]}
        if len(tool_messages) == 1 and 'A+' not in brief:
            original_root = re.search(r'/bundles/[0-9a-f-]+', tool_messages[0]['content']).group()
            path = 'references/listing-image-requirements.md' if '主图' in brief else 'references/layout-design.md'
            return {'tool_calls': [{'id': 'reference', 'type': 'function', 'function': {'name': 'read_file',
                'arguments': json.dumps({'file_path': original_root + '/' + path})}}]}
        captured['planning'].append(messages)
        return {'content': json.dumps({'status': 'ready', 'prompt': 'Task and selling objective: ' + brief
            + '\nReference roles: product identity reference.\nOutput: native PNG; preserve proportions.'})}

    def vision(url, key, model, image, question, reference=None, **kwargs):
        assert model == 'vision-model'
        if '只返回 JSON' in question:
            captured['reviews'].append((question, reference))
            return review_response()
        captured['analysis'].append((question, reference))
        return '蓝色四柱凉棚，连接结构清晰；尺寸无法确认。'

    monkeypatch.setattr('app.agent_runtime._chat', chat)
    monkeypatch.setattr('app.agent_runtime._vision', vision)
    return client, store, engine, directory, config, captured


def submit(workflow, prompt='庭院场景，保持产品结构与颜色', count=1, reference=None, **extra):
    client, store, engine, directory, config, captured = workflow
    values = {'config_id': config['id'], 'request_id': str(uuid4()), 'prompt': prompt, 'count': str(count), **extra}
    fields = {key: (None, str(value)) for key, value in values.items()}
    if reference:
        fields['reference'] = ('product.png', reference, 'image/png')
    response = client.post('/api/image-jobs/batch', files=fields)
    assert response.status_code == 202, response.text
    return response.json(), values


def test_every_image_has_pinned_skill_and_preparation_is_reused_but_review_is_per_image(workflow):
    client, store, engine, directory, config, captured = workflow
    images, values = submit(workflow, count=2, reference=png())
    first = images[0]
    skill = first['execution_profile']['skill_workflow']['primary']
    assert skill['name'] == 'premium-product-image-workflow' and skill['version'] == '2.5.2'
    assert {item['task_id'] for item in images} == {first['task_id']}
    assert process_standard_one(store, fake_executor)
    assert process_standard_one(store, fake_executor)
    assert len(captured['planning']) == 1 and len(captured['analysis']) == 1
    assert len(captured['reviews']) == 2
    for item in images:
        result = client.get('/api/image-jobs/' + item['id']).json()
        assert result['status'] == 'succeeded'
        assert result['prompt'].startswith('Task and selling objective:')
        assert result['execution_result']['agent_review']['status'] == 'passed'
        files = directory / 'image-jobs' / item['id']
        assert (files / 'result.png').read_bytes() == png()
        assert (files / 'skill-context.md').is_file() and (files / 'skill-workflow.json').is_file()
        assert (files / 'automatic-review.json').is_file()
    task = client.get('/api/image-jobs/tasks/' + first['task_id']).json()
    assert task['status'] == 'succeeded' and task['kind'] == 'free'
    with Session(engine) as session:
        assert session.get(AgentRun, first['task_id']).image_calls == 2
    fields = {key: (None, str(value)) for key, value in values.items()}
    fields['reference'] = ('product.png', png(), 'image/png')
    assert client.post('/api/image-jobs/batch', files=fields).json()[0]['id'] == first['id']
    assert not process_standard_one(store, lambda *args: pytest.fail('Replay must not generate again'))


def test_edit_inherits_skill_version_and_belongs_to_same_conversation(workflow):
    client, store, engine, directory, config, captured = workflow
    first, _ = submit(workflow, prompt='亚马逊主图 white background', reference=png())
    assert process_standard_one(store, fake_executor)
    pinned = first[0]['execution_profile']['skill_workflow']['primary']
    with Session(engine) as session, session.begin():
        session.get(SkillPackage, pinned['skill_id']).current_version_id = None
    revised, _ = submit(workflow, prompt='只更换庭院背景，保持四柱结构', source_job_id=first[0]['id'])
    assert revised[0]['execution_profile']['skill_workflow']['primary']['version_id'] == pinned['version_id']
    assert revised[0]['execution_profile']['skill_workflow']['purpose'] == 'scene'
    assert revised[0]['task_id'] == first[0]['task_id']
    assert revised[0]['mode'] == 'edit'
    assert process_standard_one(store, fake_executor)
    detail = client.get('/api/image-jobs/tasks/' + first[0]['task_id']).json()
    assert detail['turn_count'] == 2 and len(detail['items']) == 2
    turn = client.get('/api/agent/runs/' + detail['agent_run_id']).json()
    assert turn['source_job_id'] == first[0]['id'] and turn['instruction'] == '只更换庭院背景，保持四柱结构'
    third = client.post('/api/agent/runs/' + turn['id'] + '/rework', json={
        'instruction': '只调整主体颜色为黑色', 'source_job_id': revised[0]['id']})
    assert third.status_code == 200, third.text
    with Session(engine) as session:
        selected = run_snapshot(engine, directory, session.get(AgentRun, third.json()['id']))
    assert selected['purpose'] == 'scene'


def test_set_routes_main_and_aplus_to_different_reference_documents(workflow):
    client, store, engine, directory, config, captured = workflow
    plan = {'name': '整套商品图', 'shots': [
        {'name': '亚马逊主图', 'prompt': 'white background, no generated text'},
        {'name': 'A+ 场景模块', 'prompt': '展示庭院中的真实比例'}]}
    response = client.post('/api/image-jobs/sets', files={key: (None, value) for key, value in {
        'config_id': config['id'], 'request_id': str(uuid4()), 'plan': json.dumps(plan)}.items()})
    assert response.status_code == 202, response.text
    images = response.json()
    assert images[0]['execution_profile']['skill_workflow']['purpose'] == 'main-image'
    assert images[1]['execution_profile']['skill_workflow']['purpose'] == 'aplus'
    assert images[1]['execution_profile']['skill_workflow']['companions'] == []
    assert process_standard_one(store, fake_executor)
    assert process_standard_one(store, fake_executor)
    first = client.get('/api/image-jobs/' + images[0]['id']).json()['execution_result']['skill_execution']
    second = client.get('/api/image-jobs/' + images[1]['id']).json()['execution_result']['skill_execution']
    assert any(item['path'].endswith('listing-image-requirements.md') for item in first['files'])
    assert second['used_skills'][0]['name'] == 'amazon-a-plus'


def test_missing_text_model_stops_before_paid_image_call(standard):
    client, store, engine, directory = standard
    config = client.put('/api/image-configs', json={'base_url': 'https://image.example.com/v1', 'api_key': KEY, 'model_name': 'gpt-image-2.5-sunburst', 'text_model_name': ''}).json()
    response = client.post('/api/image-jobs/batch', files={key: (None, value) for key, value in {
        'config_id': config['id'], 'request_id': str(uuid4()), 'prompt': 'garden', 'count': '2'}.items()})
    assert response.status_code == 202
    assert process_standard_one(store, lambda *args: pytest.fail('No image call without skill preparation'))
    detail = client.get('/api/image-jobs/tasks/' + response.json()[0]['task_id']).json()
    assert detail['status'] == 'queued'
    assert detail['items'][0]['diagnostic']['error_type'] == 'skill_preparation'
    assert detail['items'][1]['status'] == 'queued'
    assert process_standard_one(store, lambda *args: pytest.fail('No image call without skill preparation'))
    detail = client.get('/api/image-jobs/tasks/' + response.json()[0]['task_id']).json()
    assert detail['status'] == 'failed'
    assert {item['status'] for item in detail['items']} == {'failed'}


def test_failed_review_preserves_native_image_and_requires_manual_review(workflow, monkeypatch):
    client, store, engine, directory, config, captured = workflow
    images, _ = submit(workflow)
    def fail_review(*args, **kwargs):
        raise OSError('vision unavailable')
    assert process_standard_one(store, fake_executor, reviewer=fail_review)
    result = client.get('/api/image-jobs/' + images[0]['id']).json()
    assert result['status'] == 'succeeded' and result['image_url']
    assert client.get('/api/image-jobs/tasks/' + images[0]['task_id']).json()['status'] == 'needs_review'


def test_edit_compares_to_original_product_photo_instead_of_previous_generated_errors(workflow):
    client, store, engine, directory, config, captured = workflow
    buffer = io.BytesIO()
    Image.new('RGB', (12, 8), 'red').save(buffer, 'PNG')
    generated = buffer.getvalue()
    first, _ = submit(workflow, reference=png())
    def altered_executor(folder, profile, key, prompt, reference):
        folder.mkdir(parents=True, exist_ok=True)
        (folder / 'result.png').write_bytes(generated)
        return {'native_pixels': [12, 8], 'review': {'status': 'pending'}}
    assert process_standard_one(store, altered_executor)
    revised, _ = submit(workflow, prompt='只调整背景', source_job_id=first[0]['id'])
    def edit_executor(folder, profile, key, prompt, reference):
        assert reference == generated
        return fake_executor(folder, profile, key, prompt, reference)
    assert process_standard_one(store, edit_executor)
    assert captured['analysis'][-1][1] == png()
    assert captured['reviews'][-1][1] == png()
    with Session(engine) as session:
        run = session.get(AgentRun, revised[0]['task_id'])
        assert (directory / 'agent-runs' / run.id / 'reference.png').read_bytes() == png()
    latest = client.get('/api/image-jobs/tasks/' + revised[0]['task_id']).json()['agent_run_id']
    assert (directory / 'agent-runs' / latest / 'reference.png').read_bytes() == png()


def test_text_provider_denial_saves_real_redacted_response_and_never_calls_images(workflow, monkeypatch):
    import app.agent_runtime as runtime
    client, store, engine, directory, config, captured = workflow
    images, _ = submit(workflow, count=2)
    original_client = httpx.Client
    calls = []
    def handle(request):
        calls.append(request)
        return httpx.Response(403, headers={'x-request-id': 'planning-denied'}, json={'error': {'message': 'denied ' + KEY}})
    monkeypatch.setattr(runtime, '_chat', real_chat)
    monkeypatch.setattr(runtime.httpx, 'Client', lambda **kwargs: original_client(transport=httpx.MockTransport(handle)))
    monkeypatch.setattr(runtime, 'pinned_url', lambda value: (value, {}, {}))
    assert process_standard_one(store, lambda *args: pytest.fail('Denied planning must not generate images'))
    result = client.get('/api/image-jobs/' + images[0]['id']).json()
    assert result['status'] == 'failed'
    diagnostic = client.get('/api/image-jobs/' + images[0]['id'] + '/diagnostics').json()['diagnostic']
    assert diagnostic['http_status'] == 403 and diagnostic['request_id'] == 'planning-denied'
    assert KEY not in json.dumps(diagnostic) and 'denied' in diagnostic['response_body']
    assert len(calls) == 1
