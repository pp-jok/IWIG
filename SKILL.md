---
name: xhs-url-video-capture
description: Use when a user provides a Xiaohongshu/XHS note URL and wants its visible post data, rendered comments, direct video, and a local transcript combined into one Markdown file without hosted AI APIs.
---

# XHS URL Video Capture

Capture one logged-in Xiaohongshu note at a time. Use the supplied local scripts; do not substitute private APIs, scrape credentials, or call an online transcription service.

## One-time setup

Prerequisites: macOS, Python 3.9+, Google Chrome, and a local terminal. Run:

```bash
cd <SKILL_DIRECTORY>
python3 scripts/setup.py
```

This creates `~/.xhs-url-video-capture/.venv` and installs Playwright plus faster-whisper. It does not install or use an OpenAI API key.
The first installation downloads Python packages and the speech model on its first use; allow several minutes and a network connection for that one-time setup.

## First login

On macOS, run:

```bash
zsh scripts/start_chrome.sh
```

Log into Xiaohongshu manually in the opened dedicated Chrome window. Keep that window open. Its profile is stored outside this Skill at `~/.xhs-url-video-capture/chrome-profile`, so later captures reuse the login state.

This Skill currently supports macOS only.

Never read, export, display, or submit cookies, passwords, local storage, or verification codes. If Xiaohongshu expires the session or asks for a CAPTCHA, ask the user to complete it in that Chrome window.

If `9222` is already used by another browser, choose a free port when starting Chrome, then pass the matching address to capture: `--cdp-url http://127.0.0.1:<PORT>`. Do not connect to an unknown browser instance.

## Capture one URL

Run with the virtual-environment interpreter:

```bash
~/.xhs-url-video-capture/.venv/bin/python scripts/run_capture.py \
  --url '<XHS_NOTE_URL>' \
  --output-dir ~/.xhs-url-video-capture/output \
  --max-video-seconds 600 \
  --max-video-mb 300
```

The command prints the path to one `post_and_transcript.md`. It contains post fields, displayed engagement counts, all comments that were rendered and collected within the limit, and the local faster-whisper transcript.

## Low-usage rules

- Keep the dedicated Chrome running; connect through its local CDP port instead of launching another browser for every URL.
- Capture one URL per invocation. Default comment collection stops after 90 seconds, 40 rounds, or 5 unchanged rounds.
- Skip local transcription when the video exceeds 600 seconds or 300 MB by default; the Markdown still contains the successfully collected post and comment data.
- Reuse a capture with `--run-dir <existing-output-folder>`; an existing final report exits immediately, while an existing video or `transcript.txt` avoids duplicate download or transcription.
- Do not create screenshots, frame sheets, online summaries, or analyses unless the user asks separately.
- Do not retry a failed video as HLS, Blob, DRM, or a private API request. Report the limitation in Markdown.

## Expected limitations

- Only content visible in the logged-in web UI is collected; collapsed, unloaded, deleted, or restricted comments are not treated as missing data.
- Local automatic transcription is not an audio-verified human transcript. Preserve uncertain wording rather than inventing text.
- A note without a directly downloadable MP4 still produces a Markdown report with the available page and comment data.
