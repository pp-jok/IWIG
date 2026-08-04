# Public HTML Capture MVP Design

## Goal

Validate, in an isolated experiment, whether one public Xiaohongshu sharing
link can be resolved, fetched without cookies or browser automation, parsed
from public HTML, and downloaded as a verifiable video file.

## Scope and boundaries

The experiment lives only in `experiments/public_html_capture_mvp/`. It uses
ordinary HTTPS requests with a fixed transparent desktop User-Agent and does
not use Playwright, CDP, cookies, JavaScript execution, private APIs, request
signatures, proxying, or anti-detection measures. A platform block, login,
verification, missing post data, or unavailable video ends the run with a
diagnostic report; it never falls back to the existing browser-based capture.

## Architecture

`capture_public_mvp.py` is a small command-line program composed of pure
helpers and a thin I/O orchestration layer. The pure helpers validate and
resolve URLs, extract `window.__INITIAL_STATE__` from script elements, locate
an unambiguous current-note object, normalize fields, and rank video
candidates. The orchestration layer writes one run directory, fetches the
page, streams one selected candidate to a temporary file, validates media,
and renders JSON plus Markdown artifacts.

The public request layer uses `httpx` with certificate verification enabled,
explicit timeout limits, no cookies, and at most two retries for transport
errors only. SSRF checks reject local, private, link-local, and obvious
internal hosts before every user-controlled request target.

## Data and status behavior

Each run always produces `capture.json`, `run.log`, and
`validation_report.md`. Successful stages additionally save `page.html`,
`initial_state.json`, `video_candidates.json`, and `video.mp4` when available.
The normalized capture uses schema version 1 and one of the requested status
values. It retains unknown values as `null`, records limitations explicitly,
and treats page metrics as a capture-time public snapshot.

## Testing and validation

Offline `unittest` cases precede implementation and cover URL safety,
script-state extraction, normalization, candidate ordering, and streamed-file
validation. A single real invocation against the supplied link happens only
after the offline suite passes. Its report states the outcome as feasible,
partially feasible, or infeasible based only on files produced by that run.
