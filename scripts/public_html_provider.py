"""Public-HTML-only XHS post, video, and cover capture helpers."""
from __future__ import annotations

import hashlib
import ipaddress
import json
import re
import socket
from contextlib import contextmanager
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse
from content_package import file_record, image_metadata, new_content_package, video_metadata


class PublicCaptureError(RuntimeError):
    """A public page cannot be captured within the supported boundaries."""


def request_error(error: Exception) -> PublicCaptureError:
    """Convert transport failures into the documented public-page outcome."""
    return PublicCaptureError("public_page_request_failed")


PUBLIC_HOSTS = {"xhslink.cn", "xhslink.com", "xiaohongshu.com", "www.xiaohongshu.com"}
SHORT_LINK_HOSTS = {"xhslink.cn", "xhslink.com"}
SHORT_LINK_ATTEMPTS = 3
NOTE_PATTERNS = (
    re.compile(r"^/explore/([^/?#]+)"),
    re.compile(r"^/discovery/item/([^/?#]+)"),
    re.compile(r"^/user/profile/[^/]+/([^/?#]+)"),
)
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"


def _validate_url(url: str, public_xhs_only: bool = False) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise PublicCaptureError("invalid_url")
    host = parsed.hostname.lower().rstrip(".")
    if host == "localhost" or host.endswith((".localhost", ".local", ".internal")):
        raise PublicCaptureError("invalid_url")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address and (address.is_loopback or address.is_private or address.is_link_local or address.is_reserved):
        raise PublicCaptureError("invalid_url")
    if address is None:
        try:
            resolved = {ipaddress.ip_address(item[4][0]) for item in socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)}
        except OSError as error:
            raise PublicCaptureError("invalid_url") from error
        if not resolved or any(item.is_loopback or item.is_private or item.is_link_local or item.is_reserved for item in resolved):
            raise PublicCaptureError("invalid_url")
    if public_xhs_only and host not in PUBLIC_HOSTS:
        raise PublicCaptureError("invalid_url")


REDIRECT_CODES = {301, 302, 303, 307, 308}
SENSITIVE_QUERY_NAMES = {"xsec_token", "share_id", "shareredid", "author_share", "token", "signature"}


def redact_url(url: str) -> str:
    """Keep stable link identity while omitting share and token material."""
    parsed = urlparse(url)
    query = [(key, value) for key, value in parse_qsl(parsed.query, keep_blank_values=True)
             if key.lower() not in SENSITIVE_QUERY_NAMES and "token" not in key.lower()]
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", urlencode(query), ""))


def _redirect_target(current: str, response) -> str | None:
    if response.status_code not in REDIRECT_CODES:
        return None
    location = response.headers.get("location")
    if not location or not location.strip():
        raise PublicCaptureError("redirect_location_missing")
    return urljoin(current, location)


def _request_with_validated_redirects(client, url: str, *, headers: dict | None = None,
                                      public_xhs_only: bool = False, stream: bool = False,
                                      max_redirects: int = 5, timeout=None):
    """Request a URL only after validating every location in its redirect chain.

    When ``stream`` is true this returns a context manager for the final response.
    Redirect responses are always closed before the next hop is requested.
    """
    if stream:
        return _stream_with_validated_redirects(client, url, headers=headers, public_xhs_only=public_xhs_only, max_redirects=max_redirects, timeout=timeout)
    current = url
    for hop in range(max_redirects + 1):
        _validate_url(current, public_xhs_only=public_xhs_only)
        response = client.get(current, headers=headers, follow_redirects=False, timeout=timeout)
        target = _redirect_target(current, response)
        if target is None:
            return response
        current = target
    raise PublicCaptureError("redirect_limit_exceeded")


@contextmanager
def _stream_with_validated_redirects(client, url: str, *, headers: dict | None,
                                     public_xhs_only: bool, max_redirects: int, timeout=None):
    current = url
    for _ in range(max_redirects + 1):
        _validate_url(current, public_xhs_only=public_xhs_only)
        with client.stream("GET", current, headers=headers, follow_redirects=False, timeout=timeout) as response:
            target = _redirect_target(current, response)
            if target is None:
                yield response
                return
        current = target
    raise PublicCaptureError("redirect_limit_exceeded")


