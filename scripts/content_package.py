"""Small, dependency-free primitives for public content packages."""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import platform
import tempfile
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path


COMPLETENESS_STATUSES = {"available", "partial", "zero", "not_exposed", "intentionally_omitted", "failed", "not_run"}
PROCESSING_STATUSES = {"not_run", "running", "completed", "partial", "failed"}


def compute_processing_status(processing: dict) -> str:
    statuses = [stage.get("status") for stage in processing.values() if isinstance(stage, dict) and stage.get("status") in PROCESSING_STATUSES - {"not_run"}]
    if not statuses:
        return "not_run"
    if all(status == "completed" for status in statuses):
        return "completed"
    if all(status == "failed" for status in statuses):
        return "failed"
    if any(status in {"completed", "partial", "running"} for status in statuses):
        return "partial"
    return "failed"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def upsert_active_error(package: dict, *, stage: str, code: str, detail: str | None = None) -> None:
    error = {"stage": stage, "code": code}
    if detail:
        error["detail"] = detail
    active = [item for item in package.setdefault("active_errors", []) if (item.get("stage"), item.get("code")) != (stage, code)]
    active.append(error)
    package["active_errors"] = active


def resolve_active_error(package: dict, *, stage: str, code: str | None = None) -> None:
    active, resolved = [], []
    for error in package.setdefault("active_errors", []):
        if error.get("stage") == stage and (code is None or error.get("code") == code):
            resolved.append(error)
        else:
            active.append(error)
    package["active_errors"] = active
    for error in resolved:
        record = dict(error)
        record["resolved_at"] = _now()
        package.setdefault("error_history", []).append(record)


def migrate_content_package_in_memory(package: dict) -> tuple[dict, list[str]]:
    migrated, notes = deepcopy(package), []
    legacy_errors = migrated.get("errors", [])
    index_only = bool(legacy_errors) and all(item.get("stage") == "analysis_index" and item.get("code") == "analysis_index_build_failed" for item in legacy_errors)
    primary_media = bool((migrated.get("media") or {}).get("video") or (migrated.get("media") or {}).get("images"))
    if migrated.get("status") == "partial" and index_only and primary_media:
        migrated["status"] = "completed"; notes.append("recovered:capture_status_from_legacy_index_failure")
    if "capture_status" not in migrated:
        migrated["capture_status"] = migrated.get("status", "failed"); notes.append("added:capture_status")
    migrated["status"] = migrated["capture_status"]
    if "processing_status" not in migrated:
        migrated["processing_status"] = compute_processing_status(migrated.get("processing") or {}); notes.append("added:processing_status")
    if "active_errors" not in migrated:
        migrated["active_errors"] = []; notes.append("added:active_errors")
    if "error_history" not in migrated:
        migrated["error_history"] = []; notes.append("added:error_history")
    legacy_index_errors = [item for item in migrated.get("errors", []) if item.get("stage") == "analysis_index" and item.get("code") == "analysis_index_build_failed"]
    if legacy_index_errors or "analysis_index_build_failed" in migrated.get("limitations", []):
        stage = (migrated.get("processing") or {}).get("analysis_index", {})
        if stage.get("status") in {"failed", "partial"}:
            for item in legacy_index_errors or [{"stage": "analysis_index", "code": "analysis_index_build_failed"}]:
                upsert_active_error(migrated, stage="analysis_index", code=item.get("code", "analysis_index_build_failed"), detail=item.get("detail"))
        else:
            migrated["error_history"].extend(legacy_index_errors)
        notes.append("migrated:analysis_index_error")
        migrated["errors"] = [item for item in migrated.get("errors", []) if item not in legacy_index_errors]
        migrated["limitations"] = [item for item in migrated.get("limitations", []) if item != "analysis_index_build_failed"]
    for name, stage in (migrated.get("processing") or {}).items():
        if isinstance(stage, dict) and stage.get("status") == "running":
            stage["status"] = "partial"
            stage.setdefault("warnings", []).append("interrupted_or_unfinished")
            upsert_active_error(migrated, stage=name, code="interrupted_or_unfinished")
        if isinstance(stage, dict) and stage.get("status") in {"failed", "partial"} and not any(item.get("stage") == name for item in migrated["active_errors"]):
            upsert_active_error(migrated, stage=name, code=f"{name}_failed")
    migrated["processing_status"] = compute_processing_status(migrated.get("processing") or {})
    unique_history, seen_history = [], set()
    for error in migrated["error_history"]:
        key = (error.get("stage"), error.get("code"), error.get("detail"), error.get("resolved_at"))
        if key not in seen_history: unique_history.append(error); seen_history.add(key)
    migrated["error_history"] = unique_history
    return migrated, notes


