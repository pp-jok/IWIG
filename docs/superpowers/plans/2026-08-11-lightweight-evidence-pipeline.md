# Lightweight Evidence Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Secure IWIG capture, make local ASR optional, and prepare bounded no-VLM evidence for downstream Skills.

**Architecture:** Capture persists public facts, media, and source evidence. Enrichment owns requested ASR/OCR/frame work. All visual processing is deterministic PyAV, dHash, and macOS Vision OCR; no visual-language model is used.

**Tech Stack:** Python 3.9+, unittest, httpx, PyAV, Pillow, optional faster-whisper, optional macOS Vision OCR.

## Global Constraints

- No visual model, cloud service, browser automation, login, cookie, private API, or proxy.
- Every redirect uses `follow_redirects=False`, per-hop validation, and a five-hop limit.
- Source HTML and initial state are always archived; signed media URLs are never saved.
- `capture` never loads ASR; only `enrich --transcribe` does.
- Scan-frame quantity and saved-frame quantity are separately bounded.
- Built-in validation is always available; JSON Schema remains optional.

### Task 1: Secure redirects and source contract

**Files:** `scripts/public_html_provider.py`, `scripts/iwig.py`, `scripts/run_capture.py`, `tests/test_public_html_provider.py`, `tests/test_iwig_cli.py`, `README.md`, `SKILL.md`.

- [ ] Add a failing media redirect test: a first-hop `302 Location: http://127.0.0.1/private` must raise `PublicCaptureError("invalid_url")` before a second request.
- [ ] Add a failing CLI test that `iwig capture ... --keep-raw-source` exits from argparse because the flag no longer exists.
- [ ] Replace media streaming with `_stream_with_validated_redirects(client, url, headers=headers, public_xhs_only=False, max_redirects=5, timeout=media_timeout)`.
- [ ] Remove `keep_raw_source` from all parser and forwarding paths; retain unconditional source writes; update docs.
- [ ] Run `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v`, then commit `fix: validate media redirects and source contract`.

### Task 2: Explicit configurable ASR enrichment

**Files:** `scripts/iwig.py`, `scripts/run_capture.py`, `tests/test_iwig_cli.py`, `tests/test_public_html_provider.py`, `README.md`, `SKILL.md`.

- [ ] Add a failing test that `process_local_stages(..., transcribe=False, asr_model="small", language="zh")` does not call `process_transcript`.
- [ ] Add a failing CLI forwarding test for `enrich RUN --transcribe --asr-model base --language en`.
- [ ] Add `--transcribe`, `--asr-model` (default `small`), and `--language` (default `zh`) to enrich; propagate all three through `run_capture` to transcript metadata.
- [ ] Preserve capture status when ASR is not requested or fails; expose `transcribe: not_run` or `failed` as applicable.
- [ ] Run the full suite, then commit `feat: make transcription an explicit enrichment stage`.

### Task 3: Two-stage bounded frame evidence

**Files:** `scripts/content_package.py`, `scripts/run_capture.py`, `tests/test_content_package.py`.

- [ ] Add failing pure tests for `scan_video_frames` and `select_representative_frames`; a boundary in dense scan metadata must be selected even when saved-frame limit is smaller than scan count.
- [ ] Implement a low-resolution PyAV scan returning only timestamp, perceptual hash, and source index; do not write scan images.
- [ ] Compute non-semantic boundaries from adjacent hash similarity, then save only bounded representative JPEGs for start/end, boundaries, and OCR changes.
- [ ] Persist `derived.frame_scan`, `derived.scenes`, and `derived.keyframes` independently.
- [ ] Run `tests/test_content_package.py`, then full suite; commit `feat: select representative frames from bounded scans`.

### Task 4: OCR changes, timeline, and multimodal evidence

**Files:** `scripts/content_package.py`, `scripts/run_capture.py`, `scripts/build_analysis_index.py`, `tests/test_content_package.py`.

- [ ] Add failing tests for OCR `appeared`, `changed`, and `disappeared` events from frame OCR sequence `"" → "第一句" → "第二句" → ""`.
- [ ] Add a failing test that empty transcript still produces evidence segments from scene/frame/text-change events.
- [ ] Implement factual `text_change_event` records using filtered OCR first, raw OCR second; persist `derived/text_change_events.json`.
- [ ] Extend timeline with ordered `speech`, `frame`, `scene_boundary`, and `text_change` events.
- [ ] Extend evidence construction to anchor on speech when available, or bounded visual events otherwise; add index projection/readiness.
- [ ] Run the full suite; commit `feat: organize multimodal evidence events`.

### Task 5: Image-page evidence and structural-hint boundary

**Files:** `scripts/content_package.py`, `scripts/run_capture.py`, `scripts/build_analysis_index.py`, `tests/test_content_package.py`.

- [ ] Add a failing image-page test asserting ordered image reference, dimensions, OCR reference, filtered OCR, and positive text density.
- [ ] Add width, height, format, OCR reference, filtered text, and deterministic text density to each factual page record.
- [ ] Write opt-in labels as `derived/candidate_labels.json` with `kind: "structural_hint"`; retain legacy `interpretations` only for read compatibility.
- [ ] Run the full suite; commit `feat: complete image evidence and structural hints`.

### Task 6: Versioned downstream handoff and documentation

**Files:** `SKILL.md`, `README.md`, `docs/data-contract.md`, `docs/analysis-index.md`, `docs/downstream-handoff.md`, `tests/test_public_html_provider.py`.

- [ ] Add a failing contract-doc test requiring `capture → enrich`, `--transcribe`, `analysis_index_status`, and the no-visual-model boundary in `SKILL.md`.
- [ ] Make `--json` include capture, processing, analysis-index status, readiness, active errors, package path, and valid index path.
- [ ] Document artifact selection and fallback: consume index only if `analysis_index_status=completed`; otherwise consume package plus limitation.
- [ ] State exactly that built-in validation is always active, while JSON Schema is extra only when its optional package and shipped schemas are present.
- [ ] Run `git diff --check`, full tests, and `python3 scripts/iwig.py setup --dry-run`; commit `docs: define IWIG downstream handoff`.
