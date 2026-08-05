"""Small, dependency-free primitives for public content packages."""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import platform
import tempfile
from datetime import datetime, timezone
from pathlib import Path


COMPLETENESS_STATUSES = {"available", "partial", "zero", "not_exposed", "intentionally_omitted", "failed", "not_run"}


def field_status(value, *, reason: str | None = None, count: int | None = None) -> dict:
    """Represent absence without confusing it with a real zero value."""
    if value is None:
        status = "not_exposed"
    if isinstance(value, (list, tuple, dict, set)) and not value:
        status = "not_exposed"
    elif value == 0:
        status = "zero"
    elif value is not None:
        status = "available"
    return {"status": status, "count": count if count is not None else (len(value) if isinstance(value, (list, tuple, dict, set)) else None), "reason": reason}


def completeness(status: str, count: int | None = None, reason: str | None = None) -> dict:
    if status not in COMPLETENESS_STATUSES:
        raise ValueError(f"invalid completeness status: {status}")
    return {"status": status, "count": count, "reason": reason}


def runtime_metadata() -> dict:
    versions = {"python": platform.python_version()}
    for name in ("httpx", "av", "faster_whisper", "PIL"):
        try:
            module = __import__(name)
            versions[name] = getattr(module, "__version__", "installed")
        except Exception:
            versions[name] = None
    return {"generator": {"name": "IWIG", "version": "0.3.0-alpha", "python": sys.version.split()[0], "dependencies": versions}, "provider": {"name": "xiaohongshu-public-html", "version": "1"}}


def new_content_package(status: str, input_url: str | None) -> dict:
    if status not in {"completed", "partial", "failed"}:
        raise ValueError("invalid package status")
    now = datetime.now(timezone.utc).isoformat()
    return {"schema": {"name": "iwig-content-package", "version": "2.0.0"}, "schema_version": 2, "status": status,
            "identity": {"platform": "xiaohongshu", "note_id": None, "author_id": None, "package_id": None, "snapshot_id": None, "snapshot_at": now, "content_fingerprint": None, "primary_media_sha256": None},
            "source": {"input_url": input_url, "resolved_url": None, "canonical_url": None,
                       "note_id": None, "provider": "public_html", "captured_at": now},
            "post": {"title": None, "description": None, "tags": [], "type": None, "published_at": None,
                     "author": {"id": None, "nickname": None},
                     "metrics": {"likes": None, "favorites": None, "comments": None, "shares": None}},
            "media": {"video": None, "cover": None, "images": []}, "derived": {"keyframes": [], "selected_keyframes": [], "scenes": [], "transcript": None, "ocr": {"cover": None, "images": [], "keyframes": []}, "timeline": None}, "field_provenance": {},
            "processing": {}, "errors": [], "limitations": [], "completeness": {}, "runtime": runtime_metadata()}


def atomic_write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as target:
        json.dump(value, target, ensure_ascii=False, indent=2)
        target.write("\n")
        temporary = Path(target.name)
    temporary.replace(path)


def safe_artifact_path(run_dir: Path, relative: str) -> Path:
    """Resolve a package path without permitting absolute, parent, or symlink escapes."""
    candidate = Path(relative)
    if not relative or candidate.is_absolute() or ".." in candidate.parts:
        raise ValueError("unsafe_relative_path")
    root, target = run_dir.resolve(), (run_dir / candidate).resolve()
    if root not in target.parents and target != root:
        raise ValueError("unsafe_relative_path")
    return target


def _schema(name: str) -> dict:
    path = Path(__file__).resolve().parents[1] / "schemas" / name
    return json.loads(path.read_text(encoding="utf-8"))


