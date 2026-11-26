"""Deterministic tools ported from premium-product-image-workflow scripts.

These replace running the skill's Python files: same checks, no subprocess, no network,
no access to secrets.  They are intentionally model-free.
"""
from __future__ import annotations

import json
import re
from pathlib import Path


def _has(text: str, pattern: str) -> bool:
    return bool(re.search(pattern, text, flags=re.IGNORECASE | re.DOTALL))


def _affirmative_matches(text: str, pattern: str):
    """Ignore explicit prohibitions, stopping their scope at a new clause.

    This is a lexical check, not an interpretation of arbitrary English. In
    particular, 'do not recreate from scratch' must not mean 'recreate'.
    """
    for match in re.finditer(pattern, text, flags=re.IGNORECASE):
        prefix = re.split(r'[.!?;:\n,]|\b(?:but|however|then|instead|and)\b',
                          text[:match.start()], flags=re.IGNORECASE)[-1]
        if re.search(r"\b(?:do\s+not|don['’]t|must\s+not|should\s+not|never|without|avoid|no)\b(?!\s+only\b)[^.\n]{0,100}$",
                     prefix, flags=re.IGNORECASE):
            continue
        if re.match(r'\s+(?:is|are)\s+(?:forbidden|prohibited|not allowed)\b',
                    text[match.end():], flags=re.IGNORECASE):
            continue
        yield match


def lint_prompt(text: str, route: str = 'general') -> list[dict]:
    """Ported from scripts/lint_product_prompt.py: text-detectable risks only."""
    issues: list[dict] = []

    def add(severity: str, message: str) -> None:
        issues.append({'severity': severity, 'message': message})

    placeholders = sorted({value for value in re.findall(r'\[[^\]\n]{1,100}\]', text)
                           if not re.fullmatch(r'\[\s*-?\d+(?:\.\d+)?(?:\s*,\s*-?\d+(?:\.\d+)?)*\s*\]', value)})
    if placeholders:
        add('error', f'Unfilled bracket variables: {", ".join(placeholders[:8])}')
    if _has(text, r'exact (same )?(sellable )?sku|strict product identity') and not _has(text, r'reference\s*1|product identity reference'):
        add('warning', 'SKU-lock language appears without a named product identity reference.')
    if route == 'local-edit':
        if not _has(text, r'\bedit only\b'):
            add('warning', "Local-edit route normally begins with 'Edit only [precise target]'.")
        if any(_affirmative_matches(text, r'\bfrom scratch\b|\bentirely new\b|\bcompletely redesign\b')):
            add('error', 'Local-edit route conflicts with a from-scratch or full-redesign instruction.')
    if route == 'main-image':
        if _has(text, r'\b(add|include|place)\b[^.\n]{0,50}\b(text|badge|watermark|border|logo|person|prop)\b'):
            add('error', 'Main-image route asks to add an element that is commonly non-compliant; confirm platform rules and remove it when inappropriate.')
        if not _has(text, r'white background|rgb\s*\(?255\s*,\s*255\s*,\s*255\)?'):
            add('warning', 'Main-image route does not state a clean white background; confirm the target platform requirement.')
    environment_changes = {match.group('target').lower() for match in _affirmative_matches(text,
        r'\b(?:replace|transform|change)\s+(?:only\s+)?(?:the\s+)?(?P<target>background|sky|environment)\b')}
    if any(_affirmative_matches(text, r'\bnew environment\b')):
        environment_changes.add('environment')
    environment_locks = {match.group(1).lower() for match in re.finditer(
        r'\bdo not change (?:the )?(background|sky|environment)\b', text, re.IGNORECASE)}
    environment_locks.update(match.group('target').lower() for match in _affirmative_matches(text,
        r'\bpreserve (?:the )?(?P<target>background|sky|environment) exactly\b'))
    if environment_changes & environment_locks:
        add('error', 'The prompt both changes and locks the background, sky, or environment.')
    if route == 'finished-image':
        sections = (
            'Task and selling objective', 'Reference roles', 'Product identity lock',
            'Scene and camera', 'Composition and hierarchy',
            'Art direction and physical realism', 'Exact copy',
            'Typography and graphic layout', 'Strict exclusions', 'Output',
        )
        missing = [section for section in sections if not _has(text, r'(?m)^\s*' + re.escape(section) + r'\s*:')]
        if missing:
            add('error', 'Finished-image prompt is missing sections: ' + ', '.join(missing))
        base_instructions = (
            r'(?m)^\s*(?:Task:\s*)?(?:create|generate)\b[^.\n]{0,160}\b(?:no-text|text-free|unlettered)\b',
            r'(?m)^\s*(?:do not generate (?:any )?text|leave clean negative space for verified copy|leave all text for|add (?:all )?(?:copy|text) later)\b',
            r'\bcopy to be added later in a deterministic design tool\b',
        )
        if any(_has(text, pattern) for pattern in base_instructions):
            add('error', 'Finished-image route conflicts with instructions to generate an unlettered base or postpone copy.')
        copy_match = re.search(r'(?ims)^\s*Exact copy\s*:(.*?)(?=^\s*Typography and graphic layout\s*:|\Z)', text)
        if copy_match and not re.search(r'["“][^"”]+["”]', copy_match.group(1)):
            add('error', 'Exact copy must contain quoted final text, not instructions to invent suitable copy.')
    elif _has(text, r'\btext\b|\bdimensions?\b|\bcertifications?\b') and not _has(text, r'do not generate|no generated text'):
        add('warning', 'Verify every rendered word, number and unit against confirmed source copy; use finished-image for a complete listing design.')
    if not _has(text, r'\boutput\s*:'):
        add('warning', 'No explicit Output section found for size, ratio, or delivery constraints.')
    return issues


