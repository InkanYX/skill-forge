import base64
import io
import json
from uuid import uuid4

import httpx
import pytest
from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.creation_projects import process_creation_one
from app.creation_materials import material_tools, material_path
from app.database import CreationDocument, CreationExecution, ImageJob, CreationProject
from app.standard_image_worker import process_standard_one
from app.skill_packages import seed_builtin
from test_standard_images import standard, KEY
from test_image_jobs import png


@pytest.fixture
def project_setup(standard):
    client, store, engine, directory = standard
    seed_builtin(engine, directory)
    config = client.put('/api/image-configs', json={'base_url': 'https://provider.example/v1', 'api_key': KEY,
        'model_name': 'image-editor', 'model_names': ['planner', 'image-editor'],
        'planning_model_name': 'planner', 'image_model_name': 'image-editor',
        'model_options': {'planner': {'text_parameters': {'temperature': 0.2}}, 'image-editor': {'request_parameters': {'quality': 'high'}}}})
    assert config.status_code == 200, config.text
    project = client.post('/api/creation-projects', json={'title': '凉棚整套图', 'goal': '根据说明书和实拍，制作商品图',
        'planning_model': 'planner', 'image_model': 'image-editor', 'image_count': 2}).json()
    assert 'id' in project, project
    return client, store, engine, directory, project


def upload(client, project, content=None, filename='实拍.png', kind='产品实拍'):
    response = client.post(f"/api/creation-projects/{project['id']}/materials", data={
        'revision': str(project['revision']), 'material_id': str(uuid4()), 'kind': kind},
        files={'file': (filename, content or png(), 'application/octet-stream')})
    assert response.status_code == 201, response.text
    return response.json()


def edit(client, project, stage, content):
    response = client.put(f"/api/creation-projects/{project['id']}/documents/{stage}", json={'revision': project['revision'], 'content': content})
    assert response.status_code == 200, response.text
    return response.json()


def confirm(client, project, stage):
    response = client.post(f"/api/creation-projects/{project['id']}/documents/{stage}/confirm", json={'revision': project['revision']})
    assert response.status_code == 200, response.text
    return response.json()


def confirmed_project(setup):
    client, store, engine, directory, project = setup
    project = upload(client, project)
    project = upload(client, project, kind='结构细节')
    project = confirm(client, edit(client, project, 'analysis', {'facts': '四根立柱，来源：实拍图', 'selling_points': '遮阳空间', 'questions': '抗风参数未提供'}), 'analysis')
    refs = [item['id'] for item in project['materials']]
    project = confirm(client, edit(client, project, 'brief', {'shots': [
        {'id': 'scene', 'name': '庭院场景', 'content': '产品与庭院', 'reference_ids': refs, 'size': '1200x800'},
        {'id': 'detail', 'name': '连接细节', 'content': '局部放大', 'reference_ids': refs}]}), 'brief')
    project = confirm(client, edit(client, project, 'prompts', {'prompts': [
        {'shot_id': 'scene', 'prompt': 'CONFIRMED SCENE EXACT PROMPT', 'reference_ids': refs},
        {'shot_id': 'detail', 'prompt': 'CONFIRMED DETAIL EXACT PROMPT', 'reference_ids': refs}]}), 'prompts')
    return project


def test_model_assignments_do_not_follow_the_parameter_editor(project_setup):
    client, store, engine, directory, _ = project_setup
    config = client.get('/api/image-configs').json()
    owner = next(iter(store.keys))
    with Session(engine) as session:
        from app.database import ImageConfiguration
        row = session.get(ImageConfiguration, owner)
        owner = row.owner
    assert store.resolve_text(owner)[2] == 'planner'
    assert store.parameters(owner, 'text') == {'temperature': 0.2}
    # Viewing/saving the image editor must preserve the planning assignment.
    result = client.put('/api/image-configs', json={'base_url': config['base_url'], 'model_name': 'image-editor', 'model_names': config['model_names']})
    assert result.status_code == 200 and result.json()['planning_model_name'] == 'planner'
    assert store.resolve_text(owner)[2] == 'planner'
    assert client.put('/api/image-configs', json={'base_url': config['base_url'], 'planning_model_name': 'not-added'}).status_code == 422


