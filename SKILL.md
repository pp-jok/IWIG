---
name: IWIG
description: Convert one public Xiaohongshu note URL into a traceable local multimodal content package and analysis index without browser automation, cookies, login, private APIs, or hosted AI services.
---

# IWIG

Capture one public Xiaohongshu note at a time through ordinary HTTPS. Do not use a browser, cookies, login, JavaScript execution, signatures, private APIs, proxies, or anti-detection measures.

## Setup

```bash
cd <SKILL_DIRECTORY>
python3 scripts/iwig.py setup
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

The command writes `content_package.json`, `report.md`, selected-note/request provenance, and directly exposed video, cover, or ordered images. It always archives `source/page.html` and `source/initial_state.json` so the package can be checked or reprocessed without another platform request. Capture never loads an ASR model.

## Optional local enrichment

```bash
~/.iwig/.venv/bin/python scripts/iwig.py enrich <RUN_ID> --keyframes --ocr
~/.iwig/.venv/bin/python scripts/iwig.py enrich <RUN_ID> --transcribe --asr-model small --language zh
~/.iwig/.venv/bin/python scripts/iwig.py enrich <RUN_ID> --keyframes --ocr --json
~/.iwig/.venv/bin/python scripts/iwig.py validate <RUN_ID>
```

`--transcribe` uses local faster-whisper only when explicitly requested. The defaults (`small`, `zh`, CPU int8) suit a personal Mac; choose a smaller model or a different language when needed. IWIG does not install or invoke a visual-language model: frames, OCR, and visual candidates are evidence, not semantic recognition.

For a direct note URL, an existing package with the same note ID under the output directory is reused rather than downloaded again. Use `--run-dir` to explicitly continue working in a chosen directory.
Pass `--force` to deliberately capture a fresh snapshot.

Use `python scripts/iwig.py reindex <RUN_ID>` to create the strictly local `derived/analysis_index.json` projection. It is the intended no-network input for downstream breakdown and analysis Skills.

The workflow is `setup → capture → enrich → validate/reindex → downstream handoff`. `--json` writes exactly one JSON document to stdout, including `capture_status`, `processing_status`, `analysis_index_status`, `readiness`, errors, and artifact paths. A downstream Skill may consume `analysis_index.json` only when `analysis_index_status` is `completed`; otherwise it must use `content_package.json` and explicitly report the missing evidence. Evidence references (`scan_ref`, `frame_ref`, scene and text-change references) are validated against the index registry. See [downstream handoff](docs/downstream-handoff.md).

`status` equals `capture_status` and reflects only public capture. Local-stage aggregation is `processing_status`; failures are listed in `active_errors` and resolved failures remain in `error_history`. Reuse is based on a valid completed capture and verified primary media, never on OCR, ASR, or index success. A missing or failed index returns `analysis_index: null`; downstream Skills must then use the content package and state the material limitation. `reindex` never requests the platform and upgrades older v2 packages in memory, persisting compatibility fields on the next write.

## Boundaries

- Capture only one URL per invocation, with ordinary HTTPS and a fixed transparent User-Agent.
- Validate every page and media redirect hop, reject private/local DNS targets, and stop after five redirects. Redact token-like query parameters from reports and default manifests.
- Stop on login, verification, rate limiting, missing public post data, or inaccessible content. Missing media produces a structured partial package so text-only or image-note facts remain usable.
- Do not collect comments or replies. The report must state that comments were intentionally not collected.
- Use only complete direct video and cover URLs exposed in the selected current-note object. Never invent a URL from a file ID, refresh a token, create a signature, or retry through a private endpoint.
- Keep local ASR only for successfully downloaded media and only when `--transcribe` is requested. Do not use online transcription services.
- OCR requires macOS Vision and may take longer on its first run while Swift compiles the local helper.
