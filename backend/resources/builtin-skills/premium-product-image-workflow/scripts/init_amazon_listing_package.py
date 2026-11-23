#!/usr/bin/env python3
"""Create a non-destructive Amazon Listing image-production package."""

from __future__ import annotations

import argparse
from pathlib import Path
from project_memory import save


DIRECTORIES = (
    "00_research",
    "00_brief",
    "01_plan",
    "02_prompts",
    "03_generated",
    "04_layout",
    "05_qc",
    "06_final",
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Initialize a standard Amazon Listing image-production package.")
    parser.add_argument("--out", required=True, help="New package directory; it must not already exist")
    parser.add_argument("--name", required=True, help="Listing or SKU label written into the package brief")
    args = parser.parse_args()

    output = Path(args.out)
    if output.exists():
        raise SystemExit(f"Output directory already exists: {output}")
    template = Path(__file__).resolve().parent.parent / "assets" / "amazon-listing-brief-template.md"
    if not template.exists():
        raise SystemExit(f"Brief template not found: {template}")

    output.mkdir(parents=True)
    for folder in DIRECTORIES:
        (output / folder).mkdir()
    brief = template.read_text(encoding="utf-8").replace("- Listing / SKU 版本：", f"- Listing / SKU 版本：{args.name}")
    (output / "00_brief" / "amazon-listing-brief.md").write_text(brief, encoding="utf-8")
    research_template = Path(__file__).resolve().parent.parent / "assets" / "competitor-visual-intelligence-template.md"
    if not research_template.exists():
        raise SystemExit(f"Competitor research template not found: {research_template}")
    (output / "00_research" / "competitor-visual-intelligence.md").write_text(
        research_template.read_text(encoding="utf-8"), encoding="utf-8"
    )
    (output / "01_plan" / "image-plan.md").write_text(
        "# Listing 图序计划\n\n先完成 `00_brief/amazon-listing-brief.md` 的 A/B/C 事实分级。完整套图或竞品驱动图需必须读取 `listing-image-requirement-card-template.md`，并为每张图创建独立制作卡；简表不能代替制作卡。\n",
        encoding="utf-8",
    )
    card_template = Path(__file__).resolve().parent.parent / "assets" / "listing-image-requirement-card.md"
    if not card_template.exists():
        raise SystemExit(f"Image requirement card template not found: {card_template}")
    (output / "01_plan" / "listing-image-requirement-card-template.md").write_text(
        card_template.read_text(encoding="utf-8"), encoding="utf-8"
    )
    (output / "05_qc" / "delivery-report.md").write_text(
        "# Listing 图片交付报告\n\n- 项目：" + args.name + "\n- 生产模式：直接生成含文案与排版的最终成品（主图无文字）\n- P0/P1 关闭状态：\n- 目标站点规则最终复核：\n- AIGC 标识 / 元数据：\n",
        encoding="utf-8",
    )
    save(output / "project-state.json", {
        "schema_version": 1, "project_id": args.name, "revision": 0,
        "context": {"identity_and_facts": [], "references": [], "exact_copy": {},
                    "campaign_style": {}, "generation_profile": {}, "authorization_notes": []},
        "jobs": {}, "history": [],
    }, "init-package")
    print(f"Created Amazon Listing image package: {output}")
    print("Created directories: " + ", ".join(DIRECTORIES))


if __name__ == "__main__":
    main()
