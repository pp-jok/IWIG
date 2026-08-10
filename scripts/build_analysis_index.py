#!/usr/bin/env python3
"""Build IWIG's deterministic no-network analysis projection."""
from __future__ import annotations
import json
from datetime import datetime, timezone
from pathlib import Path
from content_package import (atomic_write_json, content_payload_sha256, file_record, migrate_content_package_in_memory,
                             safe_artifact_path, validate_content_package)


class AnalysisIndexError(Exception):
    """Expected local analysis-index build failure."""


def validate_analysis_index_schema(index: dict) -> list[str]:
    try:
        from jsonschema import Draft202012Validator
        schema = json.loads((Path(__file__).resolve().parents[1] / "schemas/iwig-analysis-index-v1.schema.json").read_text())
        return [f"schema:{item.json_path}:{item.message}" for item in Draft202012Validator(schema).iter_errors(index)]
    except ImportError: return []


def validate_analysis_index(index: dict) -> list[str]: return validate_analysis_index_schema(index)


def build_analysis_index(run: Path, package: dict | None = None) -> dict:
    package_path = run / "content_package.json"
    if package is None:
        try: package, _ = migrate_content_package_in_memory(json.loads(package_path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError, TypeError) as error: raise AnalysisIndexError(f"content_package_unreadable:{type(error).__name__}") from error
    else:
        package, _ = migrate_content_package_in_memory(package)
    derived = package.get("derived", {}) or {}
    timeline_path = run / "derived/timeline.json"
    try: timeline = json.loads(timeline_path.read_text()) if timeline_path.is_file() else {"schema": {"name": "iwig-timeline", "version": "1.0.0"}, "events": [], "relations": []}
    except (OSError, json.JSONDecodeError) as error: raise AnalysisIndexError(f"timeline_invalid:{type(error).__name__}") from error
    transcript = package.get("transcript") or []
    transcript_info = derived.get("transcript") or {}
    def read_json(path):
        try: candidate = safe_artifact_path(run, path)
        except ValueError as error: raise AnalysisIndexError(f"invalid_transcript_path:{error}") from error
        if not candidate.is_file(): raise AnalysisIndexError(f"missing_transcript_artifact:{path}")
        try: return json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error: raise AnalysisIndexError(f"invalid_transcript_artifact:{path}") from error
    raw_segments = read_json(transcript_info["raw_path"]) if transcript_info.get("raw_path") else []
    normalized_segments = read_json(transcript_info["normalized_path"]) if transcript_info.get("normalized_path") else transcript
    evidence = {"field-post-title": {"type": "field", "source_path": "post.title"}, "field-post-description": {"type": "field", "source_path": "post.description"}, "field-post-tags": {"type": "field", "source_path": "post.tags"}, "field-author": {"type": "field", "source_path": "post.author"}, "field-metrics": {"type": "field", "source_path": "post.metrics"}}
    transcript = normalized_segments
    for index, segment in enumerate(transcript, 1): evidence[f"speech-{index:03}"] = {"type": "speech", "source_path": "derived/transcript_segments.json", "start": segment["start"], "end": segment["end"]}
    for frame in derived.get("keyframes", []): evidence[frame["id"]] = {"type": "frame", "source_path": frame["path"], "at": frame["time_seconds"]}
    for scan in derived.get("frame_scan", []): evidence[scan["id"]] = {"type": "scan", "at": scan["time_seconds"]}
    for scene in derived.get("scenes", []): evidence[scene["id"]] = {"type": "scene", "start": scene["start_seconds"], "end": scene["end_seconds"]}
    for event in derived.get("text_change_events", []): evidence[event["id"]] = {"type": "text_change", "at": event["at"], "frame_ref": event.get("frame_ref")}
    for number, event in enumerate(derived.get("scene_change_events", derived.get("scene_change_keyframes", [])), 1): evidence[f"scene-change-{number:03}"] = {"type": "scene_change", "scan_ref": event.get("scan_ref"), "frame_ref": event.get("frame_ref"), "at": event.get("time_seconds")}
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
    capture_status, processing = package["capture_status"], package.get("processing", {})
    unavailable = capture_status == "failed"
    readiness = {"post_copy": "unavailable" if unavailable else ("ready" if post.get("description") else "partial"), "cover": "unavailable" if unavailable or not media.get("cover") else "ready", "frames": "ready" if derived.get("keyframes") else "unavailable", "video_structure": "unavailable" if unavailable or not derived.get("keyframes") else "ready", "visual_text": "unavailable" if unavailable else ("partial" if processing.get("ocr_images", {}).get("status") == "partial" else ("ready" if any(record.get("text") for record in all_ocr) else "unavailable")), "ocr": "ready" if any(record.get("text") for record in all_ocr) else "unavailable", "transcript": "failed" if processing.get("transcribe", {}).get("status") == "failed" else ("zero" if processing.get("transcribe", {}).get("status") == "completed" and not transcript else ("ready" if transcript else "unavailable")), "timeline": "ready" if timeline.get("events") else "unavailable", "evidence": "ready" if derived.get("evidence_segments") else "unavailable", "comments": "unavailable", "engagement": "snapshot_only" if any(value is not None for value in post.get("metrics", {}).values()) else "unavailable"}
    package_errors = validate_content_package(package)
    index = {"schema": {"name": "iwig-analysis-index", "version": "1.0.0"}, "source_package": {"path": "content_package.json", "file_sha256": file_record(package_path, run)["sha256"], "content_sha256": content_payload_sha256(package), "schema_version": package.get("schema", {}).get("version"), "generated_at": datetime.now(timezone.utc).isoformat()}, "identity": package.get("identity", {}), "status": "completed", "state": {"capture": capture_status, "processing": package["processing_status"], "analysis_index": "completed"}, "capture_status": capture_status, "processing_status": package["processing_status"], "active_errors": package.get("active_errors", []), "processing": processing, "post": post, "text": {"post": post, "transcript": {"raw_segments": raw_segments, "normalized_segments": normalized_segments, "metadata": package.get("transcript_metadata", {})}}, "visual": {"cover": media.get("cover"), "images": media.get("images", []), "keyframes": derived.get("keyframes", []), "selected_keyframes": derived.get("selected_keyframes", []), "scene_change_keyframes": derived.get("scene_change_keyframes", []), "scenes": derived.get("scenes", []), "ocr": ocr, "text_change_events": derived.get("text_change_events", [])}, "media": media, "timeline": timeline, "field_provenance": package.get("field_provenance", {}), "evidence": evidence, "evidence_segments": derived.get("evidence_segments", []), "scene_change_keyframes": derived.get("scene_change_keyframes", []), "candidate_labels": derived.get("candidate_labels", derived.get("interpretations", [])), "interpretations": derived.get("interpretations", []), "completeness": package.get("completeness", {}), "quality": {"package_valid": not package_errors, "keyframe_count": len(derived.get("keyframes", [])), "transcript_segments": len(transcript), "error_count": len(package.get("active_errors", []))}, "analysis_readiness": readiness, "warnings": package.get("limitations", []) + package_errors, "errors": package.get("active_errors", []) + [{"stage": "package", "code": item} for item in package_errors]}
    return index


def write_analysis_index(run: Path, package: dict | None = None) -> Path:
    try:
        if package is None: package, _ = migrate_content_package_in_memory(json.loads((run / "content_package.json").read_text(encoding="utf-8")))
        else: package, _ = migrate_content_package_in_memory(package)
        package_errors = validate_content_package(package)
        if package_errors: raise AnalysisIndexError("content_package_invalid: " + "; ".join(package_errors))
        target = run / "derived/analysis_index.json"; index = build_analysis_index(run, package=package); errors = validate_analysis_index_schema(index)
        if errors: raise AnalysisIndexError("analysis_index_invalid: " + "; ".join(errors))
        atomic_write_json(target, index); return target
    except AnalysisIndexError:
        raise
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
        raise AnalysisIndexError(str(error)) from error
