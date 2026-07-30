# Public HTML Only Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the formal browser/CDP capture route with public-HTML-only post, video, cover, and local transcription capture.

**Architecture:** `scripts/public_html_provider.py` exposes pure parsing and downloading helpers. `scripts/run_capture.py` owns CLI arguments, output reuse, local ASR, and Markdown rendering; it calls the provider once for each supplied URL.

**Tech Stack:** Python 3.9+, httpx, faster-whisper, unittest, optional ffprobe.

## Global Constraints

- No Playwright, Chrome, CDP, cookies, login, JavaScript execution, private APIs, signatures, proxying, or comment endpoints.
- Accept exactly one public HTTP(S) XHS URL per invocation.
- Download only direct video and cover URLs found within the selected current-note object.
- Always report absent comments as intentionally uncollected.

---

### Task 1: Extract a formal public provider

**Files:**
- Create: `scripts/public_html_provider.py`
- Create: `tests/test_public_html_provider.py`

**Interfaces:**
- Produces `capture_public_note(url: str, output_dir: Path, timeout: float, max_video_bytes: int) -> dict`.

- [ ] **Step 1: Write failing tests** for direct cover URL extraction and rejection of file-id-only cover references.
- [ ] **Step 2: Run** `python3 -m unittest tests.test_public_html_provider -v`; expect import failure.
- [ ] **Step 3: Move minimal tested public parsing and download helpers** from the experiment, returning normalized post, video and cover metadata.
- [ ] **Step 4: Re-run the provider test**; expect PASS.

### Task 2: Replace the formal CLI route

**Files:**
- Modify: `scripts/run_capture.py`
- Modify: `tests/test_public_html_provider.py`

**Interfaces:**
- Consumes `capture_public_note`.
- Produces `post_and_transcript.md`, `video.mp4`, optional `cover.<extension>`, and structured provider artifacts.

- [ ] **Step 1: Write a failing CLI render test** asserting the report names a saved cover and states that comments were not collected.
- [ ] **Step 2: Run the focused test**; expect failure because the former CDP renderer lacks cover/public wording.
- [ ] **Step 3: Implement the public-only CLI** with local ASR reuse and no CDP/comment arguments.
- [ ] **Step 4: Re-run focused tests**; expect PASS.

### Task 3: Remove browser dependencies and update docs

**Files:**
- Delete: `scripts/start_chrome.sh`
- Modify: `requirements.txt`
- Modify: `scripts/setup.py`
- Modify: `README.md`
- Modify: `SKILL.md`
- Modify: `agents/openai.yaml`

- [ ] **Step 1: Write a failing source-level test** asserting formal runtime files contain no Playwright or CDP references.
- [ ] **Step 2: Run it**; expect failure against the current files.
- [ ] **Step 3: Remove browser dependencies and rewrite setup/docs** for public HTML only.
- [ ] **Step 4: Run all tests and syntax compilation**; expect PASS with no Playwright reference.
