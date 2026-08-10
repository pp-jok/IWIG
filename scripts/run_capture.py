#!/usr/bin/env python3
"""Capture one public XHS note and run resumable local processing stages."""
from __future__ import annotations

import argparse
import json
import hashlib
from datetime import datetime, timezone
from datetime import datetime
from pathlib import Path

from content_package import (atomic_write_json, atomic_write_text, build_evidence_segments, build_image_page_evidence, build_text_change_events, build_timeline, build_visual_candidates, completeness, compute_processing_status, describe_visual_records, extract_keyframes, field_status, file_record,
                             find_existing_package, new_content_package, ocr_macos,
                             ocr_macos_batch, perceptual_hash, rule_based_interpretations, scan_video_frames, scene_boundaries, select_representative_frames, select_scene_change_frames, select_structural_keyframes, should_reuse, srt,
                             safe_artifact_path, resolve_active_error, upsert_active_error, validate_content_package, migrate_content_package_in_memory)
from public_html_provider import PublicCaptureError, capture_public_note, note_id_from_url, redact_url


def _write_json(path: Path, value: object) -> None:
    atomic_write_json(path, value)


def _checkpoint(result: dict, run: Path) -> None:
    """Persist completed local work before the next CPU/native stage starts."""
    result["processing_status"] = compute_processing_status(result.get("processing", {}))
    _write_json(run / "content_package.json", result)
    atomic_write_text(run / "report.md", render_public_report(result))


def _start_stage(result: dict, run: Path, name: str, tool: str | None = None) -> None:
    previous = result.get("processing", {}).get(name, {})
    result.setdefault("processing", {})[name] = {"status": "running", "output_paths": previous.get("output_paths", []),
        "input_sha256": previous.get("input_sha256"), "options_sha256": previous.get("options_sha256"), "tool": tool or previous.get("tool"),
        "started_at": datetime.now(timezone.utc).isoformat(), "completed_at": None, "warnings": []}
    _checkpoint(result, run)


def _stage(result: dict, name: str, status: str, outputs=None, tool=None, warnings=None, code=None) -> None:
    previous = result.get("processing", {}).get(name, {})
    result.setdefault("processing", {})[name] = {"status": status, "output_paths": outputs or [], "input_sha256": previous.get("input_sha256"), "options_sha256": previous.get("options_sha256"), "tool": tool, "started_at": previous.get("started_at", datetime.now(timezone.utc).isoformat()), "completed_at": datetime.now(timezone.utc).isoformat(), "warnings": warnings or []}
    if status in {"failed", "partial"}: upsert_active_error(result, stage=name, code=code or f"{name}_failed", detail=(warnings or [None])[0])
    elif status == "completed": resolve_active_error(result, stage=name)
    result["processing_status"] = compute_processing_status(result.get("processing", {}))


def _paths_exist(run: Path, paths: list[str]) -> bool:
    try: return bool(paths) and all(safe_artifact_path(run, path).is_file() for path in paths)
    except ValueError: return False


def transcribe(video: Path, model_name: str = "small", language: str = "zh") -> tuple[list[dict], dict]:
    from faster_whisper import WhisperModel
    model = WhisperModel(model_name, device="cpu", compute_type="int8")
    segments, info = model.transcribe(str(video), language=language, vad_filter=True)
    raw = [{"start": item.start, "end": item.end, "text": item.text, "avg_logprob": getattr(item, "avg_logprob", None)} for item in segments]
    normalized = [{"start": item["start"], "end": item["end"], "text": item["text"].strip()} for item in raw if item["text"].strip()]
    return normalized, {"engine": "faster-whisper", "model": model_name, "language": getattr(info, "language", language), "segment_count": len(normalized), "warnings": [] , "raw_segments": raw}


def _path(run: Path, record: dict | None) -> Path | None:
    if not record or not record.get("path"): return None
    try: return safe_artifact_path(run, record["path"])
    except ValueError: return None


