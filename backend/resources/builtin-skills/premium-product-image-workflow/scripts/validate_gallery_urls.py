#!/usr/bin/env python3
"""Validate a browser-collected product-gallery CSV before any downloads.

This utility only reads a local CSV and writes a local Markdown report. It does
not contact marketplace pages or image URLs.
"""

from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse


REQUIRED_COLUMNS = {"asin", "gallery_position", "image_role", "image_url", "product_url"}
ALLOWED_ROLES = {"main", "gallery", "video_poster"}


def is_public_http_url(value: str) -> bool:
    parsed = urlparse(value.strip())
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def add_issue(issues: list[dict[str, str]], severity: str, row: int, asin: str, message: str) -> None:
    issues.append({"severity": severity, "row": str(row), "asin": asin or "(empty)", "message": message})


def validate(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    grouped: dict[str, list[tuple[int, dict[str, str], int | None]]] = defaultdict(list)

    for row_number, row in enumerate(rows, start=2):
        asin = row.get("asin", "").strip()
        if not asin:
            add_issue(issues, "error", row_number, asin, "asin is required")
        if not is_public_http_url(row.get("image_url", "")):
            add_issue(issues, "error", row_number, asin, "image_url must be an explicit http(s) URL")
        if not is_public_http_url(row.get("product_url", "")):
            add_issue(issues, "error", row_number, asin, "product_url must be an http(s) URL")
        role = row.get("image_role", "").strip().lower()
        if role not in ALLOWED_ROLES:
            add_issue(issues, "error", row_number, asin, f"image_role must be one of: {', '.join(sorted(ALLOWED_ROLES))}")
        try:
            position = int(row.get("gallery_position", "").strip())
            if position < 1:
                raise ValueError
        except ValueError:
            position = None
            add_issue(issues, "error", row_number, asin, "gallery_position must be a positive integer")
        if row.get("source_checked_at", "").strip():
            try:
                datetime.fromisoformat(row["source_checked_at"].strip().replace("Z", "+00:00"))
            except ValueError:
                add_issue(issues, "warning", row_number, asin, "source_checked_at is not ISO 8601")
        else:
            add_issue(issues, "warning", row_number, asin, "source_checked_at is empty")
        grouped[asin].append((row_number, row, position))

    for asin, entries in grouped.items():
        valid_positions = [(number, row, position) for number, row, position in entries if position is not None]
        positions: dict[int, list[int]] = defaultdict(list)
        urls: dict[str, list[int]] = defaultdict(list)
        product_urls = {row.get("product_url", "").strip() for _, row, _ in entries if row.get("product_url", "").strip()}
        for number, row, position in valid_positions:
            positions[position].append(number)
            urls[row.get("image_url", "").strip()].append(number)
        for position, row_numbers in positions.items():
            if len(row_numbers) > 1:
                add_issue(issues, "error", row_numbers[0], asin, f"gallery_position {position} is duplicated (rows {', '.join(map(str, row_numbers))})")
        observed = set(positions)
        if observed and observed != set(range(1, max(observed) + 1)):
            add_issue(issues, "error", valid_positions[0][0], asin, "gallery positions must be continuous, starting at 1")
        first = [(number, row) for number, row, position in valid_positions if position == 1]
        if first and first[0][1].get("image_role", "").strip().lower() != "main":
            add_issue(issues, "error", first[0][0], asin, "gallery position 1 must use image_role main")
        for number, row, position in valid_positions:
            if position and position > 1 and row.get("image_role", "").strip().lower() == "main":
                add_issue(issues, "error", number, asin, "only gallery position 1 may use image_role main")
        for url, row_numbers in urls.items():
            if url and len(row_numbers) > 1:
                add_issue(issues, "warning", row_numbers[0], asin, f"image_url repeats in rows {', '.join(map(str, row_numbers))}")
        if len(product_urls) > 1:
            add_issue(issues, "error", entries[0][0], asin, "all rows for an ASIN must have the same product_url")
    return issues


def write_report(path: Path, issues: list[dict[str, str]], row_count: int) -> None:
    errors = sum(issue["severity"] == "error" for issue in issues)
    warnings = len(issues) - errors
    lines = [
        "# 商品图库 CSV 预检报告",
        "",
        f"- 输入行数：{row_count}",
        f"- 错误：{errors}",
        f"- 警告：{warnings}",
        f"- 结果：{'可下载' if not errors else '先修复错误，再下载'}",
        "",
        "| 级别 | CSV 行 | ASIN | 问题 |",
        "|---|---:|---|---|",
    ]
    for issue in issues:
        message = issue["message"].replace("|", "\\|")
        lines.append(f"| {issue['severity']} | {issue['row']} | {issue['asin']} | {message} |")
    if not issues:
        lines.append("| info | - | - | 未发现结构问题。下载前仍应确认每行均来自当前商品的可见图库节点。 |")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate a local browser-collected product-gallery CSV.")
    parser.add_argument("--input", required=True, help="CSV with one explicit gallery image URL per row")
    parser.add_argument("--report", required=True, help="Markdown validation report path")
    parser.add_argument("--strict", action="store_true", help="Exit non-zero for warnings as well as errors")
    args = parser.parse_args()

    with Path(args.input).open(newline="", encoding="utf-8-sig") as file:
        reader = csv.DictReader(file)
        fields = set(reader.fieldnames or [])
        missing = sorted(REQUIRED_COLUMNS - fields)
        if missing:
            raise SystemExit(f"Input CSV missing required columns: {', '.join(missing)}")
        rows = list(reader)
    issues = validate(rows)
    write_report(Path(args.report), issues, len(rows))
    errors = sum(issue["severity"] == "error" for issue in issues)
    warnings = len(issues) - errors
    print(f"Validated {len(rows)} rows: {errors} error(s), {warnings} warning(s)")
    if errors or (args.strict and warnings):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
