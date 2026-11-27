"""Versioned art direction, subordinate to confirmed facts and loaded skills."""
from typing import Literal

import json
import re

from pydantic import BaseModel, ConfigDict, Field

STYLE_VERSION = '2.1.0'
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

# The contract is frozen in the project, alongside the skill snapshot.
SIGNATURES = {
    'immersive': '环境满幅延伸；前景遮挡、中景产品、远景生活环境形成三层空间；文字落在真实环境负空间，避免独立卡片。',
    'editorial': '非对称编辑网格；标题与产品尺度形成鲜明对比；文字栏与跨栏影像相互穿插，保留有节奏的基线与页边距。',
    'cinematic': '以叙事镜头为中心；明确主光方向、明暗分区和焦点层次；运用广角建立环境、近景展示动作，文字如片头般克制。',
    'technical': '以可见结构证据为中心；主产品配准确引线、局部放大与分级注释；图形服务解释，不虚构拆解或内部结构。',
    'minimal': '单一强焦点；大面积有目的的负空间；精准轮廓光与材质明暗；排版少而精，避免多视图拼贴。',
    'informative': '主视觉优先的步骤、对照或证据序列；明确编号和阅读路径；辅助视图从属于主图，不做等大模块堆叠。',
}


class ShotDesign(BaseModel):
    """Reviewable, editable decisions, not a claim that generated pixels comply."""
    model_config = ConfigDict(extra='forbid')
    style: Literal['immersive', 'editorial', 'cinematic', 'technical', 'minimal', 'informative']
    composition: str = Field(min_length=3, max_length=1200, description='Concrete subject position, frame occupancy and information organization; no generic style adjectives')
    camera: str = Field(min_length=3, max_length=800, description='Shot scale, viewpoint and lens intent')
    depth: str = Field(min_length=3, max_length=800, description='Foreground/midground/background or visible evidence layers')
    lighting: str = Field(min_length=3, max_length=800, description='Key light direction, contrast and material rendering')
    typography: str = Field(min_length=3, max_length=1200, description='Text positions, hierarchy, alignment and reading path; product-only main must say no added text or graphics')
    rationale: str = Field(min_length=3, max_length=1000, description='Why this applies the selected style; name differences from adjacent images or explain a necessary exception')


def validate_designs(shots, snapshot):
    if not snapshot or not snapshot.get('version', '').startswith('2.'):
        return
    selection = snapshot['selection']['preset']
    for shot in shots:
        if not shot.get('design'):
            raise ValueError(f'{shot["name"]}：新版规范需要逐张填写设计方案（构图、镜头、纵深、光线、文字和理由）。')
        design = ShotDesign.model_validate(shot['design'])
        if selection != 'auto' and design.style != selection:
            raise ValueError(f'{shot["name"]}：设计风格与本方案已选风格不一致，请调整后确认。')


DESIGN_START = '\n[Approved visual design v2]\n'
DESIGN_END = '\n[/Approved visual design v2]'


def bind_design_prompts(content, brief, snapshot, main_ids=()):
    """Bind while saving the visible draft, never after user confirmation."""
    if not snapshot or not snapshot.get('version', '').startswith('2.'):
        return content
    shots = {shot['id']: shot for shot in brief['shots']}
    result = []
    for item in content.get('prompts', []):
        shot = shots.get(item['shot_id'])
        if not shot or not shot.get('design'):
            raise ValueError('请先按新版规范重新策划并确认逐张设计方案。')
        prompt = re.sub(re.escape(DESIGN_START) + '.*?' + re.escape(DESIGN_END), '', item['prompt'], flags=re.S).strip()
        design = shot['design']
        block = ('Execute the following user-confirmed visual decisions. Preserve the confirmed product, SKU, facts and exact copy. '
                 'This design contract controls expression only.\n'
                 + json.dumps({'style': design['style'], 'signature': snapshot.get('signatures', {}).get(design['style'], ''),
                     'design': design, 'copy': shot.get('copy', ''), 'layout': shot.get('layout', ''),
                     'campaign_rules': snapshot['rules']}, ensure_ascii=False))
        if item['shot_id'] in main_ids:
            block += '\nProduct-only main image: no added text, icons, badges, people or non-sale props. Confirmed background remains applicable.'
        prompt = prompt + DESIGN_START + block + DESIGN_END
        if len(prompt) > 32000:
            raise ValueError(f'{shot["name"]}：合并已确认设计后提示词超过 32000 字符，请精简正文。')
        result.append({**item, 'prompt': prompt})
    return {**content, 'prompts': result}


