"""Pinned, purpose-specific skill instructions for every production image."""
import json
import re
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import SkillPackage, SkillVersion, ImageJob
from app.skill_packages import seed_builtin, version_root
from app.skill_store import read_text, ImportRejected

DEFAULT_SKILL = 'premium-product-image-workflow'
COMMON_FILES = ('SKILL.md', 'references/prompt-writing-standard.md',
                'references/prompt-composition.md', 'references/quality-gate.md')
PURPOSE_FILES = {
    'main-image': ('references/listing-image-requirements.md',),
    'scene': ('references/layout-design.md', 'references/reference-image-governance.md'),
    'detail': ('references/layout-design.md',),
    'aplus': ('references/mobile-adaptation.md', 'references/copy-review.md'),
    'general': (),
}


def purpose_for(prompt: str) -> str:
    if prompt in PURPOSE_FILES:
        return prompt
    if re.search(r'a\s*(?:\+|＋|plus|[- ]plus)', prompt, re.I):
        return 'aplus'
    if re.search(r'主图|main image', prompt, re.I):
        return 'main-image'
    if re.search(r'细节|detail', prompt, re.I):
        return 'detail'
    if re.search(r'场景|庭院|scene|garden|lifestyle', prompt, re.I):
        return 'scene'
    return 'general'


def select_skill(engine, directory: Path, owner, selection: dict | None = None,
                 inherited: dict | None = None) -> dict:
    if selection and 'mode' in selection:
        selection = next(iter(selection.get('skills', [])), None)
    if not selection and inherited:
        selection = {'skill_id': inherited['skill_id'], 'version_id': inherited['version_id']}
    selection = selection or {}
    with Session(engine) as session:
        default = session.scalar(select(SkillPackage).where(SkillPackage.name == DEFAULT_SKILL,
                                                            SkillPackage.source == 'builtin'))
    if default is None:
        seed_builtin(engine, directory)
    with Session(engine) as session:
        package = (session.get(SkillPackage, selection['skill_id']) if selection.get('skill_id') else
                   session.scalar(select(SkillPackage).where(SkillPackage.name == DEFAULT_SKILL,
                                                             SkillPackage.source == 'builtin')))
        if package is None or (package.source != 'builtin' and package.owner_id is not None and package.owner_id != owner):
            raise HTTPException(422, '请选择本人或内置的制作技能。')
        version_id = selection.get('version_id') or package.current_version_id
        version = session.get(SkillVersion, version_id) if version_id else None
        if version is None or version.skill_id != package.id:
            raise HTTPException(422, '制作技能没有可用版本，请先在技能库启用版本。')
        return {'skill_id': package.id, 'version_id': version.id, 'name': package.name,
                'description': package.description, 'version': version.version_label, 'sha256': version.content_sha256}


def snapshot_for(engine, directory: Path, owner, prompt: str, selection=None, inherited=None, purpose_hint='') -> dict:
    if not selection and inherited and 'catalog' in inherited:
        return {**inherited, 'purpose': purpose_for(purpose_hint or prompt)}
    primary = select_skill(engine, directory, owner, selection, inherited)
    purpose = purpose_for(purpose_hint)
    if purpose == 'general':
        purpose = purpose_for(prompt)
    explicit = selection.get('skills', []) if selection and 'mode' in selection else [selection] if selection else []
    pinned = [select_skill(engine, directory, owner, item) for item in explicit]
    allow_auto = selection.get('allow_auto', True) if selection and 'mode' in selection else not bool(explicit)
    catalog = []
    if allow_auto:
        with Session(engine) as session:
            rows = session.scalars(select(SkillPackage).where(SkillPackage.current_version_id.is_not(None),
                (SkillPackage.source == 'builtin') | SkillPackage.owner_id.is_(None) | (SkillPackage.owner_id == owner)))
            choices = [{'skill_id': row.id, 'version_id': row.current_version_id} for row in rows]
        catalog = [select_skill(engine, directory, owner, item) for item in choices]
    catalog = list({item['skill_id']: item for item in [*catalog, *pinned]}.values())
    if not catalog:
        raise HTTPException(422, '没有可用制作技能，请先导入并启用技能。')
    return {'primary': primary, 'companions': [], 'purpose': purpose, 'catalog': catalog,
            'pinned': [item['skill_id'] for item in pinned], 'allow_auto': allow_auto,
            'selection_mode': 'manual' if pinned else 'auto'}


def inherit_companions(snapshot: dict, previous: dict) -> dict:
    old = {item['skill_id']: item for item in previous.get('companions', [])}
    return {**snapshot, 'companions': [old.get(item['skill_id'], item) for item in snapshot.get('companions', [])]}


def run_snapshot(engine, directory, run, prompt=None, source_job_id=None):
    previous = {}
    with Session(engine) as session:
        source = session.get(ImageJob, source_job_id or run.source_job_id) if source_job_id or run.source_job_id else None
        if source:
            previous = json.loads(source.execution_profile or '{}').get('skill_workflow', {})
    hint = run.instruction
    if purpose_for(hint) == 'general':
        hint = previous.get('purpose') or purpose_for(run.goal)
    snapshot = snapshot_for(engine, directory, run.owner_id, prompt or run.goal + '\n' + run.instruction,
                            selection={'skill_id': run.skill_id, 'version_id': run.skill_version_id}, purpose_hint=hint)
    return inherit_companions(snapshot, previous)


def skill_context(directory: Path, snapshot: dict) -> tuple[str, list[dict]]:
    """Legacy entry context only; new production uses the SDK's progressive loader."""
    pieces, sources = [], []
    for skill in [snapshot['primary'], *snapshot.get('companions', [])]:
        root = version_root(directory, skill['skill_id'], skill['version_id']) / 'raw'
        paths = ['SKILL.md']
        for path in dict.fromkeys(paths):
            try:
                value = read_text(root, path, 0, 24000)
            except (ImportRejected, OSError, ValueError):
                if path == 'SKILL.md':
                    raise HTTPException(422, '已锁定的技能入口文件缺失，未调用图片接口。') from None
                continue
            content = value['content']
            while value['truncated']:
                if len(content) > 80000:
                    raise HTTPException(422, '技能参考文件过长，请精简后再制作。')
                value = read_text(root, path, len(content), 20000)
                content += value['content']
            pieces.append(f'\n技能 {skill["name"]} {skill["version"]} / {path}\n{content}')
            sources.append({'skill_id': skill['skill_id'], 'version_id': skill['version_id'], 'path': path})
    text = '\n'.join(pieces)
    if len(text) > 80000:
        raise HTTPException(422, '本次技能规范过长，请精简技能文件后再制作。')
    return text, sources
