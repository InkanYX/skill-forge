import json
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.creation_projects import process_creation_one
from app.database import ImageJob, CreationExecution, ProductImageExperience
from app.product_experience import matching_experience
from test_creation_projects import project_setup, edit, confirm
from test_product_planning import product, plan
from test_standard_images import standard
from test_auth import accounts, member


def completed_image(setup, source, plan_id=None):
    client, store, engine, directory, _ = setup
    config = client.get('/api/image-configs').json()
    response = client.post('/api/image-jobs/batch', files={'_form': (None, '1')}, data={'config_id': config['id'], 'model_name': 'image-editor',
        'request_id': str(uuid4()), 'prompt': '四根立柱的凉棚', 'experience_product_id': source['id']})
    assert response.status_code == 202, response.text
    job = response.json()[0]
    with Session(engine) as session, session.begin():
        row = session.get(ImageJob, job['id'])
        row.status = 'succeeded'
        if plan_id:
            row.execution_profile = json.dumps({'creation_project_id': plan_id})
    return job


def feedback(client, job, **extra):
    response = client.post('/api/cases', json={'job_id': job['id'], 'title': '图片反馈', 'outcome': 'rework',
        'issues': '立柱变成六根', 'requested_change': '保持四根立柱，加入连接处特写参考', 'revision': 0, **extra})
    assert response.status_code == 200, response.text
    return response.json()


def activate(client, product_id, **extra):
    response = client.post('/api/product-experience/'+product_id, json={'guidance': '保持四根立柱并使用连接特写参考', 'status': 'active', **extra})
    assert response.status_code == 201, response.text
    return response.json()


def test_negative_feedback_infers_product_and_keeps_review_and_revision(project_setup):
    client, _, engine, _, _ = project_setup
    source = product(project_setup)
    planned = plan(client, source).json()
    image = completed_image(project_setup, source, planned['id'])
    assert client.get('/api/cases/'+image['id']).json() is None
    initial = client.get('/api/cases/'+image['id']+'?feedback=true').json()
    assert initial['product_id'] == source['id'] and initial['revision'] == 0
    note = feedback(client, image)
    assert note['product_locked'] and note['product_id'] == source['id'] and note['experience'] == ''
    assert client.get('/api/image-jobs/'+image['id']).json()['execution_result']['review']['status'] == 'rework'
    assert client.post('/api/cases', json={'job_id': image['id'], 'title': '反馈', 'issues': '旧内容', 'revision': 0}).status_code == 409
    other = product(project_setup)
    assert client.post('/api/cases', json={'job_id': image['id'], 'title': '反馈', 'issues': '问题', 'revision': note['revision'], 'product_id': other['id']}).status_code == 409
    rows = client.get('/api/product-experience/'+source['id']).json()['feedback']
    assert rows[0]['job_id'] == image['id'] and rows[0]['requested_change'] == note['requested_change']
    assert client.get('/api/product-experience/'+other['id']).json()['feedback'] == []