def _get_public_page(client, url: str, max_redirects: int = 5):
    host = (urlparse(url).hostname or "").lower().rstrip(".")
    attempts = SHORT_LINK_ATTEMPTS if host in SHORT_LINK_HOSTS else 1
    for attempt in range(attempts):
        response = _request_with_validated_redirects(
            client, url, public_xhs_only=True, max_redirects=max_redirects,
        )
        if response.status_code != 404 or attempt == attempts - 1:
            return response
        response.close()


def _note_id(url: str) -> str | None:
    path = urlparse(url).path
    for pattern in NOTE_PATTERNS:
        match = pattern.match(path)
        if match:
            return match.group(1)
    return None


def note_id_from_url(url: str) -> str | None:
    """Return a direct note ID without requesting the page."""
    return _note_id(url)


class _Scripts(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.in_script = False
        self.items: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        self.in_script = tag.lower() == "script"

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "script":
            self.in_script = False

    def handle_data(self, data: str) -> None:
        if self.in_script:
            self.items.append(data)


def _object_text(source: str, start: int) -> str:
    depth, quote, escaped = 0, None, False
    for index in range(start, len(source)):
        char = source[index]
        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            continue
        if char in {"'", '"'}:
            quote = char
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return source[start:index + 1]
    raise PublicCaptureError("initial_state_parse_failed")


def _undefined_to_null(source: str) -> str:
    output, index, quote, escaped = [], 0, None, False
    while index < len(source):
        char = source[index]
        if quote:
            output.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            index += 1
            continue
        if char in {"'", '"'}:
            quote = char
        if source.startswith("undefined", index):
            before = source[index - 1] if index else ""
            end = index + 9
            after = source[end] if end < len(source) else ""
            if not (before.isalnum() or before in "_$") and not (after.isalnum() or after in "_$"):
                output.append("null")
                index = end
                continue
        output.append(char)
        index += 1
    return "".join(output)


def _initial_state(html: str) -> dict:
    parser = _Scripts()
    parser.feed(html)
    marker = "window.__INITIAL_STATE__"
    for script in parser.items:
        marker_index = script.find(marker)
        if marker_index < 0:
            continue
        equals = script.find("=", marker_index + len(marker))
        brace = script.find("{", equals + 1)
        if equals >= 0 and brace >= 0:
            try:
                value = json.loads(_undefined_to_null(_object_text(script, brace)))
            except json.JSONDecodeError as error:
                raise PublicCaptureError("initial_state_parse_failed") from error
            if isinstance(value, dict):
                return value
    raise PublicCaptureError("initial_state_not_found")


def _walk(value, path=()):
    if isinstance(value, dict):
        yield path, value
        for key, child in value.items():
            yield from _walk(child, path + (str(key),))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _walk(child, path + (str(index),))


def _first(mapping: dict, *names: str):
    for name in names:
        if mapping.get(name) is not None:
            return mapping[name]
    return None


def _current_note(state: dict, note_id: str | None) -> tuple[dict, str]:
    candidates = []
    preferred = []
    for path, item in _walk(state):
        identifier = _first(item, "noteId", "note_id")
        if identifier is not None and any(key in item for key in ("title", "desc", "user", "video", "imageList", "image_list")):
            candidate = (item, ".".join(path))
            candidates.append(candidate)
            if any(part.lower() in {"notedetailmap", "notedetail", "currentnote", "note"} for part in path):
                preferred.append(candidate)
    matches = [item for item in candidates if str(_first(item[0], "noteId", "note_id")) == str(note_id)]
    preferred_matches = [item for item in preferred if item in matches]
    chosen = preferred_matches or matches
    unique = {}
    for item, path in chosen:
        unique.setdefault(json.dumps(item, ensure_ascii=False, sort_keys=True, default=str), (item, path))
    if len(unique) == 1:
        return next(iter(unique.values()))
    raise PublicCaptureError("note_object_not_found" if not candidates else "ambiguous_note_data")


def _number(value):
    try:
        return int(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _iso_time(value):
    timestamp = _number(value)
    if timestamp is None:
        return None
    if timestamp > 10_000_000_000:
        timestamp //= 1000
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat()


def _normalize(note: dict, source: dict, selected_note_path: str) -> dict:
    user = note.get("user") or {}
    interact = _first(note, "interactInfo", "interact_info") or {}
    tags = []
    for item in _first(note, "tagList", "tag_list") or []:
        name = item.get("name") if isinstance(item, dict) else item
        if isinstance(name, str) and name.strip() and name.strip() not in tags:
            tags.append(name.strip())
    provenance = {"post.title": "title", "post.description": "desc", "post.tags": "tagList", "post.author.id": "user.userId", "post.author.nickname": "user.nickname", "post.metrics.likes": "interactInfo.likedCount", "post.metrics.favorites": "interactInfo.collectedCount", "post.metrics.comments": "interactInfo.commentCount"}
    result = new_content_package("partial", source["input_url"])
    result.update({"source": source, "post": {"title": note.get("title"), "description": _first(note, "desc", "description"), "tags": tags, "type": _first(note, "type", "noteType", "note_type"), "published_at": _iso_time(_first(note, "time", "createTime", "create_time")), "author": {"id": _first(user, "userId", "user_id", "id"), "nickname": _first(user, "nickname", "nickName")}, "metrics": {"likes": _number(_first(interact, "likedCount", "liked_count")), "favorites": _number(_first(interact, "collectedCount", "collected_count")), "comments": _number(_first(interact, "commentCount", "comment_count")), "shares": _number(_first(interact, "shareCount", "share_count"))}}, "field_provenance": {key: {"source": "initial_state", "source_path": f"{selected_note_path}.{value}".lstrip("."), "source_artifact": "source/selected_note.json", "captured_at": source["captured_at"]} for key, value in provenance.items()}, "limitations": ["Comments are intentionally not collected by the public HTML provider."]})
    return result


def cover_candidates(note: dict) -> list[dict]:
    """Return direct cover URLs already exposed by the selected note object."""
    candidates: list[tuple[int, dict]] = []
    seen: set[str] = set()
    for image_index, image in enumerate(note.get("imageList") or note.get("image_list") or []):
        if not isinstance(image, dict):
            continue
        for info_index, info in enumerate(image.get("infoList") or info.get("info_list") or []):
            if not isinstance(info, dict):
                continue
            for key in ("url", "urlDefault", "url_default"):
                url = info.get(key)
                if isinstance(url, str) and url.startswith(("http://", "https://")) and url not in seen:
                    quality = 0 if "dft" in url.lower() or str(info.get("imageScene", "")).upper() == "WB_DFT" else 1
                    candidates.append((quality, {"url": url, "source_path": f"imageList.{image_index}.infoList.{info_index}.{key}"}))
                    seen.add(url)
                    break
    return [candidate for _, candidate in sorted(candidates, key=lambda item: item[0])]


def image_candidates(note: dict) -> list[dict]:
    """Choose one directly exposed, best-quality URL for each page image."""
    selected = []
    for image_index, image in enumerate(note.get("imageList") or note.get("image_list") or []):
        if not isinstance(image, dict):
            continue
        options = []
        for info_index, info in enumerate(image.get("infoList") or info.get("info_list") or []):
            if not isinstance(info, dict):
                continue
            for key in ("url", "urlDefault", "url_default"):
                url = info.get(key)
                if isinstance(url, str) and url.startswith(("http://", "https://")):
                    quality = 0 if "dft" in url.lower() or str(info.get("imageScene", "")).upper() == "WB_DFT" else 1
                    options.append((quality, info_index, key, url))
                    break
        if options:
            _, info_index, key, url = min(options)
            selected.append({"url": url, "source_path": f"imageList.{image_index}.infoList.{info_index}.{key}", "index": image_index + 1})
    return selected


def _video_candidates(note: dict) -> list[dict]:
    found, unique = [], set()
    for path, item in _walk(note):
        for key in ("masterUrl", "master_url"):
            url = item.get(key)
            if isinstance(url, str) and url.startswith(("http://", "https://")) and url not in unique:
                found.append({"url": url, "source_path": ".".join(path + (key,)), "width": _number(item.get("width")), "height": _number(item.get("height")), "bitrate": _number(item.get("bitrate")), "is_origin_candidate": False})
                unique.add(url)
        for key in ("backupUrls", "backup_urls"):
            for index, url in enumerate(item.get(key) or []):
                if isinstance(url, str) and url.startswith(("http://", "https://")) and url not in unique:
                    found.append({"url": url, "source_path": ".".join(path + (key, str(index))), "width": _number(item.get("width")), "height": _number(item.get("height")), "bitrate": _number(item.get("bitrate")), "is_origin_candidate": False})
                    unique.add(url)
    return found


def _select_video(candidates: list[dict]) -> dict | None:
    return max(candidates, key=lambda item: (item["is_origin_candidate"], (item["width"] or 0) * (item["height"] or 0), item["bitrate"] or 0), default=None)


def select_video_candidates(candidates: list[dict]) -> list[dict]:
    """Prefer the best stream first, while retaining every public fallback."""
    return sorted(candidates, key=lambda item: (
        item["is_origin_candidate"],
        (item["width"] or 0) * (item["height"] or 0),
        item["bitrate"] or 0,
    ), reverse=True)


def public_candidate(candidate: dict) -> dict:
    """Keep candidate provenance without persisting expiring signed URLs."""
    url = candidate.get("url", "")
    parsed = urlparse(url)
    return {key: value for key, value in candidate.items() if key != "url"} | {"host": parsed.hostname, "url_sha256": "sha256:" + hashlib.sha256(url.encode("utf-8")).hexdigest()}


def _redact_urls(value):
    if isinstance(value, str) and value.startswith(("http://", "https://")):
        return public_candidate({"url": value})
    if isinstance(value, dict):
        return {key: _redact_urls(child) for key, child in value.items()}
    if isinstance(value, list): return [_redact_urls(item) for item in value]
    return value


def _extension(content_type: str, fallback: str) -> str:
    lowered = content_type.lower().split(";", 1)[0]
    return {"image/webp": ".webp", "image/jpeg": ".jpg", "image/png": ".png", "video/mp4": ".mp4"}.get(lowered, fallback)


def _stream_download(client, url: str, destination: Path, max_bytes: int, referer: str, expected: str) -> Path:
    import httpx
    part = destination.with_suffix(destination.suffix + ".part")
    headers = {"User-Agent": USER_AGENT, "Referer": referer}
    media_timeout = httpx.Timeout(connect=None, read=None, write=None, pool=None)
    try:
        _validate_url(url)
        with client.stream("GET", url, headers=headers, follow_redirects=True, timeout=media_timeout) as response:
            if response.status_code != 200:
                raise PublicCaptureError(f"{expected}_download_failed")
            content_type = response.headers.get("content-type", "").lower()
            if not content_type.startswith(expected + "/"):
                raise PublicCaptureError(f"{expected}_download_failed")
            final_path = destination.with_suffix(_extension(content_type, destination.suffix))
            written = 0
            with part.open("wb") as target:
                for chunk in response.iter_bytes():
                    written += len(chunk)
                    if written > max_bytes:
                        raise PublicCaptureError(f"{expected}_download_failed")
                    target.write(chunk)
        if written == 0:
            raise PublicCaptureError(f"{expected}_download_failed")
        if expected == "video":
            with part.open("rb") as source:
                if b"ftyp" not in source.read(32):
                    raise PublicCaptureError("video_validation_failed")
        part.replace(final_path)
        return final_path
    except PublicCaptureError:
        part.unlink(missing_ok=True)
        raise
    except Exception as error:
        part.unlink(missing_ok=True)
        raise PublicCaptureError(f"{expected}_download_failed") from error


def capture_public_note(url: str, output_dir: Path, timeout: float = 20.0,
                        max_video_bytes: int = 300 * 1024 * 1024,
                        keep_raw_source: bool = False) -> dict:
    """Capture one public note without a browser, cookies, or private APIs."""
    _validate_url(url, public_xhs_only=True)
    import httpx

    output_dir.mkdir(parents=True, exist_ok=True)
    with httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=httpx.Timeout(timeout, connect=min(timeout, 10)), follow_redirects=False, verify=True, cookies=None) as client:
        try:
            response = _get_public_page(client, url)
        except Exception as error:
            raise request_error(error) from error
        if response.status_code in {401, 403, 406, 429}:
            raise PublicCaptureError("public_page_not_accessible")
        if response.status_code != 200:
            raise PublicCaptureError("public_page_request_failed")
        html = response.text
        if any(token in html for token in ("扫码登录", "验证码", "安全验证")):
            raise PublicCaptureError("login_or_verification_required")
        source_dir, media_dir = output_dir / "source", output_dir / "media"
        source_dir.mkdir(exist_ok=True)
        media_dir.mkdir(exist_ok=True)
        state = _initial_state(html)
        resolved_url = str(response.url)
        source = {"input_url": redact_url(url), "resolved_url": redact_url(resolved_url), "canonical_url": redact_url(resolved_url), "note_id": _note_id(resolved_url), "provider": "public_html", "captured_at": datetime.now(timezone.utc).isoformat()}
        note, selected_note_path = _current_note(state, source["note_id"])
        (source_dir / "selected_note.json").write_text(json.dumps(_redact_urls(note), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (source_dir / "request.json").write_text(json.dumps({"input_url": source["input_url"], "resolved_url": source["resolved_url"], "captured_at": source["captured_at"], "provider": source["provider"]}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        if keep_raw_source:
            (source_dir / "page.html").write_text(html, encoding="utf-8")
            (source_dir / "initial_state.json").write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        result = _normalize(note, source, selected_note_path)
        videos = _video_candidates(note)
        covers = cover_candidates(note)
        images = image_candidates(note) if str(_first(note, "type", "noteType", "note_type") or "").lower() not in {"video", "video_note"} else []
        (source_dir / "media_candidates.json").write_text(json.dumps({"video": [public_candidate(item) for item in videos], "cover": [public_candidate(item) for item in covers], "images": [public_candidate(item) for item in images]}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        selected_videos = select_video_candidates(videos)
        for selected_video in selected_videos:
            try:
                video_path = _stream_download(client, selected_video["url"], media_dir / "video.mp4", max_video_bytes, source["resolved_url"], "video")
                result["media"]["video"] = {"candidate": public_candidate(selected_video), **file_record(video_path, output_dir), "metadata": video_metadata(video_path)}
                break
            except PublicCaptureError as error:
                result["errors"].append({"stage": "media_download", "code": str(error), "candidate_path": selected_video["source_path"]})
        if covers and not images:
            try:
                cover_path = _stream_download(client, covers[0]["url"], media_dir / "cover.jpg", 20 * 1024 * 1024, source["resolved_url"], "image")
                result["media"]["cover"] = {"candidate": public_candidate(covers[0]), **file_record(cover_path, output_dir), **image_metadata(cover_path)}
            except PublicCaptureError as error:
                result["errors"].append({"stage": "media_download", "code": str(error), "candidate_path": covers[0]["source_path"]})
        for image in images:
            try:
                images_dir = media_dir / "images"
                images_dir.mkdir(exist_ok=True)
                image_path = _stream_download(client, image["url"], images_dir / f"{image['index']:03}.jpg", 20 * 1024 * 1024, source["resolved_url"], "image")
                result["media"]["images"].append({"candidate": public_candidate(image), **file_record(image_path, output_dir), **image_metadata(image_path)})
            except PublicCaptureError as error:
                result["errors"].append({"stage": "media_download", "code": str(error), "candidate_path": image["source_path"]})
        if not result["media"]["cover"] and result["media"]["images"]:
            result["media"]["cover"] = result["media"]["images"][0]
        if not result["media"]["video"] and not result["media"]["images"]:
            result["errors"].append({"stage": "media_download", "code": "public_media_not_available"})
            result["limitations"].append("public_media_not_available")
            result["status"] = "partial"
            result["capture_status"] = "partial"
            return result
        result["status"] = "completed"
        result["capture_status"] = "completed"
        return result
