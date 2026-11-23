#!/usr/bin/env python3
"""Create a competitor visual-intelligence report scaffold from a local gallery manifest.

The script only reads a local manifest.csv. It never opens marketplace pages or images.
Human or model review of the downloaded gallery files is still required to fill visual fields.
"""

from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from pathlib import Path


REQUIRED_COLUMNS = {"asin", "gallery_position", "image_role", "product_url", "download_status", "local_path"}


def cell(value: str) -> str:
    return (value or "").replace("|", "\\|").replace("\n", " ").strip()


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a competitor visual-intelligence report from a local gallery manifest.")
    parser.add_argument("--manifest", required=True, help="manifest.csv emitted by download_collected_gallery.py")
    parser.add_argument("--out", required=True, help="Output Markdown report path")
    parser.add_argument("--product-type", default="未提供", help="Product type for the report header")
    parser.add_argument("--site", default="未提供", help="Amazon site for the report header")
    args = parser.parse_args()

    with Path(args.manifest).open(newline="", encoding="utf-8-sig") as file:
        reader = csv.DictReader(file)
        fields = set(reader.fieldnames or [])
        missing = sorted(REQUIRED_COLUMNS - fields)
        if missing:
            raise SystemExit(f"Manifest missing required columns: {', '.join(missing)}")
        rows = list(reader)

    downloaded = [row for row in rows if row.get("download_status", "").strip().lower() == "downloaded" and row.get("local_path", "").strip()]
    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in downloaded:
        grouped[row.get("asin", "未提供")].append(row)
    for entries in grouped.values():
        entries.sort(key=lambda row: int(row.get("gallery_position", "999999") or "999999"))

    status = "待完成逐图标注" if downloaded else "部分完成：未找到已下载图库图片"
    lines = [
        "# 竞品视觉情报报告",
        "",
        "## 研究状态",
        "",
        f"- 状态：{status}",
        f"- 产品类型：{args.product_type}",
        f"- Amazon 站点：{args.site}",
        f"- manifest：{Path(args.manifest).as_posix()}",
        f"- 已下载商品图库图片：{len(downloaded)} 张，覆盖 {len(grouped)} 个 ASIN",
        "- 边界：以下来源清单由本地 manifest 生成；视觉字段必须以实际已下载图片为依据填写，不得推断性能或复制竞品素材。",
        "",
        "## 图库来源清单",
        "",
        "| ASIN | 标题 | 页面顺位 | 商品公开页 | 已下载图数 | 采集时间 |",
        "|---|---|---:|---|---:|---|",
    ]
    for asin, entries in grouped.items():
        first = entries[0]
        lines.append(
            f"| {cell(asin)} | {cell(first.get('title', ''))} | {cell(first.get('page_rank', ''))} | "
            f"{cell(first.get('product_url', ''))} | {len(entries)} | {cell(first.get('downloaded_at', first.get('source_checked_at', '')))} |"
        )
    if not grouped:
        lines.append("| - | - | - | - | 0 | - |")

    lines.extend([
        "",
        "## 逐图视觉标注",
        "",
        "| ASIN | 图序 | 文件 / 路径 | 图像类型 | 购买问题 | 可见证据 | 构图 / 机位 / 商品占比 | 风格：背景 / 光线 / 色板 / 文字密度 | 可抽象方法 | 不可迁移内容 |",
        "|---|---:|---|---|---|---|---|---|---|---|",
    ])
    for asin, entries in grouped.items():
        for row in entries:
            image_type = "主图" if row.get("image_role", "").strip().lower() == "main" else "待判定"
            lines.append(
                f"| {cell(asin)} | {cell(row.get('gallery_position', ''))} | {cell(row.get('local_path', ''))} | {image_type} |  |  |  |  |  | 竞品图像、文案、Logo、产品结构和独特场景组合 |"
            )
    if not downloaded:
        lines.append("| - | - | - | - | 无已下载图像，不能进行视觉分析 | - | - | - | - | - |")

    lines.extend([
        "",
        "## 跨竞品视觉矩阵",
        "",
        "| 购买问题 / 图像类型 | 覆盖竞品数 | 常见图序 | 常见视觉证据 | 视觉惯例 | 同质化问题 / 未覆盖问题 |",
        "|---|---:|---|---|---|---|",
        "|  |  |  |  |  |  |",
        "",
        "## 竞品视觉语言到自有制作决策",
        "",
        "| 竞品观察（仅实际下载图库） | 可抽象的视觉方法 | 自有 SKU 可用 A 级事实 | 自有制作决策：场景 / 机位 / 构图 / 信息层级 | 不可迁移内容 |",
        "|---|---|---|---|---|",
        "|  |  |  |  | 竞品图片、文字、Logo、SKU 结构、尺寸、性能、独特场景与布局 |",
        "",
        "## 自有 Listing 的机会映射",
        "",
        "| 市场机会 | 本 SKU 可用证据 | 等级 A / B / C | 自有图号 | 原创表现方法 | 待确认资料 | 不可迁移 / 禁止项 |",
        "|---|---|---|---|---|---|---|",
        "|  |  |  |  |  |  | 竞品图片、文案、Logo、几何结构、独特场景组合 |",
        "",
        "## 图需制作卡清单",
        "",
        "每张最终图必须在 `01_plan/` 有独立制作卡，完整字段见 `listing-image-requirement-card-template.md`。制作卡须包含竞品洞察、A/B/C 事实、卖点证据、场景与机位差异、构图、风格、文案来源、一体化成品排版、完整提示词、文件和 P0/P1 QC。",
        "",
        "| 图号 | 文件名 | 唯一购买问题 | 场景 / 机位差异 | 文案状态 | 制作卡路径 |",
        "|---:|---|---|---|---|---|",
        "|  |  |  |  |  |  |",
        "",
        "## 研究结论",
        "",
        "- 可采用的图序与证据方法：",
        "- 本 SKU 可视觉化的 A 级差异点：",
        "- B 级资料需求：",
        "- C 级禁止宣称：",
        "- 下一步：更新 `01_plan/image-plan.md`，然后再写提示词。",
        "",
    ])
    output = Path(args.out)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines), encoding="utf-8")
    print(f"Created {output} from {len(downloaded)} downloaded gallery image rows")


if __name__ == "__main__":
    main()
