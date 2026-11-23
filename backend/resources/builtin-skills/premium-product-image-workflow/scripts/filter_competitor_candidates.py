#!/usr/bin/env python3
"""Filter publicly collected competitor rows and optionally download explicit public image URLs.

This utility never discovers products, accesses marketplace pages, uses proxies, solves challenges,
or constructs image URLs. It only processes a local CSV supplied by the operator.
"""

from __future__ import annotations

import argparse
import csv
import html
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

IMAGE_TYPES = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp", "image/gif": ".gif"}
MAX_IMAGE_BYTES = 10 * 1024 * 1024
DEFAULT_MAX_IMAGES_PER_PRODUCT = 5


def split_terms(value: str) -> list[str]:
    return [term.strip().lower() for term in value.split(",") if term.strip()]


def normalized(text: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(text).lower()).strip()


def term_matches(haystack: str, term: str) -> bool:
    """Match an exact phrase first, then match every word in a multiword term."""
    if term in haystack:
        return True
    words = [word for word in re.findall(r"[a-z0-9]+", term) if word]
    return len(words) > 1 and all(re.search(rf"\b{re.escape(word)}\b", haystack) for word in words)


def score_title(title: str, keywords: Iterable[str], excluded: Iterable[str]) -> tuple[int, list[str], list[str]]:
    haystack = normalized(title)
    matched = [term for term in keywords if term_matches(haystack, term)]
    excluded_hits = [term for term in excluded if term_matches(haystack, term)]
    score = sum(4 if " " in term else 1 for term in matched)
    if excluded_hits:
        score -= 100
    return score, matched, excluded_hits


def page_rank(row: dict[str, str]) -> int:
    try:
        return int((row.get("page_rank") or "").strip())
    except ValueError:
        return 999999


def public_image_urls(raw: str) -> list[str]:
    urls = []
    for item in (raw or "").split("|"):
        url = item.strip()
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme in {"http", "https"} and parsed.netloc:
            urls.append(url)
    return urls


def safe_stem(value: str, fallback: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", value.strip())
    return (cleaned[:80] or fallback).strip("._") or fallback


def download_image(url: str, destination: Path) -> tuple[bool, str]:
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; competitor-research/1.0)"})
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            content_type = response.headers.get_content_type().lower()
            if content_type not in IMAGE_TYPES:
                return False, f"skipped: unsupported content type {content_type}"
            declared_length = response.headers.get("Content-Length")
            if declared_length and int(declared_length) > MAX_IMAGE_BYTES:
                return False, "skipped: image exceeds 10 MiB limit"
            suffix = IMAGE_TYPES[content_type]
            target = destination.with_suffix(suffix)
            written = 0
            with target.open("wb") as output:
                while True:
                    block = response.read(64 * 1024)
                    if not block:
                        break
                    written += len(block)
                    if written > MAX_IMAGE_BYTES:
                        output.close()
                        target.unlink(missing_ok=True)
                        return False, "skipped: image exceeds 10 MiB limit"
                    output.write(block)
            return True, str(target)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ValueError) as error:
        return False, f"failed: {error}"


