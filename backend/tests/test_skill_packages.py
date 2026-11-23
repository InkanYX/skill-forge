import io
import json
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.database import Base, SkillPackage, SkillVersion, make_engine
from app.auth import initialize_admin
from app.main import create_app
from app.skill_packages import seed_builtin


OLD_ADMIN = 'temporary-admin-password'
ADMIN_PASSWORD = 'changed-admin-password'


@pytest.fixture
def accounts(tmp_path):
    engine = make_engine(f"sqlite:///{(tmp_path / 'accounts.db').as_posix()}")
    Base.metadata.create_all(engine)
    initialize_admin(engine, 'admin', OLD_ADMIN)
    app = create_app(tmp_path / 'data', db_url=str(engine.url), enable_auth=True,
                     enable_standard=False, start_image_worker=False)
    with TestClient(app) as admin:
        assert admin.post('/api/auth/login', json={'username': 'admin', 'password': OLD_ADMIN}).status_code == 200
        assert admin.post('/api/auth/password', json={
            'current_password': OLD_ADMIN, 'new_password': ADMIN_PASSWORD}).status_code == 200
        yield admin, app, engine, tmp_path / 'data'
    engine.dispose()


def member(accounts, name):
    admin, app, _, _ = accounts
    issued = admin.post('/api/admin/users', json={'username': name, 'display_name': name})
    assert issued.status_code == 201, issued.text
    data = issued.json()
    client = TestClient(app)
    assert client.post('/api/auth/login', json={
        'username': name, 'password': data['temporary_password']}).status_code == 200
    assert client.post('/api/auth/password', json={
        'current_password': data['temporary_password'],
        'new_password': name + '-new-password'}).status_code == 200
    return client, data['user']


def import_skill(client, skill_name='shared-skill', version='1.0.0'):
    preview = import_preview(client, package(skill_name, version))
    response = client.post('/api/skill-packages/import/confirm', json={
        'upload_id': preview['upload_id'], 'selections': [{'name': skill_name}]})
    assert response.status_code == 200, response.text
    return response.json()[0], preview


@pytest.fixture
def setup(tmp_path):
    engine = make_engine(f"sqlite:///{(tmp_path / 'skills.db').as_posix()}")
    Base.metadata.create_all(engine)
    directory = tmp_path / "data"
    yield engine, directory
    engine.dispose()


def archive(files: dict[str, bytes | str]) -> bytes:
    payload = io.BytesIO()
    with ZipFile(payload, 'w', ZIP_DEFLATED) as bundle:
        for path, content in files.items():
            if isinstance(content, str):
                content = content.encode('utf-8')
            bundle.writestr(path, content)
    return payload.getvalue()


def skill_md(name: str, version: str = '1.0.0', description: str = '测试技能') -> str:
    return f"---\nname: {name}\ndescription: \"{description}\"\nmetadata:\n  version: \"{version}\"\n---\n\n# {name}\n\n入口说明。\n"


def package(skill_name: str = 'demo-skill', version: str = '1.0.0', extra: str = '第一版') -> bytes:
    return archive({
        'skills/demo/SKILL.md': skill_md(skill_name, version),
        'skills/demo/references/prompt-writing-standard.md': '# 提示词规范\n\n十段式。\n',
        'skills/demo/references/quality-gate.md': '# 质检\n\nP0 不可交付。\n',
        'skills/demo/references/other.md': f'# 其他\n\n{extra}\n',
        'skills/demo/scripts/lint.py': 'print("never executed")\n',
        'skills/demo/assets/logo.svg': '<svg xmlns="http://www.w3.org/2000/svg"></svg>',
        'skills/second/SKILL.md': skill_md('second-skill', '0.1.0'),
    })


def import_preview(client: TestClient, data: bytes, name: str = 'bundle.zip'):
    response = client.post('/api/skill-packages/import', files={'archive': (name, data, 'application/zip')})
    assert response.status_code == 200, response.text
    return response.json()


