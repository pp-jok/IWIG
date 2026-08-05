#!/usr/bin/env python3
"""Capture one public XHS note and run resumable local processing stages."""
from __future__ import annotations

import argparse
import json
import hashlib
from datetime import datetime, timezone
from datetime import datetime
from pathlib import Path

from content_package import (atomic_write_json, build_timeline, completeness, extract_keyframes, field_status,
                             find_existing_package, new_content_package, ocr_macos,
                             ocr_macos_batch, perceptual_hash, scene_boundaries, select_structural_keyframes, should_reuse, srt,
                             validate_content_package)
from public_html_provider import PublicCaptureError, capture_public_note, note_id_from_url, redact_url


def _write_json(path: Path, value: object) -> None:
    atomic_write_json(path, value)


def _stage(result: dict, name: str, status: str, outputs=None, tool=None, warnings=None) -> None:
    result.setdefault("processing", {})[name] = {"status": status, "output_paths": outputs or [], "tool": tool, "started_at": result.get("processing", {}).get(name, {}).get("started_at", datetime.now(timezone.utc).isoformat()), "completed_at": datetime.now(timezone.utc).isoformat(), "warnings": warnings or []}


def transcribe(video: Path) -> tuple[list[dict], dict]:
    from faster_whisper import WhisperModel
    model_name = "small"
    model = WhisperModel(model_name, device="cpu", compute_type="int8")
    segments, info = model.transcribe(str(video), language="zh", vad_filter=True)
    raw = [{"start": item.start, "end": item.end, "text": item.text, "avg_logprob": getattr(item, "avg_logprob", None)} for item in segments]
    normalized = [{"start": item["start"], "end": item["end"], "text": item["text"].strip()} for item in raw if item["text"].strip()]
    return normalized, {"engine": "faster-whisper", "model": model_name, "language": getattr(info, "language", "zh"), "segment_count": len(normalized), "warnings": [] , "raw_segments": raw}


def _path(run: Path, record: dict | None) -> Path | None:
    return run / record["path"] if record and record.get("path") else None


def process_keyframes(result: dict, run: Path, enabled: bool) -> None:
    video = _path(run, result["media"].get("video"))
    if not enabled or not video or not video.is_file():
        if "extract_keyframes" not in result.get("processing", {}): _stage(result, "extract_keyframes", "not_run", warnings=["keyframes not requested or video unavailable"])
        return
    existing = result.get("derived", {}).get("keyframes") or []
    if existing and all((run / item["path"]).is_file() for item in existing):
        _stage(result, "extract_keyframes", "completed", [item["path"] for item in existing], "PyAV", ["reused existing frames"])
        return
    extracted = extract_keyframes(video, run / "derived" / "keyframes")
    frames = extracted.get("frames", [])
    for index, frame in enumerate(frames, 1):
        frame.update({"id": f"frame-{index:03}", "path": f"derived/keyframes/{frame['path']}", "perceptual_hash": perceptual_hash(run / f"derived/keyframes/{frame['path']}"), "ocr": {"status": "not_run", "text": "", "lines": []}})
    result["derived"]["keyframes"] = frames
    result["derived"]["scenes"] = scene_boundaries(frames)
    _stage(result, "extract_keyframes", extracted.get("status", "failed"), [item["path"] for item in frames], "PyAV")


def process_transcript(result: dict, run: Path) -> None:
    video = _path(run, result["media"].get("video"))
    previous = result.get("processing", {}).get("transcribe", {})
    outputs = previous.get("output_paths", [])
    if previous.get("status") == "completed" and outputs and all((run / item).is_file() for item in outputs):
        return
    if not video or not video.is_file():
        return
    try:
        normalized, metadata = transcribe(video)
        raw = metadata.pop("raw_segments")
        result["transcript"] = normalized  # compatibility
        result["transcript_metadata"] = metadata
        result["derived"]["transcript"] = {"raw_path": "derived/transcript_raw_segments.json", "normalized_path": "derived/transcript_segments.json", "metadata": metadata}
        _write_json(run / "derived" / "transcript_raw_segments.json", raw)
        _write_json(run / "derived" / "transcript_segments.json", normalized)
        (run / "derived" / "transcript.txt").write_text("\n".join(item["text"] for item in normalized) + "\n", encoding="utf-8")
        (run / "derived" / "subtitles.srt").write_text(srt(normalized), encoding="utf-8")
        _stage(result, "transcribe", "completed", ["derived/transcript_raw_segments.json", "derived/transcript_segments.json", "derived/subtitles.srt"], "faster-whisper")
    except Exception as error:
        result.setdefault("errors", []).append({"stage": "transcript", "code": type(error).__name__})
        result.setdefault("limitations", []).append(f"本地口播转写失败：{type(error).__name__}")
        _stage(result, "transcribe", "failed", tool="faster-whisper", warnings=[type(error).__name__])


