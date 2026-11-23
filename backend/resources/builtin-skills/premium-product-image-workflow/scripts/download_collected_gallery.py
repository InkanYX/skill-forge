#!/usr/bin/env python3
"""Download only explicitly collected public product-gallery image URLs.

This utility does not open marketplace pages, inspect HTML, discover products,
construct URLs, bypass access controls, or use proxies. Supply one CSV row per
image after collecting URLs from the normal, public browser-rendered product
media gallery.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import mimetypes
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

MAX_BYTES = 15 * 1024 * 1024
EXTENSIONS = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
}
REQUIRED_COLUMNS = {"asin", "gallery_position", "image_url", "product_url"}
OPTIONAL_COLUMNS = {"page_rank", "title", "image_role", "source_checked_at"}


def safe_part(value: str, fallback: str) -> str:
    value = re.sub(r"[^A-Za-z0-9._-]+", "_", value.strip())
    return (value[:100].strip("._") or fallback)


def extension(content_type: str, url: str) -> str | None:
    value = content_type.split(";", 1)[0].strip().lower()
    if value in EXTENSIONS:
        return EXTENSIONS[value]
    suffix = Path(urllib.parse.urlparse(url).path).suffix.lower()
    return suffix if suffix in set(EXTENSIONS.values()) else None


def download(url: str, target_base: Path) -> tuple[str, str]:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {"https", "http"} or not parsed.netloc:
        return "skipped", "invalid public http(s) image URL"
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (public-gallery-research/1.0)"})
    try:
        with urllib.request.urlopen(request, timeout=25) as response:
            size = response.headers.get("Content-Length")
            if size and int(size) > MAX_BYTES:
                return "skipped", "image exceeds 15 MiB limit"
            suffix = extension(response.headers.get("Content-Type", ""), url)
            if not suffix:
                return "skipped", "unsupported or missing image content type"
            target = target_base.with_suffix(suffix)
            target.parent.mkdir(parents=True, exist_ok=True)
            total = 0
            with target.open("wb") as output:
                while chunk := response.read(64 * 1024):
                    total += len(chunk)
                    if total > MAX_BYTES:
                        output.close()
                        target.unlink(missing_ok=True)
                        return "skipped", "image exceeds 15 MiB limit"
                    output.write(chunk)
            return "downloaded", str(target)
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, ValueError) as error:
        return "failed", str(error)


def main() -> None:
    parser = argparse.ArgumentParser(description="Download explicitly collected public product gallery images.")
    parser.add_argument("--input", required=True, help="CSV with one browser-collected product-gallery image URL per row")
    parser.add_argument("--output-dir", required=True, help="Directory for ASIN subfolders and manifest.csv")
    parser.add_argument("--max-images-per-product", type=int, default=10, help="Safety cap per ASIN (default: 10)")
    args = parser.parse_args()
    if not 1 <= args.max_images_per_product <= 20:
        raise SystemExit("--max-images-per-product must be between 1 and 20")

    with Path(args.input).open(newline="", encoding="utf-8-sig") as file:
        reader = csv.DictReader(file)
        if not reader.fieldnames or not REQUIRED_COLUMNS.issubset(reader.fieldnames):
            missing = ", ".join(sorted(REQUIRED_COLUMNS - set(reader.fieldnames or [])))
            raise SystemExit(f"Input CSV missing required columns: {missing}")
        rows = list(reader)

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    per_asin: dict[str, int] = {}
    manifest = []
    now = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")

    for row_number, row in enumerate(rows, start=2):
        asin = safe_part(row.get("asin", ""), f"unknown_{row_number}")
        role = (row.get("image_role") or "gallery").strip().lower()
        position_raw = (row.get("gallery_position") or "").strip()
        try:
            position = int(position_raw)
        except ValueError:
            manifest.append({**row, "download_status": "skipped", "local_path": "", "error": "gallery_position must be an integer", "downloaded_at": now})
            continue
        per_asin[asin] = per_asin.get(asin, 0) + 1
        if per_asin[asin] > args.max_images_per_product:
            manifest.append({**row, "download_status": "skipped", "local_path": "", "error": "per-ASIN safety cap reached", "downloaded_at": now})
            continue
        filename = f"{position:02d}_{safe_part(role, 'gallery')}_{hashlib.sha1(row['image_url'].encode()).hexdigest()[:8]}"
        status, detail = download(row["image_url"].strip(), output_dir / asin / filename)
        manifest.append({**row, "download_status": status, "local_path": detail if status == "downloaded" else "", "error": "" if status == "downloaded" else detail, "downloaded_at": now})

    fields = list(dict.fromkeys([*(reader.fieldnames or []), "download_status", "local_path", "error", "downloaded_at"]))
    with (output_dir / "manifest.csv").open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(manifest)
    print(f"Wrote {output_dir / 'manifest.csv'}")
    print(f"Processed {len(manifest)} browser-collected gallery image rows")


if __name__ == "__main__":
    main()
