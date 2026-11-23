#!/usr/bin/env python3
"""Create a Markdown reference-to-output comparison sheet for manual image QA."""

from __future__ import annotations

import argparse
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a manual reference-to-output comparison sheet.")
    parser.add_argument("--count", type=int, required=True, help="Number of output images to review")
    parser.add_argument("--attributes", required=True, help="Comma-separated high-risk product attributes to compare")
    parser.add_argument("--out", required=True, help="Output Markdown path")
    args = parser.parse_args()
    if args.count < 1:
        raise SystemExit("--count must be at least 1")
    attributes = [item.strip() for item in args.attributes.split(",") if item.strip()]
    if not attributes:
        raise SystemExit("Provide at least one --attributes item")

    lines = [
        "# 产品身份参考对照表",
        "",
        "- 产品身份参考图：",
        "- 复核人 / 日期：",
        "- 判定规则：关键属性错误 = P0；无法判断或关键结构被遮挡 = P1；其余问题按质量闸门分级。",
        "",
    ]
    for index in range(1, args.count + 1):
        lines.extend([
            f"## 图 {index:02d}",
            "- 成图文件 / 版本：",
            "- 图的唯一职责：",
            "- 商品身份结论：通过 / P0 / P1",
            "",
            "| 对照属性 | 参考图中的确认状态 | 成图观察与证据位置 | 判定（通过 / 不确定 / 错误） | 缺陷等级 / 返工动作 |",
            "|---|---|---|---|---|",
        ])
        lines.extend(f"| {attribute} |  |  |  |  |" for attribute in attributes)
        lines.extend(["", "- 非目标区域是否被改动：", "- 文案 / 数据状态：", "- 复检结论：", ""])
    output = Path(args.out)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines), encoding="utf-8")
    print(f"Created {output}")


if __name__ == "__main__":
    main()