def test_import_preview_confirm_and_browse(setup):
    engine, directory = setup
    with TestClient(create_app(directory, db_url=str(engine.url))) as client:
        preview = import_preview(client, package())
        names = {item['name'] for item in preview['skills']}
        assert names == {'demo-skill', 'second-skill'}
        demo = next(item for item in preview['skills'] if item['name'] == 'demo-skill')
        assert demo['file_count'] == 6
        assert demo['compiled']['core_chars'] > 0
        assert demo['compiled']['core_chars'] < demo['compiled']['full_chars']
        assert demo['existing'] is None and demo['is_upgrade'] is False
        kinds = {item['path']: item['kind'] for item in demo['files']}
        assert kinds['SKILL.md'] == 'entry'
        assert kinds['scripts/lint.py'] == 'script'
        assert kinds['assets/logo.svg'] == 'asset'

        created = client.post('/api/skill-packages/import/confirm', json={
            'upload_id': preview['upload_id'], 'selections': [{'name': 'demo-skill', 'compile_level': 'core'}]})
        assert created.status_code == 200, created.text
        row = created.json()[0]
        assert row['status'] == 'created'
        assert row['version']['compile_level'] == 'core'

        listing = client.get('/api/skill-packages').json()
        assert [item['name'] for item in listing] == ['demo-skill']
        assert listing[0]['current_version']['version_label'] == '1.0.0'
        assert listing[0]['can_activate'] is True

        detail = client.get(f"/api/skill-packages/{row['id']}").json()
        assert detail['description'] == '测试技能'
        version_id = detail['current_version']['id']

        files = client.get(f"/api/skill-packages/{row['id']}/versions/{version_id}/files").json()
        assert len(files['files']) == 6

        text = client.get(f"/api/skill-packages/{row['id']}/versions/{version_id}/files/references/other.md").json()
        assert '第一版' in text['content'] and text['total_chars'] > 0

        script = client.get(f"/api/skill-packages/{row['id']}/versions/{version_id}/files/scripts/lint.py")
        assert script.status_code == 415

        download = client.get(f"/api/skill-packages/{row['id']}/versions/{version_id}/files/scripts/lint.py?download=1")
        assert download.status_code == 200 and b'never executed' in download.content
        assert download.headers['x-content-type-options'] == 'nosniff'

        svg = client.get(f"/api/skill-packages/{row['id']}/versions/{version_id}/files/assets/logo.svg")
        assert svg.status_code == 415

        assert client.get(f"/api/skill-packages/{row['id']}/versions/{version_id}/files/../secret").status_code == 404


def test_upgrade_requires_manual_activation_and_keeps_old_version(setup):
    engine, directory = setup
    with TestClient(create_app(directory, db_url=str(engine.url))) as client:
        first = import_preview(client, package())
        created = client.post('/api/skill-packages/import/confirm', json={
            'upload_id': first['upload_id'], 'selections': [{'name': 'demo-skill'}]}).json()[0]
        skill_id = created['id']
        old_version = created['version']['id']

        second = import_preview(client, package(version='1.1.0', extra='第二版'))
        upgrade = next(item for item in second['skills'] if item['name'] == 'demo-skill')
        assert upgrade['is_upgrade'] is True and upgrade['existing']['id'] == skill_id

        added = client.post('/api/skill-packages/import/confirm', json={
            'upload_id': second['upload_id'], 'selections': [{'name': 'demo-skill', 'compile_level': 'full'}]}).json()[0]
        assert added['status'] == 'version_added'
        assert added['version']['id'] != old_version

        detail = client.get(f"/api/skill-packages/{skill_id}").json()
        assert detail['current_version']['id'] == old_version
        assert detail['version_count'] == 2

        activated = client.post(f'/api/skill-packages/{skill_id}/versions/{added["version"]["id"]}/activate')
        assert activated.status_code == 200
        assert activated.json()['current_version']['version_label'] == '1.1.0'
        assert activated.json()['current_version']['compile_level'] == 'full'

        versions = client.get(f'/api/skill-packages/{skill_id}/versions').json()
        assert [item['is_current'] for item in versions] == [True, False]
        assert client.get(f'/api/skill-packages/{skill_id}/versions/{old_version}/files/references/other.md').json()['content'].count('第一版') == 1


