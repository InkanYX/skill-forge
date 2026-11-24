import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.creation_skills import snapshot_for
from app.image_provider import GenerationError
from app.main import create_app
from app.skill_agent import plan_with_skills, ReadOnlySkills
from app.skill_packages import version_root
from app.skill_store import ImportRejected, parse_frontmatter
from test_skill_packages import setup, archive, import_preview


def imported(setup):
    engine, directory = setup
    data = archive({
        'skills/custom/SKILL.md': '---\nname: custom-layout\ndescription: >-\n  制作特殊商品图片。\n  需要读取公共版式资料。\n---\n读取 ../../docs/custom-layout.md 后制作图片。',
        'docs/custom-layout.md': '独有版式规则：布局标识 ALPHA-987，产品必须保持四根柱子。',
        'tools/unused.py': 'raise RuntimeError("must never execute")',
    })
    with TestClient(create_app(directory, db_url=str(engine.url))) as client:
        preview = import_preview(client, data)
        result = client.post('/api/skill-packages/import/confirm', json={
            'upload_id': preview['upload_id'], 'selections': [{'name': 'custom-layout'}]})
        assert result.status_code == 200, result.text
        item = result.json()[0]
    snapshot = snapshot_for(engine, directory, None, '制作商品图', selection={
        'mode': 'manual', 'skills': [{'skill_id': item['id']}], 'allow_auto': False})
    return engine, directory, item, snapshot


def test_standard_yaml_and_bom_are_supported_without_silent_corruption():
    value = parse_frontmatter('\ufeff---\nname: demo\ndescription: >-\n  第一行\n  第二行\n---\n正文')
    assert value['description'] == '第一行 第二行'
    with pytest.raises(ImportRejected, match='YAML'):
        parse_frontmatter('---\nname: [broken\n---\n正文')


@pytest.mark.parametrize('automatic', [False, True])
def test_required_reference_is_injected_and_audited_without_model_request(setup, tmp_path, automatic):
    engine, directory = setup
    marker = 'REQUIRED-STYLE-729: vary camera and layout, preserve product identity.'
    data = archive({'visual/SKILL.md': '---\nname: required-style-test\ndescription: 商品图风格\nmetadata:\n  required_references:\n    - references/campaign-style.md\n---\n按主题设计。',
                    'visual/references/campaign-style.md': marker})
    with TestClient(create_app(directory, db_url=str(engine.url))) as client:
        preview = import_preview(client, data)
        response = client.post('/api/skill-packages/import/confirm', json={
            'upload_id': preview['upload_id'], 'selections': [{'name': 'required-style-test'}]})
        assert response.status_code == 200, response.text
        item = response.json()[0]
    snapshot = snapshot_for(engine, directory, None, '设计商品图', selection={
        'mode': 'manual', 'skills': [{'skill_id': item['id']}], 'allow_auto': False})
    if automatic: snapshot['pinned'] = []
    calls = []
    def provider(messages, tools):
        calls.append(messages)
        text = json.dumps(messages, ensure_ascii=False)
        if automatic and len(calls) == 1:
            return {'tool_calls': [{'id': 'entry', 'type': 'function', 'function': {'name': 'read_file',
                'arguments': json.dumps({'file_path': f'/skills/skill-{item["id"]}/SKILL.md'})}}]}
        assert marker in text  # real model context, not just a claimed read in the log
        return {'content': '{"status":"ready","prompt":"designed"}'}
    _, trace = plan_with_skills(engine, directory, tmp_path / 'run', snapshot, '使用技能。', {}, provider)
    reads = [row for row in trace['files'] if row.get('method') == 'required_context']
    assert reads and reads[0]['path'].endswith('/references/campaign-style.md')
    assert reads[0]['chars'] == len(marker) and reads[0]['skill_id'] == item['id']
    assert len(calls) == (2 if automatic else 1)
    root = version_root(directory, item['id'], item['version']['id'])
    assert marker not in (root / 'raw' / 'SKILL.md').read_text(encoding='utf-8')
    assert 'required_context' not in trace['used_skills'][0]


@pytest.mark.parametrize('reference', ['references/missing.md', '../outside.md'])
def test_missing_or_escaping_required_reference_stops_before_provider(setup, tmp_path, reference):
    engine, directory = setup
    data = archive({'visual/SKILL.md': f'---\nname: broken-required-style\nmetadata:\n  required_references:\n    - {reference}\n---\n按规范制作。'})
    with TestClient(create_app(directory, db_url=str(engine.url))) as client:
        preview = import_preview(client, data)
        response = client.post('/api/skill-packages/import/confirm', json={
            'upload_id': preview['upload_id'], 'selections': [{'name': 'broken-required-style'}]})
        assert response.status_code == 200, response.text
        item = response.json()[0]
    snapshot = snapshot_for(engine, directory, None, '商品图', selection={'skill_id': item['id']})
    with pytest.raises(GenerationError, match='技能入口或资源无法读取'):
        plan_with_skills(engine, directory, tmp_path / 'run', snapshot, '使用技能。', {},
                         lambda *args: pytest.fail('missing required document must stop before provider'))