def _ocr_records(run: Path, records: list[dict]) -> list[dict]:
    usable = [(record, _path(run, record)) for record in records]
    usable = [(record, image) for record, image in usable if image and image.is_file()]
    return [{"path": record["path"], **value} for (record, _), value in zip(usable, ocr_macos_batch([image for _, image in usable]))]


def process_ocr_cover(result: dict, run: Path, enabled: bool) -> None:
    previous = result.get("processing", {}).get("ocr_cover", {})
    if enabled and result["media"].get("cover") and previous.get("status") != "completed":
        records = _ocr_records(run, [result["media"]["cover"]])
        if not records:
            _stage(result, "ocr_cover", "failed", warnings=["cover file unavailable"]); return
        value = records[0]
        result.setdefault("ocr", {"images": [], "keyframes": []})["cover"] = value; result["derived"]["ocr"]["cover"] = value
        _stage(result, "ocr_cover", "completed" if value["status"] == "available" else "failed", [value["path"]], "macOS Vision")


def process_ocr_images(result: dict, run: Path, enabled: bool) -> None:
    previous = result.get("processing", {}).get("ocr_images", {})
    if enabled and result["media"].get("images") and previous.get("status") != "completed":
        values = _ocr_records(run, result["media"]["images"])
        result.setdefault("ocr", {"images": [], "keyframes": []})["images"] = values; result["derived"]["ocr"]["images"] = values
        _stage(result, "ocr_images", "completed" if values and all(item["status"] == "available" for item in values) else "failed", [item["path"] for item in values], "macOS Vision")


def process_ocr_keyframes(result: dict, run: Path, enabled: bool) -> None:
    frames = result.get("derived", {}).get("keyframes", [])
    previous = result.get("processing", {}).get("ocr_keyframes", {})
    if enabled and frames and previous.get("status") != "completed":
        records = _ocr_records(run, frames)
        for record, frame in zip(records, frames):
            frame["ocr"] = {key: value for key, value in record.items() if key != "path"}
        result.setdefault("ocr", {"images": [], "keyframes": []})["keyframes"] = records
        result["derived"]["ocr"]["keyframes"] = records
        duration = (result["media"].get("video") or {}).get("metadata", {}).get("duration_seconds") or 1
        result["derived"]["selected_keyframes"] = select_structural_keyframes(frames, duration)
        _stage(result, "ocr_keyframes", "completed" if records and all(item["status"] == "available" for item in records) else "failed", [item["path"] for item in records], "macOS Vision")


def recompute_completeness(result: dict) -> None:
    video = result["media"].get("video")
    result["completeness"] = {
        "title": field_status(result["post"].get("title")), "description": field_status(result["post"].get("description")),
        "video": field_status(video), "images": field_status(result["media"].get("images")),
        "comments": completeness("intentionally_omitted", reason="public HTML capture does not collect comment bodies"),
        "transcript": field_status(result.get("transcript")) if video else completeness("not_run", reason="video unavailable"),
        "ocr": field_status(result.get("ocr")) if result.get("ocr") else completeness("not_run", reason="OCR not requested"),
    }