def test_same_content_is_reported_as_unchanged(setup):
    engine, directory = setup
    with TestClient(create_app(directory, db_url=str(engine.url))) as client:
        first = import_preview(client, package())
        created = client.post('/api/skill-packages/import/confirm', json={
            'upload_id': first['upload_id'], 'selections': [{'name': 'demo-skill'}]}).json()[0]
        again = import_preview(client, package())
        demo = next(item for item in again['skills'] if item['name'] == 'demo-skill')
        assert demo['same_content'] is True
        result = client.post('/api/skill-packages/import/confirm', json={
            'upload_id': again['upload_id'], 'selections': [{'name': 'demo-skill'}]}).json()[0]
        assert result['status'] == 'unchanged'
        assert len(client.get(f'/api/skill-packages/{created["id"]}/versions').json()) == 1


def test_import_rejects_traversal_missing_entry_and_oversized_files(setup):
    engine, directory = setup
    with TestClient(create_app(directory, db_url=str(engine.url))) as client:
        traversal = client.post('/api/skill-packages/import', files={'archive': ('x.zip', archive({'../escape.txt': b'x'}), 'application/zip')})
        assert traversal.status_code == 422 and '..' in traversal.json()['detail']

        missing = client.post('/api/skill-packages/import', files={'archive': ('x.zip', archive({'readme.md': b'# no skill'}), 'application/zip')})
        assert missing.status_code == 422 and 'SKILL.md' in missing.json()['detail']

        big = archive({'a/SKILL.md': skill_md('big'), 'a/big.bin': b'0' * (5 * 1024 * 1024 + 1)})
        oversize = client.post('/api/skill-packages/import', files={'archive': ('x.zip', big, 'application/zip')})
        assert oversize.status_code == 422 and '5 MB' in oversize.json()['detail']


def test_import_rejects_symlink_entries(setup):
    engine, directory = setup
    payload = io.BytesIO()
    with ZipFile(payload, 'w') as bundle:
        bundle.writestr('a/SKILL.md', skill_md('link-skill'))
        info = ZipInfo('a/link')
        info.external_attr = (0o120777 << 16)
        bundle.writestr(info, '/etc/passwd')
    with TestClient(create_app(directory, db_url=str(engine.url))) as client:
        response = client.post('/api/skill-packages/import', files={'archive': ('x.zip', payload.getvalue(), 'application/zip')})
        assert response.status_code == 422 and '符号链接' in response.json()['detail']


def test_folder_selection_import_and_fork(setup):
    engine, directory = setup
    with TestClient(create_app(directory, db_url=str(engine.url))) as client:
        paths = ['pkg/SKILL.md', 'pkg/references/quality-gate.md']
        preview = client.post('/api/skill-packages/import', data={'paths': json.dumps(paths)},
                              files=[('files', ('SKILL.md', skill_md('folder-skill').encode(), 'text/markdown')),
                                     ('files', ('quality-gate.md', b'# gate\n', 'text/markdown'))]).json()
        assert preview['skills'][0]['name'] == 'folder-skill'
        created = client.post('/api/skill-packages/import/confirm', json={
            'upload_id': preview['upload_id'], 'selections': [{'name': 'folder-skill'}]}).json()[0]
        forked = client.post(f"/api/skill-packages/{created['id']}/fork")
        assert forked.status_code == 200
        assert forked.json()['name'].startswith('folder-skill 副本')
        assert forked.json()['source'] == 'forked'
        assert forked.json()['current_version']['content_sha256'] == created['version']['content_sha256']


def test_seed_builtin_is_idempotent(tmp_path):
    engine = make_engine(f"sqlite:///{(tmp_path / 'seed.db').as_posix()}")
    Base.metadata.create_all(engine)
    directory = tmp_path / 'data'
    source = tmp_path / 'builtin'
    (source / 'demo').mkdir(parents=True)
    (source / 'demo' / 'SKILL.md').write_text(skill_md('builtin-demo', '2.0.0'), encoding='utf-8')
    (source / 'demo' / 'references').mkdir()
    (source / 'demo' / 'references' / 'quality-gate.md').write_text('# gate\n', encoding='utf-8')
    assert seed_builtin(engine, directory, source_root=source) == 1
    assert seed_builtin(engine, directory, source_root=source) == 0
    with Session(engine) as session:
        skill = session.query(SkillPackage).one()
        assert skill.source == 'builtin' and skill.is_readonly is True
        assert session.query(SkillVersion).count() == 1
    engine.dispose()