def test_summary_candidates_require_confirmation_and_retain_evidence(project_setup, monkeypatch):
    client, store, engine, _, _ = project_setup
    source = product(project_setup)
    image = completed_image(project_setup, source)
    note = feedback(client, image)
    seen = []
    def chat(url, key, model, messages, **kwargs):
        seen.append(messages)
        return {'content': json.dumps({'rules': [{'guidance': '对照实拍保留四根立柱，补充连接处特写。', 'feedback_ids': [note['id']]}]})}
    monkeypatch.setattr('app.agent_runtime._chat', chat)
    body = {'request_id': str(uuid4()), 'feedback': {note['id']: note['revision']}}
    root = '/api/product-experience/'+source['id']
    result = client.post(root+'/summarize', json=body)
    assert result.status_code == 200, result.text
    candidate = result.json()['experiences'][0]
    assert candidate['status'] == 'candidate' and candidate['sources'][0]['revision'] == note['revision']
    assert note['issues'] in seen[0][-1]['content']
    assert client.post(root+'/summarize', json=body).json()['experiences'][0]['id'] == candidate['id']
    assert len(seen) == 1
    with Session(engine) as session:
        assert matching_experience(session, source['id'], {}) == []
    result = client.put(root+'/'+candidate['id'], json={**candidate, 'status': 'active'})
    assert result.status_code == 200, result.text
    active = result.json()
    assert client.put(root+'/'+candidate['id'], json={**candidate, 'status': 'active'}).status_code == 409
    planned = plan(client, source).json()
    queued = client.post('/api/creation-projects/'+planned['id']+'/stages/brief',json={'revision': planned['revision'],'request_id': str(uuid4())})
    assert queued.status_code == 202, queued.text
    used = queued.json()['drawing_experience']['brief']
    assert used[0]['guidance'] == candidate['guidance'] and used[0]['revision'] == active['revision']
    assert client.put(root+'/'+candidate['id'],json={**active,'status':'disabled'}).status_code == 200
    with Session(engine) as session:
        execution = session.scalar(select(CreationExecution).where(CreationExecution.project_id == planned['id']))
        assert json.loads(execution.input)['drawing_experience']['brief'] == used
        assert matching_experience(session, source['id'], {}) == []
    def planner(_store, _id, _project, payload, _stage):
        assert payload['drawing_experience']['brief'] == used
        return {'shots':[{'id':'scene','name':'场景','content':'四根立柱'}]}, {}
    assert process_creation_one(store, planner=planner)
    second = plan(client, source).json()
    response = client.post('/api/creation-projects/'+second['id']+'/stages/brief',json={'revision':second['revision'],'request_id':str(uuid4())})
    assert response.json()['drawing_experience']['brief'] == []


def test_scope_candidate_disabled_and_other_product_are_not_applied(project_setup):
    client, _, engine, _, _ = project_setup
    source, other = product(project_setup), product(project_setup)
    universal = activate(client, source['id'])
    scoped = activate(client, source['id'], market='Amazon US', purpose='场景', style='现代')
    activate(client, other['id'], guidance='其他产品的经验')
    activate(client, source['id'], status='candidate', guidance='还没确认')
    with Session(engine) as session:
        assert [row['id'] for row in matching_experience(session, source['id'], {})] == [universal['id']]
        matching = matching_experience(session, source['id'], {'market':'Amazon US','purpose':'庭院场景','style':'现代简洁'})
        assert {row['id'] for row in matching} == {universal['id'],scoped['id']}
        assert len(matching_experience(session, source['id'], {'market':'Amazon UK','purpose':'场景','style':'现代'})) == 1


def test_direct_and_edit_jobs_freeze_associated_experience(project_setup):
    client, _, engine, _, _ = project_setup
    source = product(project_setup)
    rule = activate(client, source['id'])
    image = completed_image(project_setup, source)
    initial = client.get('/api/image-jobs/'+image['id']).json()['execution_profile']
    assert initial['drawing_experience']['direct'][0]['id'] == rule['id']
    root = '/api/product-experience/'+source['id']
    assert client.put(root+'/'+rule['id'],json={**rule,'guidance':'后续修改的经验'}).status_code == 200
    saved = client.get('/api/image-jobs/'+image['id']).json()['execution_profile']
    assert saved['drawing_experience'] == initial['drawing_experience']
    # An unassociated creation must not inherit a different product's rules.
    config = client.get('/api/image-configs').json()
    response = client.post('/api/image-jobs/batch',files={'_form': (None, '1')},data={'config_id':config['id'],'model_name':'image-editor','request_id':str(uuid4()),'prompt':'另一个产品'})
    assert response.status_code == 202, response.text
    assert not response.json()[0]['execution_profile'].get('drawing_experience')