def process_keyframes(result: dict, run: Path, enabled: bool) -> None:
    video = _path(run, result["media"].get("video"))
    if not enabled:
        if "extract_keyframes" not in result.get("processing", {}): _stage(result, "extract_keyframes", "not_run", warnings=["keyframes not requested"])
        return
    if not video or not video.is_file():
        _stage(result, "extract_keyframes", "not_run", warnings=["video unavailable"])
        _checkpoint(result, run)
        return
    existing = result.get("derived", {}).get("keyframes") or []
    if existing and _paths_exist(run, [item["path"] for item in existing]):
        if not result["derived"].get("frame_scan"):
            scan = scan_video_frames(video)
            result["derived"]["frame_scan"] = scan.get("frames", [])
            result["derived"]["scenes"] = scene_boundaries(result["derived"]["frame_scan"])
            duration = (result["media"].get("video") or {}).get("metadata", {}).get("duration_seconds")
            result["derived"]["representative_frame_plan"] = select_representative_frames(result["derived"]["frame_scan"], duration) if scan.get("status") == "available" else []
        events = [{"scan_ref": item["id"], "time_seconds": item["time_seconds"], "adjacent_similarity": item.get("adjacent_similarity"), "selection_basis": "dense_scan_perceptual_hash", "threshold": .72} for item in result["derived"].get("frame_scan", []) if item.get("adjacent_similarity") is not None and item["adjacent_similarity"] < .72]
        result["derived"]["scene_change_events"] = events
        result["derived"]["scene_change_keyframes"] = events  # legacy alias
        for scene in result["derived"].get("scenes", []):
            candidate = min(existing, key=lambda frame: abs(frame["time_seconds"] - scene["start_seconds"]), default=None)
            scene["representative_frame_ref"] = candidate.get("id") if candidate else None
        for event in result["derived"].get("scene_change_events", []):
            candidate = min(existing, key=lambda frame: abs(frame["time_seconds"] - event["time_seconds"]), default=None)
            event["frame_ref"] = candidate.get("id") if candidate else None
        _stage(result, "extract_keyframes", "completed", [item["path"] for item in existing], "PyAV", ["reused existing frames"])
        _checkpoint(result, run)
        return
    _start_stage(result, run, "extract_keyframes", "PyAV")
    try:
        scan = scan_video_frames(video)
        result["derived"]["frame_scan"] = scan.get("frames", [])
        result["derived"]["scenes"] = scene_boundaries(result["derived"]["frame_scan"])
        result["derived"]["scene_change_events"] = [{"scan_ref": item["id"], "time_seconds": item["time_seconds"], "adjacent_similarity": item.get("adjacent_similarity"), "selection_basis": "dense_scan_perceptual_hash", "threshold": .72} for item in result["derived"]["frame_scan"] if item.get("adjacent_similarity") is not None and item["adjacent_similarity"] < .72]
        result["derived"]["scene_change_keyframes"] = result["derived"]["scene_change_events"]
        duration = (result["media"].get("video") or {}).get("metadata", {}).get("duration_seconds")
        result["derived"]["representative_frame_plan"] = select_representative_frames(scan.get("frames", []), duration) if scan.get("status") == "available" else []
        extracted = extract_keyframes(video, run / "derived" / "keyframes", selected_times=[item["time_seconds"] for item in result["derived"]["representative_frame_plan"]])
        frames = extracted.get("frames", [])
        for index, frame in enumerate(frames, 1):
            frame.update({"id": f"frame-{index:03}", "path": f"derived/keyframes/{frame['path']}", "perceptual_hash": perceptual_hash(run / f"derived/keyframes/{frame['path']}"), "ocr": {"status": "not_run", "text": "", "lines": []}})
        result["derived"]["keyframes"] = frames
        for scene in result["derived"]["scenes"]:
            candidate = min(frames, key=lambda frame: abs(frame["time_seconds"] - scene["start_seconds"]), default=None)
            scene["representative_frame_ref"] = candidate.get("id") if candidate else None
        for change in result["derived"]["scene_change_keyframes"]:
            candidate = min(frames, key=lambda frame: abs(frame["time_seconds"] - change["time_seconds"]), default=None)
            change["frame_ref"] = candidate.get("id") if candidate else None
        status = "completed" if extracted.get("status") == "available" else extracted.get("status", "failed")
        _stage(result, "extract_keyframes", status, [item["path"] for item in frames], "PyAV")
    except Exception as error:
        _stage(result, "extract_keyframes", "failed", tool="PyAV", warnings=[type(error).__name__], code=type(error).__name__)
    _checkpoint(result, run)


