#!/usr/bin/env python3
"""Isolated public-HTML feasibility experiment for one XHS note URL."""
from __future__ import annotations

import argparse
import ipaddress
import hashlib
import json
import re
import shutil
import subprocess
import time
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import ParseResult, urlparse


class InvalidUrlError(ValueError):
    """Raised when a supplied URL is not a safe public XHS URL."""


class InitialStateNotFoundError(ValueError):
    """Raised when public HTML does not contain a usable initial state."""


SUPPORTED_HOSTS = {"xhslink.cn", "xhslink.com", "xiaohongshu.com", "www.xiaohongshu.com"}
NOTE_PATH_PATTERNS = (
    re.compile(r"^/explore/([^/?#]+)"),
    re.compile(r"^/discovery/item/([^/?#]+)"),
    re.compile(r"^/user/profile/[^/]+/([^/?#]+)"),
)


def validate_remote_url(url: str) -> ParseResult:
    """Reject non-HTTP and plainly internal endpoints."""
    parsed = urlparse(url.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise InvalidUrlError("only absolute http(s) URLs are accepted")
    hostname = parsed.hostname.lower().rstrip(".")
    if hostname == "localhost" or hostname.endswith((".local", ".internal", ".localhost")):
        raise InvalidUrlError("internal host names are not allowed")
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        address = None
    if address and (address.is_private or address.is_loopback or address.is_link_local or address.is_reserved):
        raise InvalidUrlError("private or local IP addresses are not allowed")
    return parsed


def validate_public_url(url: str) -> ParseResult:
    """Return a parsed public XHS URL or reject unsafe/non-XHS inputs."""
    parsed = validate_remote_url(url)
    if parsed.hostname.lower().rstrip(".") not in SUPPORTED_HOSTS:
        raise InvalidUrlError("host is not an allowed public Xiaohongshu host")
    return parsed


def resolve_note_id(url: str) -> str | None:
    """Extract a known note ID from a supported public detail URL."""
    parsed = validate_public_url(url)
    for pattern in NOTE_PATH_PATTERNS:
        match = pattern.match(parsed.path)
        if match:
            return match.group(1)
    return None


class _ScriptCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._in_script = False
        self.scripts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() == "script":
            self._in_script = True

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "script":
            self._in_script = False

    def handle_data(self, data: str) -> None:
        if self._in_script:
            self.scripts.append(data)


def _balanced_object(source: str, start: int) -> str:
    depth = 0
    quote: str | None = None
    escaped = False
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
                return source[start : index + 1]
    raise InitialStateNotFoundError("initial state object is not balanced")


def _replace_undefined_literals(source: str) -> str:
    """Replace the JavaScript value `undefined` only when it is not a string."""
    output: list[str] = []
    index = 0
    quote: str | None = None
    escaped = False
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
            after_index = index + len("undefined")
            after = source[after_index] if after_index < len(source) else ""
            if not (before.isalnum() or before in "_$") and not (after.isalnum() or after in "_$"):
                output.append("null")
                index = after_index
                continue
        output.append(char)
        index += 1
    return "".join(output)


def extract_initial_state(html: str) -> dict:
    """Parse a JSON initial-state assignment from HTML scripts without executing it."""
    collector = _ScriptCollector()
    collector.feed(html)
    marker = "window.__INITIAL_STATE__"
    for script in collector.scripts:
        marker_index = script.find(marker)
        if marker_index < 0:
            continue
        equals_index = script.find("=", marker_index + len(marker))
        if equals_index < 0:
            continue
        object_index = script.find("{", equals_index + 1)
        if object_index < 0:
            continue
        try:
            parsed = json.loads(_replace_undefined_literals(_balanced_object(script, object_index)))
        except json.JSONDecodeError as error:
            raise InitialStateNotFoundError("initial state is not standard JSON") from error
        if isinstance(parsed, dict):
            return parsed
    raise InitialStateNotFoundError("window.__INITIAL_STATE__ was not found")


def _walk_dicts(value: object, path: tuple[str, ...] = ()):
    if isinstance(value, dict):
        yield path, value
        for key, child in value.items():
            yield from _walk_dicts(child, path + (str(key),))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _walk_dicts(child, path + (str(index),))


def _value(mapping: dict, *names: str):
    for name in names:
        if mapping.get(name) is not None:
            return mapping[name]
    return None


def find_note_object(state: dict, note_id: str | None) -> dict:
    """Find the current detail-note object, preferring an exact note ID match."""
    candidates: list[dict] = []
    for _, item in _walk_dicts(state):
        identifier = _value(item, "noteId", "note_id")
        is_note_like = identifier is not None and any(
            key in item for key in ("title", "desc", "user", "interactInfo", "interact_info", "video", "imageList", "image_list")
        )
        if is_note_like:
            candidates.append(item)
    exact = [item for item in candidates if str(_value(item, "noteId", "note_id")) == str(note_id)]
    if len(exact) == 1:
        return exact[0]
    if note_id is None and len(candidates) == 1:
        return candidates[0]
    raise ValueError("note_object_not_found" if not candidates else "ambiguous_note_data")


def _integer(value: object) -> int | None:
    try:
        return int(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _iso_time(value: object) -> str | None:
    numeric = _integer(value)
    if numeric is None:
        return None
    if numeric > 10_000_000_000:
        numeric //= 1000
    try:
        return datetime.fromtimestamp(numeric, tz=timezone.utc).isoformat()
    except (OverflowError, OSError, ValueError):
        return None


def normalize_note(note: dict, source: dict) -> dict:
    """Normalize known public note fields without inventing unavailable values."""
    user = _value(note, "user") or {}
    interact = _value(note, "interactInfo", "interact_info") or {}
    raw_tags = _value(note, "tagList", "tag_list") or []
    tags = []
    for item in raw_tags:
        name = item.get("name") if isinstance(item, dict) else item
        if isinstance(name, str) and name.strip() and name.strip() not in tags:
            tags.append(name.strip())
    return {
        "schema_version": 1,
        "status": "partial",
        "source": {**source, "provider": "public_html"},
        "post": {
            "title": _value(note, "title"),
            "description": _value(note, "desc", "description"),
            "tags": tags,
            "type": _value(note, "type", "noteType", "note_type"),
            "published_at": _iso_time(_value(note, "time", "createTime", "create_time")),
            "updated_at": _iso_time(_value(note, "lastUpdateTime", "last_update_time", "updateTime")),
            "author": {
                "id": _value(user, "userId", "user_id", "id"),
                "nickname": _value(user, "nickname", "nickName"),
                "profile_url": None,
            },
            "metrics": {
                "likes": _integer(_value(interact, "likedCount", "liked_count")),
                "favorites": _integer(_value(interact, "collectedCount", "collected_count")),
                "comments": _integer(_value(interact, "commentCount", "comment_count")),
                "shares": _integer(_value(interact, "shareCount", "share_count")),
            },
        },
        "media": {"type": None, "candidates_found": 0, "selected_candidate": None, "download_status": "not_started", "path": None},
        "errors": [],
        "limitations": ["Interaction metrics are a public-page snapshot captured at run time."],
    }


def _candidate(url: object, source_path: str, parent: dict, origin: bool = False) -> dict | None:
    if not isinstance(url, str) or not url.startswith(("http://", "https://")):
        return None
    return {
        "url": url,
        "source_path": source_path,
        "width": _integer(_value(parent, "width")),
        "height": _integer(_value(parent, "height")),
        "bitrate": _integer(_value(parent, "bitrate")),
        "size_bytes": _integer(_value(parent, "size", "sizeBytes", "size_bytes")),
        "codec": _value(parent, "codec"),
        "is_origin_candidate": origin,
    }


def video_candidates(note: dict) -> list[dict]:
    """Collect explicit media URLs only from the selected current-note object."""
    found: list[dict] = []
    for path, item in _walk_dicts(note):
        for key in ("masterUrl", "master_url"):
            candidate = _candidate(item.get(key), ".".join(path + (key,)), item)
            if candidate:
                found.append(candidate)
        for key in ("backupUrls", "backup_urls"):
            values = item.get(key)
            if isinstance(values, list):
                for index, value in enumerate(values):
                    candidate = _candidate(value, ".".join(path + (key, str(index))), item)
                    if candidate:
                        found.append(candidate)
        if path[-2:] == ("video", "consumer") and "originVideoKey" in item:
            candidate = _candidate(item["originVideoKey"], ".".join(path + ("originVideoKey",)), item, origin=True)
            if candidate:
                found.append(candidate)
    unique: dict[str, dict] = {}
    for candidate in found:
        normalized_url = candidate["url"].split("#", 1)[0]
        existing = unique.get(normalized_url)
        if existing is None or (candidate["is_origin_candidate"] and not existing["is_origin_candidate"]):
            unique[normalized_url] = candidate
    return list(unique.values())


def select_candidate(candidates: list[dict]) -> dict | None:
    """Select one candidate with deterministic origin/resolution/bitrate priority."""
    if not candidates:
        return None
    return max(
        candidates,
        key=lambda item: (
            bool(item.get("is_origin_candidate")),
            (item.get("width") or 0) * (item.get("height") or 0),
            item.get("bitrate") or 0,
            item.get("size_bytes") or 0,
        ),
    )


def validate_media_file(path) -> dict:
    """Perform minimum media validation and enrich it with ffprobe when present."""
    from pathlib import Path

    media_path = Path(path)
    size = media_path.stat().st_size
    header = media_path.read_bytes()[:32]
    report = {
        "format_name": None,
        "duration_seconds": None,
        "size_bytes": size,
        "video_codec": None,
        "width": None,
        "height": None,
        "audio_codec": None,
        "basic_header_valid": size > 0 and (b"ftyp" in header or header.startswith(b"\x1aE\xdf\xa3")),
        "sha256": hashlib.sha256(media_path.read_bytes()).hexdigest(),
    }
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        report["ffprobe_not_available"] = True
        return report
    try:
        output = subprocess.check_output(
            [ffprobe, "-v", "error", "-show_entries", "format=format_name,duration,size:stream=codec_type,codec_name,width,height", "-of", "json", str(media_path)],
            text=True,
            stderr=subprocess.STDOUT,
        )
        info = json.loads(output)
        fmt = info.get("format", {})
        report["format_name"] = fmt.get("format_name")
        report["duration_seconds"] = float(fmt["duration"]) if fmt.get("duration") else None
        for stream in info.get("streams", []):
            if stream.get("codec_type") == "video":
                report.update({"video_codec": stream.get("codec_name"), "width": stream.get("width"), "height": stream.get("height")})
            if stream.get("codec_type") == "audio":
                report["audio_codec"] = stream.get("codec_name")
    except (subprocess.CalledProcessError, json.JSONDecodeError, OSError, ValueError):
        report["ffprobe_failed"] = True
    return report


FIXED_USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _empty_capture(source: dict) -> dict:
    return {
        "schema_version": 1, "status": "failed", "source": {**source, "provider": "public_html"},
        "post": {"title": None, "description": None, "tags": [], "type": None, "published_at": None, "updated_at": None, "author": {"id": None, "nickname": None, "profile_url": None}, "metrics": {"likes": None, "favorites": None, "comments": None, "shares": None}},
        "media": {"type": None, "candidates_found": 0, "selected_candidate": None, "download_status": "not_started", "path": None},
        "errors": [], "limitations": ["No cookies, browser automation, JavaScript execution, signatures, or private APIs were used."],
    }


def _report(capture: dict, stages: dict, facts: dict) -> str:
    outcome = "技术路线可行" if capture["status"] == "completed" else "技术路线部分可行" if capture["status"] == "partial" else "技术路线不可行"
    label = {"completed": "成功", "partial": "部分成功"}
    lines = ["# 公开 HTML 采集 MVP 验证报告", "", "## 实验结果", "", outcome, "", "## 阶段结果", "", "| 阶段 | 结果 |", "| --- | --- |"]
    lines += [f"| {name} | {label.get(state, '失败')} |" for name, state in stages.items()]
    lines += ["", "## 关键事实", ""] + [f"- {key}: {value if value is not None else '未获取'}" for key, value in facts.items()]
    lines += ["", "## 与现有 CDP 路线对比", "", "| 项目 | 本实验 Public HTML | 现有 CDP 路线 |", "| --- | --- | --- |", "| 是否需要登录 | 否；要求登录即停止 | 是 |", "| 是否自动操作页面 | 否 | 是 |", "| 是否能获取帖子信息 | 仅限公开 HTML | 已渲染页面 |", "| 是否能下载视频 | 仅限公开候选直链 | 页面媒体请求 |", "| 稳定性 | 受公开页面与访问策略影响 | 受登录态与页面结构影响 |", "| 失败是否可诊断 | 阶段状态和结构化产物 | 页面流程日志 |", "", "## 是否建议进入正式 Skill", "", "建议进入下一阶段" if capture["status"] == "completed" else "暂不建议", "", "## 下一步最小动作", "", "将该实验封装成正式 PublicHtmlProvider" if capture["status"] == "completed" else "保留现有 Skill，不采用该路线", ""]
    if capture["errors"]:
        lines += ["## 错误", "", *[f"- {item}" for item in capture["errors"]], ""]
    lines += ["## 限制", "", *[f"- {item}" for item in capture["limitations"]], ""]
    return "\n".join(lines)


def _download_video(client, url: str, destination: Path, max_bytes: int, referer: str) -> tuple[bool, str | None]:
    validate_remote_url(url)
    part = destination.with_suffix(".mp4.part")
    offset = part.stat().st_size if part.exists() else 0
    headers = {"Referer": referer, "User-Agent": FIXED_USER_AGENT}
    if offset:
        headers["Range"] = f"bytes={offset}-"
    try:
        with client.stream("GET", url, headers=headers, follow_redirects=True) as response:
            if response.status_code not in {200, 206}:
                return False, f"video HTTP {response.status_code}"
            content_type = response.headers.get("content-type", "").lower()
            if "text/html" in content_type or "application/json" in content_type:
                return False, f"unexpected video content type: {content_type}"
            mode = "ab" if offset and response.status_code == 206 else "wb"
            total = offset if mode == "ab" else 0
            with part.open(mode) as target:
                for chunk in response.iter_bytes():
                    total += len(chunk)
                    if total > max_bytes:
                        return False, "video exceeds configured size limit"
                    target.write(chunk)
    except Exception as error:
        return False, f"video request failed: {type(error).__name__}: {error}"
    if not validate_media_file(part)["basic_header_valid"]:
        return False, "downloaded response is not recognizable media"
    part.replace(destination)
    return True, None


def error_code_for(error: Exception) -> str:
    """Map expected stop conditions to the documented machine-readable reasons."""
    if isinstance(error, InvalidUrlError):
        return "invalid_url"
    if isinstance(error, InitialStateNotFoundError):
        return "initial_state_not_found" if "was not found" in str(error) else "initial_state_parse_failed"
    return "failed"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True)
    parser.add_argument("--output-root", default="experiments/public_html_capture_mvp/artifacts")
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--max-video-bytes", type=int, default=300 * 1024 * 1024)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)
    started = time.monotonic()
    run_dir = Path(args.output_root).expanduser() / datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    run_dir.mkdir(parents=True, exist_ok=args.force)
    source = {"input_url": args.url, "resolved_url": None, "note_id": None, "captured_at": datetime.now(timezone.utc).isoformat()}
    capture, logs = _empty_capture(source), []
    stages = {key: "failed" for key in ("URL 解析", "公开 HTML 获取", "初始化数据解析", "帖子信息提取", "视频候选提取", "视频下载", "视频校验")}
    facts = {"输入链接": args.url, "最终链接": None, "帖子 ID": None, "标题": None, "作者": None, "视频候选数量": 0, "下载结果": "未开始", "文件大小": None, "时长": None, "分辨率": None, "SHA-256": None, "全流程耗时秒": None}
    try:
        validate_public_url(args.url)
        stages["URL 解析"] = "completed"
        import httpx
        with httpx.Client(headers={"User-Agent": FIXED_USER_AGENT, "Referer": "https://www.xiaohongshu.com/"}, timeout=httpx.Timeout(args.timeout, connect=min(10.0, args.timeout)), follow_redirects=True, verify=True, cookies=None) as client:
            response = None
            for attempt in range(3):
                try:
                    response = client.get(args.url)
                    break
                except httpx.TransportError as error:
                    logs.append(f"transport_attempt_{attempt + 1}: {type(error).__name__}: {error}")
                    if attempt == 2:
                        raise RuntimeError("public_page_request_failed") from error
            assert response is not None
            source.update({"resolved_url": str(response.url), "note_id": resolve_note_id(str(response.url))})
            capture["source"].update(source)
            facts.update({"最终链接": source["resolved_url"], "帖子 ID": source["note_id"]})
            logs.append(json.dumps({"http_status": response.status_code, "content_type": response.headers.get("content-type"), "content_length": response.headers.get("content-length"), "final_url": str(response.url), "response_bytes": len(response.content), "redirect_chain": [{"status_code": item.status_code, "url": str(item.url)} for item in response.history] + [{"status_code": response.status_code, "url": str(response.url)}]}, ensure_ascii=False))
            if response.status_code in {401, 403, 406, 429}:
                capture["status"] = "rate_limited" if response.status_code == 429 else "action_required"
                capture["errors"].append("rate_limited" if response.status_code == 429 else "verification_required")
                raise RuntimeError("platform_access_blocked")
            if response.status_code == 404:
                capture["status"], capture["errors"] = "not_accessible", ["note_not_found"]
                raise RuntimeError("note_not_found")
            if response.status_code >= 400:
                raise RuntimeError(f"public_page_request_failed: HTTP {response.status_code}")
            page_html = response.text
            (run_dir / "page.html").write_text(page_html, encoding="utf-8")
            if any(token in page_html for token in ("扫码登录", "验证码", "安全验证")):
                capture["status"], capture["errors"] = "action_required", ["login_required"]
                raise RuntimeError("login_required")
            stages["公开 HTML 获取"] = "completed"
            state = extract_initial_state(page_html)
            _write_json(run_dir / "initial_state.json", state)
            stages["初始化数据解析"] = "completed"
            note = find_note_object(state, source["note_id"])
            capture = normalize_note(note, source)
            stages["帖子信息提取"] = "completed"
            facts.update({"标题": capture["post"]["title"], "作者": capture["post"]["author"]["nickname"]})
            candidates = video_candidates(note)
            _write_json(run_dir / "video_candidates.json", candidates)
            capture["media"].update({"type": "video", "candidates_found": len(candidates)})
            facts["视频候选数量"] = len(candidates)
            if not candidates:
                capture["status"], capture["errors"] = "partial", ["video_candidate_not_found"]
                raise RuntimeError("video_candidate_not_found")
            selected = select_candidate(candidates)
            capture["media"]["selected_candidate"] = selected
            stages["视频候选提取"] = "completed"
            ok, error = _download_video(client, selected["url"], run_dir / "video.mp4", args.max_video_bytes, source["resolved_url"])
            if not ok:
                capture["status"], capture["media"]["download_status"] = "partial", "failed"
                capture["errors"].append(f"video_download_failed: {error}")
                raise RuntimeError("video_download_failed")
            capture["media"].update({"download_status": "completed", "path": "video.mp4"})
            stages["视频下载"] = "completed"
            media = validate_media_file(run_dir / "video.mp4")
            stages["视频校验"] = "completed" if media["basic_header_valid"] else "failed"
            if not media["basic_header_valid"]:
                raise RuntimeError("video_validation_failed")
            capture["status"] = "completed"
            facts.update({"下载结果": "成功", "文件大小": media["size_bytes"], "时长": media["duration_seconds"], "分辨率": f"{media['width']}x{media['height']}" if media["width"] and media["height"] else None, "SHA-256": media["sha256"]})
    except Exception as error:
        logs.append(f"error: {type(error).__name__}: {error}")
        if not capture["errors"]:
            capture["errors"].append(error_code_for(error))
    finally:
        facts["全流程耗时秒"] = round(time.monotonic() - started, 3)
        _write_json(run_dir / "capture.json", capture)
        (run_dir / "run.log").write_text("\n".join(logs) + "\n", encoding="utf-8")
        (run_dir / "validation_report.md").write_text(_report(capture, stages, facts), encoding="utf-8")
        print(run_dir / "validation_report.md")
    return 0 if capture["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
