#!/usr/bin/env python3
"""Capture one public XHS note, its direct video, cover, and local transcript."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from public_html_provider import PublicCaptureError, capture_public_note, note_id_from_url
from content_package import field_status, find_existing_package, should_reuse, srt


def transcribe(video: Path) -> list[dict]:
    from faster_whisper import WhisperModel

    model = WhisperModel("small", device="cpu", compute_type="int8")
    segments, _ = model.transcribe(str(video), language="zh", vad_filter=True)
    return [{"start": segment.start, "end": segment.end, "text": segment.text.strip()} for segment in segments if segment.text.strip()]


def render_public_report(result: dict) -> str:
    post = result["post"]
    metrics = post["metrics"]
    media = result["media"]
    source = result["source"]
    lines = ["# 小红书公开帖子与本地口播", "", "## 帖子信息", "", f"- 链接：{source.get('resolved_url') or '未获取'}", f"- 帖子 ID：{source.get('note_id') or '未获取'}", f"- 标题：{post.get('title') or '未获取'}", f"- 作者：{post['author'].get('nickname') or '未获取'}", f"- 点赞：{metrics.get('likes') or '未获取'}", f"- 收藏：{metrics.get('favorites') or '未获取'}", f"- 评论数：{metrics.get('comments') or '未获取'}", f"- 标签：{' '.join(post.get('tags') or []) or '未获取'}", "", "## 正文", "", post.get("description") or "未获取", "", "## 媒体", "", f"- 视频：{media.get('video', {}).get('path') if media.get('video') else '未获取'}", f"- 封面：{media.get('cover', {}).get('path') if media.get('cover') else '未获取'}", "", "## 评论", "", "- 本 Skill 只读取公开 HTML，不采集评论详情或二级回复。", "", "## 本地口播逐字稿", ""]
    transcript = result.get("transcript") or []
    lines += ["> 来源：faster-whisper small，本地 CPU int8 自动转写；可能存在听辨或断句错误。", "", *[f"{item['start']:.2f}—{item['end']:.2f}  {item['text']}" for item in transcript]] if transcript else ["[未生成：视频不可用或本地转写失败。]"]
    lines += ["", "## 获取完整度", "", *[f"- {key}：{value}" for key, value in (result.get("completeness") or {}).items()], "", "## 限制", "", *[f"- {item}" for item in result.get("limitations") or []], ""]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--output-dir", default="output")
    parser.add_argument("--run-dir", help="Reuse this existing capture directory instead of creating a timestamped one")
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--max-video-mb", type=int, default=300)
    parser.add_argument("--force", action="store_true", help="Capture again even if the direct note ID already exists")
    args = parser.parse_args()
    output_root = Path(args.output_dir).expanduser().resolve()
    existing = None if args.run_dir else find_existing_package(output_root, note_id_from_url(args.url))
    if should_reuse(existing, args.force):
        print(existing / "report.md")
        return 0
    output = Path(args.run_dir).expanduser().resolve() if args.run_dir else output_root / __import__("datetime").datetime.now().strftime("%Y%m%d-%H%M%S")
    output.mkdir(parents=True, exist_ok=True)
    report = output / "report.md"
    if report.is_file():
        print(report)
        return 0
    try:
        result = capture_public_note(args.url, output, args.timeout, args.max_video_mb * 1024 * 1024)
        video_info = result["media"].get("video")
        if video_info:
            video = output / "media" / video_info["path"]
            try:
                result["transcript"] = transcribe(video)
                derived = output / "derived"; derived.mkdir(exist_ok=True)
                (derived / "transcript.txt").write_text("\n".join(item["text"] for item in result["transcript"]) + "\n", encoding="utf-8")
                (derived / "transcript_segments.json").write_text(json.dumps(result["transcript"], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                (derived / "subtitles.srt").write_text(srt(result["transcript"]), encoding="utf-8")
            except Exception as error:
                result["limitations"].append(f"本地口播转写失败：{type(error).__name__}: {error}")
        result["completeness"] = {"title": field_status(result["post"]["title"]), "description": field_status(result["post"]["description"]), "video": field_status(video_info), "images": field_status(result["media"]["images"]), "comments": "intentionally_not_collected", "transcript": field_status(result.get("transcript")) if video_info else "not_run"}
        (output / "content_package.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        report.write_text(render_public_report(result), encoding="utf-8")
        print(report)
        return 0
    except PublicCaptureError as error:
        failed = {"source": {"input_url": args.url}, "post": {"title": None, "description": None, "tags": [], "author": {"nickname": None}, "metrics": {}}, "media": {"video": None, "cover": None}, "limitations": [str(error)]}
        (output / "content_package.json").write_text(json.dumps(failed, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        report.write_text(render_public_report(failed), encoding="utf-8")
        print(report)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