def test_stages_cannot_skip_confirmation_or_queue_images(project_setup):
    client, store, engine, directory, project = project_setup
    url = f"/api/creation-projects/{project['id']}"
    for stage in ('brief', 'prompts'):
        result = client.post(url + '/stages/' + stage, json={'revision': project['revision'], 'request_id': str(uuid4())})
        assert result.status_code == 409
    result = client.post(url + '/generate', json={'revision': project['revision'], 'request_id': str(uuid4()), 'shot_ids': ['scene']})
    assert result.status_code == 409
    with Session(engine) as session:
        assert not list(session.scalars(select(ImageJob)))
        assert not list(session.scalars(select(CreationExecution)))


def test_stage_runs_are_durable_and_duplicate_requests_are_not_reexecuted(project_setup):
    client, store, engine, directory, project = project_setup
    url = f"/api/creation-projects/{project['id']}"
    request_id = str(uuid4())
    body = {'revision': project['revision'], 'request_id': request_id, 'instruction': '先分析产品'}
    first = client.post(url + '/stages/analysis', json=body)
    assert first.status_code == 202 and first.json()['busy']
    assert client.post(url + '/stages/analysis', json=body).status_code == 202
    assert client.put(url, json={**project['settings'], 'title': project['title'], 'revision': first.json()['revision']}).status_code == 409
    calls = []
    def planner(*args):
        calls.append(args)
        return {'facts': '已确认的结构', 'selling_points': '遮阳', 'questions': ''}, {'used_skills': [], 'materials': []}
    assert process_creation_one(store, planner)
    assert not process_creation_one(store, planner)
    assert len(calls) == 1
    saved = client.get(url).json()
    assert not saved['busy'] and saved['documents']['analysis']['confirmed_at'] is None
    assert saved['documents']['analysis']['content']['facts'] == '已确认的结构'
    assert len(client.get('/api/creation-projects').json()) == 1


def test_analysis_continues_in_same_conversation_to_read_all_30_materials(project_setup, monkeypatch):
    client, store, engine, directory, project = project_setup
    for index in range(30):
        project = upload(client, project, filename=f'product-{index}.png')
    materials = project['materials']
    calls = []
    result = {'facts': '综合全部实拍确认结构', 'selling_points': '遮阳空间', 'questions': ''}

    def chat(base_url, key, model, messages, tools, **kwargs):
        calls.append(messages)
        if len(calls) == 1:
            return {'tool_calls': [{'id': f'view-{item["id"]}', 'type': 'function', 'function': {
                'name': 'view_material', 'arguments': json.dumps({'material_id': item['id']})}} for item in materials[:13]]}
        if len(calls) == 2:
            return {'content': json.dumps(result, ensure_ascii=False)}  # premature final
        # The continuation is the third provider call; the fourth is its final result.
        if len(calls) == 3:
            history = json.dumps(messages, ensure_ascii=False)
            assert '已读 13/30 份' in history
            assert '综合全部实拍确认结构' in history
            assert materials[0]['id'] in history
            assert 'data:image/jpeg;base64,' in history
            return {'tool_calls': [{'id': f'view-{item["id"]}', 'type': 'function', 'function': {
                'name': 'view_material', 'arguments': json.dumps({'material_id': item['id']})}} for item in materials[13:]]}
        return {'content': json.dumps(result, ensure_ascii=False)}

    monkeypatch.setattr('app.agent_runtime._chat', chat)
    url = f'/api/creation-projects/{project["id"]}'
    identifier = str(uuid4())
    assert client.post(url + '/stages/analysis', json={'revision': project['revision'], 'request_id': identifier}).status_code == 202
    # Focus this regression on real material tools rather than automatic skill selection.
    with Session(engine) as session, session.begin():
        execution = session.get(CreationExecution, identifier)
        payload = json.loads(execution.input)
        payload['skill_snapshot']['pinned'] = [payload['skill_snapshot']['primary']['skill_id']]
        execution.input = json.dumps(payload)
    assert process_creation_one(store)
    saved = client.get(url).json()
    with Session(engine) as session:
        execution = session.get(CreationExecution, identifier)
        assert execution.status == 'succeeded', execution.error
        trace = json.loads(execution.output)['trace']
        assert trace['completion_continuations'] == 1
        assert {row['material_id'] for row in trace['materials']} == {item['id'] for item in materials}
    assert saved['documents']['analysis']['content'] == result
    assert len(calls) == 4
    run_dir = directory / 'creation-projects' / project['id'] / 'executions' / identifier
    assert (run_dir / 'planning-draft-1.json').is_file()
    assert len(json.loads((run_dir / 'material-read-log.json').read_text(encoding='utf-8'))) == 30


