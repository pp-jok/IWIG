"""Small, dependency-free primitives for public content packages."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


def field_status(value) -> str:
    if value is None:
        return "not_exposed"
    if value == 0:
        return "zero"
    return "available"


def find_existing_package(output_dir: Path, note_id: str | None) -> Path | None:
    if not note_id or not output_dir.is_dir():
        return None
    for manifest in output_dir.glob("*/content_package.json"):
        try:
            if json.loads(manifest.read_text(encoding="utf-8")).get("source", {}).get("note_id") == note_id:
                return manifest.parent
        except (OSError, json.JSONDecodeError):
            continue
    return None


def file_record(path: Path) -> dict:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return {"path": path.name, "size_bytes": path.stat().st_size, "sha256": digest.hexdigest()}


def image_metadata(path: Path) -> dict:
    header = path.read_bytes()[:32]
    if header.startswith(b"\x89PNG\r\n\x1a\n") and header[12:16] == b"IHDR":
        return {"format": "png", "width": int.from_bytes(header[16:20], "big"), "height": int.from_bytes(header[20:24], "big")}
    return {"format": path.suffix.lstrip(".").lower() or "unknown", "width": None, "height": None}


def video_metadata(path: Path) -> dict:
    try:
        import av
        with av.open(str(path)) as container:
            stream = next((item for item in container.streams if item.type == "video"), None)
            if stream is None:
                return {"status": "not_exposed"}
            duration = float(stream.duration * stream.time_base) if stream.duration is not None else None
            return {"status": "available", "duration_seconds": duration, "width": stream.width, "height": stream.height, "codec": stream.codec_context.name, "container": container.format.name}
    except Exception as error:
        return {"status": "failed", "reason": type(error).__name__}


def _timestamp(seconds: float) -> str:
    milliseconds = round(seconds * 1000)
    hours, milliseconds = divmod(milliseconds, 3_600_000)
    minutes, milliseconds = divmod(milliseconds, 60_000)
    seconds, milliseconds = divmod(milliseconds, 1_000)
    return f"{hours:02}:{minutes:02}:{seconds:02},{milliseconds:03}"


def srt(segments: list[dict]) -> str:
    return "".join(f"{index}\n{_timestamp(item['start'])} --> {_timestamp(item['end'])}\n{item['text']}\n" for index, item in enumerate(segments, 1))
