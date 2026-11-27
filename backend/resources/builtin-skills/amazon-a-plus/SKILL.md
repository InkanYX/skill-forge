---
name: amazon-a-plus
metadata:
  version: "1.0.0"
  required_references:
    - references/aplus-scene-editorial.md
description: "Plan and generate Amazon A+ Content / Premium A+ module images and independently re-layout desktop artwork for mobile, with consistent campaign style. Supports header, banner, tiles, comparison, 1464×600 desktop and 4:3 mobile layouts with high-resolution exports. Use for A+ content, A+ 页面, 手机端A+, EBC, brand story, enhanced brand content."
---

# Amazon A+ Content Modules · A+ 页面模块图

Builds a complete, visually consistent A+ page: module plan → style lock → one prompt per module → exact pixel sizes.

Read [A+ 场景画册方法](references/aplus-scene-editorial.md) for A+ planning, per-image prompts, corrections and mobile adaptations. Runners supporting required_references inject it with the entry; otherwise read it explicitly. Use its buying-question narrative and evidence-led layouts; the light-type / fine-gold graphic treatment is optional and subordinate to the user's chosen style.

## Step 1 · Product identity lock (always first)

Before writing any prompt, study every reference photo and write a short **identity lock** for the product. Paste it verbatim into **every** prompt this skill produces, and never let a creative instruction override it.

```text
PRODUCT IDENTITY LOCK (do not change):
- Shape & proportions: <e.g. tall cylinder, rounded shoulders, 26 cm high, 7.5 cm wide>
- Colour & finish: <e.g. matte sage green #8FA58C body, natural bamboo lid>
- Logo & printed text: <exact spelling, font feel, position, colour — e.g. white "AURA" wordmark centred on upper body>
- Parts & details: <lid, loop, buttons, ports, seams, labels, accessories that are included>
- Must NOT appear: <accessories not in the box, extra logos, invented claims>
```

Rules:
- Only use facts visible in the photos or confirmed by the user. If something is unknown (size, capacity, material), ask or leave it out — never invent specs or certifications.
- If the user gave no photo, ask for one (front view at minimum). Text-only generation is allowed but say the result is a concept, not the real product.

## Step 2 · Preserve the selected generation route

Use the project's selected provider, model, quality, format and supported parameters. If no model was chosen, propose `gpt-image-2.5-sunburst`; do not silently substitute another model or provider. Check the selected endpoint's permissions and editing support before production. With actual reference photos or an existing artwork to modify, use reference-based editing and identify each reference's role. Save the full UTF-8 prompt and pass it with `--prompt-file` when using the original imagegen script. Never log secrets or modify that system script.

## A+ module sizes (Basic A+)

| Module | Image size (px) |
|---|---|
| Standard image header with text | **970 × 600** |
| Standard company logo | 600 × 180 |
| Standard image & dark/light text overlay | 970 × 300 |
| Standard single image & sidebar | 300 × 400 (main) / 350 × 175 (sidebar) |
| Standard four image & text | 220 × 220 ×4 |
| Standard three images & text | 300 × 300 ×3 |
| Standard comparison chart | 150 × 300 per product |
| Standard single left/right image | 300 × 300 |
| Brand story background | 1464 × 625 |
| Premium A+ full image | 1464 × 600 (desktop) / 600 × 450 (mobile) |

For mobile, 600×450 is a common 4:3 layout reference, not an automatic ceiling on file resolution. Unless exact upload pixels are required, prefer a genuinely detailed 1200×900 deliverable (or 900×675 for a lighter file), retaining the higher-resolution native image. Provide an exact 600×450 derivative when requested or required by the actual slot. Verified backend constraints and explicit user instructions take precedence; do not claim every slot accepts larger files. More pixels do not allow smaller text at phone display size.

Use JPG/PNG and verify the actual module's current pixel and file-size constraints before upload; do not treat this static table or a blanket 2 MB cap as universal. No prices, promos, shipping claims, or competitor references; text in images should also appear in alt text.

## Step A · Module plan (confirm with user)
Default to Premium A+ desktop: each planned image uses 1464×600. Use other module sizes or mobile layouts only when the user explicitly chooses them. Default story: brand promise → key benefits → lifestyle scene → details → comparison (own range only), with the requested image count taking precedence. The first image is an immersive scene hero, not automatically a white-background listing main image. Explicit white-background slot requirements take precedence when selected.