def test_analysis_missing_materials_has_bounded_continuations_and_keeps_drafts(project_setup, monkeypatch):
    client, store, engine, directory, project = project_setup
    project = upload(client, project)
    calls = []
    def chat(*args, **kwargs):
        calls.append(args)
        return {'content': json.dumps({'facts': '未读取', 'selling_points': '', 'questions': ''})}
    monkeypatch.setattr('app.agent_runtime._chat', chat)
    identifier = str(uuid4())
    url = f'/api/creation-projects/{project["id"]}'
    assert client.post(url + '/stages/analysis', json={'revision': project['revision'], 'request_id': identifier}).status_code == 202
    assert process_creation_one(store)
    with Session(engine) as session:
        execution = session.get(CreationExecution, identifier)
        assert execution.status == 'failed'
        assert '补读两轮后仍未读齐' in execution.error
        assert '已读 0/1 份' in execution.error
    assert len(calls) == 3
    run_dir = directory / 'creation-projects' / project['id'] / 'executions' / identifier
    assert len(list(run_dir.glob('planning-draft-*.json'))) == 3
    assert client.get(url).json()['documents']['analysis'] is None


def test_analysis_provider_failure_does_not_trigger_coverage_retries(project_setup, monkeypatch):
    from app.image_provider import GenerationError
    client, store, engine, directory, project = project_setup
    project = upload(client, project)
    calls = []
    def chat(*args, **kwargs):
        calls.append(args)
        raise GenerationError('模拟上游请求超时，未自动重发')
    monkeypatch.setattr('app.agent_runtime._chat', chat)
    identifier = str(uuid4())
    url = f'/api/creation-projects/{project["id"]}'
    assert client.post(url + '/stages/analysis', json={'revision': project['revision'], 'request_id': identifier}).status_code == 202
    assert process_creation_one(store)
    assert len(calls) == 1
    with Session(engine) as session:
        execution = session.get(CreationExecution, identifier)
        assert execution.status == 'failed' and '模拟上游请求超时' in execution.error


def test_upstream_changes_invalidate_only_affected_documents_and_keep_history(project_setup):
    client, store, engine, directory, _ = project_setup
    project = confirmed_project(project_setup)
    old_ids = {key: value['id'] for key, value in project['documents'].items()}
    body = {'title': project['title'], **project['settings'], 'planning_model': project['settings']['planning_model'],
        'image_model': project['settings']['image_model'], 'style': '暖色庭院', 'revision': project['revision'], 'skill': project['skill']}
    # API uses planning_model/image_model, while task settings already carry those names.
    updated = client.put('/api/creation-projects/' + project['id'], json=body)
    assert updated.status_code == 200, updated.text
    project = updated.json()
    assert project['documents']['analysis']['id'] == old_ids['analysis']
    assert project['documents']['brief'] is None
    assert any(row['id'] == old_ids['brief'] for row in project['history'])
    assert project['documents']['prompts'] is None
    assert any(row['id'] == old_ids['prompts'] for row in project['history'])
    project = edit(client, project, 'analysis', {'facts': '修正立柱数量', 'selling_points': '已调整', 'questions': ''})
    assert project['documents']['brief'] is None and project['documents']['prompts'] is None
    assert len(project['history']) == 4