class VisualStyle(BaseModel):
    model_config = ConfigDict(extra='forbid')
    preset: Literal['auto', 'immersive', 'editorial', 'cinematic', 'technical', 'minimal', 'informative'] = 'auto'
    variation: Literal['steady', 'balanced', 'rich'] = 'balanced'
    density: Literal['low', 'medium', 'high'] = 'medium'
    palette: str = Field(default='', max_length=1000)
    campaign_treatment: Literal['adaptive', 'scene_editorial', 'light_gold'] = 'adaptive'


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
    campaign = ('套图与A+共用策划方法：先按购买问题安排阅读路径，按请求数量分配产品识别、场景收益、尺寸空间、完整状态对照、'
        '材质结构证据、使用情境、操作步骤和收纳清单等适用模块；不固定十张，不为凑模块虚构卖点。'
        'objective 写购买问题，notes 写模块职责、证据依据、与相邻图的内容差异和手机重排方式。'
        '用完整场景与真实动作建立纵深，大证据视图服务理解；主次分明，不将每页做成相同卡片。'
        '人物/家具比例与落地接触符合当前产品，布网/杆件等内外遮挡遵循原件；不复制案例产品参数。'
        'Listing每张附图独立回答购买问题，主图只完整展示产品，背景按确认要求，不加文字/图形/人物/非售卖道具。'
        'A+模块可连续叙事，桌面默认1464×600，不能将套图换尺寸当作A+策划。'
        '仅A+手机适配从所选最新认可桌面版独立重排4:3，完整状态上下对照、四步可用2×2、清单按实际组数；'
        '在600及375宽检查条件文字，优先换行与重排。Listing保持其确认画幅，不强改横幅或4:3。')
    if value['campaign_treatment'] in ('scene_editorial', 'light_gold'):
        campaign += ('本方案套图附图与A+采用场景画册表达：完整环境、真实尺度与清楚证据形成主次，'
            '场景、结构特写、状态对照、尺寸和步骤依据购买问题交替；字体和图形语言一致，'
            '逐张变化主体位置、镜头和阅读顺序，不机械套卡片。配色按产品品牌和用户要求，不强制白字金线。'
            '把摄影设计写具体：composition说明主体位置/占比、安全区与视觉动线，camera说明高低机位、斜向角度和景别，'
            'depth写前景框景、中景主体、远景任务环境，lighting写真实主光方向、天气与材质反光，typography写自然负空间中的文字落点。'
            '非对称来自视觉权重，不靠倾斜相机或扭曲产品；需要正视的证据图和主图按职责处理。'
            '先让照片本身有视觉中心，不依赖顶部巨型标题和底部三图标；不把同一机位反复换背景当作差异。'
            '产品参考控制身份和结构，不默认锁死原参考的机位与环境；落地接触、活动空间、人物车辆尺度与统一光照须可信。')
    if value['campaign_treatment'] == 'light_gold':
        campaign += ('仅允许带文案的附图/A+采用案例图形样式：浅色/白色标题置于环境深色负空间，细金线仅用于小图标、'
            '引线和少量分隔，少量大细节窗；统一字体而逐张变化构图和景别。不是黄色底图或商品染色，'
            '不默认米黄卡片、全幅色罩或每页同一双栏。明确用户配色、风格与可读性要求优先。')
    checks += ['套图附图/A+：购买问题与模块职责清楚，复用卖点须新增证据或决策信息',
        '主图无新增文字图形；附图/A+人物尺度、落地接触和部件遮挡正确，小屏文字可读（不可见处如实标记）']
    return {'version': STYLE_VERSION, 'selection': value, 'name': preset['name'], 'signatures': dict(SIGNATURES),
        'rules': '\n'.join([policy, preset['rules'], variation, density,
            '新版逐图设计：每张填写 design，明确 style、composition、camera、depth、lighting、typography、rationale；自动推荐也必须选定具体风格。固定风格不能被模型换成其他风格。主图不添加文字或装饰；其 typography 明确无新增文字与图形。',
            '风格执行特征：' + (SIGNATURES.get(value['preset']) or '根据产品和主题选择具体风格，并逐张说明选择理由。'),
            '图形配色要求：' + (value['palette'] or '由产品、品牌和场景决定；在图需中说明。'),
            campaign]), 'checks': checks}


def layout_warnings(shots):
    """Mechanical reminders only; never claim visual approval."""
    warnings, seen = [], {}
    previous = None
    for shot in shots:
        layout = ''.join(shot.get('layout', '').split()).lower()
        if not layout:
            warnings.append(f'{shot["name"]}：尚未填写构图与文字布局。')
        elif layout in seen:
            warnings.append(f'{shot["name"]}：构图说明与「{seen[layout]}」完全相同，请检查是否套版。')
        else:
            seen[layout] = shot['name']
        design = shot.get('design')
        if design and previous:
            repeated = [key for key in ('composition', 'camera', 'typography', 'depth') if ''.join(design[key].split()).lower() == ''.join(previous[key].split()).lower()]
            if len(repeated) >= 3:
                warnings.append(f'{shot["name"]}：与相邻图有 {len(repeated)} 项设计说明相同，检查构图节奏并说明必要原因。')
        if design: previous = design
    return warnings
