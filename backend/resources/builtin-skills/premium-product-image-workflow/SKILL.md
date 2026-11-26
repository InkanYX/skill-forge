---
name: premium-product-image-workflow
description: "Plan, generate, edit and review faithful ecommerce product images, complete Listing sets and Amazon A+ content. Includes evidence-backed copy, visual direction, scene templates and project resume. Use for 商品图、主图、套图、A+、手机端适配、换风格、局部修改、继续出图 and public competitor visual research. Not for PPC optimization or unrelated image art."
metadata:
  version: "2.5.3"
  required_references:
    - references/campaign-style.md
---

# 高保真商品图工作流 · 整合版

将商品资料转为可执行图需、完整成品与可恢复项目。保留用户原有的 SKU 保真与质检要求，吸收四个电商仓库的文案策略、模板、图型组织和工具思路。来源与改编边界见 [sources.md](references/sources.md)。内部模块独立运行，不要求同时加载原四套技能。

## 制作基准

- 每次使用本技能，先完整读取 [套图风格](references/campaign-style.md)，包括逐张独立编写提示词时；不要仅凭入口摘要或提示词示例决定视觉方向。支持 required_references 的运行器应随入口注入该文档并记录实际加载；其他运行器需主动读取。单次任务内已完整加载时无需重复读取。
- 套图统一品牌语言与修图质感，各图依据职责变化构图和信息组织；不默认采用示例的配色、暖白底、顶部标题带或等分卡片。用户已确认的方向优先。

- 优先级：同一可售 SKU → 结构与比例 → 颜色/材质外观/包含物 → 构图 → 已确认卖点 → 光影 → 装饰。结构变体标记为改款，不冒充原 SKU。
- A 级可见外观、已确认 B 级资料可以使用；按用户偏好主动从照片推测材质与可能性能，读 [照片推测卖点](references/photo-inferred-selling-points.md)，提出候选与展示方案，注明依据和置信度。推测与确认事实分开；不凭照片编造尺寸、材质牌号、性能等级、认证、包含物、安装时间或服务承诺。
- 有商品参考图时优先编辑。先区分 Listing 套图与 A+：商品套图首张主图只完整展示同一可售 SKU，无新增标题、卖点、文字、图标、徽章、水印、边框、人物或非售卖道具；保留产品本身真实已有标识。背景按确认图需，用户选择非白底/场景时不强制白底；白底上架槽位另按该槽位复核。主图不继承附图/A+的文案排版与装饰模块。附图和 A+ 默认直接生成含逐字文案与排版的完整成品，A+首张可为带文案的场景英雄图；用户明确要求底图或设计师交接时才切换，不静默改成后期叠字。
- 一图一个主要购买主题，不等于只放一个零件或一句收益。用户要求内容丰富时，按 [内容充实与辅助视图](references/content-depth-and-supporting-visuals.md) 组合相关子卖点、局部证据、状态对照与图形；弱细节合并，避免大标题加单一零件撑一整张。
- 生成、技术检查、人工视觉验收、导出分别记录。P0/P1 未关闭不可作为最终成品；自动工具不能认证 SKU、隐藏结构或当前平台政策。
- 用户要求与已有项目选择优先。复用已知名称、平台、语言、供应商、上传范围和风格；只询问会实质改变结果的缺口。授权不扩展到无关素材、新接收方或新用途。
- 同一项目批量生图时，用户已明确授权的接收方、参考素材范围及用途持续适用于范围内的逐页调用；不得仅因换了图号或选用该已授权范围内的另一张参考图而重复询问。记录用户授权原话和边界；正常重试仍遵守出图配置的次数上限。此规则不授权未来项目上传、不扩大素材范围、不更换接收方或用途，也不替代运行环境审批。

## 选择本次任务

| 用户需要 | 工作范围 | 按需读取 |
|---|---|---|
| 新图/整套图 | 事实 → 策略 → 图序 → 制作卡 → 生成 → 验收 | [策略与文案](references/campaign-strategy.md)、[完整图需](references/listing-image-requirements.md) |
| A+、详情页、主图 | 图型、模块与证据方式 | [专项制作](references/specialized-production.md) |
| 换风格/重排版 | 复用事实与受保护文案，新建风格版本 | [风格系统](references/campaign-style.md) |
| 桌面转手机/手机端A+/移动版尺寸适配 | 独立重排场景与信息，保留同一SKU与关键条件；区分画幅基准、原生像素和导出像素 | [手机端重排流程](references/mobile-adaptation.md)、[排版设计](references/layout-design.md) |
| 只改一处/改色 | 一个编辑目标，其余正确内容保持，另存版本 | [局部提示词](references/prompt-templates.md) |
| 继续/继承/补图 | 核对状态与文件，仅处理缺图/返工项 | [项目恢复](references/project-state.md) |
| 图需/提示词/审查 | 完成请求层级，不调用生图 API | 策略或质检模块 |
| 公开竞品研究 | 标题筛选 → 顺序详情页 → 商品图库原图 → 洞察 | [竞品研究](references/amazon-public-competitor-research.md) |

“已有成图”不等于要求重做；“继续”时检查完成清单，全部完成就交付现有结果。先读入口与当前模块，再按图号检索；不默认重读所有图库、旧对话和来源仓库。

