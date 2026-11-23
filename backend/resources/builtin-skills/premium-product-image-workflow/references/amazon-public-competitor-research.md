# Amazon 公开竞品套图研究与下载

## 目的与边界

从 Amazon 正常公开可访问的 Best Sellers 列表页开始，以标题初筛后顺序访问少量高相关详情页。核心交付物是每个候选的**商品主图与商品图库套图原文件**，而不是商品详情页首屏截图。

只可下载浏览器在商品图库中正常显示或已正常加载到图库节点的公开图片 URL。不得猜测、拼接、解密图片 URL，不得访问隐藏接口、绕过验证、使用代理、重放请求或导出 Cookie。竞品图片只用于内部视觉研究，不得直接复用到商品页面、广告素材或训练数据。

## 必填输入

- 产品类型
- Amazon 站点，例如 `amazon.com`
- 类目 / Best Sellers 列表页 URL
- 标题关键词：核心名称词、同义词、功能词、材质词、形态词
- 排除词（可选）
- 候选详情页上限：默认 20
- 下载目录：必须指定

## 工作流

### 1. 读取公开榜单并筛选

1. 在独立浏览器会话中正常打开用户提供的榜单页。
2. 确认商品卡片标题和链接已出现，再记录页面实际显示的顺位、标题、商品 URL、ASIN（可见时）及缩略图 URL（可见时）。
3. 按标题关键词打分；完整词组优先，命中排除词的候选直接排除。
4. 人工剔除配件、替换件、临时帐篷或其他非目标形态；按相关度和页面顺位排序，最多顺序访问 20 个详情页。

### 2. 从商品图库采集主图与套图

对每个候选页按以下优先级提取：

1. 定位商品主图和商品图库缩略图轨道，先在页面中确认图片属于当前 SKU。
2. 从商品图库的已加载图片节点获取公开图片 URL；必要时正常点击缩略图以触发懒加载，再重新检查图库节点。
3. 建立“一张图片一行”的 `gallery_urls.csv`，不可只把多个 URL 混在单个字段中。
4. 严格按图库顺序编号：第 1 张标记为 `main`，第 2 张及以后标记为 `gallery`；只有确实属于商品视频预览时才标记 `video_poster`。
5. 排除以下内容：页面首屏截图、A+ 横幅、品牌故事图、推荐商品图、买家评论图、搜索广告图、页面装饰图和浏览器插件图。
6. 若图片 URL 可公开打开，使用本技能脚本下载；若受访问控制则停止当前站点研究，保留阻断原因。不得用网页截图替代套图。
7. 仅当图库节点完全不可读、但必须记录已确认的页面状态时，保存一张命名为 `evidence_screenshot` 的截图作为阻断证据；不得把它报告为商品主图或套图。

`gallery_urls.csv` 必填列：

```csv
asin,gallery_position,image_role,image_url,product_url,page_rank,title,source_checked_at
B0XXXXXXX,1,main,https://m.media-amazon.com/images/I/example.jpg,https://www.amazon.com/dp/B0XXXXXXX,4,Example product,2026-10-29T17:00:00+08:00
B0XXXXXXX,2,gallery,https://m.media-amazon.com/images/I/example2.jpg,https://www.amazon.com/dp/B0XXXXXXX,4,Example product,2026-10-29T17:00:00+08:00
```

### 3. 预检并下载公开已采集的图库图片

先在本地检查 CSV；此步骤不会访问任何 URL 或页面：

```bash
python scripts/validate_gallery_urls.py \
  --input gallery_urls.csv \
  --report gallery_preflight.md
```

预检会阻止下载，直到修复以下错误：缺失必填字段、非 HTTP(S) URL、非正整数图序、同一 ASIN 的重复或跳号图序、首图不是 `main`、后续图误标为 `main`，以及同一 ASIN 指向多个商品页。重复图片 URL 和缺失 / 非 ISO 采集时间会作为警告写入报告。通过后再运行：

```bash
python scripts/download_collected_gallery.py \
  --input gallery_urls.csv \
  --output-dir competitor_gallery_downloads \
  --max-images-per-product 10
```

脚本只处理 CSV 中已明确提供的公开 URL：

- 按 ASIN 创建子目录；
- 命名为 `01_main_*`、`02_gallery_*` 等；
- 每张图最大 15 MiB；
- 输出 `manifest.csv`，记录来源页、图库顺序、下载状态、本地路径与失败原因；
- 不访问 Amazon 页面，不发现图片，不构造 URL，不绕过访问控制。

标题筛选 CSV 的情况下，可先运行 `scripts/filter_competitor_candidates.py`；该脚本的 `image_urls` 字段只适合已收集 URL 的粗筛。实际下载与图序管理必须使用上面的逐图 `gallery_urls.csv`。

## 停止条件

出现 CAPTCHA、机器人验证、Access Denied、403/429、登录墙、异常跳转、图片访问控制或页面不属于目标站点/类目时，立即停止当前站点。记录已完成下载、停止时间和原因；不得重试规避。

## 输出结构

交付必须包含：

| 字段 | 说明 |
|---|---|
| page_rank | Best Sellers 页面实际显示顺位，非独立核验 BSR |
| title / asin / product_url | 商品身份与公开来源 |
| gallery_position / image_role | `01_main` 与后续套图的顺序及角色 |
| image_url / local_path | 已公开获取 URL 与实际下载文件 |
| source_checked_at / access_status | 采集时间和状态 |

视觉研究必须以下载到的商品图组为依据，逐项总结主图背景、商品占比、机位、套图图序、文字密度、场景类型、卖点证明方式、共性和差异化机会。不得将首屏截图当作图片套图分析依据。
