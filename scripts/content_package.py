"""Small, dependency-free primitives for public content packages."""
from __future__ import annotations

import hashlib
import json
import subprocess
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


def should_reuse(existing: Path | None, force: bool) -> bool:
    return existing is not None and not force


def file_record(path: Path) -> dict:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return {"path": path.name, "size_bytes": path.stat().st_size, "sha256": digest.hexdigest()}


def image_metadata(path: Path) -> dict:
    header = path.read_bytes()
    if header.startswith(b"\x89PNG\r\n\x1a\n") and header[12:16] == b"IHDR":
        return {"format": "png", "width": int.from_bytes(header[16:20], "big"), "height": int.from_bytes(header[20:24], "big")}
    if header.startswith(b"\xff\xd8"):
        index = 2
        while index + 9 < len(header):
            if header[index] != 0xFF:
                index += 1; continue
            marker = header[index + 1]
            length = int.from_bytes(header[index + 2:index + 4], "big")
            if marker in {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}:
                return {"format": "jpeg", "width": int.from_bytes(header[index + 7:index + 9], "big"), "height": int.from_bytes(header[index + 5:index + 7], "big")}
            index += 2 + length
    if header.startswith(b"RIFF") and header[8:12] == b"WEBP" and header[12:16] == b"VP8X" and len(header) >= 30:
        return {"format": "webp", "width": int.from_bytes(header[24:27], "little") + 1, "height": int.from_bytes(header[27:30], "little") + 1}
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


def extract_keyframes(path: Path, destination: Path, interval_seconds: int = 30, max_frames: int = 12) -> dict:
    try:
        import av
        destination.mkdir(parents=True, exist_ok=True)
        saved, next_second = [], 0.0
        with av.open(str(path)) as container:
            stream = next(item for item in container.streams if item.type == "video")
            for frame in container.decode(stream):
                seconds = float(frame.time or 0)
                if seconds < next_second:
                    continue
                target = destination / f"{len(saved) + 1:03}.jpg"
                frame.to_image().save(target, quality=85)
                saved.append({"path": target.name, "time_seconds": seconds})
                next_second = seconds + interval_seconds
                if len(saved) >= max_frames:
                    break
        return {"status": "available", "frames": saved}
    except Exception as error:
        return {"status": "failed", "reason": type(error).__name__, "frames": []}


def ocr_macos(image: Path) -> dict:
    script = Path(__file__).with_name("ocr_macos.swift")
    try:
        completed = subprocess.run(["/usr/bin/swift", str(script), str(image)], capture_output=True, text=True, check=True, timeout=60)
        return {"status": "available", **json.loads(completed.stdout)}
    except Exception as error:
        return {"status": "failed", "reason": type(error).__name__, "text": "", "lines": []}


def _timestamp(seconds: float) -> str:
    milliseconds = round(seconds * 1000)
    hours, milliseconds = divmod(milliseconds, 3_600_000)
    minutes, milliseconds = divmod(milliseconds, 60_000)
    seconds, milliseconds = divmod(milliseconds, 1_000)
    return f"{hours:02}:{minutes:02}:{seconds:02},{milliseconds:03}"


def srt(segments: list[dict]) -> str:
    return "".join(f"{index}\n{_timestamp(item['start'])} --> {_timestamp(item['end'])}\n{item['text']}\n" for index, item in enumerate(segments, 1))