def canonical_content_payload(package: dict) -> dict:
    payload = deepcopy(package)
    payload.pop("runtime", None)
    payload.pop("processing_status", None)
    payload["processing"] = dict(payload.get("processing") or {})
    payload["processing"].pop("analysis_index", None)
    payload["active_errors"] = [item for item in payload.get("active_errors", []) if item.get("stage") != "analysis_index"]
    payload["error_history"] = [item for item in payload.get("error_history", []) if item.get("stage") != "analysis_index"]
    return payload


def content_payload_sha256(package: dict) -> str:
    encoded = json.dumps(canonical_content_payload(package), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


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
            "capture_status": status, "processing_status": "not_run", "active_errors": [], "error_history": [],
            "identity": {"platform": "xiaohongshu", "note_id": None, "author_id": None, "package_id": None, "snapshot_id": None, "snapshot_at": now, "content_fingerprint": None, "primary_media_sha256": None},
            "source": {"input_url": input_url, "resolved_url": None, "canonical_url": None,
                       "note_id": None, "provider": "public_html", "captured_at": now},
            "post": {"title": None, "description": None, "tags": [], "type": None, "published_at": None,
                     "author": {"id": None, "nickname": None},
                     "metrics": {"likes": None, "favorites": None, "comments": None, "shares": None}},
            "media": {"video": None, "cover": None, "images": []}, "derived": {"keyframes": [], "selected_keyframes": [], "scene_change_keyframes": [], "scenes": [], "evidence_segments": [], "interpretations": [], "transcript": None, "ocr": {"cover": None, "images": [], "keyframes": []}, "timeline": None}, "field_provenance": {},
            "processing": {}, "errors": [], "limitations": [], "completeness": {}, "runtime": runtime_metadata()}


def atomic_write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as target:
        json.dump(value, target, ensure_ascii=False, indent=2)
        target.write("\n")
        temporary = Path(target.name)
    temporary.replace(path)


def atomic_write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as target:
        target.write(value)
        temporary = Path(target.name)
    temporary.replace(path)


def safe_artifact_path(run_dir: Path, relative: str) -> Path:
    """Resolve a package path without permitting absolute, parent, or symlink escapes."""
    if not isinstance(relative, str) or not relative:
        raise ValueError("unsafe_relative_path")
    candidate = Path(relative)
    if candidate.is_absolute() or ".." in candidate.parts:
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
        issues = []
    return issues + _path_issues(package)


def validate_content_package(package: dict) -> list[str]:
    required = ("schema", "schema_version", "status", "capture_status", "processing_status", "active_errors", "error_history", "identity", "source", "post", "media", "derived", "field_provenance", "processing", "errors", "limitations", "completeness", "runtime")
    errors = [f"missing:{name}" for name in required if name not in package]
    if package.get("status") not in {"completed", "partial", "failed"}:
        errors.append("invalid:status")
    if package.get("capture_status") not in {"completed", "partial", "failed"}:
        errors.append("invalid:capture_status")
    if package.get("processing_status") not in {"not_run", "completed", "partial", "failed"}:
        errors.append("invalid:processing_status")
    if not isinstance(package.get("active_errors"), list):
        errors.append("invalid:active_errors")
    if not isinstance(package.get("error_history"), list):
        errors.append("invalid:error_history")
    if package.get("status") != package.get("capture_status"):
        errors.append("inconsistent:status_capture_status")
    if package.get("processing_status") != compute_processing_status(package.get("processing") or {}):
        errors.append("inconsistent:processing_status")
    seen = set()
    for error in package.get("active_errors") or []:
        identity = (error.get("stage"), error.get("code"))
        if identity in seen: errors.append("duplicate:active_error")
        seen.add(identity)
    for name, stage in (package.get("processing") or {}).items():
        if isinstance(stage, dict) and stage.get("status") == "failed" and not any(error.get("stage") == name for error in package.get("active_errors") or []):
            errors.append(f"missing:active_error.{name}")
    for key, value in (package.get("completeness") or {}).items():
        if not isinstance(value, dict) or value.get("status") not in COMPLETENESS_STATUSES:
            errors.append(f"invalid:completeness.{key}")
    if not isinstance(package.get("media"), dict):
        errors.append("invalid:media")
    return errors + validate_content_package_schema(package)


