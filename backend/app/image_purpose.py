"""Separate Listing product presentation from copy-bearing A+ modules."""
import re


def project_image_type(settings):
    selected = (settings.get('learning') or {}).get('image_type', 'any')
    if selected != 'any':
        return selected
    goal = settings.get('goal', '')
    if re.search(r'a\s*(?:\+|＋|plus|[- ]plus)', goal, re.I):
        return 'a_plus'
    if re.search(r'套图|商品图|产品图|listing', goal, re.I):
        return 'listing'
    return 'any'


def main_shot_ids(settings, brief):
    kind = project_image_type(settings)
    if kind in ('a_plus', 'detail'):
        return set()
    shots = brief.get('shots', [])
    result = {shot['id'] for shot in shots if re.search(r'主图|\bmain[-_ ]?image\b', shot['name'], re.I)}
    if kind == 'listing' and shots:
        result.add(shots[0]['id'])
    return result


def has_image_copy(value):
    return bool(value.strip()) and not re.fullmatch(r'无|无文字|无文案|不加字|none|no text|text-free|n/a|-', value.strip(), re.I)


def main_prompt_has_copy(prompt):
    """Reject explicit rendered-copy instructions, without interpreting natural scenery."""
    if re.search(r'(?im)^\s*exact copy\s*[:：]\s*\n\s*(?:[-*]\s*)?["“][^"”\n]+["”]', prompt):
        return True
    for line in prompt.splitlines():
        match = re.match(r'\s*(?:[-*]\s*)?(?:exact copy|headline|subtitle|标题|副标题|成品文案)\s*[:：]\s*(.+)', line, re.I)
        if match and has_image_copy(match[1].strip(' "“”\'')):
            return True
        if re.search(r'\b(?:no|not|never|without)\b|禁止|不得|不要|不添加', line, re.I):
            continue
        if re.search(r'\b(?:add|render|place|include)\b[^.\n]{0,35}\b(?:text|headline|badge|watermark|caption)\b|(?:添加|绘制|渲染).{0,12}(?:文字|标题|徽章)', line, re.I):
            return True
    return False
