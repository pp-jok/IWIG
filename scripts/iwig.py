#!/usr/bin/env python3
"""The single stable IWIG command line entrypoint."""
from __future__ import annotations
import argparse
import contextlib
import json
import os
import sys
from datetime import datetime
from pathlib import Path

from build_analysis_index import validate_analysis_index_schema, write_analysis_index
from content_package import atomic_write_json, file_record, find_existing_package, validate_content_package
import run_capture
from public_html_provider import note_id_from_url

HOME = Path(os.environ.get("IWIG_HOME", Path.home() / ".iwig"))


def _result(run: Path, package: dict) -> dict:
    return {"status": package["status"], "run_dir": str(run), "content_package": str(run / "content_package.json"), "analysis_index": str(run / "derived" / "analysis_index.json"), "report": str(run / "report.md")}


def validate(run: Path) -> dict:
    package_path = run / "content_package.json"
    try:
        package = json.loads(package_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        return {"valid": False, "errors": [f"package_unreadable:{type(error).__name__}"], "warnings": []}
    errors, warnings = validate_content_package(package), []
    for record in [item for item in [package.get("media", {}).get("video"), package.get("media", {}).get("cover")] if item] + package.get("media", {}).get("images", []):
        path = run / record.get("path", "")
        if not path.is_file(): errors.append(f"missing_artifact:{record.get('path')}")
        elif record.get("sha256") and file_record(path, run)["sha256"] != record["sha256"]: errors.append(f"hash_mismatch:{record['path']}")
    index_path = run / "derived" / "analysis_index.json"
    if index_path.is_file():
        try:
            index = json.loads(index_path.read_text(encoding="utf-8")); errors += validate_analysis_index_schema(index)
            if index.get("source_package", {}).get("sha256") != file_record(package_path, run)["sha256"]: errors.append("analysis_index_stale")
        except (OSError, json.JSONDecodeError) as error: errors.append(f"analysis_index_unreadable:{type(error).__name__}")
    else: warnings.append("analysis_index_missing")
    output = {"valid": not errors, "errors": errors, "warnings": warnings}; atomic_write_json(run / "processing" / "validation.json", output); return output


def _capture_run_dir(args) -> Path:
    if args.run_dir: return Path(args.run_dir).expanduser().resolve()
    return Path(args.output_dir).expanduser().resolve() / datetime.now().strftime("%Y%m%d-%H%M%S-%f")


def main() -> int:
    parser = argparse.ArgumentParser(prog="iwig"); sub = parser.add_subparsers(dest="command", required=True)
    setup = sub.add_parser("setup"); setup.add_argument("--home"); setup.add_argument("--dry-run", action="store_true")
    capture = sub.add_parser("capture")
    capture.add_argument("--url", required=True); capture.add_argument("--output-dir", default=str(HOME / "output")); capture.add_argument("--run-dir"); capture.add_argument("--timeout", type=float, default=20); capture.add_argument("--max-video-mb", type=int, default=300); capture.add_argument("--force", action="store_true"); capture.add_argument("--keyframes", action="store_true"); capture.add_argument("--ocr", action="store_true"); capture.add_argument("--keep-raw-source", action="store_true"); capture.add_argument("--json", action="store_true")
    enrich = sub.add_parser("enrich"); enrich.add_argument("run_dir"); enrich.add_argument("--keyframes", action="store_true"); enrich.add_argument("--ocr", action="store_true")
    for name in ("reindex", "validate"): sub.add_parser(name).add_argument("run_dir")
    migrate = sub.add_parser("migrate-legacy-home"); migrate.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if args.command == "setup":
        from setup import main as setup_main
        forwarded = ([] if not args.home else ["--home", args.home]) + (["--dry-run"] if args.dry_run else [])
        return setup_main(forwarded)
    if args.command == "migrate-legacy-home":
        from migrate_legacy_home import main as migrate_main
        return migrate_main(["--dry-run"] if args.dry_run else [])
    if args.command == "validate":
        outcome = validate(Path(args.run_dir)); print(json.dumps(outcome)); return 0 if outcome["valid"] else 5
    if args.command == "reindex":
        try: print(write_analysis_index(Path(args.run_dir))); return 0
        except ValueError as error: print(str(error), file=sys.stderr); return 5
    if args.command == "enrich":
        code = run_capture.main(["--enrich-dir", args.run_dir] + (["--keyframes"] if args.keyframes else []) + (["--ocr"] if args.ocr else []))
        run = Path(args.run_dir).expanduser().resolve()
        if (run / "content_package.json").is_file(): write_analysis_index(run)
        return code
    root = Path(args.output_dir).expanduser().resolve()
    existing = None if args.run_dir or args.force else find_existing_package(root, note_id_from_url(args.url))
    if existing:
        package = json.loads((existing / "content_package.json").read_text(encoding="utf-8"))
        if args.json: print(json.dumps(_result(existing, package), ensure_ascii=False))
        else: print(existing / "report.md")
        return {"completed": 0, "partial": 2, "failed": 3}[package["status"]]
    run = _capture_run_dir(args); run.mkdir(parents=True, exist_ok=True)
    manifest = run / "content_package.json"
    if args.run_dir and any(run.iterdir()):
        try:
            existing = json.loads(manifest.read_text(encoding="utf-8"))
            expected, actual = note_id_from_url(args.url), existing.get("source", {}).get("note_id")
            if expected and actual and actual != expected:
                print("run_directory_identity_mismatch", file=sys.stderr); return 4
        except (OSError, json.JSONDecodeError):
            print("run_directory_identity_mismatch", file=sys.stderr); return 4
    forwarded = ["--url", args.url, "--run-dir", str(run), "--timeout", str(args.timeout), "--max-video-mb", str(args.max_video_mb)] + (["--force"] if args.force else []) + (["--keyframes"] if args.keyframes else []) + (["--ocr"] if args.ocr else []) + (["--keep-raw-source"] if args.keep_raw_source else [])
    with contextlib.redirect_stdout(sys.stderr if args.json else sys.stdout): run_capture.main(forwarded)
    package = json.loads((run / "content_package.json").read_text(encoding="utf-8")); write_analysis_index(run)
    if args.json: print(json.dumps(_result(run, package), ensure_ascii=False))
    return {"completed": 0, "partial": 2, "failed": 3}.get(package["status"], 6)


if __name__ == "__main__": raise SystemExit(main())