def build_text_change_events(frames: list[dict]) -> list[dict]:
    events, previous, previous_frame = [], "", None
    for frame in frames:
        current = ((frame.get("ocr") or {}).get("filtered_text") or (frame.get("ocr") or {}).get("text") or "").strip()
        if current == previous:
            previous_frame = frame
            continue
        change = "appeared" if current and not previous else "disappeared" if previous and not current else "changed"
        events.append({"id": f"text-change-{len(events) + 1:03}", "kind": "fact", "type": "text_change",
                       "change": change, "at": frame.get("time_seconds", 0), "frame_ref": frame.get("id"),
                       "previous_frame_ref": previous_frame.get("id") if previous_frame else None,
                       "previous_text": previous, "text": current})
        previous, previous_frame = current, frame
    return events


def build_timeline(transcript: list[dict], frames: list[dict], scenes: list[dict] | None = None, duration_seconds: float | None = None, text_events: list[dict] | None = None) -> dict:
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
    for scene in scenes or []: events.append({"id": scene["id"], "type": "scene_boundary", "start": scene["start_seconds"], "end": scene["end_seconds"]})
    for event in text_events or []: events.append({"id": event["id"], "type": "text_change", "at": event["at"], "frame_ref": event.get("frame_ref"), "change": event["change"], "text": event["text"]})
    events.sort(key=lambda item: (item.get("at", item.get("start", 0)), item["id"]))
    return {"schema": {"name": "iwig-timeline", "version": "1.1.0"}, "duration_seconds": duration_seconds, "events": events, "relations": relations}


def find_existing_package(output_dir: Path, note_id: str | None) -> Path | None:
    if not note_id or not output_dir.is_dir():
        return None
    candidates = []
    for manifest in output_dir.glob("*/content_package.json"):
        try:
            package, _ = migrate_content_package_in_memory(json.loads(manifest.read_text(encoding="utf-8")))
            if package.get("source", {}).get("note_id") == note_id and package.get("capture_status") == "completed" and not package.get("stale") and not validate_content_package(package):
                media = package.get("media", {}); records = [item for item in [media.get("video"), media.get("cover")] if item] + media.get("images", [])
                primary = bool(media.get("video") or media.get("images"))
                if primary and all(safe_artifact_path(manifest.parent, record["path"]).is_file() and file_record(safe_artifact_path(manifest.parent, record["path"]), manifest.parent)["sha256"] == record.get("sha256") for record in records): candidates.append((package["source"].get("captured_at") or "", manifest.parent))
        except (OSError, json.JSONDecodeError, ValueError, KeyError, TypeError):
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
    optional = {"frame_rate": None, "video_bitrate": None, "audio_codec": None, "audio_bitrate": None, "sample_rate": None, "channels": None}
    try:
        import av
        with av.open(str(path)) as container:
            stream = next((item for item in container.streams if item.type == "video"), None)
            if stream is None:
                return {"status": "not_exposed", **optional}
            duration = float(stream.duration * stream.time_base) if stream.duration is not None else None
            audio = next((item for item in container.streams if item.type == "audio"), None)
            return {"status": "available", "duration_seconds": duration, "width": stream.width, "height": stream.height, "codec": stream.codec_context.name, "container": container.format.name, "frame_rate": float(stream.average_rate) if stream.average_rate else None, "video_bitrate": stream.bit_rate, "audio_codec": audio.codec_context.name if audio else None, "audio_bitrate": audio.bit_rate if audio else None, "sample_rate": audio.rate if audio else None, "channels": audio.codec_context.channels if audio else None}
    except Exception as error:
        return {"status": "failed", "reason": type(error).__name__, **optional}


def adaptive_keyframe_interval(duration_seconds: float | None, default_interval: int = 30, max_frames: int = 12, minimum_interval: int = 3) -> float:
    """Use denser coverage for short clips while bounding all local work."""
    if not duration_seconds or duration_seconds <= 0:
        return float(default_interval)
    return round(min(float(default_interval), max(float(minimum_interval), duration_seconds / max(max_frames - 1, 1))), 1)


def scan_video_frames(path: Path, cadence_seconds: float = 1.0, max_samples: int = 180) -> dict:
    """Read bounded, low-cost visual signatures without retaining scan images."""
    try:
        import av
        from PIL import Image
        samples, next_second = [], 0.0
        with av.open(str(path)) as container:
            stream = next(item for item in container.streams if item.type == "video")
            for frame in container.decode(stream):
                at = float(frame.time or 0)
                if at < next_second:
                    continue
                image = frame.to_image().convert("L").resize((9, 8))
                pixels = image.load()
                bits = "".join("1" if pixels[x, y] > pixels[x + 1, y] else "0" for y in range(8) for x in range(8))
                samples.append({"id": f"scan-{len(samples) + 1:03}", "time_seconds": at, "perceptual_hash": f"{int(bits, 2):016x}"})
                next_second = at + cadence_seconds
                if len(samples) >= max_samples:
                    break
        scene_boundaries(samples)
        return {"status": "available", "frames": samples}
    except Exception as error:
        return {"status": "failed", "reason": type(error).__name__, "frames": []}


