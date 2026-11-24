"""Immutable skill packages: import, preview, safe file access and manual activation."""
from __future__ import annotations

import hashlib
import json
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Annotated, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Form, HTTPException, Request, UploadFile, File
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.authorization import principal
from app.database import SkillFile, SkillPackage, SkillVersion
from app.skill_store import (
    MAX_PACKAGE_BYTES, ImportRejected, compile_context, content_fingerprint,
    copy_tree, extract_archive, file_entries, find_skill_roots, read_text,
    safe_join, verify_manifest, write_uploads, wrap_entry, SKIP_DIRS, parse_frontmatter, walk_files,
)

IMPORT_TTL = 24 * 3600
SCHEMA_LIMITS = {'package_bytes': MAX_PACKAGE_BYTES, 'files': 1000, 'file_bytes': 5 * 1024 * 1024}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def is_global(row: SkillPackage) -> bool:
    """Built-in packages have no owner and are shared by every account."""
    return row.source == 'builtin' or row.owner_id is None


def can_view(row: SkillPackage, user) -> bool:
    # Admins may inspect every package (read-only troubleshooting).
    if user is None or user['role'] == 'admin':
        return True
    return is_global(row) or row.owner_id == user['id']


def can_activate(row: SkillPackage, user) -> bool:
    # Built-in versions belong to the application release; personal versions belong to their owner.
    if user is None:
        return True
    if is_global(row):
        return user['role'] == 'admin'
    return row.owner_id == user['id']


def scope_filter(user):
    """Rows a user may see; admins and auth-disabled installs see everything."""
    if user is None or user['role'] == 'admin':
        return None
    return or_(SkillPackage.source == 'builtin', SkillPackage.owner_id == user['id'],
               SkillPackage.owner_id.is_(None))


def import_filter(user):
    """Packages an import may extend: built-in names (reserved) plus the caller's own packages."""
    if user is None:
        return None
    return or_(SkillPackage.source == 'builtin', SkillPackage.owner_id == user['id'],
               SkillPackage.owner_id.is_(None))


def name_taken(session: Session, name: str, owner: str | None) -> bool:
    condition = or_(SkillPackage.source == 'builtin',
                    SkillPackage.owner_id.is_(None) if owner is None else SkillPackage.owner_id == owner)
    return session.scalar(select(SkillPackage.id).where(SkillPackage.name == name, condition)) is not None


def skills_root(directory: Path) -> Path:
    return directory / 'skills'


def imports_root(directory: Path) -> Path:
    return directory / 'skill-imports'


def check_import_owner(stage: Path):
    owner_file = stage / 'owner.json'
    user = principal.get()
    if user and (not owner_file.is_file() or json.loads(owner_file.read_text())['owner'] != user['id']):
        raise HTTPException(404, '导入会话不存在或已过期，请重新上传。')


def version_root(directory: Path, skill_id: str, version_id: str) -> Path:
    return skills_root(directory) / skill_id / version_id


def import_fingerprint(source: Path, bundle: Path | None = None) -> str:
    if bundle is None or source == bundle:
        return content_fingerprint(file_entries(source))
    # Shared docs and tools are part of a version too, even outside its skill directory.
    value = content_fingerprint(file_entries(bundle)) + '\n' + source.relative_to(bundle).as_posix()
    return hashlib.sha256(value.encode()).hexdigest()


def preserve_bundle(directory: Path, source: Path) -> str:
    fingerprint = content_fingerprint(file_entries(source))
    root = directory / 'skill-bundles' / fingerprint
    if not root.exists():
        staged = root.with_name(f'.tmp-{uuid4().hex[:12]}')
        shutil.copytree(source, staged, ignore=shutil.ignore_patterns(*SKIP_DIRS, '.DS_Store', 'Thumbs.db'))
        try:
            staged.rename(root)
        except FileExistsError:
            shutil.rmtree(staged)
    return fingerprint


