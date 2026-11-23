#!/usr/bin/env python3
"""Create a Markdown quality checklist for a product image delivery batch."""

from __future__ import annotations

import argparse
from pathlib import Path

CHECKS = [
    "同一可售 SKU、关键部件数量和连接关系正确",
    "无新增、缺失、重复、替换、拉伸、扭曲或错误透视",
    "材质、颜色、纹理、接缝和五金与参考一致",
    "光源、高光、阴影、反射、环境色和尺度关系可信",
    "商品为视觉中心，且每张图只有一个明确任务",
    "文字、数字、单位、参数和宣称均已确认并可读",
    "主图无文字、图标、徽章、Logo、水印、边框、人物、道具和非售卖物",
    "已按平台规则和适用 AIGC 标识要求复核",
]


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate an image-delivery QC checklist in Markdown.")
    parser.add_argument("--count", type=int, required=True, help="Number of images in the batch.")
    parser.add_argument("--out", required=True, help="Output Markdown path.")
    args = parser.parse_args()
    if args.count < 1:
        raise SystemExit("--count must be at least 1")

    lines = ["# 商品图交付质检表", ""]
    for index in range(1, args.count + 1):
        lines.extend([f"## 图 {index}", "- 名称 / 职责：", "- 输出规格：", "- 已确认数据来源："])
        lines.extend(f"- [ ] {check}" for check in CHECKS)
        lines.extend(["- 缺陷等级：通过 / P0 / P1 / P2 / P3", "- 返工动作：", ""])
    output = Path(args.out)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines), encoding="utf-8")
    print(f"Created {output}")


if __name__ == "__main__":
    main()