def process_local_stages(result: dict, run: Path, *, keyframes: bool, ocr: bool) -> None:
    process_keyframes(result, run, keyframes)
    process_transcript(result, run)
    process_ocr_cover(result, run, ocr)
    process_ocr_images(result, run, ocr)
    process_ocr_keyframes(result, run, ocr)
    frames = result.get("derived", {}).get("keyframes", [])
    duration = (result["media"].get("video") or {}).get("metadata", {}).get("duration_seconds")
    timeline = build_timeline(result.get("transcript") or [], frames, result.get("derived", {}).get("scenes", []), duration)
    _write_json(run / "derived" / "timeline.json", timeline)
    result["derived"]["timeline"] = {"path": "derived/timeline.json"}
    _stage(result, "build_timeline", "completed", ["derived/timeline.json"])
    recompute_completeness(result)
    identity = result["identity"]
    source, post, video = result["source"], result["post"], result["media"].get("video")
    identity.update({"note_id": source.get("note_id"), "author_id": post.get("author", {}).get("id"), "snapshot_at": source.get("captured_at"), "primary_media_sha256": (video or {}).get("sha256")})
    seed = "\n".join(str(item or "") for item in (source.get("note_id"), post.get("title"), post.get("description"), identity["author_id"], identity["primary_media_sha256"]))
    identity["content_fingerprint"] = hashlib.sha256(seed.encode()).hexdigest(); identity["package_id"] = hashlib.sha256(f"xiaohongshu:{source.get('note_id')}".encode()).hexdigest()[:20]; identity["snapshot_id"] = hashlib.sha256(f"{identity['package_id']}:{identity['snapshot_at']}".encode()).hexdigest()[:20]


def render_public_report(result: dict) -> str:
    post, media, source = result["post"], result["media"], result["source"]
    value = lambda item: "未获取" if item is None else item
    lines = ["# 小红书公开内容包", "", "## 帖子信息", "", f"- 链接：{value(source.get('canonical_url') or source.get('resolved_url'))}", f"- 帖子 ID：{value(source.get('note_id'))}", f"- 标题：{value(post.get('title'))}", f"- 作者：{value(post['author'].get('nickname'))}", f"- 点赞：{value(post['metrics'].get('likes'))}", f"- 收藏：{value(post['metrics'].get('favorites'))}", f"- 评论数：{value(post['metrics'].get('comments'))}", "", "## 正文", "", post.get("description") or "未获取", "", "## 媒体", "", f"- 视频：{media.get('video', {}).get('path') if media.get('video') else '未获取'}", f"- 封面：{media.get('cover', {}).get('path') if media.get('cover') else '未获取'}", f"- 图文页：{len(media.get('images') or [])}", "", "## 评论", "", "- 本 Skill 只读取公开 HTML，不采集评论详情或二级回复。", "", "## 获取完整度", ""]
    lines += [f"- {key}：{item.get('status') if isinstance(item, dict) else item}" for key, item in result.get("completeness", {}).items()]
    return "\n".join(lines + ["", "## 限制", "", *[f"- {item}" for item in result.get("limitations") or []], ""])


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url"); parser.add_argument("--output-dir", default="output"); parser.add_argument("--run-dir")
    parser.add_argument("--timeout", type=float, default=20); parser.add_argument("--max-video-mb", type=int, default=300)
    parser.add_argument("--force", action="store_true"); parser.add_argument("--keyframes", action="store_true"); parser.add_argument("--ocr", action="store_true")
    parser.add_argument("--enrich-dir"); parser.add_argument("--keep-raw-source", action="store_true")
    args = parser.parse_args(argv)
    if args.enrich_dir:
        output = Path(args.enrich_dir).expanduser().resolve(); manifest = output / "content_package.json"
        result = json.loads(manifest.read_text(encoding="utf-8")); process_local_stages(result, output, keyframes=args.keyframes, ocr=args.ocr)
    else:
        if not args.url: parser.error("--url is required unless --enrich-dir is used")
        root = Path(args.output_dir).expanduser().resolve(); existing = None if args.run_dir else find_existing_package(root, note_id_from_url(args.url))
        if should_reuse(existing, args.force): print(existing / "report.md"); return 0
        output = Path(args.run_dir).expanduser().resolve() if args.run_dir else root / datetime.now().strftime("%Y%m%d-%H%M%S"); output.mkdir(parents=True, exist_ok=True)
        try:
            result = capture_public_note(args.url, output, args.timeout, args.max_video_mb * 1024 * 1024, args.keep_raw_source)
            process_local_stages(result, output, keyframes=args.keyframes, ocr=args.ocr)
        except PublicCaptureError as error:
            result = new_content_package("failed", redact_url(args.url)); result["errors"].append({"stage": "capture", "code": str(error)}); result["limitations"].append(str(error)); recompute_completeness(result)
    result["errors"].extend({"stage": "schema", "code": item} for item in validate_content_package(result))
    _write_json(output / "content_package.json", result); (output / "report.md").write_text(render_public_report(result), encoding="utf-8")
    print(output / "report.md"); return 0 if result["status"] != "failed" else 1


if __name__ == "__main__": raise SystemExit(main())
