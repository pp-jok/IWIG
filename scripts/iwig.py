#!/usr/bin/env python3
"""The single stable IWIG command line entrypoint."""
from __future__ import annotations
import argparse
import contextlib
import json
import os
import sys
from copy import deepcopy
from datetime import datetime
from pathlib import Path

from build_analysis_index import AnalysisIndexError, validate_analysis_index_schema, write_analysis_index
from content_package import (atomic_write_json, atomic_write_text, compute_processing_status, content_payload_sha256,
                             file_record, find_existing_package, migrate_content_package_in_memory,
                             resolve_active_error, safe_artifact_path, upsert_active_error, validate_content_package)
import run_capture
from public_html_provider import note_id_from_url

HOME = Path(os.environ.get("IWIG_HOME", Path.home() / ".iwig"))


def _normalize_processing_state(package: dict) -> None:
    migrated, _ = migrate_content_package_in_memory(package)
    package.clear(); package.update(migrated)


def _exit_code(package: dict) -> int:
    if package.get("capture_status", package.get("status")) == "failed" or package.get("status") == "failed":
        return 3
    if package.get("processing_status") in {"partial", "failed"} or package.get("status") == "partial":
        return 2
    return 0


def _persist_processing_state(run: Path, package: dict) -> None:
    atomic_write_json(run / "content_package.json", package)
    atomic_write_text(run / "report.md", run_capture.render_public_report(package))


def _result(run: Path, package: dict) -> dict:
    index_path = run / "derived" / "analysis_index.json"
    index_complete = package.get("processing", {}).get("analysis_index", {}).get("status") == "completed" and index_path.is_file()
    if index_complete:
        try:
            index = json.loads(index_path.read_text(encoding="utf-8"))
            index_complete = not validate_analysis_index_schema(index) and index.get("source_package", {}).get("content_sha256") == content_payload_sha256(package)
        except (OSError, json.JSONDecodeError):
            index_complete = False
    index_status = package.get("processing", {}).get("analysis_index", {}).get("status", "not_run")
    if not index_complete and index_status == "completed":
        index_status = "invalid" if index_path.is_file() else "missing"
    readiness = index.get("analysis_readiness", {}) if index_complete else {"transcript": package.get("processing", {}).get("transcribe", {}).get("status", "not_run"), "frames": package.get("processing", {}).get("extract_keyframes", {}).get("status", "not_run"), "ocr": "ready" if any(name.startswith("ocr_") and stage.get("status") == "completed" for name, stage in package.get("processing", {}).items()) else "unavailable", "timeline": package.get("processing", {}).get("build_timeline", {}).get("status", "not_run"), "evidence": package.get("processing", {}).get("build_evidence_segments", {}).get("status", "not_run")}
    return {"status": package["status"], "capture_status": package.get("capture_status", package["status"]),
            "processing_status": package.get("processing_status", "not_run"), "run_dir": str(run),
            "content_package": str(run / "content_package.json"), "analysis_index": str(index_path) if index_complete else None,
            "analysis_index_status": "completed" if index_complete else index_status, "readiness": readiness,
            "active_errors": [{key: value for key, value in item.items() if key in {"stage", "code", "detail"}} for item in package.get("active_errors", [])],
            "report": str(run / "report.md")}


def _set_analysis_index_failure(run: Path, package: dict, detail: str) -> None:
    target = run / "derived" / "analysis_index.json"
    stale = run / "derived" / f"analysis_index.stale.{datetime.now().strftime('%Y%m%d-%H%M%S-%f')}.json"
    if target.is_file():
        try:
            target.replace(stale)
        except OSError:
            pass
    package.setdefault("processing", {})["analysis_index"] = {"status": "failed", "output_paths": [], "warnings": [detail]}
    upsert_active_error(package, stage="analysis_index", code="analysis_index_build_failed", detail=detail)
    package["processing_status"] = compute_processing_status(package.get("processing", {}))


def _set_analysis_index_success(package: dict) -> None:
    package.setdefault("processing", {})["analysis_index"] = {"status": "completed", "output_paths": ["derived/analysis_index.json"], "warnings": []}
    resolve_active_error(package, stage="analysis_index")
    package["processing_status"] = compute_processing_status(package.get("processing", {}))