def bundle_resources(directory: Path, skill_id: str, version_id: str):
    metadata = version_root(directory, skill_id, version_id) / 'bundle.json'
    if not metadata.is_file():
        return None, []
    value = json.loads(metadata.read_text(encoding='utf-8'))
    identifier = value['bundle_id']
    if len(identifier) != 64 or any(char not in '0123456789abcdef' for char in identifier):
        raise HTTPException(422, '技能资源快照无效。')
    root = directory / 'skill-bundles' / identifier
    prefix = value['skill_root'].rstrip('/') + '/'
    files = [item for item in file_entries(root) if value['skill_root'] != '.' and not item['path'].startswith(prefix)]
    return root, files


def unique_version_label(session: Session, package: SkillPackage, base: str, fingerprint: str) -> str:
    label = (base or '0.0.0')[:64]
    if session.scalar(select(SkillVersion).where(SkillVersion.skill_id == package.id,
                                                 SkillVersion.version_label == label)):
        label = f'{label[:55]}-{fingerprint[:8]}'
        suffix = 2
        while session.scalar(select(SkillVersion).where(SkillVersion.skill_id == package.id,
                                                        SkillVersion.version_label == label)):
            tail = f'{fingerprint[:8]}-{suffix}'
            label = f'{base[:63 - len(tail)]}-{tail}'
            suffix += 1
    return label


def install_version(session: Session, directory: Path, package: SkillPackage, source_root: Path,
                    label: str, level: str, created_by: str | None, note: str = '',
                    bundle_root: Path | None = None, entry_path: str = 'SKILL.md') -> SkillVersion:
    """Copy the raw tree, compile it, and record both.  Never mutates existing versions."""
    files = file_entries(source_root)
    if not files:
        raise ImportRejected('技能目录是空的。')
    compiled, index = compile_context(source_root, files, level)
    version_id = str(uuid4())
    target = version_root(directory, package.id, version_id)
    copy_tree(source_root, target / 'raw')
    if bundle_root is not None:
        bundle_id = preserve_bundle(directory, bundle_root)
        (target / 'bundle.json').write_text(json.dumps({'bundle_id': bundle_id,
            'skill_root': source_root.relative_to(bundle_root).as_posix()}, ensure_ascii=False), encoding='utf-8')
    compiled_dir = target / 'compiled'
    compiled_dir.mkdir(parents=True, exist_ok=True)
    (compiled_dir / 'context.md').write_text(compiled, encoding='utf-8')
    (compiled_dir / 'index.json').write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding='utf-8')
    version = SkillVersion(
        id=version_id, skill_id=package.id, version_label=label, status='ready', compile_level=level,
        content_sha256=import_fingerprint(source_root, bundle_root), compiled_sha256=hashlib.sha256(compiled.encode('utf-8')).hexdigest(),
        compiled_chars=len(compiled), file_count=len(files), total_bytes=sum(item['size'] for item in files),
        entry_path=entry_path, created_at=now(), created_by=created_by, import_note=note,
    )
    session.add(version)
    for item in files:
        session.add(SkillFile(version_id=version_id, path=item['path'], kind=item['kind'],
                              size=item['size'], sha256=item['sha256'], is_text=item['is_text']))
    return version


def package_view(session: Session, row: SkillPackage) -> dict:
    current = session.get(SkillVersion, row.current_version_id) if row.current_version_id else None
    version_count = len(session.scalars(select(SkillVersion.id).where(SkillVersion.skill_id == row.id)).all())
    user = principal.get()
    return {
        'id': row.id, 'name': row.name, 'description': row.description, 'source': row.source,
        'owner_id': row.owner_id, 'is_readonly': row.is_readonly, 'created_at': row.created_at,
        'updated_at': row.updated_at, 'version_count': version_count,
        'can_activate': can_activate(row, user),
        'can_edit': can_activate(row, user),
        'current_version': version_view(current) if current else None,
    }