def test_sdk_reads_custom_skill_and_shared_resources_progressively(setup, tmp_path):
    engine, directory, item, snapshot = imported(setup)
    meta = json.loads((version_root(directory, item['id'], item['version']['id']) / 'bundle.json').read_text())
    shared = f'/bundles/{meta["bundle_id"]}/docs/custom-layout.md'
    calls = []

    def provider(messages, tools):
        calls.append(messages)
        if len(calls) == 1:
            # Pinning supplies the entry, but not its referenced document.
            assert 'ALPHA-987' not in json.dumps(messages, ensure_ascii=False)
            return {'tool_calls': [{'id': 'read-1', 'type': 'function', 'function': {
                'name': 'read_file', 'arguments': json.dumps({'file_path': shared})}}]}
        assert 'ALPHA-987' in json.dumps(messages, ensure_ascii=False)
        return {'content': '{"status":"ready","prompt":"使用 ALPHA-987 版式"}'}

    reply, trace = plan_with_skills(engine, directory, tmp_path / 'run', snapshot,
        '读取技能并按需读取资料后返回 JSON。', {'requirements': '制作商品图'}, provider)
    assert 'ALPHA-987' in reply
    assert trace['planning_method'] == 'deepagents'
    assert [skill['name'] for skill in trace['used_skills']] == ['custom-layout']
    assert any(row['path'] == shared for row in trace['files'])
    assert any(row['method'] == 'pinned' for row in trace['files'])
    assert len(calls) == 2
    assert not [path for path in (tmp_path / 'run').glob('skill-read-*') if path.is_dir()]


def test_auto_mode_requires_actual_skill_read(setup, tmp_path):
    engine, directory, item, snapshot = imported(setup)
    snapshot['pinned'] = []
    with pytest.raises(GenerationError, match='未读取任何'):
        plan_with_skills(engine, directory, tmp_path / 'run', snapshot, '使用技能。', {},
            lambda messages, tools: {'content': '{"status":"ready","prompt":"ignored skills"}'})


def test_auto_discovers_entry_then_reads_it_with_read_only_tools(setup, tmp_path):
    engine, directory, item, snapshot = imported(setup)
    snapshot['pinned'] = []
    calls = []

    def provider(messages, tools):
        calls.append(messages)
        assert {tool['function']['name'] for tool in tools} == {'ls', 'read_file', 'glob', 'grep'}
        if len(calls) == 1:
            text = json.dumps(messages, ensure_ascii=False)
            assert '制作特殊商品图片' in text
            path = re.search(r'/skills/skill-[0-9a-f-]+/SKILL.md', text).group()
            return {'tool_calls': [{'id': 'read-entry', 'type': 'function', 'function': {
                'name': 'read_file', 'arguments': json.dumps({'file_path': path})}}]}
        return {'content': '{"status":"needs_input","explanation":"需要确认产品资料"}'}

    _, trace = plan_with_skills(engine, directory, tmp_path / 'run', snapshot, '使用技能。', {}, provider)
    assert trace['used_skills'][0]['skill_id'] == item['id']
    assert len(calls) == 2


def test_explicit_markdown_entry_and_duplicate_skill_names(setup):
    engine, directory = setup
    with TestClient(create_app(directory, db_url=str(engine.url))) as client:
        result = client.post('/api/skill-packages/import', data={'entry_path': 'guide/制作说明.md'},
            files={'archive': ('skill.zip', archive({'guide/制作说明.md': '# 制作说明\n保持产品结构。'}), 'application/zip')})
        assert result.status_code == 200, result.text
        assert result.json()['skills'][0]['name'] == '制作说明'
        repeated = archive({'a/SKILL.md': '---\nname: same\n---\nA', 'b/SKILL.md': '---\nname: same\n---\nB'})
        result = client.post('/api/skill-packages/import', files={'archive': ('skill.zip', repeated, 'application/zip')})
        assert result.status_code == 200 and len(result.json()['skills']) == 2
        preview = result.json()
        ambiguous = client.post('/api/skill-packages/import/confirm', json={
            'upload_id': preview['upload_id'], 'selections': [{'name': 'same'}]})
        assert ambiguous.status_code == 422 and '同名技能入口' in ambiguous.text
        imported = client.post('/api/skill-packages/import/confirm', json={
            'upload_id': preview['upload_id'], 'selections': [
                {'name': 'same', 'root': 'a', 'import_name': '第一套规范'},
                {'name': 'same', 'root': 'b', 'import_name': '第二套规范'}]})
        assert imported.status_code == 200 and len(imported.json()) == 2


