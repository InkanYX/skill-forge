#!/usr/bin/env python3
"""Read one curated visual recipe; templates never establish product facts."""
import argparse
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("list", "show"))
    parser.add_argument("id", nargs="?")
    args = parser.parse_args()
    catalog = json.loads((Path(__file__).resolve().parents[1] / "assets" / "scenario-catalog.json").read_text(encoding="utf-8"))
    if args.command == "list":
        result = [{"id": row["id"], "name": row["name"]} for row in catalog["scenarios"]]
    else:
        result = next((row for row in catalog["scenarios"] if row["id"] == args.id), None)
        if result is None:
            parser.error("Unknown scenario ID; use list first")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