def count_copy(text: str, language: str = 'zh') -> int:
    """Ported from scripts/count-copy.py: internal layout convention, not platform rules."""
    return len(text.split()) if language == 'en' else sum(not char.isspace() for char in text)


HARD_COPY = {
    '待补/待确认/待核': r'待(?:补证?|确认|定|核实?|核验)',
    '未提供类括注': r'[（(][^）)\n]*(?:未提供|未给出|缺失|待提供)[^）)\n]*[）)]',
    'TODO/TBD': r'\b(?:TODO|TBD|FIXME)\b',
    '空占位': r'【\s*】|\[\s*\]|X{3,}|\?{3,}|？{3,}',
}
SOFT_COPY = {
    '内部建议口吻': r'(?:^|[，。；\s])(?:建议|备注|注意)[:：]',
    '此处填写': r'此处(?:填|放|写|补)',
    '暂定/拟定': r'暂(?:定|无|不|未)|拟(?:定|用|补)',
    '含括注，请人工确认不是内部说明': r'[（(][^）)\n]{1,40}[）)]',
}


def scan_copy(text: str) -> dict:
    """Ported from scripts/scan-final-copy.py: lexical check, not a legal review."""
    return {'hard': [name for name, pattern in HARD_COPY.items() if re.search(pattern, text)],
            'soft': [name for name, pattern in SOFT_COPY.items() if re.search(pattern, text)]}


QC_CHECKS = [
    '同一可售 SKU、关键部件数量和连接关系正确',
    '无新增、缺失、重复、替换、拉伸、扭曲或错误透视',
    '材质、颜色、纹理、接缝和五金与参考一致',
    '光源、高光、阴影、反射、环境色和尺度关系可信',
    '商品为视觉中心，且每张图只有一个明确任务',
    '文字、数字、单位、参数和宣称均已确认并可读',
    '主图无文字、图标、徽章、Logo、水印、边框、人物、道具和非售卖物',
    '已按平台规则和适用 AIGC 标识要求复核',
]


def qc_checklist(count: int) -> str:
    if count < 1:
        raise ValueError('图片数量至少为 1。')
    lines = ['# 商品图交付质检表', '']
    for index in range(1, count + 1):
        lines.extend([f'## 图 {index}', '- 名称 / 职责：', '- 输出规格：', '- 已确认数据来源：'])
        lines.extend(f'- [ ] {check}' for check in QC_CHECKS)
        lines.extend(['- 缺陷等级：通过 / P0 / P1 / P2 / P3', '- 返工动作：', ''])
    return '\n'.join(lines)


def scenario_catalog(skill_root: Path, command: str = 'list', identifier: str = '') -> dict | list:
    path = skill_root / 'assets' / 'scenario-catalog.json'
    if not path.is_file():
        raise ValueError('该技能没有场景目录文件。')
    data = json.loads(path.read_text(encoding='utf-8'))
    rows = data.get('scenarios') if isinstance(data, dict) else None
    if not isinstance(rows, list):
        raise ValueError('场景目录格式无法识别。')
    if command == 'show':
        for row in rows:
            if isinstance(row, dict) and row.get('id') == identifier:
                return row
        raise ValueError('未找到该场景。')
    return [{'id': row.get('id'), 'name': row.get('name'), 'keywords': row.get('keywords', [])}
            for row in rows if isinstance(row, dict)]
