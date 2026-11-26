# 完整成品提示词写作规范

## 默认交付与事实边界

Amazon 附图、卖点图和 A+ 默认直接生成带文案、字体层级、信息模块和排版的最终成品。不能用无文字底图或“以后加字”代替用户要求的成品。Listing 套图首张主图独立处理：仅完整展示同一商品，无新增广告字、标题、卖点或图形装饰，无人物与非售卖道具；背景按用户确认，非白底也仍无新增文字。保留产品自带真实标识，不给主图套用下方附图的 Exact copy / Typography 模板。A+ 首张可为带文案的场景英雄图，不等同于 Listing 主图。用户明确要求底图时才采用底图路线。工具不支持直接成品时说明实际限制，不静默切换为先底图后拼字。

先区分已确认事实、视觉创作意图、不可改变项、未确认事实。竞品用于确定购买问题、视觉证据和信息层级，不提供本 SKU 的尺寸、性能或文案事实。未知数据直接省略，不在可调用提示词中留占位符。已确认文字进入成品提示词，不表示生成结果自动正确。

## 1. 从制作卡到实际调用

写本图前按 [提示词编排](prompt-composition.md) 选取已通过卖点、实际参考和布局区域；[排版设计](layout-design.md) 用于落实信息预算、字体层级和移动端目标。以下十段式继续作为唯一成品格式。

每张附图先有完整制作卡，然后逐项映射：

| 制作卡字段 | 必须进入同一条成品提示词 |
|---|---|
| 购买问题与卖点 | 本图唯一职责、可见证据及其与标题的关系 |
| 产品身份 | 参考图编号、部件名称/数量/连接关系、比例、颜色、材料外观、易漂移部件 |
| 场景与镜头 | 地点、时段、天气、活动、景别、角度、商品画幅占比、背景层次、道具边界 |
| 风格 | 品牌视觉气质、色板、对比度、光向、反射、材质、修图程度 |
| 构图与版式 | 主体和信息区位置、阅读顺序、模块数、对齐、边距、禁止遮挡的部件 |
| 文案 | 标题、副标题、标签、免责声明逐字原文，换行和大小写 |
| 字体与图形 | 标题/正文风格、相对字号、字重、字色、卡片、引线/图标与证据的对应关系 |
| 输出与限制 | 单张完整成品、比例、目标尺寸、文件格式；未确认宣称与结构改动禁止项 |

不得只写“premium”“same product”“add suitable text”或“follow the brief”。实际调用应自包含，不能假设模型能读取未上传的制作卡。无固定字数下限：完整性以制作决策是否落实为准，不以堆砌形容词或负面词扩充篇幅。

## 2. 十段式英文成品模板

完整附图必须包含以下十段；局部编辑和无文案主图可按自身任务精简。替换所有变量后才能调用。正文为英文；目标站点为其他语言时，Exact copy 保留目标语言。