def test_manifest_verification_reports_mismatch(setup):
    engine, directory = setup
    manifest = {'files': [{'path': 'skills/demo/SKILL.md', 'sha256': '0' * 64}]}
    files = {
        'skills/demo/SKILL.md': skill_md('demo-skill'),
        'manifest.json': json.dumps(manifest),
    }
    with TestClient(create_app(directory, db_url=str(engine.url))) as client:
        preview = import_preview(client, archive(files))
        assert preview['manifest']['present'] is True
        assert preview['manifest']['ok'] is False
        assert preview['manifest']['mismatch'] == ['skills/demo/SKILL.md']


def test_personal_packages_are_private_and_may_share_names(accounts):
    admin, app, engine, directory = accounts
    alice, alice_user = member(accounts, 'alice')
    bob, bob_user = member(accounts, 'bob')

    alice_skill, _ = import_skill(alice, 'shared-skill')
    assert alice_skill['status'] == 'created'
    bob_skill, bob_preview = import_skill(bob, 'shared-skill')

    # Same name is allowed per owner, but it resolves to a different package.
    preview_item = next(item for item in bob_preview['skills'] if item['name'] == 'shared-skill')
    assert preview_item['existing'] is None
    assert bob_skill['id'] != alice_skill['id']

    assert [item['name'] for item in alice.get('/api/skill-packages').json()] == ['shared-skill']
    assert [item['id'] for item in alice.get('/api/skill-packages').json()] == [alice_skill['id']]
    assert [item['id'] for item in bob.get('/api/skill-packages').json()] == [bob_skill['id']]
    assert len(admin.get('/api/skill-packages').json()) == 2

    # Members cannot see or use another member's package, including direct UUID access.
    assert bob.get(f"/api/skill-packages/{alice_skill['id']}").status_code == 404
    assert bob.get(f"/api/skill-packages/{alice_skill['id']}/versions").status_code == 404
    assert bob.get(f"/api/skill-packages/{alice_skill['id']}/versions/{alice_skill['version']['id']}/files").status_code == 404
    assert bob.post(f"/api/skill-packages/{alice_skill['id']}/versions/{alice_skill['version']['id']}/activate").status_code == 404

    # Admin may inspect read-only, but only the owner may activate a personal version.
    detail = admin.get(f"/api/skill-packages/{bob_skill['id']}")
    assert detail.status_code == 200
    assert detail.json()['owner_id'] == bob_user['id'] and detail.json()['can_activate'] is False
    assert admin.post(f"/api/skill-packages/{bob_skill['id']}/versions/{bob_skill['version']['id']}/activate").status_code == 403

    added, _ = import_skill(bob, 'shared-skill', version='1.1.0')
    activated = bob.post(f"/api/skill-packages/{bob_skill['id']}/versions/{added['version']['id']}/activate")
    assert activated.status_code == 200
    assert activated.json()['current_version']['version_label'] == '1.1.0'

    # Agent runs may only use built-in or the caller's own packages.
    payload = json.dumps({'goal': '测试归属', 'skill_id': alice_skill['id'],
                          'config_id': '00000000-0000-0000-0000-000000000000'})
    assert bob.post('/api/agent/runs', files={'payload': (None, payload)}).status_code == 404
    assert admin.post('/api/agent/runs', files={'payload': (None, payload)}).status_code == 404
    own = json.dumps({'goal': '测试归属', 'skill_id': bob_skill['id'],
                      'config_id': '00000000-0000-0000-0000-000000000000'})
    # Package is accepted; the request stops later at the missing image configuration.
    assert bob.post('/api/agent/runs', files={'payload': (None, own)}).status_code == 422