def version_view(row: SkillVersion) -> dict:
    return {
        'id': row.id, 'skill_id': row.skill_id, 'version_label': row.version_label,
        'status': row.status, 'compile_level': row.compile_level,
        'content_sha256': row.content_sha256, 'compiled_sha256': row.compiled_sha256,
        'compiled_chars': row.compiled_chars, 'file_count': row.file_count,
        'total_bytes': row.total_bytes, 'created_at': row.created_at, 'import_note': row.import_note,
    }


def build_preview(directory: Path, engine, upload_id: str) -> dict:
    stage = imports_root(directory) / upload_id
    package_root = stage / 'package'
    if not package_root.is_dir():
        raise HTTPException(404, '导入会话不存在或已过期，请重新上传。')
    check_import_owner(stage)
    try:
        found = find_skill_roots(package_root)
    except ImportRejected as error:
        raise HTTPException(422, str(error)) from None
    candidates = [{'path': path, 'name': PurePosixPath(path).stem} for path in walk_files(package_root)
                  if PurePosixPath(path).suffix.lower() in {'.md', '.markdown', '.txt'}]
    skills = []
    user = principal.get()
    with Session(engine) as session:
        for item in found:
            files = file_entries(item['path'])
            fingerprint = import_fingerprint(item['path'], package_root)
            core, _ = compile_context(item['path'], files, 'core')
            full, _ = compile_context(item['path'], files, 'full')
            condition = import_filter(user)
            statement = select(SkillPackage).where(SkillPackage.name == item['name'])
            if condition is not None:
                statement = statement.where(condition)
            existing = session.scalar(statement)
            current = session.get(SkillVersion, existing.current_version_id) if existing and existing.current_version_id else None
            same = bool(current and current.content_sha256 == fingerprint)
            skills.append({
                'root': item['root'], 'name': item['name'], 'description': item['description'],
                'resource_only': any(part in {'runtime', 'tools'} for part in PurePosixPath(item['root']).parts),
                'version_label': item['version_label'], 'file_count': len(files),
                'total_bytes': sum(value['size'] for value in files),
                'content_sha256': fingerprint,
                'compiled': {'core_chars': len(core), 'full_chars': len(full)},
                'files': [{'path': value['path'], 'kind': value['kind'], 'size': value['size']} for value in files],
                'existing': ({'id': existing.id, 'name': existing.name,
                              'current_label': current.version_label if current else None} if existing else None),
                'same_content': same,
                'reserved': bool(existing and existing.source == 'builtin'),
                'is_upgrade': bool(existing and existing.source != 'builtin' and not same),
            })
    return {'upload_id': upload_id, 'skills': skills, 'entry_candidates': candidates if not found else [],
            'needs_entry': not bool(found), 'manifest': verify_manifest(package_root),
            'limits': SCHEMA_LIMITS}


class Selection(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    root: str | None = Field(default=None, max_length=2048)
    import_name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=1000)
    compile_level: Literal['core', 'full'] = 'core'

    @field_validator('import_name')
    @classmethod
    def clean_name(cls, value):
        if value is not None and (not value.strip() or any(ord(char) < 32 for char in value)):
            raise ValueError('请填写不包含换行的技能名称。')
        return value.strip() if value else value


class ConfirmInput(BaseModel):
    upload_id: UUID
    selections: list[Selection] = Field(min_length=1, max_length=50)


class EntryInput(BaseModel):
    upload_id: UUID
    path: str = Field(min_length=1, max_length=2048)


class TextInput(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default='', max_length=1000)
    content: str = Field(min_length=1, max_length=20000)
    compile_level: Literal['core', 'full'] = 'core'

    @field_validator('name', 'content')
    @classmethod
    def nonblank(cls, value, info):
        if not value.strip():
            raise ValueError('请填写技能名称和内容。')
        return value.strip() if info.field_name == 'name' else value


