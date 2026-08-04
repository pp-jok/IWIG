---
name: xhs-url-video-capture
description: Use when a user provides one Xiaohongshu/XHS note URL and wants a public-HTML-only structured content package for a video or image note.
---

# XHS Public HTML Video Capture

Capture one public Xiaohongshu note at a time through ordinary HTTPS. Do not use a browser, cookies, login, JavaScript execution, signatures, private APIs, proxies, or anti-detection measures.

## Setup

```bash
cd <SKILL_DIRECTORY>
python3 scripts/setup.py
```

This creates `~/.xhs-url-video-capture/.venv` and installs `httpx` plus `faster-whisper`. No OpenAI API key is required.

## Capture one URL

```bash
~/.xhs-url-video-capture/.venv/bin/python scripts/run_capture.py \
  --url '<XHS_NOTE_URL>' \
  --output-dir ~/.xhs-url-video-capture/output \
  --max-video-mb 300
```

The command writes `content_package.json`, `report.md`, source HTML/state, and directly exposed video, cover, or ordered images. Video transcription additionally creates local text, timestamp segments, and SRT subtitles when available.

For a direct note URL, an existing package with the same note ID under the output directory is reused rather than downloaded again. Use `--run-dir` to explicitly continue working in a chosen directory.
Pass `--force` to deliberately capture a fresh snapshot.

## Boundaries

- Capture only one URL per invocation, with ordinary HTTPS and a fixed transparent User-Agent.
- Stop immediately on login, verification, rate limiting, missing public post data, missing direct video, or inaccessible content.
- Do not collect comments or replies. The report must state that comments were intentionally not collected.
- Use only complete direct video and cover URLs exposed in the selected current-note object. Never invent a URL from a file ID, refresh a token, create a signature, or retry through a private endpoint.
- Keep local ASR only for successfully downloaded media. Do not use online transcription services.