def process_transcript(result: dict, run: Path, asr_model: str = "small", language: str = "zh") -> None:
    video = _path(run, result["media"].get("video"))
    previous = result.get("processing", {}).get("transcribe", {})
    input_hash = file_record(video, run)["sha256"] if video and video.is_file() else None
    options_hash = hashlib.sha256(json.dumps({"model": asr_model, "language": language, "device": "cpu", "compute_type": "int8", "vad_filter": True}, sort_keys=True).encode()).hexdigest()
    outputs = previous.get("output_paths", [])
    legacy_metadata = (result.get("derived", {}).get("transcript") or {}).get("metadata") or result.get("transcript_metadata") or {}
    if previous.get("status") == "completed" and previous.get("input_sha256") == input_hash and not previous.get("options_sha256") and legacy_metadata.get("model") == asr_model and legacy_metadata.get("language") == language and _paths_exist(run, outputs):
        previous["options_sha256"] = options_hash
        return
    if previous.get("status") == "completed" and previous.get("input_sha256") == input_hash and previous.get("options_sha256") == options_hash and _paths_exist(run, outputs):
        return
    if not video or not video.is_file():
        _stage(result, "transcribe", "not_run", warnings=["video unavailable"])
        _checkpoint(result, run)
        return
    _start_stage(result, run, "transcribe", "faster-whisper")
    try:
        normalized, metadata = transcribe(video, asr_model, language)
        raw = metadata.pop("raw_segments")
        result["transcript"] = normalized  # compatibility
        result["transcript_metadata"] = metadata
        result["derived"]["transcript"] = {"raw_path": "derived/transcript_raw_segments.json", "normalized_path": "derived/transcript_segments.json", "metadata": metadata}
        _write_json(run / "derived" / "transcript_raw_segments.json", raw)
        _write_json(run / "derived" / "transcript_segments.json", normalized)
        atomic_write_text(run / "derived" / "transcript.txt", "\n".join(item["text"] for item in normalized) + "\n")
        atomic_write_text(run / "derived" / "subtitles.srt", srt(normalized))
        _stage(result, "transcribe", "completed", ["derived/transcript_raw_segments.json", "derived/transcript_segments.json", "derived/transcript.txt", "derived/subtitles.srt"], "faster-whisper")
        result["processing"]["transcribe"]["input_sha256"] = input_hash
        result["processing"]["transcribe"]["options_sha256"] = options_hash
    except Exception as error:
        result.setdefault("errors", []).append({"stage": "transcript", "code": type(error).__name__})
        result.setdefault("limitations", []).append(f"本地口播转写失败：{type(error).__name__}")
        _stage(result, "transcribe", "failed", tool="faster-whisper", warnings=[type(error).__name__], code=type(error).__name__)
    _checkpoint(result, run)


def _ocr_records(run: Path, records: list[dict]) -> list[dict]:
    usable = [(record, _path(run, record)) for record in records]
    usable = [(record, image) for record, image in usable if image and image.is_file()]
    values = [{"path": record["path"], **value} for (record, _), value in zip(usable, ocr_macos_batch([image for _, image in usable]))]
    from content_package import filtered_ocr_text
    for value in values:
        value["filtered_text"] = filtered_ocr_text(value)
    return values


def process_ocr_cover(result: dict, run: Path, enabled: bool) -> None:
    previous = result.get("processing", {}).get("ocr_cover", {})
    if not enabled or previous.get("status") == "completed":
        return
    if not result["media"].get("cover"):
        _stage(result, "ocr_cover", "not_run", warnings=["cover unavailable"])
        _checkpoint(result, run)
        return
    _start_stage(result, run, "ocr_cover", "macOS Vision")
    try:
        records = _ocr_records(run, [result["media"]["cover"]])
        if not records:
            _stage(result, "ocr_cover", "failed", warnings=["cover file unavailable"])
        else:
            value = records[0]
            result.setdefault("ocr", {"images": [], "keyframes": []})["cover"] = value; result["derived"]["ocr"]["cover"] = value
            _stage(result, "ocr_cover", "completed" if value["status"] == "available" else "failed", [value["path"]], "macOS Vision")
    except Exception as error:
        _stage(result, "ocr_cover", "failed", tool="macOS Vision", warnings=[type(error).__name__], code=type(error).__name__)
    _checkpoint(result, run)