def test_invalid_summary_or_changed_feedback_never_creates_active_rules(project_setup, monkeypatch):
    client, _, engine, _, _ = project_setup
    source = product(project_setup); image = completed_image(project_setup, source); note = feedback(client, image)
    root = '/api/product-experience/'+source['id']
    body = {'request_id':str(uuid4()),'feedback':{note['id']:note['revision']}}
    monkeypatch.setattr('app.agent_runtime._chat', lambda *a, **k: {'content':json.dumps({'rules':[{'guidance':'无依据的建议','feedback_ids':[str(uuid4())]}]})})
    assert client.post(root+'/summarize',json=body).status_code == 502
    assert client.post(root+'/summarize',json={**body,'feedback':{note['id']:999}}).status_code == 409
    assert client.get(root).json()['experiences'] == []
    with Session(engine) as session:
        assert session.scalar(select(ProductImageExperience)) is None


def test_members_can_share_feedback_but_cannot_activate_others_product(accounts):
    admin, app, engine, directory = accounts
    first, _ = member(accounts, 'first')
    second, _ = member(accounts, 'second')
    product_response = first.post('/api/creation-projects',json={'kind':'product','title':'团队凉棚'})
    assert product_response.status_code == 201, product_response.text
    source = product_response.json()
    root = '/api/product-experience/'+source['id']
    assert second.get(root).status_code == 404
    assert second.post(root,json={'guidance':'不应允许','status':'active'}).status_code == 404
    assert first.post(root,json={'guidance':'作者确认的经验','status':'active'}).status_code == 201
    assert second.get(root).status_code == 404
    assert first.get(root).json()['experiences'][0]['guidance'] == '作者确认的经验'


def test_actual_planner_receives_guidance_and_image_execution_preserves_confirmed_prompt(project_setup, monkeypatch):
    from app.creation_projects import run_planning
    client, store, engine, directory, _ = project_setup
    source = product(project_setup)
    rule = activate(client, source['id'])
    planned = plan(client, source).json()
    root = '/api/creation-projects/'+planned['id']
    queued = client.post(root+'/stages/brief',json={'revision':planned['revision'],'request_id':str(uuid4())}).json()
    captured = []
    def skill_planner(_engine, _data, _dir, _snapshot, _instructions, brief, _chat, **kwargs):
        captured.append(brief)
        return json.dumps({'shots':[{'id':'main','name':'主图','content':'保留四根立柱'}]}), {}
    monkeypatch.setattr('app.skill_agent.plan_with_skills', skill_planner)
    assert process_creation_one(store)
    assert captured[0]['product_drawing_experience'][0]['id'] == rule['id']
    planned = confirm(client, client.get(root).json(), 'brief')
    planned = confirm(client, edit(client, planned, 'prompts', {'prompts':[{'shot_id':'main','prompt':'EXACT CONFIRMED PROMPT'}]}), 'prompts')
    response = client.post(root+'/generate',json={'revision':planned['revision'],'request_id':str(uuid4()),'shot_ids':['main'],'image_model':'image-editor'})
    assert response.status_code == 202, response.text
    assert process_creation_one(store)
    jobs = client.get(root).json()['images']
    assert len(jobs) == 1 and jobs[0]['prompt'] == 'EXACT CONFIRMED PROMPT'
    assert jobs[0]['execution_profile']['drawing_experience']['brief'][0]['id'] == rule['id']
    assert jobs[0]['execution_profile']['prepared_by_agent']


def test_feedback_changed_during_summary_is_rejected(project_setup, monkeypatch):
    from app.database import CreativeCase
    client, _, engine, _, _ = project_setup
    source = product(project_setup); image = completed_image(project_setup, source); note = feedback(client, image)
    def chat(*args, **kwargs):
        with Session(engine) as session, session.begin():
            row = session.get(CreativeCase, note['id']); row.revision += 1; row.issues = '反馈已经改正'
        return {'content':json.dumps({'rules':[{'guidance':'基于旧反馈的建议','feedback_ids':[note['id']]}]})}
    monkeypatch.setattr('app.agent_runtime._chat',chat)
    response = client.post('/api/product-experience/'+source['id']+'/summarize',json={'request_id':str(uuid4()),'feedback':{note['id']:note['revision']}})
    assert response.status_code == 409, response.text
    assert client.get('/api/product-experience/'+source['id']).json()['experiences'] == []