def cleanup_imports(directory: Path) -> None:
    root = imports_root(directory)
    if not root.is_dir():
        return
    cutoff = time.time() - IMPORT_TTL
    for path in root.iterdir():
        try:
            if path.is_dir() and path.stat().st_mtime < cutoff:
                shutil.rmtree(path, ignore_errors=True)
        except OSError:
            continue


def confirm_import(directory: Path, engine, data: ConfirmInput) -> list[dict]:
    upload_id = str(data.upload_id)
    stage = imports_root(directory) / upload_id
    package_root = stage / 'package'
    if not package_root.is_dir():
        raise HTTPException(404, '导入会话不存在或已过期，请重新上传。')
    check_import_owner(stage)
    found = find_skill_roots(package_root)
    user = principal.get()
    owner = user['id'] if user else None
    created = []
    target_names = [item.import_name or item.name for item in data.selections]
    if len(target_names) != len(set(target_names)):
        raise HTTPException(422, '本次导入存在重复名称，请在确认页区分技能名称。')
    try:
        with Session(engine) as session, session.begin():
            for selection in data.selections:
                matches = [item for item in found if item['name'] == selection.name
                           and (selection.root is None or item['root'] == selection.root)]
                if not matches:
                    raise HTTPException(422, f'未找到技能：{selection.name}')
                if len(matches) > 1:
                    raise HTTPException(422, '存在同名技能入口，请指定对应目录后导入。')
                candidate = matches[0]
                target_name = selection.import_name or candidate['name']
                description = selection.description.strip() if selection.description is not None else candidate['description']
                files = file_entries(candidate['path'])
                fingerprint = import_fingerprint(candidate['path'], package_root)
                condition = import_filter(user)
                statement = select(SkillPackage).where(SkillPackage.name == target_name)
                if condition is not None:
                    statement = statement.where(condition)
                package = session.scalar(statement)
                if package is not None and package.source == 'builtin':
                    raise HTTPException(422, f'「{target_name}」是内置技能名，请在确认页修改名称后导入副本。')
                status = 'created'
                if package is None:
                    package = SkillPackage(
                        id=str(uuid4()), name=target_name, description=description,
                        source='imported', owner_id=owner, is_readonly=True,
                        created_at=now(), updated_at=now(),
                    )
                    session.add(package)
                    session.flush()
                else:
                    if package.owner_id != owner:
                        raise HTTPException(409, '该名称已被其他账号的技能包占用，请改名或使用“复制为副本”。')
                    status = 'version_added'
                    current = session.get(SkillVersion, package.current_version_id) if package.current_version_id else None
                    if current and current.content_sha256 == fingerprint:
                        if description:
                            package.description = description
                        created.append({'id': package.id, 'name': package.name, 'status': 'unchanged',
                                        'version': version_view(current)})
                        continue
                label = unique_version_label(session, package, candidate['version_label'], fingerprint)
                version = install_version(session, directory, package, candidate['path'], label,
                                          selection.compile_level, owner, bundle_root=package_root,
                                          entry_path=candidate['entry_path'])
                package.description = description or package.description
                package.updated_at = now()
                if package.current_version_id is None:
                    package.current_version_id = version.id
                    status = 'created'
                created.append({'id': package.id, 'name': package.name, 'status': status,
                                'version': version_view(version)})
            session.flush()
    except IntegrityError:
        raise HTTPException(409, '同名技能已存在，请刷新后重试。') from None
    shutil.rmtree(stage, ignore_errors=True)
    return created


def _frontmatter_value(value: str) -> str:
    cleaned = ' '.join(str(value).split())
    return '"' + cleaned.replace('"', "'") + '"'


