"""Versioned art direction, subordinate to confirmed facts and loaded skills."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

STYLE_VERSION = '1.0.1'
PRESETS = [
    {'id': 'auto', 'name': 'AI 根据产品推荐', 'description': '先理解产品与购买主题，再提出适合整套图的视觉方向。',
     'rules': '结合产品、受众和图型推荐主风格，在 art_direction 说明选择理由；图需由用户确认后才进入提示词。不要默认黄色背景或卡片拼图。'},
    {'id': 'immersive', 'name': '沉浸场景', 'description': '环境铺满画面，前中后景建立纵深，文案顺着场景留白。',
     'rules': '以完整可信环境承载产品，明确前景、中景、背景和视觉动线；主次有序，标题融入自然留白，避免顶部横条加等分卡片。细节证据图可按职责分区。'},
    {'id': 'editorial', 'name': '品牌杂志', 'description': '非对称构图、大标题与精细字体层级，形成编辑设计感。',
     'rules': '采用有节奏的非对称网格、主次字号与图文穿插，产品或场景占据视觉重心；区分标题、副标题、证据说明。逐张变化主体和文字位置，不套同一双栏。'},
    {'id': 'cinematic', 'name': '电影叙事', 'description': '用光影、景深与镜头讲故事，少量文字强化主题。',
     'rules': '用具有叙事目的的机位、景深及合理光影构建场景，保留商品真实颜色与结构；文字有焦点且避开主体。不同主题采用不同景别，不用调色遮盖产品证据。'},
    {'id': 'technical', 'name': '科技解析', 'description': '特写、引线和细节证据，清楚表达结构与功能。',
     'rules': '产品结构或使用细节为视觉中心，使用克制的引线、局部放大与清晰标注层级；引线准确指向可见证据，不臆造内部结构、参数或认证。不强制蓝色、发光特效或拆解。'},
    {'id': 'minimal', 'name': '极简高端', 'description': '突出产品、克制用色与文案，让留白服务视觉重心。',
     'rules': '用鲜明的产品占比、精准光影和材质表现建立品质，留白有明确阅读用途；文案精炼而不删关键条件。背景依据商品与品牌选择，不默认白底、米黄或暖白。'},
    {'id': 'informative', 'name': '高信息说明', 'description': '步骤、对比与局部证据分层组织，复杂信息也易读。',
     'rules': '按步骤、对照或证据层级组织信息，一张一个主要购买主题；主视觉与辅助视图有主次。明确阅读顺序，避免所有信息等大堆砌；只比较已确认事实，不编造竞品差异。'},
]


class VisualStyle(BaseModel):
    model_config = ConfigDict(extra='forbid')
    preset: Literal['auto', 'immersive', 'editorial', 'cinematic', 'technical', 'minimal', 'informative'] = 'auto'
    variation: Literal['steady', 'balanced', 'rich'] = 'balanced'
    density: Literal['low', 'medium', 'high'] = 'medium'
    palette: str = Field(default='', max_length=1000)


def snapshot_style(selection):
    if selection is None:
        return None
    value = VisualStyle.model_validate(selection).model_dump()
    preset = next(item for item in PRESETS if item['id'] == value['preset'])
    variation = {
        'steady': '统一稳重：保留相同网格语言，按图型调整主体、景别或文字位置，避免机械重复。',
        'balanced': '适度变化：相邻图至少在主体位置、镜头景别、文字位置、信息组织中改变两项；统一字体、品牌图形和修图质感。',
        'rich': '丰富变化：按主题交替使用场景、特写、对照和叙事等适用图型；相邻图显著变化三项构图要素，仍保持品牌一致，不为变化编造结构或场景功能。',
    }[value['variation']]
    density = {
        'low': '少文字：一个主标题和必要短说明，精简装饰性措辞。',
        'medium': '适中文字：主标题、简短收益及必要证据说明，层级分明。',
        'high': '多信息：采用明确分组与阅读路径，主视觉优先，不缩小文字塞满画面。',
    }[value['density']]
    policy = ('图型优先：Listing套图主图只完整展示产品，无新增文案、图标或装饰模块，背景依用户确认；下述文字密度、标题和图形排版仅用于允许带文案的附图与A+，不适用于主图。'
        '风格只控制视觉表达，不提供产品事实。必须读取并遵循锁定技能及其必读资源；SKU、已确认事实、'
        '文案数字和关键条件优先。用户明确的补充要求优先于预设默认，冲突在图需 notes 说明并待确认。'
        '配色独立于风格：未指定时按品牌、产品与环境选择，不默认黄色、米黄、象牙白或全套同底色；不改变商品本色。'
        '统一字体家族、品牌语言和修图质感，每张 layout 明确主体占比/位置、视觉动线、文字层级与位置、'
        '场景深度或证据组织，并在 notes 写明与相邻图的区别。文字密度不允许删除已确认的数字、警示或适用条件。')
    checks = ['主体构图与选定风格一致', '标题、正文和证据层级清晰，手机预览可读',
        '场景纵深或结构证据符合本图职责', '商品本色、SKU、数字与关键条件保持准确',
        '整套字体与品牌一致，逐张构图有区别（需整套人工检查）']
    return {'version': STYLE_VERSION, 'selection': value, 'name': preset['name'],
        'rules': '\n'.join([policy, preset['rules'], variation, density,
            '图形配色要求：' + (value['palette'] or '由产品、品牌和场景决定；在图需中说明。')]), 'checks': checks}


def layout_warnings(shots):
    """Mechanical reminders only; never claim visual approval."""
    warnings, seen = [], {}
    for shot in shots:
        layout = ''.join(shot.get('layout', '').split()).lower()
        if not layout:
            warnings.append(f'{shot["name"]}：尚未填写构图与文字布局。')
        elif layout in seen:
            warnings.append(f'{shot["name"]}：构图说明与「{seen[layout]}」完全相同，请检查是否套版。')
        else:
            seen[layout] = shot['name']
    return warnings