def test_prompt_matching_references_and_stale_revisions_are_rejected(project_setup):
    client, store, engine, directory, _ = project_setup
    project = confirmed_project(project_setup)
    url = '/api/creation-projects/' + project['id']
    invalid = {'revision': project['revision'], 'content': {'prompts': [{'shot_id': 'scene', 'prompt': 'x', 'reference_ids': []}]}}
    assert client.put(url + '/documents/prompts', json=invalid).status_code == 422
    assert client.post(url + '/documents/prompts/confirm', json={'revision': 1}).status_code == 409
    # Unknown images from another task must not be accepted as references.
    assert client.put(url + '/documents/brief', json={'revision': project['revision'], 'content': {'shots': [{'id':'scene','name':'场景','content':'庭院','reference_ids':[str(uuid4())]}]}}).status_code == 422


def test_generation_uses_confirmed_prompt_multireferences_and_no_planner(project_setup, monkeypatch):
    client, store, engine, directory, _ = project_setup
    project = confirmed_project(project_setup)
    request_id = str(uuid4())
    body = {'revision': project['revision'], 'request_id': request_id, 'shot_ids': ['scene', 'detail']}
    url = '/api/creation-projects/' + project['id']
    assert client.post(url + '/generate', json=body).status_code == 202
    assert process_creation_one(store, lambda *args: pytest.fail('must not plan after confirmation'))
    assert client.post(url + '/generate', json=body).status_code == 202
    saved = client.get(url).json()
    assert len(saved['images']) == 2 and len(saved['batches']) == 1
    calls = []
    native = png()
    original = httpx.Client
    def handle(request):
        calls.append(request)
        assert request.url.path == '/v1/images/edits'
        assert request.content.count(b'name="image[]"') == 2
        return httpx.Response(200, json={'data': [{'b64_json': base64.b64encode(native).decode()}]})
    monkeypatch.setattr('app.image_provider.pinned_url', lambda value: (value, {}, {}))
    monkeypatch.setattr(httpx, 'Client', lambda **kwargs: original(transport=httpx.MockTransport(handle)))
    assert process_standard_one(store, preparer=lambda *args: pytest.fail('must not rewrite confirmed prompts'))
    assert process_standard_one(store, preparer=lambda *args: pytest.fail('must not rewrite confirmed prompts'))
    assert len(calls) == 2
    assert b'CONFIRMED SCENE EXACT PROMPT' in calls[0].content
    assert b'1200x800' in calls[0].content
    assert b'1200x800' not in calls[1].content
    assert b'image-editor' in calls[0].content and b'planner' not in calls[0].content
    with Session(engine) as session:
        jobs = list(session.scalars(select(ImageJob).where(ImageJob.task_id == project['id']).order_by(ImageJob.task_index)))
        assert [job.prompt for job in jobs] == ['CONFIRMED SCENE EXACT PROMPT', 'CONFIRMED DETAIL EXACT PROMPT']
        assert all(job.status == 'succeeded' for job in jobs)
        assert len(json.loads(jobs[0].execution_result)['references']) == 2
    assert all(KEY.encode() not in file.read_bytes() for file in directory.rglob('*') if file.is_file())


def test_material_type_validation_and_removal_preserve_originals(project_setup):
    client, store, engine, directory, project = project_setup
    project = upload(client, project)
    item = project['materials'][0]
    url = f"/api/creation-projects/{project['id']}/materials/{item['id']}"
    assert client.get(url + '?preview=true').headers['content-type'] == 'image/jpeg'
    result = client.post(f"/api/creation-projects/{project['id']}/materials", data={'revision': project['revision'], 'material_id':str(uuid4()),'kind':'说明书'}, files={'file':('invalid.pdf', b'%PDF-broken', 'application/pdf')})
    assert result.status_code == 422
    result = client.delete(url + '?revision=' + str(project['revision']))
    assert result.status_code == 200 and not result.json()['materials']
    assert material_path(directory, project['id'], item['id']).is_file()