def process_ocr_images(result: dict, run: Path, enabled: bool) -> None:
    previous = result.get("processing", {}).get("ocr_images", {})
    if not enabled or previous.get("status") == "completed":
        return
    if not result["media"].get("images"):
        _stage(result, "ocr_images", "not_run", warnings=["images unavailable"])
        _checkpoint(result, run)
        return
    _start_stage(result, run, "ocr_images", "macOS Vision")
    try:
        values = _ocr_records(run, result["media"]["images"])
        result.setdefault("ocr", {"images": [], "keyframes": []})["images"] = values; result["derived"]["ocr"]["images"] = values
        _stage(result, "ocr_images", "completed" if values and all(item["status"] == "available" for item in values) else "failed", [item["path"] for item in values], "macOS Vision")
    except Exception as error:
        _stage(result, "ocr_images", "failed", tool="macOS Vision", warnings=[type(error).__name__], code=type(error).__name__)
    _checkpoint(result, run)


def process_ocr_keyframes(result: dict, run: Path, enabled: bool) -> None:
    frames = result.get("derived", {}).get("keyframes", [])
    previous = result.get("processing", {}).get("ocr_keyframes", {})
    if not enabled or previous.get("status") == "completed":
        return
    if not frames:
        _stage(result, "ocr_keyframes", "not_run", warnings=["keyframes unavailable"])
        _checkpoint(result, run)
        return
    _start_stage(result, run, "ocr_keyframes", "macOS Vision")
    try:
        records = _ocr_records(run, frames)
        for record, frame in zip(records, frames):
            frame["ocr"] = {key: value for key, value in record.items() if key != "path"}
        result.setdefault("ocr", {"images": [], "keyframes": []})["keyframes"] = records
        result["derived"]["ocr"]["keyframes"] = records
        duration = (result["media"].get("video") or {}).get("metadata", {}).get("duration_seconds") or 1
        result["derived"]["selected_keyframes"] = select_structural_keyframes(frames, duration)
        _stage(result, "ocr_keyframes", "completed" if records and all(item["status"] == "available" for item in records) else "failed", [item["path"] for item in records], "macOS Vision")
    except Exception as error:
        _stage(result, "ocr_keyframes", "failed", tool="macOS Vision", warnings=[type(error).__name__], code=type(error).__name__)
    _checkpoint(result, run)


def recompute_completeness(result: dict) -> None:
    video = result["media"].get("video")
    result["completeness"] = {
        "title": field_status(result["post"].get("title")), "description": field_status(result["post"].get("description")),
        "video": field_status(video), "images": field_status(result["media"].get("images")),
        "comments": completeness("intentionally_omitted", reason="public HTML capture does not collect comment bodies"),
        "transcript": completeness("zero", 0, "transcription completed; no speech detected") if result.get("processing", {}).get("transcribe", {}).get("status") == "completed" and result.get("transcript") == [] else (field_status(result.get("transcript")) if video else completeness("not_run", reason="video unavailable")),
        "ocr": completeness("available" if any(stage.get("status") == "completed" for name, stage in result.get("processing", {}).items() if name.startswith("ocr_")) else "failed", reason="derived from OCR stages") if any(name.startswith("ocr_") for name in result.get("processing", {})) else completeness("not_run", reason="OCR not requested"),
    }


