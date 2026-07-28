#!/usr/bin/env python3
"""Capture one visible XHS note into a single local Markdown report."""
import argparse
import json
import re
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from playwright.sync_api import Error as PlaywrightError, sync_playwright


EXPAND_REPLY_PATTERN = re.compile(r"^(展开\s*\d+\s*条回复|展开更多回复|查看全部.*回复)$")


class NoteUnavailableError(Exception):
    pass


def visible_login(page) -> bool:
    try:
        phone = page.get_by_text("手机号登录", exact=True)
        code = page.get_by_text("获取验证码", exact=True)
        return phone.count() == 1 and code.count() == 1 and phone.is_visible() and code.is_visible()
    except PlaywrightError:
        return False


def wait_for_detail(page, seconds: float) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if page.locator("#detail-title").count() or page.locator(".comments-el").count():
            return
        page.wait_for_timeout(500)


def wait_for_comments(page, seconds: float) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        total = page.locator(".comments-el .total")
        try:
            if total.count() == 1 and "条评论" in total.inner_text(timeout=800):
                return True
        except PlaywrightError:
            pass
        page.wait_for_timeout(500)
    return False


def note_is_unavailable(visible_text: str) -> bool:
    return "当前笔记暂时无法浏览" in visible_text or "笔记不存在" in visible_text


def target_note_unavailable(url: str, visible_text: str) -> bool:
    return ("/404" in url and "error_code=300031" in url) or note_is_unavailable(visible_text)


def page_data(page) -> dict:
    data = page.evaluate("""() => {
      const text = s => document.querySelector(s)?.innerText?.trim() || null;
      const meta = name => document.querySelector(`meta[property="${name}"],meta[name="${name}"]`)?.content?.trim() || null;
      const title = text('#detail-title') || meta('og:title') || document.title.replace(/ - 小红书$/, '');
      const author = text('.author-wrapper .username') || text('.author .name');
      const content = text('#detail-desc') || text('.note-content') || meta('og:description');
      const tags = [...document.querySelectorAll('#detail-desc a, .note-content a')]
        .map(x => x.innerText.trim()).filter(x => x.startsWith('#'));
      const video = document.querySelector('video');
      return {title, author, content, tags:[...new Set(tags)],
        metrics:{comments:text('.comments-el .total')},
        duration_seconds: Number.isFinite(video?.duration) ? video.duration : null,
        video_url: video?.currentSrc || video?.src || null};
    }""")
    try:
        visible = page.locator("body").inner_text(timeout=3_000)
    except PlaywrightError:
        visible = ""
    data["tags"] = list(dict.fromkeys(data.get("tags") or re.findall(r"#[^\s#]{1,50}", visible)))[:20]
    comment_total = re.search(r"共\s*([0-9.]+\s*(?:万|千)?)\s*条评论", visible)
    interaction_tail = re.search(r"说点什么\.\.\.\s*\n\s*([0-9.]+\s*(?:万|千)?)\s*\n\s*([0-9.]+\s*(?:万|千)?)\s*\n\s*([0-9.]+\s*(?:万|千)?)", visible)
    data["metrics"].update({
        "likes": interaction_tail.group(1).strip() if interaction_tail else None,
        "favorites": interaction_tail.group(2).strip() if interaction_tail else None,
        "comments": comment_total.group(1).strip() if comment_total else data["metrics"].get("comments"),
    })
    if data.get("author"):
        data["author"] = re.sub(r"\s*关注$", "", data["author"])
    return data


def collect_comments(page, max_seconds: float, max_rounds: int, stable_rounds: int) -> tuple[list[dict], dict]:
    comments: dict[str, dict] = {}
    start, stable, clicked = time.monotonic(), 0, 0
    for round_index in range(max_rounds):
        rows = page.locator(".comments-el .comment-item").evaluate_all("""items => items.map(x => ({
          author:x.querySelector('.author .name')?.innerText?.trim() || '',
          text:x.querySelector('.content .note-text')?.innerText?.trim() || '',
          meta:x.querySelector('.info .date')?.innerText?.trim() || '',
          likes:x.querySelector('.interactions .like .count')?.innerText?.trim() || null
        }))""")
        before = len(comments)
        for row in rows:
            if row['text']:
                comments[json.dumps(row, ensure_ascii=False, sort_keys=True)] = row
        buttons = page.get_by_text(EXPAND_REPLY_PATTERN)
        count = min(buttons.count(), 10)
        for index in range(count):
            try:
                buttons.nth(index).click(timeout=800)
                clicked += 1
            except PlaywrightError:
                pass
        page.evaluate("() => document.querySelector('.comments-el')?.scrollBy(0, 1200)")
        page.wait_for_timeout(600)
        stable = stable + 1 if len(comments) == before else 0
        if stable >= stable_rounds or time.monotonic() - start >= max_seconds:
            break
    return list(comments.values()), {"collected":len(comments), "expand_clicks":clicked, "elapsed_seconds":round(time.monotonic()-start, 2)}