def test_optional_review_uses_task_planner_and_keeps_confirmed_prompt(project_setup):
    client, store, engine, directory, _ = project_setup
    project = confirmed_project(project_setup)
    config = client.get('/api/image-configs').json()
    assert client.put('/api/image-configs',json={'base_url':config['base_url'],'auto_review':True}).status_code == 200
    response = client.post('/api/creation-projects/'+project['id']+'/generate',json={'revision':project['revision'],
        'request_id':str(uuid4()),'shot_ids':['scene']})
    assert response.status_code == 202
    assert process_creation_one(store)
    calls=[]
    def executor(path, profile, key, prompt, references):
        assert prompt == 'CONFIRMED SCENE EXACT PROMPT' and len(references) == 2
        path.mkdir(parents=True,exist_ok=True);(path/'result.png').write_bytes(png())
        return {'native_pixels':[12,8]}
    def reviewer(store, owner, path, requirements, prompt, reference, profile=None):
        calls.append(profile['review_model'])
        return {'status':'passed','summary':'模拟审核通过','checks':[],'model':profile['review_model']}
    assert process_standard_one(store,executor=executor,reviewer=reviewer)
    saved=client.get('/api/creation-projects/'+project['id']).json()['images'][0]
    assert calls == ['planner'] and saved['status'] == 'succeeded'
    assert saved['execution_result']['agent_review']['compared_reference_count'] == 1


def test_pdf_text_and_real_image_tools_are_given_to_skill_agent(project_setup, monkeypatch):
    client, store, engine, directory, project = project_setup
    project = upload(client, project)
    # A small standard PDF with a real text layer; no external authoring dependency.
    raw = b'%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 300 200]/Resources<</Font<</F1 4 0 R>>>>/Contents 5 0 R>>endobj\n4 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj\n5 0 obj<</Length 47>>stream\nBT /F1 12 Tf 20 100 Td (FOUR POSTS ALUMINUM) Tj ET\nendstream\nendobj\ntrailer<</Root 1 0 R>>\n%%EOF'
    project = upload(client, project, raw, '规格.pdf', '规格书')
    image, pdf = project['materials']
    assert pdf['pages'] == 1 and pdf['media_type'] == 'application/pdf'
    assert client.get(f"/api/creation-projects/{project['id']}/materials/{pdf['id']}?preview=true").status_code == 200
    calls=[]
    def provider(base_url, key, model, messages, tools, **kwargs):
        calls.append(messages)
        assert model == 'planner'
        if len(calls) == 1:
            # Explicitly pin a skill for this test to focus on material tools.
            return {'tool_calls': [
                {'id':'read-pdf','type':'function','function':{'name':'read_material','arguments':json.dumps({'material_id':pdf['id'],'page':1})}},
                {'id':'view-photo','type':'function','function':{'name':'view_material','arguments':json.dumps({'material_id':image['id']})}}]}
        text = json.dumps(messages)
        assert 'FOUR POSTS' in text and 'data:image/jpeg;base64,' in text
        return {'content': json.dumps({'facts':'铝合金四根立柱，规格.pdf 第1页','selling_points':'遮阳','questions':''})}
    # Pin the already available skill to ensure it is loaded before provider invocation.
    with Session(engine) as session, session.begin():
        row = session.get(CreationProject, project['id']); data=json.loads(row.content)
        data['skill_snapshot']['pinned']=[data['skill_snapshot']['primary']['skill_id']]
        row.content=json.dumps(data)
    monkeypatch.setattr('app.agent_runtime._chat', provider)
    response=client.post(f"/api/creation-projects/{project['id']}/stages/analysis",json={'revision':project['revision'],'request_id':str(uuid4())})
    assert response.status_code==202,response.text
    assert process_creation_one(store)
    saved=client.get('/api/creation-projects/'+project['id']).json()
    assert saved['executions'][0]['status']=='succeeded',saved['executions'][0]
    assert len(calls)==2 and saved['documents']['analysis']
    assert {row['method'] for row in saved['executions'][0]['output']['trace']['materials']}=={'text','image'}


def test_foreign_task_cannot_be_read_modified_or_downloaded(project_setup):
    client, store, engine, directory, project = project_setup
    project=upload(client,project)
    with Session(engine) as session, session.begin():
        row=session.get(CreationProject,project['id']);row.owner_id='another-owner'
    root='/api/creation-projects/'+project['id']
    assert client.get(root).status_code==404
    assert client.get(root+'/materials/'+project['materials'][0]['id']).status_code==404
    assert client.get('/api/creation-projects').json()==[]
    assert client.post(root+'/stages/analysis',json={'revision':project['revision'],'request_id':str(uuid4())}).status_code==404
