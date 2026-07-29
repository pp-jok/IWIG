# Public HTML Capture MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an isolated public-HTML feasibility CLI that emits verifiable artifacts without browser automation or cookies.

**Architecture:** One focused Python module exposes pure, offline-testable helpers and a CLI orchestration function. HTTP fetching and streaming download are limited to public HTTPS/HTTP URLs after SSRF validation; every stop condition becomes structured output rather than a fallback.

**Tech Stack:** Python 3.9+, `httpx`, standard-library `unittest`, optional system `ffprobe`.

## Global Constraints

- Create only `experiments/public_html_capture_mvp/`; do not change the existing formal capture workflow.
- No browser automation, JavaScript execution, cookies, internal APIs, signing, proxying, anti-detection, comments, or account actions.
- Retry only ordinary network transport failures, at most two times; stop immediately on platform access blocks.
- Always write `capture.json`, `run.log`, and `validation_report.md`; never represent a failed download as success.

---

### Task 1: Scaffold and URL safety

**Files:**
- Create: `experiments/public_html_capture_mvp/requirements.txt`
- Create: `experiments/public_html_capture_mvp/tests/test_capture_public_mvp.py`
- Create: `experiments/public_html_capture_mvp/capture_public_mvp.py`

**Interfaces:**
- Produces `validate_public_url(url: str) -> urllib.parse.ParseResult` and `resolve_note_id(url: str) -> str | None`.

- [ ] **Step 1: Write failing URL tests** for accepted short/explore/discovery/profile URLs and rejected `file:`, localhost, and private IP URLs.
- [ ] **Step 2: Run** `python -m unittest discover -s experiments/public_html_capture_mvp/tests -v`; expect import/function failures.
- [ ] **Step 3: Implement minimal URL parsing** with `urllib.parse`, `ipaddress`, and a public-host allowlist.
- [ ] **Step 4: Re-run the suite**; expect URL cases to pass.

### Task 2: State parsing and note normalization

**Files:**
- Modify: `experiments/public_html_capture_mvp/capture_public_mvp.py`
- Modify: `experiments/public_html_capture_mvp/tests/test_capture_public_mvp.py`

**Interfaces:**
- Produces `extract_initial_state(html: str) -> dict`, `find_note_object(state: dict, note_id: str | None) -> dict`, and `normalize_note(note: dict, source: dict) -> dict`.

- [ ] **Step 1: Write failing fixture-based tests** for nested JSON, braces in strings, missing state, field naming variants, milliseconds, and empty tags.
- [ ] **Step 2: Run the focused tests** and verify expected failures.
- [ ] **Step 3: Implement script-node extraction** using `html.parser`, balanced braces, `json.loads`, and optional `json5`; implement conservative recursive current-note selection.
- [ ] **Step 4: Re-run tests**; expect parsing and normalization cases to pass.

### Task 3: Video candidates and file validation

**Files:**
- Modify: `experiments/public_html_capture_mvp/capture_public_mvp.py`
- Modify: `experiments/public_html_capture_mvp/tests/test_capture_public_mvp.py`

**Interfaces:**
- Produces `video_candidates(note: dict) -> list[dict]`, `select_candidate(candidates: list[dict]) -> dict | None`, and `validate_media_file(path: Path) -> dict`.

- [ ] **Step 1: Write failing tests** for origin precedence, resolution/bitrate tie-breakers, URL de-duplication, no candidates, and tiny MP4-header files.
- [ ] **Step 2: Run focused tests** and verify expected failures.
- [ ] **Step 3: Implement bounded note-object traversal**, deterministic sorting, SHA-256, MP4 signature checks, and optional `ffprobe` inspection.
- [ ] **Step 4: Re-run tests**; expect candidate and validation cases to pass.

### Task 4: CLI orchestration and real validation

**Files:**
- Modify: `experiments/public_html_capture_mvp/capture_public_mvp.py`
- Create: `experiments/public_html_capture_mvp/README.md`

**Interfaces:**
- Produces `main(argv: list[str] | None = None) -> int` with `--url`, `--output-root`, `--timeout`, `--max-video-bytes`, and `--force`.

- [ ] **Step 1: Write failing tests** for artifact creation on an early invalid URL and rejected HTML media response using a local mocked transport.
- [ ] **Step 2: Run focused tests** and verify expected failures.
- [ ] **Step 3: Implement the request/downloader orchestration** with `httpx`, `.part` files, byte limits, range continuation, atomic rename, and structured reports.
- [ ] **Step 4: Run the complete offline suite**; expect all tests to pass.
- [ ] **Step 5: Run exactly one supplied-link validation** and record the produced report without any fallback.