def import_text_package(directory: Path, engine, data: TextInput) -> dict:
    """Create a normal immutable package from a single plain-text skill."""
    name = data.name.strip()
    content = data.content.strip()
    try:
        metadata = parse_frontmatter(content)
    except ImportRejected as error:
        raise HTTPException(422, str(error)) from None
    if metadata:
        lines = content.splitlines()
        end = next(i for i in range(1, len(lines)) if lines[i].strip() == '---')
        content = '\n'.join(lines[end + 1:]).strip()
        if not content:
            raise HTTPException(422, '技能正文不能为空。')
    version_info = metadata.get('metadata') if isinstance(metadata.get('metadata'), dict) else {}
    source_version = str(version_info.get('version') or metadata.get('version') or '1.0.0')
    supplied = ' '.join(data.description.split())[:1000]
    user = principal.get()
    owner = user['id'] if user else None
    stage = imports_root(directory) / str(uuid4())
    package_root = stage / 'package'
    try:
        with Session(engine) as session, session.begin():
            condition = import_filter(user)
            statement = select(SkillPackage).where(SkillPackage.name == name)
            if condition is not None:
                statement = statement.where(condition)
            package = session.scalar(statement)
            if package is not None and package.source == 'builtin':
                raise HTTPException(422, '内置技能名已保留，请换一个名称，或先复制内置技能为副本。')
            if package is not None and package.owner_id != owner:
                raise HTTPException(409, '该名称已被其他账号占用，请换一个名称。')
            # Keep the existing description when a re-import omits it, so identical
            # content stays byte-identical instead of producing a spurious version.
            description = supplied or str(metadata.get('description') or '') or (package.description if package else '')
            if not description:
                description = ' '.join(content.splitlines()[0].split()).lstrip('#').strip()[:200]
            markdown = (
                '---\n'
                f'name: {_frontmatter_value(name)}\n'
                f'description: {_frontmatter_value(description)}\n'
                f'metadata:\n  version: {_frontmatter_value(source_version)}\n'
                '---\n\n'
                f'{content}\n'
            )
            package_root.mkdir(parents=True, exist_ok=True)
            (package_root / 'SKILL.md').write_text(markdown, encoding='utf-8')
            fingerprint = content_fingerprint(file_entries(package_root))
            status = 'created'
            if package is None:
                package = SkillPackage(
                    id=str(uuid4()), name=name, description=description, source='text',
                    owner_id=owner, is_readonly=True, created_at=now(), updated_at=now(),
                )
                session.add(package)
                session.flush()
            else:
                status = 'version_added'
                current = session.get(SkillVersion, package.current_version_id) if package.current_version_id else None
                if current and current.content_sha256 == fingerprint:
                    return {'id': package.id, 'name': package.name, 'status': 'unchanged',
                            'version': version_view(current)}
            label = unique_version_label(session, package, source_version, fingerprint)
            version = install_version(session, directory, package, package_root, label,
                                      data.compile_level, owner, note='文本技能导入')
            package.description = description or package.description
            package.updated_at = now()
            if package.current_version_id is None:
                package.current_version_id = version.id
                status = 'created'
            return {'id': package.id, 'name': package.name, 'status': status,
                    'version': version_view(version)}
    except IntegrityError:
        raise HTTPException(409, '同名技能已存在，请刷新后重试。') from None
    finally:
        shutil.rmtree(stage, ignore_errors=True)