def process_evidence(result: dict, run: Path, enabled: bool, describe_visuals: bool = False) -> None:
    derived = result.setdefault("derived", {})
    derived.setdefault("scene_change_keyframes", [])
    derived.setdefault("evidence_segments", [])
    derived.setdefault("interpretations", [])
    pages = build_image_page_evidence(result["media"].get("images", []), derived.get("ocr", {}).get("images", []))
    derived["image_pages"] = pages
    if pages:
        _write_json(run / "derived" / "image_pages.json", pages)
        _stage(result, "build_image_page_evidence", "completed", ["derived/image_pages.json"], "local factual linker")
    candidates = build_visual_candidates(derived.get("keyframes", []), (result["media"].get("video") or {}).get("metadata", {}).get("duration_seconds"))
    derived["visual_candidates"] = candidates
    text_events = build_text_change_events(derived.get("keyframes", []))
    derived["text_change_events"] = text_events
    if text_events:
        _write_json(run / "derived" / "text_change_events.json", text_events)
        _stage(result, "build_text_change_events", "completed", ["derived/text_change_events.json"], "local factual linker")
    transcript = result.get("transcript") or []
    segments = []
    if transcript or text_events or derived["scene_change_keyframes"]:
        segments = build_evidence_segments(transcript, derived.get("keyframes", []), derived["scene_change_keyframes"], derived.get("ocr", {}), text_events)
        derived["evidence_segments"] = segments
        _write_json(run / "derived" / "evidence_segments.json", segments)
        _stage(result, "build_evidence_segments", "completed", ["derived/evidence_segments.json"], "local factual linker")
    else:
        _stage(result, "build_evidence_segments", "not_run", warnings=["no speech, scene, or OCR evidence available"])
    if enabled and segments:
        labels = [{**item, "kind": "structural_hint"} for item in rule_based_interpretations(derived["evidence_segments"])]
        derived["candidate_labels"] = labels
        derived["interpretations"] = labels  # compatibility for existing consumers
        _write_json(run / "derived" / "candidate_labels.json", labels)
        _stage(result, "interpret_evidence", "completed", ["derived/candidate_labels.json"], "rule_based_v1")
    elif enabled:
        _stage(result, "interpret_evidence", "not_run", warnings=["evidence segments unavailable"])
    else:
        _stage(result, "interpret_evidence", "not_run", warnings=["interpretation not requested"])
    if describe_visuals:
        visual = describe_visual_records(pages + candidates)
        derived.setdefault("interpretations", []).extend(visual)
        _write_json(run / "derived" / "visual_descriptions.json", visual)
        _stage(result, "describe_visuals", "completed", ["derived/visual_descriptions.json"], "ocr_density_v1")


def process_local_stages(result: dict, run: Path, *, keyframes: bool, ocr: bool, transcribe: bool = False,
                         asr_model: str = "small", language: str = "zh", interpret: bool = False,
                         describe_visuals: bool = False) -> None:
    process_keyframes(result, run, keyframes)
    _checkpoint(result, run)
    if transcribe:
        process_transcript(result, run, asr_model, language)
    elif "transcribe" not in result.get("processing", {}):
        _stage(result, "transcribe", "not_run", warnings=["transcription not requested"])
    _checkpoint(result, run)
    process_ocr_cover(result, run, ocr)
    process_ocr_images(result, run, ocr)
    process_ocr_keyframes(result, run, ocr)
    _checkpoint(result, run)
    _start_stage(result, run, "build_evidence_segments", "local factual linker")
    process_evidence(result, run, interpret, describe_visuals)
    _checkpoint(result, run)
    frames = result.get("derived", {}).get("keyframes", [])
    duration = (result["media"].get("video") or {}).get("metadata", {}).get("duration_seconds")
    try:
        _start_stage(result, run, "build_timeline")
        timeline = build_timeline(result.get("transcript") or [], frames, result.get("derived", {}).get("scenes", []), duration, result.get("derived", {}).get("text_change_events", []))
        _write_json(run / "derived" / "timeline.json", timeline)
        result["derived"]["timeline"] = {"path": "derived/timeline.json"}
        _stage(result, "build_timeline", "completed", ["derived/timeline.json"])
    except (OSError, TypeError, ValueError) as error:
        _stage(result, "build_timeline", "failed", warnings=[type(error).__name__], code=type(error).__name__)
    recompute_completeness(result)
    identity = result["identity"]
    source, post, video = result["source"], result["post"], result["media"].get("video")
    identity.update({"note_id": source.get("note_id"), "author_id": post.get("author", {}).get("id"), "snapshot_at": source.get("captured_at"), "primary_media_sha256": (video or {}).get("sha256")})
    seed = "\n".join(str(item or "") for item in (source.get("note_id"), post.get("title"), post.get("description"), identity["author_id"], identity["primary_media_sha256"]))
    identity["content_fingerprint"] = hashlib.sha256(seed.encode()).hexdigest(); identity["package_id"] = hashlib.sha256(f"xiaohongshu:{source.get('note_id')}".encode()).hexdigest()[:20]; identity["snapshot_id"] = hashlib.sha256(f"{identity['package_id']}:{identity['snapshot_at']}".encode()).hexdigest()[:20]