```text
Task and selling objective:
Create one finished marketplace listing image with the final copy and graphic layout
already rendered into the image. Answer this one buying question: [question].
Communicate [verified benefit] through [visible product evidence].

Reference roles:
Reference 1 is the strict product identity reference.
Reference 2 is [style or layout only, if actually supplied].
Do not transfer product geometry, accessories or unverified claims from style references.

Product identity lock:
Preserve [named components, exact counts, connections, color, material appearance,
proportions, curtains or included accessories]. A new camera angle changes visibility,
not the total physical component count. Do not invent hidden mechanisms.

Scene and camera:
Use [specific place, time, weather, activity and background depth].
Show [view, angle, camera height and approximate product occupancy].
Allow only [props]; these must not obscure [critical parts] or imply inclusion.

Composition and hierarchy:
Place [product] in [region] and [text] in [region].
Use [reading order, number of detail modules, alignment and safe margins].
Keep labels beside the corresponding evidence and leader lines ending on the correct parts.

Art direction and physical realism:
Use [brand visual character, palette, lighting direction, softness and exposure].
Keep product highlights, contact shadows, reflections, fabric folds and environmental
color consistent. Use [specific retouching level], with realistic scale and textures.

Exact copy:
Render only the following text, exactly as written, preserving spelling, punctuation,
capitalization, line breaks and units:
Headline: "[final headline]"
Subheadline: "[final subheadline]"
Detail labels: "[confirmed labels, if needed]"
Disclaimer: "[necessary final disclaimer, if needed]"
Do not add text outside this list. Omit absent fields entirely.

Typography and graphic layout:
Use [headline type style, weight, relative size, line count and color].
Use [body style, hierarchy and line spacing].
Place [specific text] at [position], with [alignment, width, card background and padding].
Keep strong contrast and readable type at mobile preview size. Do not cover the product.

Strict exclusions:
Do not alter [specific protected parts] or invent [relevant unknown claims/data].
Do not create placeholder text, fake certification marks, watermarks or additional copy.

Output:
One complete finished image with all specified copy and layout rendered in the image.
[Aspect ratio, target pixels, format and commercial finish].
Do not deliver a blank base, an unlettered scene, or an image awaiting later typesetting.
```

画幅位置可用百分比和相对比例约束，这是设计目标，不是像素精确保证。输出尺寸必须使用工具实际支持的参数；提示词写了 2000×2000 不代表原生输出达到该尺寸。检查实际文件后如实报告。

文案精简但完整：通常一个标题、一个短副标题，必要时一至三个细节标签与免责声明。尺寸/清单可按任务增加已确认数据，不能为塞入内容而缩成难以阅读的小字。认证必须有真实来源与使用资格，不用模型臆造徽章。品牌 Logo 需要精确复现时使用获准素材，不以相似字形冒充。

## 3. 完整写法示例：傍晚庭院生活方式成品

以下是模板示例，不是历史调用记录。产品结构仅在当前身份参考确认时适用，所有文案和版式需匹配实际制作卡；参考 2 只有实际提供且允许使用时才能写入调用。

示例仅展示提示词结构，不提供默认色板或通用版式；每张必须先读取 campaign-style.md，并使用已确认的视觉方向和本张制作卡。不得把示例的信息区位置、背景或配色批量复制到整套。

