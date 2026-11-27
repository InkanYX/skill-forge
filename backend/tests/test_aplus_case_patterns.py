import copy
import hashlib
import json
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.creation_skills import snapshot_for, refresh_builtin_snapshot
from app.database import SkillPackage, SkillVersion, CreationProject
from app.skill_agent import plan_with_skills
from app.skill_packages import seed_builtin, version_root
from app.visual_styles import VisualStyle, snapshot_style, bind_design_prompts
from test_skill_packages import setup
from test_visual_design_v2 import shot
from test_creation_projects import project_setup, confirmed_project
from test_standard_images import standard


def test_case_style_is_opt_in_to_legacy_and_frozen_in_visible_prompt():
    assert VisualStyle.model_validate({'preset': 'auto'}).campaign_treatment == 'adaptive'
    with pytest.raises(ValidationError):
        VisualStyle.model_validate({'campaign_treatment': 'unknown'})
    adaptive = snapshot_style({'preset': 'immersive'})
    chosen = snapshot_style({'preset': 'immersive', 'campaign_treatment': 'scene_editorial', 'palette': '品牌蓝'})
    assert adaptive != chosen
    frozen = copy.deepcopy(chosen)
    brief = {'shots': [shot('immersive')]}
    draft = {'prompts': [{'shot_id': 'scene', 'prompt': 'Finished A+ scene, exact approved copy.'}]}
    prompt = bind_design_prompts(draft, brief, chosen)['prompts'][0]['prompt']
    contract = json.loads(prompt.split('\n[Approved visual design v2]\n')[1].split('\n', 1)[1].split('\n[/Approved visual design v2]')[0])
    assert contract['campaign_rules'] == chosen['rules']
    assert chosen == frozen and draft['prompts'][0]['prompt'] != prompt
    assert 'Listing每张附图独立回答购买问题' in contract['campaign_rules']
    assert '品牌蓝' in contract['campaign_rules']


@pytest.mark.parametrize('name', ['premium-product-image-workflow', 'amazon-a-plus'])
@pytest.mark.parametrize('automatic', [False, True])
def test_real_bundled_playbook_reaches_model_and_is_audited(setup, tmp_path, name, automatic):
    engine, directory = setup
    seed_builtin(engine, directory)
    with Session(engine) as session:
        package = session.scalar(select(SkillPackage).where(SkillPackage.name == name))
        skill_id = package.id
    snapshot = snapshot_for(engine, directory, None, '制作 A+', selection={
        'mode': 'manual', 'skills': [{'skill_id': skill_id}], 'allow_auto': False})
    item = snapshot['primary']
    if automatic:
        snapshot['pinned'] = []
    raw = version_root(directory, skill_id, item['version_id']) / 'raw'
    content = (raw / 'references/aplus-scene-editorial.md').read_bytes().decode('utf-8')
    listing = ((raw / 'references/listing-scene-editorial.md').read_text(encoding='utf-8')
               if name == 'premium-product-image-workflow' else None)
    calls = []
    def provider(messages, tools):
        calls.append(messages)
        if automatic and len(calls) == 1:
            return {'tool_calls': [{'id': 'entry', 'type': 'function', 'function': {
                'name': 'read_file', 'arguments': json.dumps({
                    'file_path': f'/skills/skill-{skill_id}/SKILL.md', 'limit': 20})}}]}
        assert any(content.replace('\r', '').strip() in message.get('content', '').replace('\r', '')
                   for message in messages if isinstance(message.get('content'), str))
        if listing:
            assert any(listing.strip() in message.get('content', '').replace('\r', '')
                       for message in messages if isinstance(message.get('content'), str))
        return {'content': '{"status":"ready"}'}
    _, trace = plan_with_skills(engine, directory, tmp_path / 'run', snapshot, '策划 A+。', {}, provider)
    audit = [entry for entry in trace['files'] if entry.get('method') == 'required_context'
             and entry['path'].endswith('/references/aplus-scene-editorial.md')]
    assert audit and audit[0]['chars'] == len(content)
    assert audit[0]['sha256'] == hashlib.sha256(content.encode()).hexdigest()
    if listing:
        assert any(entry.get('method') == 'required_context' and
                   entry['path'].endswith('/references/listing-scene-editorial.md') for entry in trace['files'])
    assert content not in (raw / 'SKILL.md').read_text(encoding='utf-8')
    assert len(calls) == (2 if automatic else 1)