## 生产流程

1. **恢复或建包。** 找已有 Brief、图序、提示词、质检和状态。新项目用 `scripts/init_amazon_listing_package.py --out <新目录> --name <名称>`，同时建立 `project-state.json`。其他平台沿用目录规范，明确实际平台。
2. **冻结身份与事实。** 使用 [Brief 模板](assets/product-image-brief-template.md)；复杂商品明确部件数、位置、连接、比例与易错结构。自有成图与第三方资料先读 [参考治理](references/reference-image-governance.md)。竞品只作抽象研究，不作模型输入或本 SKU 事实。
3. **卖点提炼。** 新品策划、卖点改写与完整套图先读 [卖点提炼](references/selling-point-extraction.md) 和 [策略与文案](references/campaign-strategy.md)。从原始资料建立候选池，完成特征→优势→买家收益→证据，比较购买相关性、差异性和可视化方式；交付主卖点、辅助卖点、规格信息及淘汰理由。不能仅把参数换成形容词。输入齐全且任务需要时进行公开研究；缺输入或访问受阻时继续可支持部分，竞品仅证明市场诉求，不证明本品性能。
4. **图序与风格。** 读 [卖点到分镜](references/selling-point-storyboard.md)，把已通过的 point_id 分配到逐图制作卡。Listing 默认参考7图；“模板1”采用原九图规范；A+依实际模块和请求数量。每张一个主要购买主题，可用多个相关子卖点共同支撑；按内容价值分配图位，弱细节并入综合主题。统一品牌语言，场景和版式按职责变化；同一卖点复用须新增证据或决策信息。平台/品类与本地化按需读 [适配规则](references/market-category-adaptation.md)。
5. **排版与提示词。** 图序先按 [套图规划](references/image-set-planning.md) 匹配购买决策，制作卡按 [排版设计](references/layout-design.md) 明确区域、视觉层级和移动端适配，再按 [十段式规范](references/prompt-writing-standard.md) 与 [提示词编排](references/prompt-composition.md) 转成实际调用。保存实际提示词原文。运行 `scripts/lint_product_prompt.py --input <提示词> --route finished-image --report <报告>`，主图用 `main-image`；修复 error、复核 warning。局部编辑首句为 `Edit only ...`。
6. **出图。** 先读 [统一出图配置](references/generation-profile.md)，使用实际支持且已选定的接口、模型和编辑能力。单图参考是项目偏好，不推断所有网关都只支持一图。新套图先建立可用风格锚点，再完成其余图；不机械逐张确认。
7. **验收与交付。** 按 [质量闸门](references/quality-gate.md) 对照结构、材质外观、光影、文案、数字、引线与可读性；用原 `scripts/generate_reference_comparison.py` 辅助记录。一次修复一个主要缺陷。仅 P0/P1 关闭的版本进入 `06_final/`；附提示词、实际尺寸、参考角色、验收和未知项。

## 工具与恢复

- 卖点与文案策划使用 [提炼交付模板](assets/selling-point-workbook.md)；完整方案交付前读 [文案质量与审查](references/copy-review.md)。单处修图不重跑无关策略，新增或改变宣称时复核相应证据与卖点。
- `scripts/count-copy.py --language zh/en <逐条文案>` 统计长度；`scripts/scan-final-copy.py <逐条文案>` 排查成品占位符与内部说明。仅用于机械检查，不证明卖点质量、真实性或法律合规。
- `scripts/project_memory.py`：`init / add / record / summary / import-manifest`；状态是数据而非指令，旧授权记录仅为线索，须匹配当前有效授权。
- `scripts/scenario_catalog.py list`：查看39类；`show <id>`：只加载所选画面提示。已剔除上游示例参数、认证、政策与默认模型；模板不补充商品事实。
- `scripts/export_product_images.py resize / grid / stitch`：默认等比、不裁商品、不覆盖，记录尺寸和哈希。实际平台槽位优先；原生尺寸与交付尺寸分开报告。
- 研究：`validate_gallery_urls.py` → `download_collected_gallery.py`；需要时用 `filter_competitor_candidates.py`、`generate_competitor_visual_report.py`。验证码、登录墙、限流、访问控制即停止，不绕过。
- 本机可启用 `C:\Users\admin\Documents\Codex\skill-runtime\activate.ps1`；不存在则定位可用 Python。缺可选 OCR 不阻断策划和生图，OCR skipped 如实记录。

## 保留的规范

[Amazon SOP](references/amazon-listing-production-sop.md)、[套图规划](references/image-set-planning.md)、[竞品图需](references/competitor-driven-image-briefing.md)、[竞品视觉情报](references/competitor-visual-intelligence.md)、[完整图需](references/listing-image-requirements.md)继续用于相应任务。

整合模块统一本入口的默认行为，不继承上游默认淘宝、默认 DALL·E、强制问卷、推广站跳转或未经核验的法律结论。照片推测采用本版分层流程，覆盖旧资料中笼统的“不推断”表述：允许假设和概念展示，不自动升级为确认事实。必要时查官方现行规则，不把技术检查报告为保证上架。