def _path_issues(value, path="") -> list[str]:
    issues = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}" if path else key
            if key == "path" and isinstance(child, str) and (Path(child).is_absolute() or ".." in Path(child).parts):
                issues.append(f"invalid_relative_path:{child_path}")
            issues.extend(_path_issues(child, child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value): issues.extend(_path_issues(child, f"{path}.{index}"))
    return issues


def validate_content_package_schema(package: dict) -> list[str]:
    try:
        from jsonschema import Draft202012Validator
        issues = [f"schema:{item.json_path}:{item.message}" for item in Draft202012Validator(_schema("iwig-content-package-v2.schema.json")).iter_errors(package)]
    except ImportError:
        issues = ["schema:jsonschema_not_installed"]
    return issues + _path_issues(package)


def validate_content_package(package: dict) -> list[str]:
    required = ("schema", "schema_version", "status", "identity", "source", "post", "media", "derived", "field_provenance", "processing", "errors", "limitations", "completeness", "runtime")
    errors = [f"missing:{name}" for name in required if name not in package]
    if package.get("status") not in {"completed", "partial", "failed"}:
        errors.append("invalid:status")
    for key, value in (package.get("completeness") or {}).items():
        if not isinstance(value, dict) or value.get("status") not in COMPLETENESS_STATUSES:
            errors.append(f"invalid:completeness.{key}")
    if not isinstance(package.get("media"), dict):
        errors.append("invalid:media")
    return errors + validate_content_package_schema(package)


def build_timeline(transcript: list[dict], frames: list[dict], scenes: list[dict] | None = None, duration_seconds: float | None = None) -> dict:
    events, relations = [], []
    for index, segment in enumerate(transcript, 1):
        speech_id = f"speech-{index:03}"
        events.append({"id": speech_id, "type": "speech", "start": segment["start"], "end": segment["end"], "text": segment.get("text", "")})
    for frame in frames:
        frame_id, at = frame.get("id"), frame.get("time_seconds", 0)
        events.append({"id": frame_id, "type": "frame", "at": at, "frame_ref": frame_id})
        text = (frame.get("ocr") or {}).get("text", "")
        if text: events.append({"id": f"ocr-{frame_id}", "type": "ocr", "at": at, "frame_ref": frame_id, "text": text})
        for speech in [event for event in events if event["type"] == "speech" and event["start"] <= at <= event["end"]]: relations.append({"from": frame_id, "to": speech["id"], "type": "overlaps"})
    for scene in scenes or []: events.append({"id": scene["id"], "type": "scene", "start": scene["start_seconds"], "end": scene["end_seconds"]})
    return {"schema": {"name": "iwig-timeline", "version": "1.0.0"}, "duration_seconds": duration_seconds, "events": events, "relations": relations}


def find_existing_package(output_dir: Path, note_id: str | None) -> Path | None:
    if not note_id or not output_dir.is_dir():
        return None
    candidates = []
    for manifest in output_dir.glob("*/content_package.json"):
        try:
            package = json.loads(manifest.read_text(encoding="utf-8"))
            if package.get("source", {}).get("note_id") == note_id and package.get("status") == "completed" and not package.get("stale") and not validate_content_package(package):
                media = package.get("media", {}); records = [item for item in [media.get("video"), media.get("cover")] if item] + media.get("images", [])
                if all(safe_artifact_path(manifest.parent, record["path"]).is_file() and file_record(safe_artifact_path(manifest.parent, record["path"]), manifest.parent)["sha256"] == record.get("sha256") for record in records): candidates.append((package["source"].get("captured_at") or "", manifest.parent))
        except (OSError, json.JSONDecodeError):
            continue
    return max(candidates, default=("", None))[1]


def should_reuse(existing: Path | None, force: bool) -> bool:
    return existing is not None and not force


def file_record(path: Path, run_dir: Path | None = None) -> dict:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    try:
        value = path.relative_to(run_dir).as_posix() if run_dir else path.name
    except ValueError:
        value = path.name
    return {"path": value, "size_bytes": path.stat().st_size, "sha256": digest.hexdigest()}


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


def perceptual_hash(path: Path) -> str | None:
    """A compact, dependency-optional dHash used only for local frame comparison."""
    try:
        from PIL import Image
        with Image.open(path) as image:
            pixels = image.convert("L").resize((9, 8)).load()
            bits = "".join("1" if pixels[x, y] > pixels[x + 1, y] else "0" for y in range(8) for x in range(8))
        return f"{int(bits, 2):016x}"
    except Exception:
        return None


def hash_similarity(left: str | None, right: str | None) -> float | None:
    if not left or not right:
        return None
    distance = bin(int(left, 16) ^ int(right, 16)).count("1")
    return round(1 - distance / max(len(left) * 4, 1), 3)


def scene_boundaries(frames: list[dict], threshold: float = 0.72) -> list[dict]:
    scenes, start, previous = [], 0, None
    for index, frame in enumerate(frames):
        similarity = hash_similarity(previous.get("perceptual_hash") if previous else None, frame.get("perceptual_hash"))
        frame["adjacent_similarity"] = similarity
        if previous and similarity is not None and similarity < threshold:
            scenes.append(_scene(frames, start, index - 1, similarity, len(scenes) + 1))
            start = index
        previous = frame
    if frames:
        scenes.append(_scene(frames, start, len(frames) - 1, frames[start].get("adjacent_similarity"), len(scenes) + 1))
    return scenes


def _scene(frames: list[dict], start: int, end: int, similarity: float | None, number: int) -> dict:
    scene_id = f"scene-{number:03}"
    members = frames[start:end + 1]
    for frame in members: frame["scene_id"] = scene_id
    return {"id": scene_id, "start_seconds": members[0].get("time_seconds", 0), "end_seconds": members[-1].get("time_seconds", 0), "frame_ids": [item.get("id") for item in members], "representative_frame_id": members[0].get("id"), "boundary_similarity": similarity}


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


def select_structural_keyframes(frames: list[dict], duration_seconds: float, limit: int = 8) -> list[dict]:
    ranked = []
    previous_text = ""
    for frame in frames:
        position = frame.get("time_seconds", 0) / max(duration_seconds, 1)
        text = (frame.get("ocr") or {}).get("text", "")
        words = set(text.replace("\n", " ").split())
        previous_words = set(previous_text.replace("\n", " ").split())
        novelty = 1 if words and words != previous_words else 0
        score_components = {"text_density": round(min(len(text), 80) / 20, 2), "ocr_novelty": novelty * 2, "scene_change": 2 if frame.get("adjacent_similarity") is not None and frame["adjacent_similarity"] < .72 else 0}
        score = sum(score_components.values())
        reasons = ["ocr_text_density"] if text else []
        if position <= 0.08:
            score += 4; score_components["start"] = 4; reasons.append("start")
        elif position >= 0.9:
            score += 2; score_components["end"] = 2; reasons.append("end")
        ranked.append({**frame, "score": round(score, 2), "score_components": score_components, "reasons": reasons})
        previous_text = text
    return sorted(ranked, key=lambda item: (-item["score"], item["time_seconds"]))[:limit]


def ocr_macos_batch(images: list[Path]) -> list[dict]:
    script = Path(__file__).with_name("ocr_macos.swift")
    if not images:
        return []
    try:
        completed = subprocess.run(["/usr/bin/swift", str(script), *map(str, images)], capture_output=True, text=True, check=True, timeout=300)
        return [{"status": "available", **item} for item in json.loads(completed.stdout)]
    except Exception as error:
        return [{"status": "failed", "reason": type(error).__name__, "text": "", "lines": []} for _ in images]


def ocr_macos(image: Path) -> dict:
    return ocr_macos_batch([image])[0]


def _timestamp(seconds: float) -> str:
    milliseconds = round(seconds * 1000)
    hours, milliseconds = divmod(milliseconds, 3_600_000)
    minutes, milliseconds = divmod(milliseconds, 60_000)
    seconds, milliseconds = divmod(milliseconds, 1_000)
    return f"{hours:02}:{minutes:02}:{seconds:02},{milliseconds:03}"


def srt(segments: list[dict]) -> str:
    return "".join(f"{index}\n{_timestamp(item['start'])} --> {_timestamp(item['end'])}\n{item['text']}\n" for index, item in enumerate(segments, 1))
