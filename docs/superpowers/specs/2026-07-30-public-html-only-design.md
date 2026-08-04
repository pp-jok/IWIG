# Public HTML Only Design

## Goal

Make public HTML the only capture route. The Skill must obtain one public XHS
post, its direct video and its directly provided cover image without Chrome,
Playwright, CDP, cookies, login, JavaScript execution, or comment endpoints.
Local faster-whisper transcription remains available after a verified video
download.

## Architecture

`scripts/run_capture.py` becomes a thin public-HTML orchestration CLI. It
uses focused helpers from `scripts/public_html_provider.py` for URL safety,
redirect resolution, `window.__INITIAL_STATE__` extraction, post
normalization, media candidate selection, and streamed download. The CLI
keeps the existing Markdown and local transcription concerns, but reports
that comments are intentionally not collected.

The cover extractor only accepts direct, complete image URLs already present
under the selected current note's `imageList` / image info. It does not turn a
`thumbnailFileid` into a guessed CDN URL and does not create signatures. The
first valid image candidate is streamed to `cover.<extension>` after content
type and non-empty-file checks.

## Changes

- Remove Playwright from requirements, setup, documentation and source.
- Delete `scripts/start_chrome.sh`.
- Add `httpx` to the formal runtime requirements.
- Add cover candidate metadata and a downloaded cover path to the Markdown
  report.
- Remove the CDP URL and comment collection CLI options.
- Preserve output reuse, download size limits, local ASR limits, and explicit
  failure reporting.

## Boundaries

The implementation remains single-URL and low-concurrency. It stops on login,
verification, rate limiting, inaccessible content, missing post data, missing
direct video, or missing direct cover. It never falls back to browser
automation, cookies, private APIs, signing, proxies, or comment endpoints.

## Verification

Offline tests cover public URL checks, initial-state parsing, note
normalization, video and cover candidate selection, streamed media headers,
and Markdown wording. One manual public-link smoke test verifies that a video
and cover are saved without a browser process.
