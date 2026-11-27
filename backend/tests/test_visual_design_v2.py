import copy
import json

import pytest
from sqlalchemy.orm import Session

from app.database import CreationProject
from app.visual_styles import snapshot_style, validate_designs, bind_design_prompts, layout_warnings, SIGNATURES, DESIGN_START, STYLE_VERSION
from test_creation_projects import project_setup, confirmed_project, edit, confirm
from test_standard_images import standard


def shot(style='cinematic'):
    return {'id':'scene','name':'产品主图','copy':'','layout':'产品居右，占六成，左侧环境负空间','design':{
        'style':style,'composition':'产品居右占六成，环境完整延伸','camera':'低机位广角全景','depth':'前景树叶，中景产品，远景庭院',
        'lighting':'左后方柔和逆光突出轮廓，保留商品原色','typography':'无新增文字或图形，仅保留真实产品标识','rationale':'用低机位和三层光影构建电影场景'}}


def test_v2_requires_concrete_design_and_respects_preset():
    snapshot=snapshot_style({'preset':'cinematic'})
    validate_designs([shot()],snapshot)
    with pytest.raises(ValueError,match='设计方案'): validate_designs([{'name':'旧图'}],snapshot)
    with pytest.raises(ValueError,match='不一致'): validate_designs([shot('minimal')],snapshot)
    validate_designs([{'name':'旧图'}],{'version':'1.0.1'})
    assert len(set(SIGNATURES.values()))==6
    validate_designs([shot()],snapshot_style({'preset':'auto'}))


def test_design_binding_is_visible_idempotent_and_uses_frozen_snapshot():
    snapshot=snapshot_style({'preset':'cinematic'})
    brief={'shots':[shot()]}
    original={'prompts':[{'shot_id':'scene','prompt':'Show complete product. No added text.'}]}
    result=bind_design_prompts(original,brief,snapshot,{'scene'})
    prompt=result['prompts'][0]['prompt']
    assert '低机位广角全景' in prompt and json.dumps(snapshot['rules'],ensure_ascii=False) in prompt
    assert 'no added text, icons' in prompt
    assert original['prompts'][0]['prompt']=='Show complete product. No added text.'
    assert bind_design_prompts(result,brief,snapshot,{'scene'})==result
    changed=copy.deepcopy(brief);changed['shots'][0]['design']['lighting']='右侧柔光，阴影向左'
    result=bind_design_prompts(result,changed,snapshot,{'scene'})
    assert result['prompts'][0]['prompt'].count(DESIGN_START)==1
    assert '右侧柔光' in result['prompts'][0]['prompt']
    assert bind_design_prompts(original,brief,{'version':'1.0.1'})==original
    assert layout_warnings([shot(),{**shot(),'name':'第二张'}])


def test_explicit_upgrade_preserves_history_and_requires_reconfirmation(project_setup):
    client,_,engine,_,_=project_setup
    project=confirmed_project(project_setup)
    root='/api/creation-projects/'+project['id']
    # Simulate a real frozen v1 project; catalog upgrades cannot rewrite it.
    with Session(engine) as session, session.begin():
        row=session.get(CreationProject,project['id']);data=json.loads(row.content)
        data['visual_style']={'preset':'cinematic','variation':'balanced','density':'medium','palette':''}
        data['visual_style_snapshot']={**snapshot_style(data['visual_style']),'version':'1.0.1'}
        row.content=json.dumps(data)
    project=client.get(root).json()
    settings={**project['settings'],'title':project['title'],'skill':project['skill'],'revision':project['revision']}
    saved=client.put(root,json=settings).json()
    assert saved['visual_style_snapshot']['version']=='1.0.1'
    assert saved['documents']['brief']['confirmed_at']
    upgraded=client.put(root,json={**settings,'revision':saved['revision'],'refresh_visual_style':True})
    assert upgraded.status_code==200,upgraded.text
    upgraded=upgraded.json()
    assert upgraded['visual_style_snapshot']['version']==STYLE_VERSION
    assert upgraded['documents']['analysis']['id']==project['documents']['analysis']['id']
    assert upgraded['documents']['brief'] is None and upgraded['documents']['prompts'] is None
    assert len(upgraded['history'])==3
    brief=project['documents']['brief']['content']
    response=client.put(root+'/documents/brief',json={'revision':upgraded['revision'],'content':brief})
    assert response.status_code==422
    for value in brief['shots']: value['design']=shot()['design']
    upgraded=confirm(client,edit(client,upgraded,'brief',brief),'brief')
    upgraded=edit(client,upgraded,'prompts',project['documents']['prompts']['content'])
    prompts=upgraded['documents']['prompts']['content']
    assert all(DESIGN_START in p['prompt'] for p in prompts['prompts'])
    upgraded=confirm(client,upgraded,'prompts')
    assert upgraded['documents']['prompts']['content']==prompts