def seed_builtin(engine, directory: Path, source_root: Path | None = None, level: str = 'core') -> int:
    """Idempotently install bundled skills.  Matching content is skipped, never overwritten."""
    root = source_root or Path(__file__).resolve().parents[1] / 'resources' / 'builtin-skills'
    if not root.is_dir():
        return 0
    count = 0
    with Session(engine) as session, session.begin():
        for candidate in find_skill_roots(root):
            files = file_entries(candidate['path'])
            fingerprint = content_fingerprint(files)
            package = session.scalar(select(SkillPackage).where(SkillPackage.name == candidate['name'],
                                                               SkillPackage.source == 'builtin'))
            if package is not None:
                current = session.get(SkillVersion, package.current_version_id) if package.current_version_id else None
                if current and current.content_sha256 == fingerprint:
                    continue
            if package is None:
                package = SkillPackage(id=str(uuid4()), name=candidate['name'],
                                       description=candidate['description'], source='builtin',
                                       owner_id=None, is_readonly=True, created_at=now(), updated_at=now())
                session.add(package)
                session.flush()
            label = candidate['version_label'] or '0.0.0'
            if session.scalar(select(SkillVersion).where(SkillVersion.skill_id == package.id,
                                                        SkillVersion.version_label == label)):
                label = f'{label}-{fingerprint[:8]}'
            version = install_version(session, directory, package, candidate['path'], label[:64], level, None,
                                      note='内置技能，随应用发布')
            if package.current_version_id is None:
                package.current_version_id = version.id
            package.updated_at = now()
            count += 1
    return count


