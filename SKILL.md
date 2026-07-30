---
name: xhs-url-video-capture
description: Use when a user provides one Xiaohongshu/XHS note URL and wants its public post data, direct video, directly exposed cover, and local transcript in one Markdown report without browser automation.
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

The command writes one `post_and_transcript.md`, `capture.json`, `page.html`, `initial_state.json`, video candidates, cover candidates, `video.mp4`, and an optional `cover.webp` / `cover.jpg` / `cover.png`.

## Boundaries

- Capture only one URL per invocation, with ordinary HTTPS and a fixed transparent User-Agent.
- Stop immediately on login, verification, rate limiting, missing public post data, missing direct video, or inaccessible content.
- Do not collect comments or replies. The report must state that comments were intentionally not collected.
- Use only complete direct video and cover URLs exposed in the selected current-note object. Never invent a URL from a file ID, refresh a token, create a signature, or retry through a private endpoint.
- Keep local ASR only for successfully downloaded media. Do not use online transcription services.