```text
Task and selling objective:
Create one finished Amazon US lifestyle listing image, including the final English
headline, supporting line and disclaimer as part of the generated design.
Answer: What could this gazebo look like in an evening outdoor gathering setting?
Use the complete visible structure and a believable seating arrangement as the evidence.
Make no weather-protection, capacity or included-furniture claims.

Reference roles:
Reference 1 is the strict gazebo product identity reference.
Preserve its sellable product. Build an original setting around it.

Product identity lock:
Preserve the rectangular gazebo, double-tier smoky-gray segmented roof, charcoal frame,
six physical support posts, diagonal braces, base feet, gathered dark-gray curtains
and tiebacks, with the same joints, roof profile and natural proportions.
Keep all six posts physically present; a new perspective must not duplicate or remove
posts to force every post into view. Do not invent netting, fans or roof fixtures.

Scene and camera:
Show a blue-hour landscaped garden on pale stone paving, with a small pool visible
only in the distant left background. Place restrained neutral seating under the gazebo
without hiding post bases, braces or curtains. No people, installed decorative lights
or unrelated branded objects. Use an eye-level three-quarter full view with all roof
edges and product feet inside the canvas.

Composition and hierarchy:
Use a square canvas. Place the gazebo mainly in the right and lower portions,
occupying approximately 65–70 percent of the canvas width, with natural perspective.
Keep the upper-left approximately 32 percent of the canvas width as a calm information
area; no bright plants or pool highlights behind the words.
Reading order: headline, gazebo, supporting line, small bottom disclaimer.
Maintain approximately 5 percent outer safe margins. Do not cover the roof or posts.

Art direction and physical realism:
Use the confirmed campaign art direction, with colors drawn from the dusk garden
and the approved brand palette. Do not impose a uniform colored page background.
Balance cool blue-hour surroundings with soft warm ambient illumination.
Make roof reflections, frame highlights, ground contact shadows and distant water
reflections agree with the same dusk lighting. Retain visible fabric folds and realistic
panel reflections. Avoid artificial HDR, saturated cyan and a pasted-on product look.

Exact copy:
Render only this English copy, with exactly these spellings and punctuation:
Headline:
"Make Evenings
Feel Special."
Subheadline:
"A place to gather as the day slows down."
Disclaimer:
"Furniture and decorative accessories are not included."
No additional text, brand names, feature claims or labels.

Typography and graphic layout:
Set the two-line headline in an elegant bold serif with an appearance similar to Georgia
Bold, dark charcoal, about twice the supporting text height. Do not claim exact font
reproduction. Set the supporting line in a clean regular sans serif, no more than three
short lines, left aligned below the headline.
Place the information directly in a calm upper-left area of the scene with generous
breathing room and readable contrast. Add a subtle local gradient only if needed;
do not insert a default solid-color panel. Keep text clear of the roof silhouette.
Put the readable disclaimer in a narrow dark translucent strip along the bottom, using
high-contrast light sans serif type. Keep it inside the safe margin and away from the feet.
Do not add decorative icons, inset cards or extra badges to this lifestyle image.

Strict exclusions:
Do not redesign the gazebo, change its roof layers, omit posts, replace curtains,
add accessories or imply that furniture is included.
Do not add dimensions, UV ratings, waterproof claims, wind ratings, certifications,
packaging, watermarks or any words outside the Exact copy list.

Output:
One finished square Amazon US lifestyle listing image with all specified copy and
graphic layout already rendered. Photorealistic commercial finish, highest supported
quality and square resolution. Verify actual exported pixel dimensions.
Do not return a no-text base or an image awaiting later typesetting.
```

功能成品沿用上述结构，但用一幅大结构证据加一至两个可读细节模块；每个标签准确对应部件。不能把上例的泳池、版式或文案机械用于所有图。

## 4. 预检与成品校对

- 附图使用 `lint_product_prompt.py --route finished-image`，主图使用 `--route main-image`；脚本检查文本风险，不能证明事实正确或美术达标。
- 对照制作卡核对每项卖点、证据、风格、构图、文案与排版均进入实际提示词。
- 检查身份参考真的作为图像输入上传；风格和版式参考标注实际上传状态，不能声称上传未使用的图。
- 检查没有“生成成品”与“不要文字/以后排版”互相冲突的指令。
- 生成后逐字对照 Exact copy，校对拼写、大小写、数字、单位、遗漏和多余文字；必要时使用 OCR 辅助并人工复核。
- 以原图和手机缩略图检查阅读顺序、对比度、文字遮挡、模块证据、引线端点和跨图一致性。
- SKU 错误按 P0；错字、错数字、文案缺失、关键标签错位或不可读按 P1。未关闭不能进入最终交付。

## 5. 局部编辑与返工

原有局部改色、局部结构和换背景任务仍以最小改动为主，首句使用 `Edit only` 并保护几何、材质、构图与场景。成品生成是一个完整设计任务，不能因含摄影、文案和版式就强制拆成底图与后期。

对成品一次修复一个明确缺陷，保留正确产品、场景、风格和其他文字：

```text
Edit only the headline text region of the provided finished image.
Replace the incorrect headline with exactly: "[verified corrected headline]".
Preserve the headline position, typography hierarchy, color and line count.
Keep every product part, scene element, other text and layout module unchanged.
Output: the same complete finished image with only this text correction.
```

同一缺陷最多进行两次局部修复；仍失败则记录未解决项，使用最近正确版本重新生成该张成品或报告工具限制，不无限重试、不交付缺字成品。实际调用提示词、模型、输入参考和生成状态须可追溯。
