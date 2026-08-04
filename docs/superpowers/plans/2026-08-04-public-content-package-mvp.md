# Public Content Package MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans (recommended) or superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce a schema-v2 public XHS content package for video and image notes.

**Architecture:** `public_html_provider.py` continues to fetch and parse only public HTML, but returns normalized media candidates for both note types. `run_capture.py` owns package directories, optional local derived media, and human-readable reporting. A small `content_package.py` module owns field-status, hashing, image metadata, and subtitles so provider parsing stays focused.

**Tech Stack:** Python 3.9+, httpx, Pillow, faster-whisper/PyAV when local ASR is installed, unittest.

## Global Constraints

- One public XHS URL per invocation; no browser, cookies, login, JavaScript execution, private APIs, signatures, proxies, or comment collection.
- Preserve partial data and write a field-level completeness status for every supported output.
- Never manufacture image or video URLs from identifiers.
- Local ASR only; no hosted transcription service.

---

### Task 1: Package primitives

**Files:**
- Create: `scripts/content_package.py`
- Modify: `requirements.txt`
- Test: `tests/test_content_package.py`

**Interfaces:**
- Produces `field_status(value) -> str`, `file_record(path) -> dict`,
  `image_metadata(path) -> dict`, and `srt(segments) -> str`.

- [ ] **Step 1: Write failing tests** for zero vs missing status, SHA-256 file
  records, PNG dimensions, and 0--1.2 second SRT formatting.
- [ ] **Step 2: Run** `python3 -m unittest tests.test_content_package -v` and
  confirm import failure.
- [ ] **Step 3: Implement** the four primitives with `hashlib`, `PIL.Image`,
  and a timestamp formatter; add `Pillow>=10,<12` to requirements.
- [ ] **Step 4: Run** the focused test and confirm pass.

### Task 2: Provider media candidates for both note types

**Files:**
- Modify: `scripts/public_html_provider.py`
- Modify: `tests/test_public_html_provider.py`

**Interfaces:**
- Produces `image_candidates(note) -> list[dict]` and a result whose media has
  `video`, `cover`, and ordered `images` fields.

- [ ] **Step 1: Write failing tests** showing a two-image note preserves order,
  favours direct default-quality URLs, and does not need a video candidate.
- [ ] **Step 2: Run** `python3 -m unittest tests.test_public_html_provider -v`
  and confirm missing behavior.
- [ ] **Step 3: Implement** direct image candidate selection, independent media
  downloads, source evidence paths, and partial-status failures.
- [ ] **Step 4: Run** the focused test and confirm pass.

### Task 3: Schema-v2 writer and local transcript artifacts

**Files:**
- Modify: `scripts/run_capture.py`
- Modify: `tests/test_content_package.py`

**Interfaces:**
- Produces `content_package.json`, `report.md`, `derived/transcript.txt`,
  `derived/transcript_segments.json`, and `derived/subtitles.srt`.

- [ ] **Step 1: Write failing tests** asserting the report lists availability,
  image order, intentionally uncollected comments, and linked transcript
  artifacts.
- [ ] **Step 2: Run** the focused test and confirm failure.
- [ ] **Step 3: Implement** version-2 assembly, source/media directories,
  timestamped local ASR segments, SRT output, and failure isolation.
- [ ] **Step 4: Run** all unit tests and confirm pass.

### Task 4: Docs and regression verification

**Files:**
- Modify: `SKILL.md`
- Modify: `README.md`
- Test: `tests/test_public_html_provider.py`

- [ ] **Step 1: Write a failing documentation assertion** that the public-only
  boundary remains documented and the new package files are named.
- [ ] **Step 2: Update** skill and README with video/image behavior, status
  semantics, and optional derived outputs.
- [ ] **Step 3: Run** `python3 -m unittest discover -s tests -v` and
  `python3 -m py_compile scripts/*.py`; expect all tests and compilation pass.
- [ ] **Step 4: Commit** only product source, tests, docs, and the plan/spec;
  exclude generated output and `.DS_Store`.