def select_representative_frames(scan: list[dict], duration_seconds: float | None, limit: int = 12) -> list[dict]:
    """Select bounded evidence from scan metadata, never from semantic labels."""
    if not scan or limit <= 0:
        return []
    if any("adjacent_similarity" not in frame for frame in scan):
        scene_boundaries(scan)
    duration = max(duration_seconds or scan[-1].get("time_seconds", 0), 1)
    candidates = []
    for index, frame in enumerate(scan):
        bases = []
        if index == 0: bases.append("start")
        if index == len(scan) - 1: bases.append("end")
        if frame.get("adjacent_similarity") is not None and frame["adjacent_similarity"] < .72: bases.append("scene_boundary")
        if bases:
            candidates.append({"scan_ref": frame["id"], "time_seconds": frame["time_seconds"], "selection_bases": bases,
                               "selection_score": len(bases) + (2 if "scene_boundary" in bases else 0)})
    if not candidates:
        candidates.append({"scan_ref": scan[0]["id"], "time_seconds": scan[0]["time_seconds"], "selection_bases": ["start"], "selection_score": 1})
    candidates.sort(key=lambda item: (-item["selection_score"], item["time_seconds"]))
    selected = candidates[:limit]
    return sorted(selected, key=lambda item: item["time_seconds"])


def extract_keyframes(path: Path, destination: Path, interval_seconds: int = 30, max_frames: int = 12) -> dict:
    try:
        import av
        destination.mkdir(parents=True, exist_ok=True)
        saved, next_second = [], 0.0
        with av.open(str(path)) as container:
            stream = next(item for item in container.streams if item.type == "video")
            duration = float(stream.duration * stream.time_base) if stream.duration is not None else None
            interval_seconds = adaptive_keyframe_interval(duration, interval_seconds, max_frames)
            for frame in container.decode(stream):
                seconds = float(frame.time or 0)
                if seconds < next_second:
                    continue
                target = destination / f"{len(saved) + 1:03}.jpg"
                with av.open(str(target), "w") as output:
                    jpeg = output.add_stream("mjpeg", rate=1)
                    jpeg.width, jpeg.height, jpeg.pix_fmt = frame.width, frame.height, "yuvj420p"
                    for packet in jpeg.encode(frame):
                        output.mux(packet)
                    for packet in jpeg.encode(None):
                        output.mux(packet)
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


def filtered_ocr_text(record: dict, minimum_confidence: float = .80) -> str:
    """Return a reproducible confidence-filtered view while retaining raw OCR."""
    return "\n".join(
        str(line.get("text", "")).strip()
        for line in record.get("lines") or []
        if str(line.get("text", "")).strip()
        and float(line.get("confidence", 0.0) or 0.0) >= minimum_confidence
    )


def select_scene_change_frames(frames: list[dict], threshold: float = .72, limit: int = 6) -> list[dict]:
    candidates = [
        frame for frame in frames
        if frame.get("adjacent_similarity") is not None and frame["adjacent_similarity"] < threshold
    ]
    candidates.sort(key=lambda frame: (frame["adjacent_similarity"], frame.get("time_seconds", 0)))
    return [{
        "frame_ref": frame["id"], "time_seconds": frame["time_seconds"],
        "adjacent_similarity": frame["adjacent_similarity"],
        "selection_basis": "adjacent_perceptual_hash", "threshold": threshold,
    } for frame in candidates[:limit]]