def test_shared_documents_are_versioned_and_can_be_browsed(setup):
    engine, directory = setup
    with TestClient(create_app(directory, db_url=str(engine.url))) as client:
        def upload(content):
            payload = archive({'skills/demo/SKILL.md': '---\nname: shared-doc-test\ndescription: 读取公共资料\n---\n读 ../../docs/layout.md',
                               'docs/layout.md': content})
            preview = import_preview(client, payload)
            result = client.post('/api/skill-packages/import/confirm', json={
                'upload_id': preview['upload_id'], 'selections': [{'name': 'shared-doc-test'}]})
            assert result.status_code == 200, result.text
            return result.json()[0]
        first, second = upload('旧版布局'), upload('新版布局')
        assert second['status'] == 'version_added'
        assert first['version']['content_sha256'] != second['version']['content_sha256']
        prefix = f'/api/skill-packages/{first["id"]}/versions'
        assert client.get(f'{prefix}/{first["version"]["id"]}/resources/docs/layout.md').json()['content'] == '旧版布局'
        assert client.get(f'{prefix}/{second["version"]["id"]}/resources/docs/layout.md').json()['content'] == '新版布局'
        assert any(item['path'] == 'docs/layout.md' for item in client.get(f'{prefix}/{first["version"]["id"]}/files').json()['resources'])


def test_file_tools_cannot_escape_root_or_read_an_unavailable_skill(tmp_path):
    root = tmp_path / 'workspace'
    root.mkdir()
    (tmp_path / 'outside.md').write_text('not available')
    backend = ReadOnlySkills(root, {})
    assert backend.read('/../outside.md').error
    assert backend.read('/other/SKILL.md').error
    assert backend.read('/script.py').error


def test_markdown_text_import_preserves_its_metadata_and_rejects_bad_yaml(setup):
    engine, directory = setup
    with TestClient(create_app(directory, db_url=str(engine.url))) as client:
        response = client.post('/api/skill-packages/import/text', json={'name': 'text-entry',
            'content': '---\nname: original\ndescription: >-\n  完整描述\n  第二行\nmetadata:\n  version: "3.2.1"\n---\n\n实际技能正文'})
        assert response.status_code == 200, response.text
        row = response.json()
        assert row['version']['version_label'] == '3.2.1'
        detail = client.get(f'/api/skill-packages/{row["id"]}').json()
        assert detail['description'] == '完整描述 第二行'
        response = client.post('/api/skill-packages/import/text', json={'name': 'bad-entry', 'content': '---\nname: [broken\n---\n正文'})
        assert response.status_code == 422


def test_multiple_plain_documents_request_entry_confirmation_and_allow_metadata_edit(setup):
    engine, directory = setup
    payload = archive({'instructions/制作步骤.md': '# 制作方法\n先读取 ../notes/版式.md。',
                       'notes/版式.md': '保留四柱结构，使用绿色主题。'})
    with TestClient(create_app(directory, db_url=str(engine.url))) as client:
        response = client.post('/api/skill-packages/import', files={'archive': ('docs.zip', payload, 'application/zip')})
        assert response.status_code == 200, response.text
        preview = response.json()
        assert preview['needs_entry'] and not preview['skills']
        assert {item['path'] for item in preview['entry_candidates']} == {'instructions/制作步骤.md', 'notes/版式.md'}
        response = client.post('/api/skill-packages/import/entry', json={
            'upload_id': preview['upload_id'], 'path': 'instructions/制作步骤.md'})
        preview = response.json()
        assert not preview['needs_entry']
        response = client.post('/api/skill-packages/import/confirm', json={'upload_id': preview['upload_id'],
            'selections': [{'name': '制作步骤', 'root': 'instructions', 'import_name': '团队场景制作',
                            'description': '凉棚庭院场景使用，强调结构保真和绿色主题。'}]})
        assert response.status_code == 200, response.text
        imported = response.json()[0]
        detail = client.get(f'/api/skill-packages/{imported["id"]}').json()
        assert detail['name'] == '团队场景制作' and '凉棚庭院场景' in detail['description']
        snapshot = snapshot_for(engine, directory, None, '庭院场景', selection={'skill_id': imported['id']})
        assert snapshot['catalog'][0]['description'] == detail['description']
        original = client.get(f'/api/skill-packages/{imported["id"]}/versions/{imported["version"]["id"]}/files/制作步骤.md').json()
        assert original['content'] == '# 制作方法\n先读取 ../notes/版式.md。'