def render_public_report(result: dict) -> str:
    post, media, source = result["post"], result["media"], result["source"]
    value = lambda item: "未获取" if item is None else item
    lines = ["# 小红书公开内容包", "", "## 帖子信息", "", f"- 链接：{value(source.get('canonical_url') or source.get('resolved_url'))}", f"- 帖子 ID：{value(source.get('note_id'))}", f"- 标题：{value(post.get('title'))}", f"- 作者：{value(post['author'].get('nickname'))}", f"- 点赞：{value(post['metrics'].get('likes'))}", f"- 收藏：{value(post['metrics'].get('favorites'))}", f"- 评论数：{value(post['metrics'].get('comments'))}", "", "## 正文", "", post.get("description") or "未获取", "", "## 媒体", "", f"- 视频：{media.get('video', {}).get('path') if media.get('video') else '未获取'}", f"- 封面：{media.get('cover', {}).get('path') if media.get('cover') else '未获取'}", f"- 图文页：{len(media.get('images') or [])}", "", "## 处理状态", "", f"- 采集：{result.get('capture_status', result.get('status'))}", f"- 本地处理：{result.get('processing_status', 'not_run')}", f"- 分析索引：{result.get('processing', {}).get('analysis_index', {}).get('status', 'not_run')}", "", "## 评论", "", "- 本 Skill 只读取公开 HTML，不采集评论详情或二级回复。", "", "## 获取完整度", ""]
    lines += [f"- {key}：{item.get('status') if isinstance(item, dict) else item}" for key, item in result.get("completeness", {}).items()]
    active_errors = result.get("active_errors") or []
    return "\n".join(lines + ["", "## 限制", "", *[f"- {item}" for item in result.get("limitations") or []], "", "## 当前处理问题", "", *[f"- {item.get('stage')}：{item.get('code')}" for item in active_errors], ""])


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url"); parser.add_argument("--output-dir", default="output"); parser.add_argument("--run-dir")
    parser.add_argument("--timeout", type=float, default=20); parser.add_argument("--max-video-mb", type=int, default=300)
    parser.add_argument("--force", action="store_true"); parser.add_argument("--keyframes", action="store_true"); parser.add_argument("--ocr", action="store_true"); parser.add_argument("--transcribe", action="store_true"); parser.add_argument("--asr-model", default="small"); parser.add_argument("--language", default="zh"); parser.add_argument("--interpret", action="store_true"); parser.add_argument("--describe-visuals", action="store_true")
    parser.add_argument("--enrich-dir")
    args = parser.parse_args(argv)
    if args.enrich_dir:
        output = Path(args.enrich_dir).expanduser().resolve(); manifest = output / "content_package.json"
        result, _ = migrate_content_package_in_memory(json.loads(manifest.read_text(encoding="utf-8"))); process_local_stages(result, output, keyframes=args.keyframes, ocr=args.ocr, transcribe=args.transcribe, asr_model=args.asr_model, language=args.language, interpret=args.interpret, describe_visuals=args.describe_visuals)
    else:
        if not args.url: parser.error("--url is required unless --enrich-dir is used")
        root = Path(args.output_dir).expanduser().resolve(); existing = None if args.run_dir else find_existing_package(root, note_id_from_url(args.url))
        if should_reuse(existing, args.force): print(existing / "report.md"); return 0
        output = Path(args.run_dir).expanduser().resolve() if args.run_dir else root / datetime.now().strftime("%Y%m%d-%H%M%S"); output.mkdir(parents=True, exist_ok=True)
        try:
            result = capture_public_note(args.url, output, args.timeout, args.max_video_mb * 1024 * 1024)
            # Checkpoint capture before CPU-bound local stages so interruption is recoverable.
            _write_json(output / "content_package.json", result)
            atomic_write_text(output / "report.md", render_public_report(result))
            process_local_stages(result, output, keyframes=args.keyframes, ocr=args.ocr, transcribe=False, asr_model=args.asr_model, language=args.language, interpret=args.interpret, describe_visuals=args.describe_visuals)
        except PublicCaptureError as error:
            result = new_content_package("failed", redact_url(args.url)); result["errors"].append({"stage": "capture", "code": str(error)}); result["limitations"].append(str(error)); recompute_completeness(result)
    result["errors"].extend({"stage": "schema", "code": item} for item in validate_content_package(result))
    result["processing_status"] = compute_processing_status(result.get("processing", {}))
    _write_json(output / "content_package.json", result); atomic_write_text(output / "report.md", render_public_report(result))
    print(output / "report.md"); return 0 if result["status"] != "failed" else 1


if __name__ == "__main__": raise SystemExit(main())
