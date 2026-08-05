---
name: IWIG
description: Convert one public Xiaohongshu note URL into a traceable local multimodal content package and analysis index without browser automation, cookies, login, private APIs, or hosted AI services.
---

# IWIG

Capture one public Xiaohongshu note at a time through ordinary HTTPS. Do not use a browser, cookies, login, JavaScript execution, signatures, private APIs, proxies, or anti-detection measures.

## Setup

```bash
cd <SKILL_DIRECTORY>
python3 scripts/setup.py
```

This creates `~/.iwig/.venv` and installs local dependencies. No OpenAI API key is required.

## Capture one URL

```bash
~/.iwig/.venv/bin/python scripts/iwig.py capture \
  --url '<XHS_NOTE_URL>' \
  --output-dir ~/.iwig/output \
  --max-video-mb 300
```

Add `--keyframes --ocr` to extract up to 12 local representative frames and run macOS Vision OCR on the cover, image pages, and frames. OCR is optional and never uploads media.

The command writes `content_package.json`, `report.md`, selected-note/request provenance, and directly exposed video, cover, or ordered images. Add `--keep-raw-source` only when raw HTML and full initial state are required for debugging. Video transcription additionally creates raw and normalized timestamp segments, text, and SRT subtitles when available.

For a direct note URL, an existing package with the same note ID under the output directory is reused rather than downloaded again. Use `--run-dir` to explicitly continue working in a chosen directory.
Pass `--force` to deliberately capture a fresh snapshot.

Use `scripts/build_analysis_index.py --run-dir <RUN_ID>` to create the strictly local `derived/analysis_index.json` projection. It is the intended no-network input for downstream breakdown and analysis Skills.

## Boundaries

- Capture only one URL per invocation, with ordinary HTTPS and a fixed transparent User-Agent.
- Validate every page and media redirect hop, reject private/local DNS targets, and stop after five redirects. Redact token-like query parameters from reports and default manifests.
- Stop immediately on login, verification, rate limiting, missing public post data, missing direct video, or inaccessible content.
- Do not collect comments or replies. The report must state that comments were intentionally not collected.
- Use only complete direct video and cover URLs exposed in the selected current-note object. Never invent a URL from a file ID, refresh a token, create a signature, or retry through a private endpoint.
- Keep local ASR only for successfully downloaded media. Do not use online transcription services.
- OCR requires macOS Vision and may take longer on its first run while Swift compiles the local helper.
