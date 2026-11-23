#!/usr/bin/env python3
"""Local project ledger. Never calls a model or interprets stored text as code."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import tempfile
from datetime import datetime, timezone


def stamp():
    return datetime.now(timezone.utc).isoformat()


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def fingerprint(path):
    path = Path(path).resolve()
    if not path.is_file():
        raise ValueError(f"File not found: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return {"path": str(path), "sha256": digest.hexdigest()}


def valid_file(record):
    if not record:
        return False
    try:
        return fingerprint(record["path"])["sha256"] == record["sha256"]
    except (ValueError, OSError, KeyError):
        return False


def new_job(job_id, kind, purpose):
    return {"id": job_id, "kind": kind, "purpose": purpose, "prompt": None,
            "references": [], "generated": None,
            "review": {"status": "pending", "issues": []}, "export": None}


def classify(job):
    if not job.get("generated"):
        return "planned"
    if not valid_file(job["generated"]):
        return "missing_or_changed"
    review = job.get("review", {})
    if review.get("status") == "repair" or any(i in ("P0", "P1") for i in review.get("issues", [])):
        return "repair"
    if review.get("status") != "pass":
        return "needs_review"
    if review.get("source_sha256") != job["generated"]["sha256"] or not valid_file(review.get("evidence")):
        return "needs_review"
    if job.get("export"):
        return "complete" if valid_file(job["export"]) else "missing_or_changed"
    return "needs_export"


def save(path, data, event):
    data["revision"] += 1
    data["history"].append({"at": stamp(), "event": event})
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=".project-state-", suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(data, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        os.replace(temporary, path)
    finally:
        if temporary and temporary.exists():
            temporary.unlink()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("init", "add", "record", "summary", "import-manifest"):
        child = sub.add_parser(command)
        child.add_argument("--root", required=True)
        if command == "init":
            child.add_argument("--project-id", required=True)
        elif command == "add":
            child.add_argument("--id", required=True)
            child.add_argument("--kind", required=True)
            child.add_argument("--purpose", required=True)
            child.add_argument("--prompt")
            child.add_argument("--reference", action="append", default=[])
            child.add_argument("--based-on")
        elif command == "record":
            child.add_argument("--id", required=True)
            child.add_argument("--generated")
            child.add_argument("--review", choices=("pass", "repair", "pending"))
            child.add_argument("--evidence")
            child.add_argument("--issue", action="append", choices=("P0", "P1", "P2", "P3"), default=[])
            child.add_argument("--export")
            child.add_argument("--note", default="")
        elif command == "import-manifest":
            child.add_argument("--manifest", required=True)
            child.add_argument("--final-dir", required=True)
            child.add_argument("--qc-report")
    args = parser.parse_args()
    root = Path(args.root).resolve()
    state_path = root / "project-state.json"
    if args.command == "init":
        if state_path.exists():
            raise ValueError("Project state already exists; use summary to resume")
        state = {"schema_version": 1, "project_id": args.project_id, "revision": 0,
                 "context": {"identity_and_facts": [], "references": [], "exact_copy": {},
                             "campaign_style": {}, "generation_profile": {}, "authorization_notes": []},
                 "jobs": {}, "history": []}
    else:
        state = read_json(state_path)
        if state.get("schema_version") != 1:
            raise ValueError("Unsupported project-state schema")
    if args.command == "summary":
        rows = [{"id": key, "kind": job["kind"], "purpose": job["purpose"],
                 "status": classify(job)} for key, job in state["jobs"].items()]
        print(json.dumps({"project_id": state["project_id"], "revision": state["revision"],
                          "jobs": rows, "generation_needed": [r["id"] for r in rows if r["status"] in ("planned", "repair")],
                          "attention": [r["id"] for r in rows if r["status"] not in ("planned", "repair", "complete")]},
                         ensure_ascii=False, indent=2))
        return
    if args.command == "add":
        if args.id in state["jobs"]:
            raise ValueError("Job ID already exists; use a new version ID")
        job = new_job(args.id, args.kind, args.purpose)
        job["prompt"] = fingerprint(args.prompt) if args.prompt else None
        job["references"] = [fingerprint(path) for path in args.reference]
        if args.based_on:
            previous = state["jobs"][args.based_on]
            if not valid_file(previous.get("generated")):
                raise ValueError("Source job image is missing or changed")
            job["based_on"] = {"job_id": args.based_on, **previous["generated"]}
        state["jobs"][args.id] = job
    elif args.command == "record":
        job = state["jobs"][args.id]
        if args.generated:
            job["generated"] = fingerprint(args.generated)
            job["review"] = {"status": "pending", "issues": []}
            job["export"] = None
        if args.review:
            if not valid_file(job.get("generated")):
                raise ValueError("Cannot review missing or changed image")
            if args.review == "pass" and (not args.evidence or any(i in ("P0", "P1") for i in args.issue)):
                raise ValueError("Pass requires a review evidence file and no open P0/P1")
            job["review"] = {"status": args.review, "issues": args.issue,
                             "source_sha256": job["generated"]["sha256"], "note": args.note,
                             "evidence": fingerprint(args.evidence) if args.evidence else None}
            job["export"] = None
        elif args.issue:
            raise ValueError("--issue requires --review")
        if args.export:
            if classify(job) != "needs_export":
                raise ValueError("Export requires a current passing review with evidence")
            job["export"] = fingerprint(args.export)
    elif args.command == "import-manifest":
        records = read_json(args.manifest)
        if not isinstance(records, list):
            raise ValueError("Expected a list of export manifest records")
        final_dir = Path(args.final_dir).resolve()
        evidence = fingerprint(args.qc_report) if args.qc_report else None
        for record in records:
            job_id = record["id"]
            if job_id in state["jobs"]:
                raise ValueError(f"Job already exists: {job_id}")
            image_path = (final_dir / record["filename"]).resolve()
            if not image_path.is_relative_to(final_dir):
                raise ValueError("Manifest image path escapes final-dir")
            actual = fingerprint(image_path)
            if actual["sha256"] != record["sha256"].lower():
                raise ValueError(f"Manifest hash mismatch: {job_id}")
            job = new_job(job_id, "imported", "Imported existing export; inspect prior QC before reuse")
            job["generated"] = actual
            job["prior_export"] = actual
            job["prior_qc"] = evidence
            job["native_pixels"] = record.get("native_pixels")
            job["final_pixels"] = record.get("final_pixels")
            state["jobs"][job_id] = job
        # A matching hash or an old report does not automatically mark visual QC as passed.
    save(state_path, state, args.command)
    print(json.dumps({"ok": True, "state": str(state_path), "revision": state["revision"]}))


if __name__ == "__main__":
    try:
        main()
    except (ValueError, KeyError, OSError, json.JSONDecodeError) as error:
        raise SystemExit(f"Project memory error: {error}")
