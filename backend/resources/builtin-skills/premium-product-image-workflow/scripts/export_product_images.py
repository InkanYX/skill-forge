#!/usr/bin/env python3
"""Proportional exports with no implicit crop, overwrite or input reordering."""
import argparse
import hashlib
import json
import math
from pathlib import Path
from PIL import Image, ImageOps


SIZES = {"header": (970, 600), "banner": (970, 300), "tile300": (300, 300),
         "tile220": (220, 220), "premium": (1464, 600),
         "premium-mobile": (600, 450), "brand-story": (1464, 625)}


def dimensions(text):
    try:
        width, height = map(int, text.lower().split("x"))
        if min(width, height) <= 0 or width * height > 150_000_000:
            raise ValueError()
        return width, height
    except ValueError:
        raise argparse.ArgumentTypeError("Expected positive WxH, at most 150 million pixels")


def load(path):
    with Image.open(path) as source:
        return ImageOps.exif_transpose(source).convert("RGB")


def image_record(path):
    path = Path(path).resolve()
    with Image.open(path) as source:
        size = list(source.size)
    return {"path": str(path), "pixels": size, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def fitted(image, size, background):
    scaled = ImageOps.contain(image, size, Image.Resampling.LANCZOS)
    canvas = Image.new("RGB", size, background)
    canvas.paste(scaled, ((size[0] - scaled.width) // 2, (size[1] - scaled.height) // 2))
    return canvas


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="mode", required=True)
    resize = sub.add_parser("resize")
    resize.add_argument("images", nargs=1)
    target = resize.add_mutually_exclusive_group(required=True)
    target.add_argument("--size", type=dimensions)
    target.add_argument("--module", choices=SIZES)
    resize.add_argument("--fit", choices=("strict", "contain"), default="strict")
    resize.add_argument("--crop", help="Explicit reviewed background crop: x0,y0,x1,y1")
    grid = sub.add_parser("grid")
    grid.add_argument("images", nargs="+")
    grid.add_argument("--cols", type=int, default=2)
    grid.add_argument("--cell", type=dimensions, default=(732, 300))
    grid.add_argument("--gap", type=int, default=16)
    stitch = sub.add_parser("stitch")
    stitch.add_argument("images", nargs="+")
    stitch.add_argument("--width", type=int, default=750)
    for child in (resize, grid, stitch):
        child.add_argument("--out", required=True)
        child.add_argument("--background", default="#FFFFFF")
    args = parser.parse_args()
    output = Path(args.out).resolve()
    sidecar = output.with_name(output.name + ".export.json")
    if output.exists() or sidecar.exists():
        raise ValueError("Output or export record already exists; choose a new version")
    inputs = [image_record(path) for path in args.images]
    if args.mode == "resize":
        image = load(args.images[0])
        if args.crop:
            box = tuple(map(int, args.crop.split(",")))
            if len(box) != 4 or not (0 <= box[0] < box[2] <= image.width and 0 <= box[1] < box[3] <= image.height):
                raise ValueError("Invalid crop box")
            image = image.crop(box)
        size = SIZES[args.module] if args.module else args.size
        if args.fit == "strict" and abs((image.width / image.height) / (size[0] / size[1]) - 1) > .01:
            raise ValueError("Aspect ratio differs by more than 1%; use reviewed crop or explicit --fit contain")
        result = fitted(image, size, args.background)
    elif args.mode == "grid":
        if args.cols <= 0 or args.gap < 0:
            raise ValueError("cols must be positive and gap nonnegative")
        rows = math.ceil(len(args.images) / args.cols)
        size = (args.cols * args.cell[0] + (args.cols + 1) * args.gap,
                rows * args.cell[1] + (rows + 1) * args.gap)
        if size[0] * size[1] > 150_000_000:
            raise ValueError("Grid too large")
        result = Image.new("RGB", size, args.background)
        for index, path in enumerate(args.images):
            row, col = divmod(index, args.cols)
            result.paste(fitted(load(path), args.cell, args.background),
                         (args.gap + col * (args.cell[0] + args.gap), args.gap + row * (args.cell[1] + args.gap)))
    else:
        if args.width <= 0:
            raise ValueError("width must be positive")
        images = []
        for path in args.images:
            image = load(path)
            images.append(image.resize((args.width, max(1, round(image.height * args.width / image.width))), Image.Resampling.LANCZOS))
        size = (args.width, sum(image.height for image in images))
        if size[0] * size[1] > 150_000_000:
            raise ValueError("Long image too large")
        result = Image.new("RGB", size, args.background)
        offset = 0
        for image in images:
            result.paste(image, (0, offset))
            offset += image.height
    format_name = {".png": "PNG", ".jpg": "JPEG", ".jpeg": "JPEG", ".webp": "WEBP"}.get(output.suffix.lower())
    if not format_name:
        raise ValueError("Choose PNG, JPEG or WebP")
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("xb") as stream:
        result.save(stream, format=format_name, **({"quality": 95} if format_name != "PNG" else {}))
    record = {"operation": args.mode, "inputs": inputs, "output": image_record(output),
              "crop": getattr(args, "crop", None), "fit": getattr(args, "fit", "contain"),
              "note": "Derivative export; original files retained. No platform or SKU certification."}
    with sidecar.open("x", encoding="utf-8") as stream:
        json.dump(record, stream, ensure_ascii=False, indent=2)
    print(json.dumps(record, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError) as error:
        raise SystemExit(f"Export error: {error}")
