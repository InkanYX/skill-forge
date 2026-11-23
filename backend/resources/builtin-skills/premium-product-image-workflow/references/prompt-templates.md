# 商品生图提示词模板库

## 1. 复杂产品 SKU 锁定模块

```text
Preserve the exact same sellable SKU shown in Reference 1.
Keep [component A], [component B], [component C], [exact count], [materials], [colors], [connection points], and [natural proportions] exactly as shown.
Do not add, remove, duplicate, simplify, replace, redesign, stretch, narrow, heighten, warp, rotate, crop or obscure any product part.
Maintain the original [front-facing / three-quarter] camera angle and natural perspective unless a new view is explicitly requested.
```

将所有可能被模型改错的部件写明；不要仅使用 `same product`。

## 2. 无文字主图

```text
Create a clean, high-resolution e-commerce hero image of the provided product.
Use Reference 1 as the strict product identity reference. Preserve the exact SKU, structure, proportions, colors, materials, texture, seams, hardware, and included components.
Show the complete sellable product clearly, sharply, naturally proportioned, centered, and visually dominant with no cropped edges.
Use a pure clean white background, soft even studio lighting, balanced exposure, realistic material highlights, and only a very subtle natural contact shadow.
Do not add people, props, packaging, text, badges, dimensions, icons, logos, watermarks, borders, decorations, extra accessories, dramatic reflections, strong shadows, or scene elements.
Do not redesign, simplify, stretch, narrow, widen, distort, crop, recolor, or replace any product part.
Output: [ratio / pixel size], photorealistic high resolution.
```

## 3. 带文案排版的场景成品

使用 `prompt-writing-standard.md` 的十段式模板及完整场景示例。必须写清购买问题、SKU 锁定、参考角色、场景、机位、构图、风格、逐字文案、字体和版式、限制及成品输出。摄影、文案和版式随同一次调用直接生成，不得写“以后加字”或“无文字底图”。用户明确要求纯摄影或底图时才省略文案。

## 4. 局部改色

```text
Edit only the color of [specific material / part].
Change [original color] to [target color] with a [warm / cool] undertone and [brightness / saturation] level. Do not make it [unwanted color 1], [unwanted color 2], or overly saturated.
Apply the new color consistently only to [all relevant areas]. Preserve realistic highlights, shadows, folds, texture, stitching, thickness and reflections; keep sunlit areas lighter than shaded areas.
Do not change shape, dimensions, proportions, materials, components, camera angle, perspective, composition, lighting, background, exposure, color grading or any non-target object.
Do not add, remove, crop, resize, blur, replace or move anything.
Output: same original composition with only the requested color correction.
```

## 5. 局部结构微调

```text
Edit only [specific structural area].
Adjust [direction] by approximately [relative amount], while preserving [full width / symmetry / center position / support alignment / connection points].
Make surrounding materials, seams, ribs, folds, highlights, shadows and reflections follow the adjusted shape naturally with realistic tension and perspective.
Do not change any other component, overall dimensions, product angle, perspective, background, composition, color grading or lighting.
Output: same original image with only [specific structural adjustment].
```

## 6. 换背景、天空或时间

```text
Transform only the [sky / background environment / environmental lighting] from [current condition] to [target condition].
Use [specific time, weather, lighting direction and exposure]. Update ground shadows, material highlights, reflections, water / glass / metal surfaces, vegetation, and ambient color naturally to match the new environment.
Preserve the exact product design, structure, dimensions, proportions, materials, colors, position, angle, perspective, all foreground objects, location and composition.
Do not add, remove, move, crop, redesign or replace anything. Do not create mismatched shadows, inconsistent reflections, artificial HDR, clipped highlights or floating objects.
Output: the same composition with only the environment and related light behavior changed.
```

## 7. 带文案排版的卖点 / 功能成品

同样使用十段式成品模板，以下内容必须具体化后嵌入对应段落：

- 唯一已确认卖点与视觉证据：一幅大主体和一至两个清晰特写，不能用不匹配的裁图凑模块。
- 构图：主体占比、细节区域、对齐网格、安全边距、阅读顺序和不遮挡的部件。
- Exact copy：逐字列出标题、副标题、部件标签和必要免责声明；只用已确认事实。
- Typography and graphic layout：标题/正文风格、字号层级、字重、字色、卡片背景、引线起止部件。
- Output：完整画面、文字、模块及引线已一体生成的单张最终成品。

尺寸成品仅使用已确认数字、单位和端点。未确认尺寸时改为无数值产品概览成品，不猜测参数；生成后逐字、逐项校对。

## 8. 尺寸适配

```text
Adapt the provided image to exactly [width] × [height] px, [aspect ratio].
Preserve the product's exact natural proportions. Do not squeeze, stretch, narrow, widen, shorten, elongate, distort, warp, rotate or crop the product. Only uniform proportional scaling of the whole product is allowed.
Reduce outer margins, empty background areas, card padding and nonessential spacing before reducing the product. If cropping is unavoidable, crop only nonessential outer background at extreme edges.
Preserve all verified original text exactly. Do not change, delete, add, rewrite, rearrange or misspell text.
Output one clean image at exactly [width] × [height] px.
```

## 9. 返工模板

```text
Previous result changed unrelated product details.
Retry with strict product identity locking.
Correct only [specific defect]. Restore [correct component / count / proportion / material / verified copy].
Preserve everything already correct: [scene, camera angle, lighting, layout, palette, verified text].
Do not alter any non-target product component, background element or text. Do not introduce new accessories, claims, dimensions, logos or decorations.
```