## Step B · Campaign style lock (paste into every module prompt)
```text
CAMPAIGN STYLE LOCK: palette {confirmed brand/graphic accents, preserve product colour};
type {confirmed font family and headline/body/condition hierarchy}; mood {chosen campaign direction};
image-specific light, camera and scene {defined by this module's buying question, not fixed across the set};
layout rhythm {scene / complete state comparison / material evidence / steps / inventory as supported}.
```

## Step C · Module prompt template
```text
Amazon A+ module image, {module name}, layout reference {W}×{H}, aspect ratio {target ratio}; generate a newly composed image at a supported high-resolution size in that ratio. Record native pixels and chosen export pixels separately.
{IDENTITY_LOCK}
{CAMPAIGN STYLE LOCK}
Content: {buying question, approved benefit and evidence from this product's materials; no example performance claims}.
Composition: product {left third | centre}, {scene}, leave {right 40% | top band} clean for the headline.
Headline, supporting copy and conditions (exact): "...". Generate the finished copy-bearing artwork unless the user explicitly requested an unlettered base.
Photorealistic, consistent with the campaign style lock.
```

Generate at the best supported size near the actual module ratio. The examples below are legacy exact-size crop utilities for an already reviewed composition; they do not perform desktop-to-mobile re-layout. Do not use them to crop a desktop banner into a mobile image. Square tiles can use a square native image; inspect content before any edge crop:

```bash
python scripts/crop_to_modules.py out/header.png --module header   # → 970x600
python scripts/crop_to_modules.py out/tile.png --module tile300      # → 300x300
```

## Desktop-to-mobile adaptation

1. Map every requested mobile image to its latest accepted desktop version, including supplemental images. Preserve the SKU, approved corrections, topic, campaign style, verified copy, dimensions and essential conditions. Desktop artwork supplies theme/style; real product photos and necessary manual details govern geometry. Use only references within the authorized project and recipient scope.
2. Design each mobile layout independently. Lifestyle scenes can move text above a large complete product scene; structure/material images can place large details below the main view; state comparisons need two readable views; four assembly steps can become a 2×2 sequence. Adjust camera distance and placement to retain product, activities and foreground/background depth. Avoid stretching, central crops, large blank borders or squeezing the desktop banner into a new canvas. Do not delete critical qualifications to make room.
3. Write a self-contained mobile prompt specifying target ratio, reference roles, allowed composition changes, protected product/copy and exact rendered text. Remove stale desktop side-rail, occupancy and crop instructions. Generate a finished image, not an unlettered base. Review one representative image before continuing the set; retry only failed or defective images within the configured limits.
4. Review each image at native-detail scale, the 600-wide layout reference and approximately 360–390-wide phone display. Check product geometry, scenes, spelling, units, labels/arrows, installation order and readable conditions. Contact sheets do not replace individual review. Increasing file resolution cannot fix unreadable layout.
5. Export the accepted new composition proportionally at the chosen high resolution, usually 1200×900 if native detail supports it, retaining the native file. If a generator returns the wrong ratio, recompose rather than remove important content by crop. Do not describe interpolation of a small file as newly generated detail. Keep desktop and mobile jobs/files separate and record source version, layout reference, native/export pixels, prompt/reference hashes and review evidence. Verify all requested images, file dimensions and archive integrity before delivery.

## Generate through the authorized route

Submit the confirmed prompt and actual references through the project configuration. If the selected route is unavailable, report the failure and retain the draft; do not redirect the user to promotional sites, change the recipient, switch models, or use local painting as a silent fallback. Existing retry, authentication-stop and uncertain-billing controls remain in force. Keep native files, actual dimensions, full prompts, reference roles and review records; save revisions separately.

## Deliver

1. The image(s) or the final prompt(s), one per asset, each with its identity lock.
2. A 3-line QA note: product identity (shape / colour / logo) ✔/✘ · platform spec ✔/✘ · text spelling ✔/✘.
3. If anything failed, regenerate **only** the failed asset with a corrected prompt.