def test_text_skill_import_creates_readonly_package(setup):
    engine, directory = setup
    with TestClient(create_app(directory, db_url=str(engine.url))) as client:
        response = client.post('/api/skill-packages/import/text', json={
            'name': 'text-skill', 'description': '文本说明',
            'content': '# 做法\n\n保持产品结构与颜色。'})
        assert response.status_code == 200, response.text
        created = response.json()
        assert created['status'] == 'created'

        detail = client.get(f"/api/skill-packages/{created['id']}").json()
        assert detail['source'] == 'text' and detail['is_readonly'] is True
        assert detail['current_version']['version_label'] == '1.0.0'

        files = client.get(
            f"/api/skill-packages/{created['id']}/versions/{created['version']['id']}/files").json()['files']
        assert [item['path'] for item in files] == ['SKILL.md']
        body = client.get(
            f"/api/skill-packages/{created['id']}/versions/{created['version']['id']}/files/SKILL.md").json()
        assert 'name: "text-skill"' in body['content']
        assert '保持产品结构与颜色' in body['content']

        unchanged = client.post('/api/skill-packages/import/text', json={
            'name': 'text-skill', 'content': '# 做法\n\n保持产品结构与颜色。'}).json()
        assert unchanged['status'] == 'unchanged'

        added = client.post('/api/skill-packages/import/text', json={
            'name': 'text-skill', 'content': '# 做法\n\n保持结构，并检查连接件。'}).json()
        assert added['status'] == 'version_added'
        assert client.get(f"/api/skill-packages/{created['id']}").json()['current_version']['id'] == created['version']['id']
        activated = client.post(
            f"/api/skill-packages/{created['id']}/versions/{added['version']['id']}/activate")
        assert activated.status_code == 200
        assert '检查连接件' in client.get(
            f"/api/skill-packages/{created['id']}/versions/{added['version']['id']}/files/SKILL.md").json()['content']


def test_text_skill_rejects_blank_and_builtin_name(accounts):
    admin, app, engine, directory = accounts
    source = directory / 'builtin-source'
    (source / 'demo').mkdir(parents=True)
    (source / 'demo' / 'SKILL.md').write_text(skill_md('builtin-demo', '2.0.0'), encoding='utf-8')
    assert seed_builtin(engine, directory, source_root=source) == 1

    alice, alice_user = member(accounts, 'dana')
    blank = alice.post('/api/skill-packages/import/text', json={'name': 'x', 'content': '   '})
    assert blank.status_code == 422
    reserved = alice.post('/api/skill-packages/import/text', json={
        'name': 'builtin-demo', 'content': '不能覆盖内置技能。'})
    assert reserved.status_code == 422 and '内置技能名' in reserved.json()['detail']

    created = alice.post('/api/skill-packages/import/text', json={
        'name': 'alice-text', 'content': '仅 Alice 可见。'}).json()
    assert created['status'] == 'created'
    assert alice.get(f"/api/skill-packages/{created['id']}").json()['owner_id'] == alice_user['id']
    bob, _ = member(accounts, 'erin')
    assert bob.get(f"/api/skill-packages/{created['id']}").status_code == 404


def test_builtin_names_are_reserved_and_builtin_versions_need_admin(accounts):
    admin, app, engine, directory = accounts
    source = directory / 'builtin-source'
    (source / 'demo').mkdir(parents=True)
    (source / 'demo' / 'SKILL.md').write_text(skill_md('builtin-demo', '2.0.0'), encoding='utf-8')
    (source / 'demo' / 'references').mkdir()
    (source / 'demo' / 'references' / 'quality-gate.md').write_text('# gate\n', encoding='utf-8')
    assert seed_builtin(engine, directory, source_root=source) == 1

    builtin = next(item for item in admin.get('/api/skill-packages').json() if item['name'] == 'builtin-demo')
    assert builtin['source'] == 'builtin' and builtin['owner_id'] is None

    alice, _ = member(accounts, 'carol')
    assert [item['name'] for item in alice.get('/api/skill-packages').json()] == ['builtin-demo']
    assert alice.post(f"/api/skill-packages/{builtin['id']}/versions/{builtin['current_version']['id']}/activate").status_code == 403

    preview = import_preview(alice, package('builtin-demo', '3.0.0'))
    item = next(skill for skill in preview['skills'] if skill['name'] == 'builtin-demo')
    assert item['reserved'] is True
    rejected = alice.post('/api/skill-packages/import/confirm', json={
        'upload_id': preview['upload_id'], 'selections': [{'name': 'builtin-demo'}]})
    assert rejected.status_code == 422 and '内置技能名' in rejected.json()['detail']

    forked = alice.post(f"/api/skill-packages/{builtin['id']}/fork")
    assert forked.status_code == 200
    assert forked.json()['name'] == 'builtin-demo 副本'
    assert forked.json()['source'] == 'forked' and forked.json()['can_activate'] is True
    assert [item['name'] for item in admin.get('/api/skill-packages').json()].count('builtin-demo') == 1
