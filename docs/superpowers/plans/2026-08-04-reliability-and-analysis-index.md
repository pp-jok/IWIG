# Reliability and Analysis Index Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `executing-plans` to execute this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Make public XHS content packages reliable, safe, schema-stable, and directly consumable by a no-network analysis index Skill.

**Architecture:** Keep `public_html_provider.py` limited to public HTML and directly exposed media. Move shared package semantics into `content_package.py`; make `run_capture.py` run idempotent processing stages; make `build_analysis_index.py` produce a strictly validated analysis projection.

**Tech Stack:** Python 3.9+, httpx, Pillow, optional PyAV/faster-whisper/macOS Vision, unittest, JSON Schema.

## Global Constraints

- One user-provided public URL per capture; no browser, Cookie, login, private API, signature, proxy, or comment collection.
- Every redirect hop must pass URL, DNS/IP and redirect-limit checks.
- A failed media or derived stage must preserve all earlier facts and use one package schema.
- All derived processing is local; indexer makes no network request.

### Task 1: Secure HTTP and download reliability

**Files:** `scripts/public_html_provider.py`, `tests/test_public_html_provider.py`

- [ ] Add `_request_with_validated_redirects()` for pages and media. It must call `_validate_url()` before every request, use `follow_redirects=False`, resolve relative `Location`, reject invalid/missing locations, and stop after five hops.
- [ ] Replace media stream auto-redirects with this helper while preserving streaming and content-type validation.
- [ ] Try at most two already exposed video candidates in ranked order; append `{stage, code, candidate_path}` failures; never construct URLs.
- [ ] Make image-note cover reference `media.images[0]` rather than download it twice.
- [ ] Add tests for private redirect, redirect limit, primary-candidate failure/backup success, `.part` cleanup, and media-failure partial result.

### Task 2: Stable content-package contract

**Files:** `scripts/content_package.py`, `scripts/run_capture.py`, `schemas/content-package-v1.schema.json`, `tests/test_content_package.py`

- [ ] Replace string-only completeness with objects: `{status, count, reason}`; represent zero, absent, intentionally omitted, failed and not-run distinctly.
- [ ] Return run-relative paths such as `media/images/001.jpg` from all records; update all readers.
- [ ] Add `new_content_package(status, input_url)` and use it for completed, partial and failed results.
- [ ] Add generator version, commit, dependency versions, model name and model revision/cache identity when available.
- [ ] Validate every output package against required schema keys; add schema fixture tests for completed, partial and failed packages.

### Task 3: Source minimization and provenance

**Files:** `scripts/public_html_provider.py`, `scripts/run_capture.py`, `tests/test_public_html_provider.py`

- [ ] Store `source/selected_note.json` and request metadata by default.
- [ ] Add `--keep-raw-source` for page HTML and full initial state; default to off.
- [ ] Store canonical note URL and redact token-like query parameters in reports and default manifests.
- [ ] Resolve duplicate selected-note objects by known detail-map paths first, then deduplicate fallback matches by serialized object hash.
- [ ] Expand `field_provenance` to exact JSON paths, capture time and source artifact.

### Task 4: Idempotent local processing stages

**Files:** `scripts/run_capture.py`, `scripts/content_package.py`, `tests/test_content_package.py`

- [ ] Implement `process_transcript`, `process_keyframes`, `process_ocr_cover`, `process_ocr_images`, `process_ocr_keyframes`, `recompute_completeness`.
- [ ] Make capture and `--enrich-dir` call the same stages; each stage checks existing artifacts and valid manifest state before reuse.
- [ ] Persist raw ASR segments separately from normalized segments; record engine/model/language/segment count and warnings.
- [ ] Precompile the macOS Vision helper once and accept multiple image paths in one process; store line text, confidence and normalized bounding boxes.
- [ ] Add tests for video without OCR transcription, image OCR without video, rerun idempotency and failed-stage recovery.

### Task 5: Visual and timeline indexing

**Files:** `scripts/content_package.py`, `scripts/build_analysis_index.py`, `schemas/analysis-index-v1.schema.json`, `tests/test_content_package.py`

- [ ] Add perceptual hashes and adjacent-frame similarity to images and frames.
- [ ] Add scene-boundary events based on configurable frame-difference threshold, including representative frame, start/end and similarity score.
- [ ] Select structural frames from forced start/end, scene boundaries, OCR novelty and transcript topic/paused-segment changes; record score components and reason.
- [ ] Build `derived/timeline.json` containing speech, frame, OCR and scene references per segment.
- [ ] Build `derived/analysis_index.json` only from local package artifacts; validate it and include quality/warning summary.

### Task 6: Verification, evidence and release

**Files:** `docs/validation/public-html-validation-2026-08-04.md`, `README.md`, `SKILL.md`, tests

- [ ] Add unit tests for every new branch above and run `python3 -m unittest discover -s tests -v` plus `python3 -m py_compile scripts/*.py`.
- [ ] Run one public video capture without cookies/browser; commit only a redacted validation record with note ID, final status, field completeness, candidate count, media hash/duration and commit SHA.
- [ ] Run one public image-note capture when a user-provided public image-note URL is available; record the same redacted evidence.
- [ ] Update README and both Skill documents with schema, local processing, redaction, indexer and limitation semantics.
- [ ] Commit all source/docs/tests, exclude media/raw pages, push `main` after final tests pass.

## Completion Criteria

- Redirect, media, partial-result, schema, idempotency and indexer tests pass.
- Every status path produces the same top-level package contract.
- A redacted public-video validation record is committed; image-note validation is documented as pending only if no public image-note input exists.
- `main` is pushed and clean except user-owned ignored files.