def test_explicit_skill_upgrade_preserves_scope_personal_and_old_snapshot(setup, tmp_path):
    engine, directory = setup
    source = tmp_path / 'builtin' / 'release-test'
    source.mkdir(parents=True)
    entry = source / 'SKILL.md'
    def release(version):
        entry.write_text('---\nname: release-test\ndescription: A+ style\nmetadata:\n  version: "' + version + '"\n---\n' + version, encoding='utf-8')
    release('1.0.0')
    assert seed_builtin(engine, directory, source.parent) == 1
    with Session(engine) as session:
        package = session.scalar(select(SkillPackage).where(SkillPackage.name == 'release-test'))
        skill_id = package.id
    snapshot = snapshot_for(engine, directory, None, 'A+', selection={
        'mode': 'manual', 'skills': [{'skill_id': skill_id}], 'allow_auto': False})
    old = copy.deepcopy(snapshot)
    old_raw = version_root(directory, skill_id, old['primary']['version_id']) / 'raw/SKILL.md'
    old_text = old_raw.read_bytes()
    release('2.0.0')
    assert seed_builtin(engine, directory, source.parent) == 1
    assert seed_builtin(engine, directory, source.parent) == 0  # inactive releases don't duplicate
    assert refresh_builtin_snapshot(engine, directory, None, snapshot) == snapshot
    with Session(engine) as session, session.begin():
        versions = session.scalars(select(SkillVersion).where(SkillVersion.skill_id == skill_id)).all()
        assert len(versions) == 2
        current = next(item for item in versions if item.version_label == '2.0.0')
        session.get(SkillPackage, skill_id).current_version_id = current.id
        personal_id = str(uuid4())
        session.add(SkillPackage(id=personal_id, name='personal', description='personal', source='imported',
            owner_id=None, is_readonly=False, created_at='now', updated_at='now'))
    personal = {'skill_id': personal_id, 'version_id': 'personal-pinned', 'sha256': 'personal-hash'}
    snapshot['catalog'].append(personal)
    snapshot['pinned'].append(personal_id)
    upgraded = refresh_builtin_snapshot(engine, directory, None, snapshot)
    assert upgraded['primary']['version'] == '2.0.0'
    assert upgraded['catalog'][-1] == personal
    assert upgraded['pinned'] == snapshot['pinned'] and upgraded['allow_auto'] is False
    assert snapshot['primary'] == old['primary'] and old_raw.read_bytes() == old_text


def test_project_upgrade_adopts_active_builtin_without_touching_history(project_setup, tmp_path):
    client, _, engine, directory, _ = project_setup
    project = confirmed_project(project_setup)
    with Session(engine) as session:
        previous = json.loads(session.get(CreationProject, project['id']).content)['skill_snapshot']
    source = tmp_path / 'release' / 'premium-product-image-workflow'
    source.mkdir(parents=True)
    (source / 'SKILL.md').write_text('---\nname: premium-product-image-workflow\ndescription: updated A+\nmetadata:\n  version: "9.0.0-test"\n---\nNew case rules.', encoding='utf-8')
    seed_builtin(engine, directory, source.parent)
    with Session(engine) as session, session.begin():
        package = session.get(SkillPackage, previous['primary']['skill_id'])
        version = session.scalar(select(SkillVersion).where(
            SkillVersion.skill_id == package.id, SkillVersion.version_label == '9.0.0-test'))
        package.current_version_id = version.id
    settings = {**project['settings'], 'title': project['title'], 'skill': project['skill'],
        'revision': project['revision'], 'visual_style': {'preset': 'auto', 'campaign_treatment': 'scene_editorial'},
        'refresh_visual_style': True}
    result = client.put('/api/creation-projects/' + project['id'], json=settings)
    assert result.status_code == 200, result.text
    updated = result.json()
    assert updated['documents']['analysis']['id'] == project['documents']['analysis']['id']
    assert updated['documents']['brief'] is None and updated['documents']['prompts'] is None
    assert len(updated['history']) == len(project['history'])
    with Session(engine) as session:
        snapshot = json.loads(session.get(CreationProject, project['id']).content)['skill_snapshot']
    assert snapshot['primary']['version'] == '9.0.0-test'
    assert snapshot['primary']['version_id'] != previous['primary']['version_id']
