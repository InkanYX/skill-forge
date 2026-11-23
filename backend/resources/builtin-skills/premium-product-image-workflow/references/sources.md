# 来源、版本与整合边界

整合版本2.3.0，2026-11-02。以用户原有技能为基准；保留全部原参考、模板和研究/质检脚本。上游仓库作为模块设计来源，不作为当前模型能力或法律规则的权威。2.2按用户偏好新增照片材质/性能推测、置信度与展示候选；这些假设不自动成为已确认事实。

2.3在原图序、风格和十段式提示词上补充购买障碍驱动排序、A+/详情节奏、8种布局的区域设计、手机重排、制作卡到调用的编排及冲突检查。`layout-design.md`、`prompt-composition.md`与图序矩阵为本地改编与编排，沿用既有来源声明，不声称上游具有同名算法或这些策略已验证转化率。未增加新图像供应商、付费调用或自动后期排字路线。

| 来源 | 采用部分 | 适配与舍弃 |
|---|---|---|
| [feichanggege/ecommerce-visual-copywriting-skill](https://github.com/feichanggege/ecommerce-visual-copywriting-skill) | 证据账本、六类购买驱动力、FABE、分镜角色、首图识别、文案质量/FAQ/本地化、平台品类方法、审查与交接、原版字数与占位扫描工具 | 改为证据型通过/待修复；保留用户的直接成品路线，不导入强制问卷/缺品牌名暂停；平台与法规重新核验，不继承历史访问结论 |
| [buluslan/gpt-image2-ecommerce](https://github.com/buluslan/gpt-image2-ecommerce) | 39类场景导航、风格锁定、编辑职责 | 目录分类和触发词来自原JSON，visual_recipe为改编文字；剔除原示例数字、认证、政策、模型和推广信息 |
| [wzj177/ecommerce-image-suite](https://github.com/wzj177/ecommerce-image-suite) | 结构化商品分析、输入图识别、卖点视觉关键词、动态商品描述、8类图型分工、布局选择、风格方向、同模特与重试一致性、多供应商配置思路 | 改为已确认事实驱动；不固定风格与平台绑定，不自动补未知背面；未复制API/视频执行脚本，不继承默认DALL·E、看图猜材质或视频追加流程 |
| [xianyu110/ecommerce-image-skills](https://github.com/xianyu110/ecommerce-image-skills) | 12项专项任务的组织、A+预设与确定性导出思路 | 导出工具重新实现：去掉默认中心裁与文件名重排，不继承推广链接或默认供应商 |

本地源快照入口哈希见 `../assets/source-snapshots.json`，39类原JSON哈希见场景目录。哈希用于追溯实际已安装文件；未记录commit的来源不冒充已锁定上游提交。

2.1新增的卖点筛选/去重/分层与工作簿为本地编排，不冒称上游原算法或经过转化率测试。`selling-point-extraction.md`、`campaign-strategy.md`、`selling-point-storyboard.md`、`copy-review.md`、`market-category-adaptation.md` 为重新编写的适配模块。两个文案检查脚本原样复制自文案技能，沿用其MIT声明；机器检查只验证字符串，不验证事实或营销效果。

本次目标是整合商品视觉与卖点策划相关能力，未接入额外视频生成、HTML详情页生产、多服务商执行适配与原45人模特素材库；这些不是本主技能已实现能力。原生视觉分析可直接完成结构化商品分析，无需另开付费分析接口。

许可证：文案技能MIT、ecom-image2 MIT、ecommerce-image-suite Apache-2.0、xianyu110套件MIT。原文保存在 licenses/。未将用户原有技能统一重新许可；第三方部分仍保留相应声明。改编文件已在本文和各模块说明来源与变更。

此次未卸载或修改四个独立仓库，也未修改它们的自动发现设置。需要整合流程时明确使用 `$premium-product-image-workflow`；选择器仍可能发现其他已安装技能，不能仅凭新增入口保证它们永不触发。以后更新只比较源快照，先复核差异，不自动覆盖整合规则。
