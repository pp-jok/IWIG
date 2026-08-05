#!/usr/bin/env python3
"""Build IWIG's deterministic no-network analysis projection."""
from __future__ import annotations
import json
from datetime import datetime, timezone
from pathlib import Path
from content_package import atomic_write_json, file_record, safe_artifact_path, validate_content_package


def validate_analysis_index_schema(index: dict) -> list[str]:
    try:
        from jsonschema import Draft202012Validator
        schema = json.loads((Path(__file__).resolve().parents[1] / "schemas/iwig-analysis-index-v1.schema.json").read_text())
        return [f"schema:{item.json_path}:{item.message}" for item in Draft202012Validator(schema).iter_errors(index)]
    except ImportError: return ["schema:jsonschema_not_installed"]


def validate_analysis_index(index: dict) -> list[str]: return validate_analysis_index_schema(index)


def build_analysis_index(run: Path) -> dict:
    package_path = run / "content_package.json"; package = json.loads(package_path.read_text(encoding="utf-8")); derived = package.get("derived", {}) or {}
    timeline_path = run / "derived/timeline.json"; timeline = json.loads(timeline_path.read_text()) if timeline_path.is_file() else {"schema": {"name": "iwig-timeline", "version": "1.0.0"}, "events": [], "relations": []}
    transcript = package.get("transcript") or []
    transcript_info = derived.get("transcript") or {}
    def read_json(path):
        try: candidate = safe_artifact_path(run, path)
        except ValueError: return []
        try: return json.loads(candidate.read_text(encoding="utf-8")) if candidate.is_file() else []
        except (OSError, json.JSONDecodeError): return []
    raw_segments = read_json(transcript_info.get("raw_path", ""))
    normalized_segments = read_json(transcript_info.get("normalized_path", "")) or transcript
    evidence = {"field-post-title": {"type": "field", "source_path": "post.title"}, "field-post-description": {"type": "field", "source_path": "post.description"}, "field-post-tags": {"type": "field", "source_path": "post.tags"}, "field-author": {"type": "field", "source_path": "post.author"}, "field-metrics": {"type": "field", "source_path": "post.metrics"}}
    transcript = normalized_segments
    for index, segment in enumerate(transcript, 1): evidence[f"speech-{index:03}"] = {"type": "speech", "source_path": "derived/transcript_segments.json", "start": segment["start"], "end": segment["end"]}
    for frame in derived.get("keyframes", []): evidence[frame["id"]] = {"type": "frame", "source_path": frame["path"], "at": frame["time_seconds"]}
    for scene in derived.get("scenes", []): evidence[scene["id"]] = {"type": "scene", "start": scene["start_seconds"], "end": scene["end_seconds"]}
    ocr = derived.get("ocr", {})
    frame_ids = {frame.get("path"): frame.get("id") for frame in derived.get("keyframes", [])}
    for kind in ("cover", "images", "keyframes"):
        records = [ocr.get(kind)] if kind == "cover" and ocr.get(kind) else (ocr.get(kind) or [])
        for number, record in enumerate(records, 1):
            if record and record.get("text"):
                evidence_id = f"ocr-{frame_ids[record['path']]}" if kind == "keyframes" and record.get("path") in frame_ids else f"ocr-{'cover' if kind == 'cover' else 'image'}-{number:03}"
                evidence[evidence_id] = {"type": "ocr", "source_path": record.get("path"), "text": record["text"]}
    all_ocr = [record for kind in ("cover", "images", "keyframes") for record in (([ocr.get(kind)] if kind == "cover" and ocr.get(kind) else (ocr.get(kind) or [])) or [])]
    post, media = package.get("post", {}), package.get("media", {})
    readiness = {"post_copy": "ready" if post.get("description") else "partial", "cover": "ready" if media.get("cover") else "unavailable", "video_structure": "ready" if derived.get("keyframes") else "unavailable", "visual_text": "ready" if any(record.get("text") for record in all_ocr) else "unavailable", "transcript": "ready" if transcript else "unavailable", "comments": "unavailable", "engagement": "snapshot_only" if any(value is not None for value in post.get("metrics", {}).values()) else "unavailable"}
    package_errors = validate_content_package(package)
    index = {"schema": {"name": "iwig-analysis-index", "version": "1.0.0"}, "source_package": {"path": "content_package.json", "sha256": file_record(package_path, run)["sha256"], "schema_version": package.get("schema", {}).get("version"), "generated_at": datetime.now(timezone.utc).isoformat()}, "identity": package.get("identity", {}), "status": package.get("status", "failed"), "post": post, "text": {"post": post, "transcript": {"raw_segments": raw_segments, "normalized_segments": normalized_segments, "metadata": package.get("transcript_metadata", {})}}, "visual": {"cover": media.get("cover"), "images": media.get("images", []), "keyframes": derived.get("keyframes", []), "selected_keyframes": derived.get("selected_keyframes", []), "scenes": derived.get("scenes", []), "ocr": ocr}, "media": media, "timeline": timeline, "field_provenance": package.get("field_provenance", {}), "evidence": evidence, "completeness": package.get("completeness", {}), "quality": {"package_valid": not package_errors, "keyframe_count": len(derived.get("keyframes", [])), "transcript_segments": len(transcript), "error_count": len(package.get("errors", []))}, "analysis_readiness": readiness, "warnings": package.get("limitations", []) + package_errors, "errors": package.get("errors", []) + [{"stage": "package", "code": item} for item in package_errors]}
    return index


def write_analysis_index(run: Path) -> Path:
    package = json.loads((run / "content_package.json").read_text(encoding="utf-8")); package_errors = validate_content_package(package)
    if package_errors: raise ValueError("content_package_invalid: " + "; ".join(package_errors))
    target = run / "derived/analysis_index.json"; index = build_analysis_index(run); errors = validate_analysis_index_schema(index)
    if errors: raise ValueError("analysis_index_invalid: " + "; ".join(errors))
    atomic_write_json(target, index); return target