def download(url: Optional[str], path: Path, referer: str, max_bytes: Optional[int] = None) -> bool:
    if not url or '.mp4' not in url.lower().split('?')[0]:
        return False
    headers = {
        "Referer": referer,
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120 Safari/537.36",
    }
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=90) as response, path.open('wb') as target:
            written = 0
            while chunk := response.read(1024 * 1024):
                written += len(chunk)
                if max_bytes is not None and written > max_bytes:
                    raise ValueError("video exceeds configured size limit")
                target.write(chunk)
        return path.stat().st_size > 0
    except Exception:
        path.unlink(missing_ok=True)
        return False


def first_mp4(candidates: list[str], fallback: Optional[str]) -> Optional[str]:
    for url in [fallback, *candidates]:
        if url and ".mp4" in url.lower().split("?")[0]:
            return url
    return None


def can_transcribe(duration_seconds: Optional[float], file_bytes: int, max_seconds: float, max_bytes: int) -> bool:
    return (duration_seconds is None or duration_seconds <= max_seconds) and file_bytes <= max_bytes


def transcribe(video: Path) -> list[str]:
    from faster_whisper import WhisperModel
    model = WhisperModel("small", device="cpu", compute_type="int8")
    segments, _ = model.transcribe(str(video), language="zh", vad_filter=True)
    return [segment.text.strip() for segment in segments if segment.text.strip()]