def build_skill_router(engine, directory: Path) -> APIRouter:
    router = APIRouter(prefix='/api/skill-packages', tags=['skill-packages'])

    def require_db():
        if engine is None:
            raise HTTPException(503, '技能包需要配置数据库并执行迁移。')

    def get_package(skill_id: UUID) -> SkillPackage:
        with Session(engine) as session:
            row = session.get(SkillPackage, str(skill_id))
        if row is None or not can_view(row, principal.get()):
            raise HTTPException(404, '技能包不存在。')
        return row

    def get_version(row: SkillPackage, version_id: str) -> SkillVersion:
        with Session(engine) as session:
            version = session.get(SkillVersion, version_id)
            if version is None or version.skill_id != row.id:
                raise HTTPException(404, '技能版本不存在。')
            return version

    @router.get('')
    def list_packages():
        require_db()
        with Session(engine) as session:
            statement = select(SkillPackage).order_by(SkillPackage.updated_at.desc())
            condition = scope_filter(principal.get())
            if condition is not None:
                statement = statement.where(condition)
            rows = session.scalars(statement).all()
            return [package_view(session, row) for row in rows]

    @router.get('/limits')
    def limits():
        return {**SCHEMA_LIMITS, 'compile_levels': ['core', 'full'],
                'rules': ['直接上传现有资料，自动识别或确认入口', '名称与用途可在确认页补充', '导入后只读',
                          '脚本只存档不执行', '内置技能名保留，个人技能不能覆盖',
                          '个人技能包仅创建者可见、可启用；管理员可只读查看',
                          '文本技能会生成单文件 SKILL.md，后续修改作为新版本',
                          '同名个人技能作为新版本，需手动启用']}

    @router.post('/import')
    def import_package(request: Request,
                       archive: Annotated[UploadFile | None, File()] = None,
                       files: Annotated[list[UploadFile], File()] = [],
                       paths: Annotated[str, Form(max_length=200000)] = '',
                       entry_path: Annotated[str, Form(max_length=2048)] = ''):
        require_db()
        cleanup_imports(directory)
        upload_id = str(uuid4())
        stage = imports_root(directory) / upload_id
        target = stage / 'package'
        try:
            if archive is not None:
                data = archive.file.read(MAX_PACKAGE_BYTES + 1)
                if len(data) > MAX_PACKAGE_BYTES:
                    raise ImportRejected('压缩包不能超过 20 MB。')
                extract_archive(data, target)
            else:
                try:
                    values = json.loads(paths) if paths else []
                    if not isinstance(values, list) or len(values) != len(files):
                        raise ValueError()
                except ValueError:
                    raise HTTPException(422, '文件夹导入参数无效，请重新选择。') from None
                write_uploads(target, [(path, upload.file.read(MAX_PACKAGE_BYTES + 1)) for path, upload in zip(values, files)])
            if entry_path.strip():
                wrap_entry(target, entry_path.strip())
            elif not find_skill_roots(target):
                entries = [path for path in walk_files(target)
                           if PurePosixPath(path).suffix.lower() in {'.md', '.markdown', '.txt'}]
                if len(entries) == 1:
                    wrap_entry(target, entries[0])
            user = principal.get()
            (stage / 'owner.json').write_text(json.dumps({'owner': user['id'] if user else None}), encoding='utf-8')
        except ImportRejected as error:
            shutil.rmtree(stage, ignore_errors=True)
            raise HTTPException(422, str(error)) from None
        return build_preview(directory, engine, upload_id)

    @router.post('/import/entry')
    def choose_entry(data: EntryInput):
        require_db()
        stage = imports_root(directory) / str(data.upload_id)
        target = stage / 'package'
        if not target.is_dir():
            raise HTTPException(404, '导入会话不存在或已过期，请重新上传。')
        check_import_owner(stage)
        try:
            if not find_skill_roots(target):
                wrap_entry(target, data.path)
        except ImportRejected as error:
            raise HTTPException(422, str(error)) from None
        return build_preview(directory, engine, str(data.upload_id))

    @router.post('/import/confirm')
    def confirm(data: ConfirmInput):
        require_db()
        return confirm_import(directory, engine, data)

    @router.post('/import/text')
    def import_text(data: TextInput):
        require_db()
        return import_text_package(directory, engine, data)

    @router.get('/{skill_id}')
    def get_one(skill_id: UUID):
        require_db()
        with Session(engine) as session:
            row = session.get(SkillPackage, str(skill_id))
            if row is None or not can_view(row, principal.get()):
                raise HTTPException(404, '技能包不存在。')
            return package_view(session, row)

    @router.get('/{skill_id}/versions')
    def list_versions(skill_id: UUID):
        require_db()
        with Session(engine) as session:
            row = session.get(SkillPackage, str(skill_id))
            if row is None or not can_view(row, principal.get()):
                raise HTTPException(404, '技能包不存在。')
            rows = session.scalars(select(SkillVersion).where(SkillVersion.skill_id == row.id)
                                   .order_by(SkillVersion.created_at.desc())).all()
            return [{**version_view(item), 'is_current': item.id == row.current_version_id} for item in rows]

    @router.post('/{skill_id}/versions/{version_id}/activate')
    def activate(skill_id: UUID, version_id: UUID):
        require_db()
        user = principal.get()
        with Session(engine) as session, session.begin():
            row = session.get(SkillPackage, str(skill_id), with_for_update=True)
            if row is None or not can_view(row, user):
                raise HTTPException(404, '技能包不存在。')
            if not can_activate(row, user):
                raise HTTPException(403, '内置技能版本只能由管理员启用；个人技能版本只能由创建者启用。')
            version = session.get(SkillVersion, str(version_id))
            if version is None or version.skill_id != row.id:
                raise HTTPException(404, '技能版本不存在。')
            row.current_version_id = version.id
            row.updated_at = now()
            return package_view(session, row)

    @router.get('/{skill_id}/versions/{version_id}/files')
    def list_files(skill_id: UUID, version_id: UUID):
        require_db()
        package = get_package(skill_id)
        version = get_version(package, str(version_id))
        with Session(engine) as session:
            rows = session.scalars(select(SkillFile).where(SkillFile.version_id == version.id)
                                   .order_by(SkillFile.path)).all()
            _, resources = bundle_resources(directory, package.id, version.id)
            return {'version': version_view(version), 'resources': resources,
                    'files': [{'path': row.path, 'kind': row.kind, 'size': row.size,
                               'sha256': row.sha256, 'is_text': row.is_text} for row in rows]}

    @router.get('/{skill_id}/versions/{version_id}/resources/{path:path}')
    def get_resource(skill_id: UUID, version_id: UUID, path: str, download: bool = False):
        require_db()
        package = get_package(skill_id)
        version = get_version(package, str(version_id))
        root, files = bundle_resources(directory, package.id, version.id)
        if root is None or not any(item['path'] == path for item in files):
            raise HTTPException(404, '同包资源不存在。')
        if not download:
            try:
                return read_text(root, path)
            except ImportRejected as error:
                raise HTTPException(415, str(error)) from None
        return FileResponse(safe_join(root, path), media_type='application/octet-stream',
                            filename=PurePosixPath(path).name,
                            headers={'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff'})

    @router.get('/{skill_id}/versions/{version_id}/files/{path:path}')
    def get_file(skill_id: UUID, version_id: UUID, path: str, download: bool = False):
        require_db()
        package = get_package(skill_id)
        version = get_version(package, str(version_id))
        with Session(engine) as session:
            row = session.get(SkillFile, (version.id, path))
            if row is None:
                raise HTTPException(404, '技能文件不存在。')
        root = version_root(directory, package.id, version.id) / 'raw'
        target = safe_join(root, path)
        if not target.is_file():
            raise HTTPException(404, '技能文件缺失，请重新导入。')
        if row.is_text and not download:
            try:
                return read_text(root, path)
            except ImportRejected as error:
                raise HTTPException(422, str(error)) from None
        suffix = PurePosixPath(path).suffix.lower()
        inline = not download and row.kind == 'asset' and suffix in ('.png', '.jpg', '.jpeg', '.webp')
        if not inline and not download:
            raise HTTPException(415, '该文件只能下载，不能在页面中预览。')
        media = f'image/{suffix.lstrip(".")}' if inline else 'application/octet-stream'
        return FileResponse(target, media_type=media,
                            filename=None if inline else f'skill-{version.version_label}-{PurePosixPath(path).name}',
                            headers={'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff'})

    @router.post('/{skill_id}/fork')
    def fork(skill_id: UUID, version_id: UUID | None = None):
        require_db()
        user = principal.get()
        owner = user['id'] if user else None
        with Session(engine) as session, session.begin():
            source = session.get(SkillPackage, str(skill_id))
            if source is None or not can_view(source, user):
                raise HTTPException(404, '技能包不存在。')
            source_version = session.get(SkillVersion, str(version_id)) if version_id else (
                session.get(SkillVersion, source.current_version_id) if source.current_version_id else None)
            if source_version is None or source_version.skill_id != source.id:
                raise HTTPException(404, '技能版本不存在。')
            base = f'{source.name} 副本'
            name, index = base[:200], 2
            while name_taken(session, name, owner):
                suffix = f' {index}'
                name = base[:200 - len(suffix)] + suffix
                index += 1
            package = SkillPackage(id=str(uuid4()), name=name, description=source.description,
                                   source='forked', owner_id=owner,
                                   is_readonly=True, created_at=now(), updated_at=now())
            session.add(package)
            session.flush()
            origin = version_root(directory, source.id, source_version.id)
            target = version_root(directory, package.id, str(uuid4()))
            copy_tree(origin / 'raw', target / 'raw')
            copy_tree(origin / 'compiled', target / 'compiled')
            if (origin / 'bundle.json').is_file():
                shutil.copyfile(origin / 'bundle.json', target / 'bundle.json')
            version = SkillVersion(
                id=target.name, skill_id=package.id, version_label=source_version.version_label,
                status='ready', compile_level=source_version.compile_level,
                content_sha256=source_version.content_sha256, compiled_sha256=source_version.compiled_sha256,
                compiled_chars=source_version.compiled_chars, file_count=source_version.file_count,
                total_bytes=source_version.total_bytes, entry_path=source_version.entry_path,
                created_at=now(), created_by=owner,
                import_note=f'复制自 {source.name}',
            )
            session.add(version)
            for row in session.scalars(select(SkillFile).where(SkillFile.version_id == source_version.id)):
                session.add(SkillFile(version_id=version.id, path=row.path, kind=row.kind,
                                      size=row.size, sha256=row.sha256, is_text=row.is_text))
            package.current_version_id = version.id
            session.flush()
            return package_view(session, package)

    return router