def build_evidence_segments(transcript: list[dict], frames: list[dict], scene_candidates: list[dict], ocr: dict, text_events: list[dict] | None = None) -> list[dict]:
    """Link local factual artifacts by time; it deliberately makes no semantic claim."""
    frame_ids_by_path = {frame.get("path"): frame.get("id") for frame in frames}
    frame_ocr_refs = {
        frame_ids_by_path.get(record.get("path")): f"ocr-{frame_ids_by_path[record.get('path')]}"
        for record in ocr.get("keyframes", []) or []
        if frame_ids_by_path.get(record.get("path"))
    }
    records = []
    for number, speech in enumerate(transcript, 1):
        start = speech.get("start", 0)
        end = speech.get("end", start)
        frame_refs = [frame["id"] for frame in frames if start <= frame.get("time_seconds", -1) <= end]
        records.append({
            "id": f"evidence-{number:03}", "kind": "fact", "start": start, "end": end,
            "transcript_refs": [f"speech-{number:03}"], "transcript_text": speech.get("text", ""),
            "frame_refs": frame_refs,
            "ocr_refs": [frame_ocr_refs[frame_id] for frame_id in frame_refs if frame_id in frame_ocr_refs],
            "scene_candidate_refs": [candidate["frame_ref"] for candidate in scene_candidates if start <= candidate.get("time_seconds", -1) <= end],
        })
    if not records:
        anchors = sorted(scene_candidates + (text_events or []), key=lambda item: item.get("time_seconds", item.get("at", 0)))
        for number, anchor in enumerate(anchors, 1):
            at = anchor.get("time_seconds", anchor.get("at", 0))
            records.append({"id": f"evidence-{number:03}", "kind": "fact", "start": at, "end": at,
                            "transcript_refs": [], "transcript_text": "", "frame_refs": [anchor.get("frame_ref")] if anchor.get("frame_ref") else [],
                            "ocr_refs": [], "scene_candidate_refs": [anchor.get("frame_ref")] if anchor.get("frame_ref") else [],
                            "text_change_refs": [anchor["id"]] if anchor.get("type") == "text_change" else []})
    return records


def rule_based_interpretations(segments: list[dict]) -> list[dict]:
    """Produce opt-in hypotheses; callers must keep them separate from facts."""
    rules = [
        ("hook", ("今天", "你知道", "别再")),
        ("problem", ("问题", "困扰", "难题")),
        ("case", ("案例", "我之前", "比如")),
        ("method", ("方法", "步骤", "第一步")),
        ("result", ("结果", "效果", "最后")),
        ("call_to_action", ("关注", "评论", "点赞")),
    ]
    output = []
    for segment in segments:
        text = segment.get("transcript_text", "")
        label = next((name for name, words in rules if any(word in text for word in words)), "unknown")
        output.append({
            "id": f"inference-{segment['id']}", "kind": "inference", "label": label,
            "confidence": .60 if label != "unknown" else .0,
            "evidence_refs": [segment["id"]], "method": "rule_based_v1",
        })
    return output


def build_image_page_evidence(images: list[dict], ocr_records: list[dict]) -> list[dict]:
    ocr_by_path = {item.get("path"): item for item in ocr_records}
    return [{"id": f"image-page-{index:03}", "kind": "fact", "page_number": index,
             "image_ref": image.get("path"), "ocr_ref": f"ocr-image-{index:03}" if image.get("path") in ocr_by_path else None,
             "ocr_text": (ocr_by_path.get(image.get("path")) or {}).get("filtered_text", ""),
             "width": image.get("width"), "height": image.get("height"), "format": image.get("format"),
             "text_density": round(len((ocr_by_path.get(image.get("path")) or {}).get("filtered_text", "")) / max((image.get("width") or 1) * (image.get("height") or 1), 1) * 1_000_000, 4)}
            for index, image in enumerate(images, 1)]


def build_visual_candidates(frames: list[dict], duration_seconds: float | None) -> list[dict]:
    duration = max(duration_seconds or 1, 1)
    output = []
    previous = ""
    for frame in frames:
        bases, at = [], frame.get("time_seconds", 0)
        if at / duration <= .08: bases.append("start")
        if at / duration >= .90: bases.append("end")
        if frame.get("adjacent_similarity") is not None and frame["adjacent_similarity"] < .72: bases.append("scene_change")
        text = (frame.get("ocr") or {}).get("filtered_text") or (frame.get("ocr") or {}).get("text", "")
        if text and text != previous: bases.append("subtitle_change")
        if bases: output.append({"id": f"candidate-{frame['id']}", "kind": "fact", "frame_ref": frame["id"], "time_seconds": at, "selection_bases": bases, "ocr_text": text, "selection_score": len(bases)})
        previous = text
    return output


def describe_visual_records(records: list[dict]) -> list[dict]:
    output = []
    for record in records:
        text = (record.get("ocr_text") or record.get("text") or "").lower()
        label = "text_card" if len(text) >= 12 else ("subtitle_overlay" if text else "unknown")
        output.append({"id": f"visual-{record['id']}", "kind": "inference", "label": label,
                       "confidence": .60 if label != "unknown" else .0, "method": "ocr_density_v1",
                       "evidence_refs": [record["id"]]})
    return output


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
