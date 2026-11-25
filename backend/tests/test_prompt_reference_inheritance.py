import json
from uuid import uuid4

from app.creation_projects import process_creation_one
from test_creation_projects import project_setup, confirmed_project
from test_standard_images import standard


def test_manual_prompt_save_inherits_exact_reference_order(project_setup):
    client, store, engine, directory, _ = project_setup
    project = confirmed_project(project_setup)
    shots = project['documents']['brief']['content']['shots']
    response = client.put('/api/creation-projects/'+project['id']+'/documents/prompts', json={
        'revision':project['revision'], 'content':{'prompts':[
            {'shot_id':shots[0]['id'], 'prompt':'Keep original product', 'reference_ids':[str(uuid4())]},
            {'shot_id':shots[1]['id'], 'prompt':'Show details'},
        ]}})
    assert response.status_code == 200, response.text
    prompts = response.json()['documents']['prompts']['content']['prompts']
    assert [p['reference_ids'] for p in prompts] == [s['reference_ids'] for s in shots]
    assert prompts[0]['prompt'] == 'Keep original product'


def test_model_extra_references_cannot_change_confirmed_materials(project_setup, monkeypatch):
    client, store, engine, directory, _ = project_setup
    project = confirmed_project(project_setup)
    shots = project['documents']['brief']['content']['shots']
    raw = {'prompts':[
        {'shot_id':shots[0]['id'], 'prompt':'Scene prompt', 'reference_ids':[str(uuid4()) for _ in range(10)]},
        {'shot_id':shots[1]['id'], 'prompt':'Detail prompt'},
    ]}
    def planner(*args, **kwargs):
        schema = args[5]['output_schema']
        assert 'reference_ids' not in json.dumps(schema)
        return json.dumps(raw), {'used_skills':[], 'files':[]}
    monkeypatch.setattr('app.skill_agent.plan_with_skills', planner)
    result = client.post('/api/creation-projects/'+project['id']+'/stages/prompts', json={
        'revision':project['revision'], 'request_id':str(uuid4())})
    assert result.status_code == 202, result.text
    assert process_creation_one(store)
    saved = client.get('/api/creation-projects/'+project['id']).json()
    execution = saved['executions'][-1]
    assert execution['status'] == 'succeeded', execution
    prompts = saved['documents']['prompts']['content']['prompts']
    assert [p['reference_ids'] for p in prompts] == [s['reference_ids'] for s in shots]
    assert not saved['documents']['prompts']['confirmed_at']
    recorded = directory/'creation-projects'/project['id']/'executions'/execution['id']/'planning-response.txt'
    assert json.loads(recorded.read_text(encoding='utf-8')) == raw