def render(data: dict, comments: list[dict], transcript: list[str], summary: dict, url: str, limitations: list[str]) -> str:
    lines = ["# 小红书帖子与本地口播", "", "## 帖子信息", "", f"- 链接：{url}", f"- 标题：{data.get('title') or '未获取'}", f"- 作者：{data.get('author') or '未获取'}", f"- 点赞：{data['metrics'].get('likes') or '未获取'}", f"- 收藏：{data['metrics'].get('favorites') or '未获取'}", f"- 评论：{data['metrics'].get('comments') or '未获取'}", f"- 标签：{' '.join(data.get('tags') or []) or '未获取'}", "", "## 正文", "", data.get('content') or '未获取', "", "## 评论采集", "", f"- 可见评论条数：{summary['collected']}", f"- 展开回复点击：{summary['expand_clicks']}", f"- 采集耗时：{summary['elapsed_seconds']} 秒", "", "## 完整评论", ""]
    lines += [f"- **{item['author'] or '匿名'}**：{item['text']}（{item['meta'] or '时间未显示'}；赞 {item['likes'] or '未显示'}）" for item in comments] or ["- 未获取到已渲染评论。"]
    lines += ["", "## 本地口播逐字稿", ""]
    if transcript:
        lines += ["> 来源：faster-whisper small，本地 CPU int8 自动转写；可能存在听辨或断句错误。", "", *transcript]
    else:
        lines += ["[未生成：页面未提供可直接下载的 MP4，或本地转写失败。]"]
    lines += ["", "## 限制", "", "- 仅采集登录态网页中已渲染的公开内容。", "- 未显示或未加载的评论、字幕、语气词不会被补写。"]
    lines += [f"- {item}" for item in limitations]
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--output-dir", default="output")
    parser.add_argument("--run-dir", help="Reuse this existing capture directory instead of creating a timestamped one")
    parser.add_argument("--cdp-url", default="http://127.0.0.1:9222")
    parser.add_argument("--max-seconds", type=float, default=90)
    parser.add_argument("--max-rounds", type=int, default=40)
    parser.add_argument("--stable-rounds", type=int, default=5)
    parser.add_argument("--max-video-seconds", type=float, default=600)
    parser.add_argument("--max-video-mb", type=int, default=300)
    args = parser.parse_args()
    output = Path(args.run_dir).expanduser().resolve() if args.run_dir else Path(args.output_dir).expanduser().resolve() / datetime.now().strftime("%Y%m%d-%H%M%S")
    output.mkdir(parents=True, exist_ok=True)
    report = output / "post_and_transcript.md"
    if report.is_file():
        print(report)
        return 0
    with sync_playwright() as p:
        try:
            browser = p.chromium.connect_over_cdp(args.cdp_url)
        except PlaywrightError:
            raise SystemExit("Chrome is not available. Run scripts/start_chrome.sh, log in manually, and retry.")
        if not browser.contexts:
            raise SystemExit("Chrome is connected but has no browser context. Restart it with scripts/start_chrome.sh.")
        context = browser.contexts[0]
        page = context.new_page()
        media_candidates: list[str] = []

        def observe_response(response) -> None:
            content_type = response.headers.get("content-type", "")
            if ".mp4" in response.url.lower().split("?")[0] or "video/mp4" in content_type.lower():
                if response.url not in media_candidates:
                    media_candidates.append(response.url)

        page.on("response", observe_response)
        try:
            data = {"title": None, "author": None, "content": None, "tags": [], "metrics": {}}
            comments: list[dict] = []
            summary = {"collected": 0, "expand_clicks": 0, "elapsed_seconds": 0}
            limitations: list[str] = []
            transcript: list[str] = []
            try:
                page.goto(args.url, wait_until="domcontentloaded", timeout=45_000)
                initial_text = page.locator("body").inner_text(timeout=3_000)
                if target_note_unavailable(page.url, initial_text):
                    raise NoteUnavailableError
                wait_for_detail(page, 20)
                visible_after_detail = page.locator("body").inner_text(timeout=3_000)
                if target_note_unavailable(page.url, visible_after_detail):
                    raise NoteUnavailableError
                if visible_login(page):
                    raise SystemExit("需要登录：请在专用 Chrome 窗口完成登录后重试。")
                comments_ready = wait_for_comments(page, 20)
                if not comments_ready:
                    limitations.append("评论区在 20 秒内未就绪；评论数量可能不完整或为 0。")
                data = page_data(page)
                try:
                    visible_text = page.locator("body").inner_text(timeout=3_000)
                except PlaywrightError:
                    visible_text = ""
                comments, summary = collect_comments(page, args.max_seconds, args.max_rounds, args.stable_rounds)
                video, transcript_file = output / "video.mp4", output / "transcript.txt"
                max_bytes = args.max_video_mb * 1024 * 1024
                if transcript_file.is_file():
                    transcript = [line for line in transcript_file.read_text(encoding="utf-8").splitlines() if line.strip()]
                elif data.get("duration_seconds") and data["duration_seconds"] > args.max_video_seconds:
                    limitations.append(f"视频时长超过 {args.max_video_seconds:g} 秒上限，跳过本地口播转写。")
                elif video.is_file() or download(first_mp4(media_candidates, data.get('video_url')), video, page.url, max_bytes):
                    if not can_transcribe(data.get("duration_seconds"), video.stat().st_size, args.max_video_seconds, max_bytes):
                        limitations.append(f"视频超过 {args.max_video_mb} MB 上限，跳过本地口播转写。")
                    else:
                        try:
                            transcript = transcribe(video)
                            transcript_file.write_text("\n".join(transcript) + "\n", encoding="utf-8")
                        except Exception as error:
                            limitations.append(f"本地口播转写失败：{type(error).__name__}: {error}")
                else:
                    limitations.append("未找到、无法下载或超过大小上限的直接 MP4，未生成本地口播。")
            except SystemExit as error:
                limitations.append(str(error))
                raise
            except NoteUnavailableError:
                limitations.append("帖子不可访问、已删除或当前无法浏览；已停止评论、视频和口播采集。")
            except Exception as error:
                limitations.append(f"页面或评论采集失败：{type(error).__name__}: {error}")
            finally:
                report.write_text(render(data, comments, transcript, summary, args.url, limitations), encoding="utf-8")
                print(report)
        finally:
            page.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