def _rebuild_index_safely(run: Path, package: dict) -> str | None:
    _normalize_processing_state(package)
    try:
        package.setdefault("processing", {})["analysis_index"] = {"status": "running", "output_paths": [], "warnings": []}
        package["processing_status"] = compute_processing_status(package.get("processing", {}))
        _persist_processing_state(run, package)
        success_package = deepcopy(package)
        _set_analysis_index_success(success_package)
        write_analysis_index(run, package=success_package)
        target = run / "derived" / "analysis_index.json"
        index = json.loads(target.read_text(encoding="utf-8"))
        errors = validate_analysis_index_schema(index)
        if errors or index.get("source_package", {}).get("content_sha256") != content_payload_sha256(success_package):
            raise AnalysisIndexError("analysis_index_postcondition_failed")
    except AnalysisIndexError as error:
        _set_analysis_index_failure(run, package, str(error))
        _persist_processing_state(run, package)
        return str(error)
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as error:
        _set_analysis_index_failure(run, package, str(error))
        _persist_processing_state(run, package)
        return str(error)
    package.clear(); package.update(success_package)
    try: _persist_processing_state(run, package)
    except OSError as error: return f"package_state_persist_failed:{type(error).__name__}"
    return None


def validate(run: Path) -> dict:
    package_path = run / "content_package.json"
    try:
        package, migrations = migrate_content_package_in_memory(json.loads(package_path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError) as error:
        return {"valid": False, "errors": [f"package_unreadable:{type(error).__name__}"], "warnings": []}
    errors, warnings = validate_content_package(package), [f"migration:{item}" for item in migrations]
    def require_relative(relative, label):
        if not isinstance(relative, str) or Path(relative).is_absolute() or ".." in Path(relative).parts:
            errors.append(f"unsafe_path:{label}"); return
        target = (run / relative).resolve()
        if run.resolve() not in target.parents and target != run.resolve(): errors.append(f"unsafe_path:{label}")
        elif not target.is_file(): errors.append(f"missing_artifact:{relative}")
    for record in [item for item in [package.get("media", {}).get("video"), package.get("media", {}).get("cover")] if item] + package.get("media", {}).get("images", []):
        try: path = safe_artifact_path(run, record.get("path", ""))
        except ValueError: errors.append(f"unsafe_path:media:{record.get('path')}"); continue
        if not path.is_file(): errors.append(f"missing_artifact:{record.get('path')}")
        elif record.get("sha256") and file_record(path, run)["sha256"] != record["sha256"]: errors.append(f"hash_mismatch:{record['path']}")
    derived = package.get("derived", {})
    transcript = derived.get("transcript") or {}
    for key in ("raw_path", "normalized_path"):
        if transcript.get(key): require_relative(transcript[key], f"derived.transcript.{key}")
    for frame in derived.get("keyframes", []): require_relative(frame.get("path"), f"frame:{frame.get('id')}")
    timeline = derived.get("timeline") or {}
    if timeline.get("path"): require_relative(timeline["path"], "derived.timeline.path")
    index_path = run / "derived" / "analysis_index.json"
    index_stage = package.get("processing", {}).get("analysis_index", {}).get("status", "not_run")
    if index_path.is_file():
        try:
            index = json.loads(index_path.read_text(encoding="utf-8")); errors += validate_analysis_index_schema(index)
            if index.get("source_package", {}).get("content_sha256") != content_payload_sha256(package): errors.append("analysis_index_stale")
        except (OSError, json.JSONDecodeError) as error: errors.append(f"analysis_index_unreadable:{type(error).__name__}")
    else: warnings.append("analysis_index_missing")
    if index_stage == "completed" and not index_path.is_file(): errors.append("analysis_index_missing_for_completed_stage")
    if index_stage == "failed" and index_path.is_file(): errors.append("analysis_index_present_for_failed_stage")
    output = {"valid": not errors, "errors": errors, "warnings": warnings}; atomic_write_json(run / "processing" / "validation.json", output); return output


def _capture_run_dir(args) -> Path:
    if args.run_dir: return Path(args.run_dir).expanduser().resolve()
    return Path(args.output_dir).expanduser().resolve() / datetime.now().strftime("%Y%m%d-%H%M%S-%f")


def main() -> int:
    parser = argparse.ArgumentParser(prog="iwig"); sub = parser.add_subparsers(dest="command", required=True)
    setup = sub.add_parser("setup"); setup.add_argument("--home"); setup.add_argument("--dry-run", action="store_true")
    capture = sub.add_parser("capture")
    capture.add_argument("--url", required=True); capture.add_argument("--output-dir", default=str(HOME / "output")); capture.add_argument("--run-dir"); capture.add_argument("--timeout", type=float, default=20); capture.add_argument("--max-video-mb", type=int, default=300); capture.add_argument("--force", action="store_true"); capture.add_argument("--keyframes", action="store_true"); capture.add_argument("--ocr", action="store_true"); capture.add_argument("--json", action="store_true")
    enrich = sub.add_parser("enrich"); enrich.add_argument("run_dir"); enrich.add_argument("--keyframes", action="store_true"); enrich.add_argument("--ocr", action="store_true"); enrich.add_argument("--transcribe", action="store_true"); enrich.add_argument("--asr-model", default="small"); enrich.add_argument("--language", default="zh"); enrich.add_argument("--interpret", action="store_true"); enrich.add_argument("--describe-visuals", action="store_true"); enrich.add_argument("--json", action="store_true")
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
        run = Path(args.run_dir).expanduser().resolve()
        try:
            package, _ = migrate_content_package_in_memory(json.loads((run / "content_package.json").read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError) as error:
            print(str(error), file=sys.stderr); return 5
        error = _rebuild_index_safely(run, package)
        if error:
            print(error, file=sys.stderr); return 5
        print(run / "derived" / "analysis_index.json")
        return 0
    if args.command == "enrich":
        forwarded = ["--enrich-dir", args.run_dir] + (["--keyframes"] if args.keyframes else []) + (["--ocr"] if args.ocr else []) + (["--transcribe", "--asr-model", args.asr_model, "--language", args.language] if args.transcribe else []) + (["--interpret"] if args.interpret else []) + (["--describe-visuals"] if args.describe_visuals else [])
        with contextlib.redirect_stdout(sys.stderr if args.json else sys.stdout):
            code = run_capture.main(forwarded)
        run = Path(args.run_dir).expanduser().resolve()
        if (run / "content_package.json").is_file():
            package, _ = migrate_content_package_in_memory(json.loads((run / "content_package.json").read_text(encoding="utf-8")))
            _rebuild_index_safely(run, package)
            package = json.loads((run / "content_package.json").read_text(encoding="utf-8"))
            if args.json: print(json.dumps(_result(run, package), ensure_ascii=False))
            return max(code, _exit_code(package))
        return code
    root = Path(args.output_dir).expanduser().resolve()
    existing = None if args.run_dir or args.force else find_existing_package(root, note_id_from_url(args.url))
    if existing:
        package, _ = migrate_content_package_in_memory(json.loads((existing / "content_package.json").read_text(encoding="utf-8")))
        index_path = existing / "derived" / "analysis_index.json"
        needs_index = package.get("processing", {}).get("analysis_index", {}).get("status") != "completed" or not index_path.is_file()
        if not needs_index:
            try:
                index = json.loads(index_path.read_text(encoding="utf-8"))
                needs_index = bool(validate_analysis_index_schema(index)) or index.get("source_package", {}).get("content_sha256") != content_payload_sha256(package)
            except (OSError, json.JSONDecodeError): needs_index = True
        if needs_index:
            _rebuild_index_safely(existing, package)
        if existing:
            package, _ = migrate_content_package_in_memory(json.loads((existing / "content_package.json").read_text(encoding="utf-8")))
            if args.json: print(json.dumps(_result(existing, package), ensure_ascii=False))
            else: print(existing / "report.md")
            return _exit_code(package)
    run = _capture_run_dir(args); run.mkdir(parents=True, exist_ok=True)
    manifest = run / "content_package.json"
    if args.run_dir and any(run.iterdir()):
        try:
            existing = json.loads(manifest.read_text(encoding="utf-8"))
            expected, actual = note_id_from_url(args.url), existing.get("source", {}).get("note_id")
            same_url = existing.get("source", {}).get("input_url") == __import__("public_html_provider").redact_url(args.url)
            if expected and actual and actual != expected:
                print("run_directory_identity_mismatch", file=sys.stderr); return 4
            if not expected and actual and not same_url:
                print("run_directory_identity_mismatch", file=sys.stderr); return 4
        except (OSError, json.JSONDecodeError):
            print("run_directory_identity_mismatch", file=sys.stderr); return 4
    forwarded = ["--url", args.url, "--run-dir", str(run), "--timeout", str(args.timeout), "--max-video-mb", str(args.max_video_mb)] + (["--force"] if args.force else []) + (["--keyframes"] if args.keyframes else []) + (["--ocr"] if args.ocr else [])
    with contextlib.redirect_stdout(sys.stderr if args.json else sys.stdout): run_capture.main(forwarded)
    package, _ = migrate_content_package_in_memory(json.loads((run / "content_package.json").read_text(encoding="utf-8"))); _rebuild_index_safely(run, package)
    package, _ = migrate_content_package_in_memory(json.loads((run / "content_package.json").read_text(encoding="utf-8")))
    if args.json: print(json.dumps(_result(run, package), ensure_ascii=False))
    return _exit_code(package)


if __name__ == "__main__": raise SystemExit(main())
