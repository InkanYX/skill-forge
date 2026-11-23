#!/usr/bin/env python3
"""Check a local product-image prompt for common, text-detectable risks.

The linter does not access images, generate content, or verify product facts. It flags
unfilled variables and potentially contradictory instructions for human review.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path


def add_issue(issues: list[tuple[str, str]], severity: str, message: str) -> None:
    issues.append((severity, message))


def has(text: str, pattern: str) -> bool:
    return bool(re.search(pattern, text, flags=re.IGNORECASE | re.DOTALL))


def lint(text: str, route: str) -> list[tuple[str, str]]:
    issues: list[tuple[str, str]] = []
    placeholders = sorted(set(re.findall(r"\[[^\]\n]{1,100}\]", text)))
    if placeholders:
        add_issue(issues, "error", f"Unfilled bracket variables: {', '.join(placeholders[:8])}")
    if has(text, r"exact (same )?(sellable )?sku|strict product identity") and not has(text, r"reference\s*1|product identity reference"):
        add_issue(issues, "warning", "SKU-lock language appears without a named product identity reference.")
    if route == "local-edit":
        if not has(text, r"\bedit only\b"):
            add_issue(issues, "warning", "Local-edit route normally begins with 'Edit only [precise target]'.")
        if has(text, r"\bfrom scratch\b|\bentirely new\b|\bcompletely redesign\b"):
            add_issue(issues, "error", "Local-edit route conflicts with a from-scratch or full-redesign instruction.")
    if route == "main-image":
        if has(text, r"\b(add|include|place)\b[^.\n]{0,50}\b(text|badge|watermark|border|logo|person|prop)\b"):
            add_issue(issues, "error", "Main-image route asks to add an element that is commonly non-compliant; confirm platform rules and remove it when inappropriate.")
        if not has(text, r"white background|rgb\s*\(?255\s*,\s*255\s*,\s*255\)?"):
            add_issue(issues, "warning", "Main-image route does not state a clean white background; confirm the target platform requirement.")
    environment_change = has(text, r"replace only the background|replace the background|transform only the sky|change the sky|new environment")
    environment_lock = has(text, r"do not change (the )?(background|sky|environment)|preserve (the )?(background|sky|environment) exactly")
    if environment_change and environment_lock:
        add_issue(issues, "error", "The prompt both changes and locks the background, sky, or environment.")
    if route == "finished-image":
        sections = (
            "Task and selling objective", "Reference roles", "Product identity lock",
            "Scene and camera", "Composition and hierarchy",
            "Art direction and physical realism", "Exact copy",
            "Typography and graphic layout", "Strict exclusions", "Output",
        )
        missing = [section for section in sections if not has(text, r"(?m)^\s*" + re.escape(section) + r"\s*:")]
        if missing:
            add_issue(issues, "error", "Finished-image prompt is missing sections: " + ", ".join(missing))
        base_instructions = (
            r"(?m)^\s*(?:Task:\s*)?(?:create|generate)\b[^.\n]{0,160}\b(?:no-text|text-free|unlettered)\b",
            r"(?m)^\s*(?:do not generate (?:any )?text|leave clean negative space for verified copy|leave all text for|add (?:all )?(?:copy|text) later)\b",
            r"\bcopy to be added later in a deterministic design tool\b",
        )
        if any(has(text, pattern) for pattern in base_instructions):
            add_issue(issues, "error", "Finished-image route conflicts with instructions to generate an unlettered base or postpone copy.")
        copy_match = re.search(r"(?ims)^\s*Exact copy\s*:(.*?)(?=^\s*Typography and graphic layout\s*:|\Z)", text)
        if copy_match and not re.search(r'[\"“][^\"”]+[\"”]', copy_match.group(1)):
            add_issue(issues, "error", "Exact copy must contain quoted final text, not instructions to invent suitable copy.")
    elif has(text, r"\btext\b|\bdimensions?\b|\bcertifications?\b") and not has(text, r"do not generate|no generated text"):
        add_issue(issues, "warning", "Verify every rendered word, number and unit against confirmed source copy; use finished-image for a complete listing design.")
    if not has(text, r"\boutput\s*:"):
        add_issue(issues, "warning", "No explicit Output section found for size, ratio, or delivery constraints.")
    return issues


def write_report(path: Path, route: str, issues: list[tuple[str, str]]) -> None:
    errors = sum(severity == "error" for severity, _ in issues)
    warnings = len(issues) - errors
    lines = [
        "# 商品图提示词预检报告",
        "",
        f"- 路由：{route}",
        f"- 错误：{errors}",
        f"- 警告：{warnings}",
        "- 限制：此报告只检查文本模式；它不验证 SKU、规格、平台合规或最终图像。",
        "",
        "| 级别 | 结果 |",
        "|---|---|",
    ]
    if issues:
        lines.extend(f"| {severity} | {message} |" for severity, message in issues)
    else:
        lines.append("| info | 未发现可由文本规则识别的问题。仍须按 brief 和质量闸门人工验收。 |")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Lint a local product-image prompt before generation or editing.")
    parser.add_argument("--input", required=True, help="UTF-8 text or Markdown file containing one prompt")
    parser.add_argument("--route", choices=["general", "local-edit", "main-image", "finished-image"], default="general")
    parser.add_argument("--report", required=True, help="Output Markdown report")
    parser.add_argument("--strict", action="store_true", help="Exit non-zero for warnings as well as errors")
    args = parser.parse_args()
    issues = lint(Path(args.input).read_text(encoding="utf-8-sig"), args.route)
    write_report(Path(args.report), args.route, issues)
    errors = sum(severity == "error" for severity, _ in issues)
    warnings = len(issues) - errors
    print(f"Linted prompt: {errors} error(s), {warnings} warning(s)")
    if errors or (args.strict and warnings):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