def write_csv(rows: list[dict[str, str]], fields: list[str], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_report(rows: list[dict[str, str]], keywords: list[str], excluded: list[str], path: Path, downloads: dict[str, list[str]]) -> None:
    created = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    lines = [
        "# 公开竞品候选筛选报告",
        "",
        f"- 生成时间：{created}",
        f"- 标题关键词：{', '.join(keywords) or '未提供'}",
        f"- 排除词：{', '.join(excluded) or '未提供'}",
        f"- 入选候选：{len(rows)}",
        "- 数据边界：仅处理操作方从正常公开页面已获得的 CSV；页面排名仅为来源页面显示顺序，非独立核验 BSR。",
        "",
        "| 页面排名 | 标题 | ASIN | 命中词 | 得分 | 图片 URL 数 | 下载结果 | 来源 |",
        "|---:|---|---|---|---:|---:|---|---|",
    ]
    for row in rows:
        key = row.get("_key", "")
        files = "; ".join(downloads.get(key, [])) or "未下载"
        title = (row.get("title") or "").replace("|", "\\|")
        source = (row.get("product_url") or "").replace("|", "%7C")
        lines.append(
            f"| {row.get('page_rank', '')} | {title} | {row.get('asin', '')} | {row.get('keyword_hits', '')} | "
            f"{row.get('relevance_score', '')} | {len(public_image_urls(row.get('image_urls', '')))} | {files} | {source} |"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Filter locally collected competitor candidates by title keywords.")
    parser.add_argument("--input", required=True, help="Local CSV with at least a title column.")
    parser.add_argument("--keywords", required=True, help="Comma-separated relevant title keywords.")
    parser.add_argument("--exclude", default="", help="Comma-separated title exclusion terms.")
    parser.add_argument("--max-candidates", type=int, default=20, help="Maximum high-relevance rows to retain (default: 20).")
    parser.add_argument("--output", required=True, help="Filtered CSV output path.")
    parser.add_argument("--report", required=True, help="Markdown report output path.")
    parser.add_argument("--download-dir", help="Optional directory for explicit public image URLs from image_urls.")
    parser.add_argument("--max-images-per-product", type=int, default=DEFAULT_MAX_IMAGES_PER_PRODUCT)
    args = parser.parse_args()

    if not 1 <= args.max_candidates <= 100:
        raise SystemExit("--max-candidates must be between 1 and 100")
    if not 1 <= args.max_images_per_product <= 10:
        raise SystemExit("--max-images-per-product must be between 1 and 10")

    keywords, excluded = split_terms(args.keywords), split_terms(args.exclude)
    if not keywords:
        raise SystemExit("Provide at least one non-empty --keywords term")

    input_path = Path(args.input)
    with input_path.open(newline="", encoding="utf-8-sig") as file:
        reader = csv.DictReader(file)
        if not reader.fieldnames or "title" not in reader.fieldnames:
            raise SystemExit("Input CSV must include a 'title' column")
        source_fields = list(reader.fieldnames)
        processed = []
        for index, row in enumerate(reader, start=1):
            score, hits, excluded_hits = score_title(row.get("title", ""), keywords, excluded)
            if score <= 0 or excluded_hits:
                continue
            row = dict(row)
            row["keyword_hits"] = ", ".join(hits)
            row["relevance_score"] = str(score)
            row["_key"] = f"{index}:{row.get('asin', '')}:{row.get('title', '')}"
            processed.append(row)

    processed.sort(key=lambda row: (-int(row["relevance_score"]), page_rank(row), row.get("title", "")))
    selected = processed[: args.max_candidates]

    download_results: dict[str, list[str]] = {}
    if args.download_dir:
        target_dir = Path(args.download_dir)
        target_dir.mkdir(parents=True, exist_ok=True)
        for candidate_index, row in enumerate(selected, start=1):
            product_id = safe_stem(row.get("asin", ""), f"candidate_{candidate_index:02d}")
            results = []
            for image_index, url in enumerate(public_image_urls(row.get("image_urls", ""))[: args.max_images_per_product], start=1):
                ok, result = download_image(url, target_dir / f"{candidate_index:02d}_{product_id}_{image_index:02d}")
                results.append(result if ok else f"{url} ({result})")
            download_results[row["_key"]] = results

    fields = source_fields + [field for field in ["keyword_hits", "relevance_score"] if field not in source_fields]
    for row in selected:
        row.pop("_key", None)
    write_csv(selected, fields, Path(args.output))

    # Rebuild internal keys solely for report/download lookup after CSV cleanup.
    for index, row in enumerate(selected, start=1):
        row["_key"] = f"report:{index}:{row.get('asin', '')}:{row.get('title', '')}"
    if download_results:
        # Download results correspond to selection order; remap them deterministically.
        values = list(download_results.values())
        download_results = {row["_key"]: values[index] for index, row in enumerate(selected) if index < len(values)}
    write_report(selected, keywords, excluded, Path(args.report), download_results)

    print(f"Selected {len(selected)} candidates from {input_path}")
    print(f"Wrote {args.output}")
    print(f"Wrote {args.report}")
    if args.download_dir:
        print(f"Downloaded only explicit public image URLs to {args.download_dir}")


if __name__ == "__main__":
    main()
