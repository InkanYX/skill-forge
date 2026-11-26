import json
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from app.database import CreationDocument, ImageConfiguration
from app.creation_projects import process_creation_one
from app.image_purpose import main_shot_ids, main_prompt_has_copy, project_image_type
from test_creation_projects import project_setup, confirmed_project, edit, confirm
from test_standard_images import standard
from test_agent_runtime import review_response
from test_image_jobs import png


@pytest.mark.parametrize(('settings', 'expected'), [
    ({'goal':'制作商品套图'}, 'listing'),
    ({'goal':'制作Premium A+，参考商品套图'}, 'a_plus'),
    ({'goal':'参考 A+ 风格制作套图','learning':{'image_type':'listing'}}, 'listing'),
    ({'goal':'商品图','learning':{'image_type':'a_plus'}}, 'a_plus'),
    ({'goal':'只做细节','learning':{'image_type':'detail'}}, 'detail'),
])
def test_explicit_project_kind_wins_over_incidental_keywords(settings, expected):
    assert project_image_type(settings) == expected
    ids = main_shot_ids(settings, {'shots':[{'id':'one','name':'场景主图'},{'id':'two','name':'细节'}]})
    assert ids == ({'one'} if expected == 'listing' else set())


@pytest.mark.parametrize(('prompt', 'invalid'), [
    ('Product on a garden background. No added text, preserve original product markings.', False),
    ('Do not add text or badges.\nExact copy: none', False),
    ('Headline: "LUXURY OUTDOORS"', True),
    ('Exact copy: "Verified headline"', True),
    ('Exact copy:\n"Verified headline"\nTypography and graphic layout: serif', True),
    ('Add a headline with text above the product.', True),
    ('添加卖点文字', True),
])
def test_main_image_rejects_copy_but_preserves_nonwhite_background(prompt, invalid):
    assert main_prompt_has_copy(prompt) == invalid


def test_listing_copy_validation_isolated_from_supporting_images(project_setup):
    client, *_ = project_setup
    project = confirmed_project(project_setup)
    shots = project['documents']['brief']['content']['shots']
    shots[0]['copy'] = 'Headline: Backyard living'
    response = client.put('/api/creation-projects/'+project['id']+'/documents/brief', json={
        'revision':project['revision'],'content':{'shots':shots}})
    assert response.status_code == 422 and '主图' in response.json()['detail']
    shots[0]['copy'] = ''
    shots[0]['content'] = '完整产品，在已确认的庭院背景中展示；保留产品原有标识'
    shots[1]['copy'] = 'Headline: Connection detail'
    project = confirm(client, edit(client,project,'brief',{'shots':shots}), 'brief')
    prompts = {'prompts':[{'shot_id':'scene','prompt':'Headline: "Backyard living"'},
        {'shot_id':'detail','prompt':'Exact copy: "Connection detail"'}]}
    response = client.put('/api/creation-projects/'+project['id']+'/documents/prompts',json={
        'revision':project['revision'],'content':prompts})
    assert response.status_code == 422 and '主图' in response.json()['detail']
    prompts['prompts'][0]['prompt'] = 'Show the complete product in the confirmed garden. No added text or graphics; preserve real product markings.'
    project = confirm(client, edit(client,project,'prompts',prompts), 'prompts')
    response=client.post('/api/creation-projects/'+project['id']+'/generate',json={
        'revision':project['revision'],'request_id':str(uuid4()),'shot_ids':['detail','scene']})
    assert response.status_code == 202, response.text
    assert process_creation_one(project_setup[1])
    images=client.get('/api/creation-projects/'+project['id']).json()['images']
    assert [image['execution_profile']['shot_role'] for image in images] == ['supporting-image','main-image']
    assert images[1]['prompt'] == prompts['prompts'][0]['prompt']


def test_old_confirmed_main_copy_is_blocked_before_any_image_submission(project_setup):
    client, store, engine, *_ = project_setup
    project = confirmed_project(project_setup)
    with Session(engine) as session, session.begin():
        document = session.get(CreationDocument, project['documents']['brief']['id'])
        content = json.loads(document.content)
        content['shots'][0]['copy'] = 'Legacy advertising headline'
        document.content = json.dumps(content)
    response = client.post('/api/creation-projects/'+project['id']+'/generate',json={
        'revision':project['revision'],'request_id':str(uuid4()),'shot_ids':['scene']})
    assert response.status_code == 422 and '主图' in response.json()['detail']
    assert not client.get('/api/creation-projects/'+project['id']).json()['images']


def test_planner_receives_explicit_listing_role_policy(project_setup, monkeypatch):
    client, store, engine, directory, _ = project_setup
    project = confirmed_project(project_setup)
    captured = {}
    def planner(engine, storage, output, snapshot, instructions, brief, provider, extra_tools=None):
        captured.update(brief)
        return json.dumps({'prompts':[{'shot_id':'scene','prompt':'Complete product. No added text.'},
            {'shot_id':'detail','prompt':'Exact copy: "Connection detail"'}]}), {}
    monkeypatch.setattr('app.skill_agent.plan_with_skills',planner)
    response = client.post('/api/creation-projects/'+project['id']+'/stages/prompts',json={
        'revision':project['revision'],'request_id':str(uuid4())})
    assert response.status_code == 202, response.text
    assert process_creation_one(store)
    assert captured['settings']['image_type'] == 'listing'
    assert captured['image_policy']['main_shot_ids'] == ['scene']
    assert captured['settings']['learning']['image_type'] == 'any'


def test_visual_review_uses_product_only_role_even_without_style(project_setup, monkeypatch):
    from app.skill_image_workflow import review
    client, store, engine, directory, _ = project_setup
    config_id = client.get('/api/image-configs').json()['id']
    with Session(engine) as session:
        owner = session.get(ImageConfiguration, config_id).owner
    profile = store.snapshot(owner, config_id)
    profile.update(review_model='planner', shot_role='main-image')
    captured = []
    def vision(url, key, model, image, question, **kwargs):
        captured.append(question)
        return review_response()
    monkeypatch.setattr('app.agent_runtime._vision', vision)
    preview = directory / 'role-review'
    preview.mkdir()
    (preview/'preview.jpg').write_bytes(png())
    result = review(store, owner, preview, '商品主图', 'No added text.', None, profile)
    assert result['status'] == 'passed'
    assert '非售卖道具' in captured[0] and '不强制白底' in captured[0]
    assert 'Listing 商品套图主图' in captured[0]
