#!/usr/bin/env python3
"""Build IWIG's deterministic no-network analysis projection."""
from __future__ import annotations
import json
from datetime import datetime, timezone
from pathlib import Path
from content_package import atomic_write_json, file_record


def validate_analysis_index_schema(index: dict) -> list[str]:
    try:
        from jsonschema import Draft202012Validator
        schema = json.loads((Path(__file__).resolve().parents[1] / "schemas/iwig-analysis-index-v1.schema.json").read_text())
        return [f"schema:{item.json_path}:{item.message}" for item in Draft202012Validator(schema).iter_errors(index)]
    except ImportError: return ["schema:jsonschema_not_installed"]


def validate_analysis_index(index: dict) -> list[str]: return validate_analysis_index_schema(index)


def build_analysis_index(run: Path) -> dict:
    package_path = run / "content_package.json"; package = json.loads(package_path.read_text(encoding="utf-8")); derived = package.get("derived", {})
    timeline_path = run / "derived/timeline.json"; timeline = json.loads(timeline_path.read_text()) if timeline_path.is_file() else {"schema": {"name": "iwig-timeline", "version": "1.0.0"}, "events": [], "relations": []}
    transcript = package.get("transcript") or []
    evidence = {"field-post-title": {"type": "field", "source_path": "post.title"}, "field-post-description": {"type": "field", "source_path": "post.description"}}
    for index, segment in enumerate(transcript, 1): evidence[f"speech-{index:03}"] = {"type": "speech", "source_path": "derived/transcript_segments.json", "start": segment["start"], "end": segment["end"]}
    for frame in derived.get("keyframes", []): evidence[frame["id"]] = {"type": "frame", "source_path": frame["path"], "at": frame["time_seconds"]}
    readiness = {"post_copy": "ready" if package["post"].get("description") else "partial", "cover": "ready" if package["media"].get("cover") else "unavailable", "video_structure": "ready" if derived.get("keyframes") else "unavailable", "visual_text": "ready" if any((frame.get("ocr") or {}).get("text") for frame in derived.get("keyframes", [])) else "unavailable", "transcript": "ready" if transcript else "unavailable", "comments": "unavailable", "engagement": "snapshot_only" if package["post"].get("metrics") else "unavailable"}
    index = {"schema": {"name": "iwig-analysis-index", "version": "1.0.0"}, "source_package": {"path": "content_package.json", "sha256": file_record(package_path, run)["sha256"], "schema_version": package["schema"]["version"], "generated_at": datetime.now(timezone.utc).isoformat()}, "identity": package["identity"], "status": package["status"], "post": package["post"], "text": {"post": package["post"], "transcript": {"raw_segments": [], "normalized_segments": transcript, "metadata": package.get("transcript_metadata", {})}}, "visual": {"cover": package["media"].get("cover"), "images": package["media"].get("images", []), "keyframes": derived.get("keyframes", []), "selected_keyframes": derived.get("selected_keyframes", []), "scenes": derived.get("scenes", []), "ocr": derived.get("ocr", {})}, "media": package["media"], "timeline": timeline, "field_provenance": package.get("field_provenance", {}), "evidence": evidence, "completeness": package["completeness"], "quality": {"package_valid": True, "keyframe_count": len(derived.get("keyframes", [])), "transcript_segments": len(transcript), "error_count": len(package["errors"])}, "analysis_readiness": readiness, "warnings": package["limitations"], "errors": package["errors"]}
    return index


def write_analysis_index(run: Path) -> Path:
    target = run / "derived/analysis_index.json"; index = build_analysis_index(run); atomic_write_json(target, index); return target
