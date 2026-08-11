# IWIG

Local-first public content capture and multimodal analysis packaging for Xiaohongshu.

IWIG converts one user-provided public Xiaohongshu note into a traceable local content package and analysis index. It never uses browser automation, cookies, login, JavaScript execution, private APIs, signatures, proxies, or hosted AI services.

```text
public note URL → public HTML provider → content_package.json → local media/ASR/OCR → analysis_index.json
```

## Install

Requirements:

- Python 3.9 or newer, including `venv` support.
- macOS: Xcode Command Line Tools (`xcode-select --install`) when OCR is needed. OCR uses the local macOS Vision framework; it is not available on other operating systems.
- Network access only while capturing the public page and downloading public media. ASR, frame extraction, OCR, indexing, and visual labels run locally.

```bash
git clone https://github.com/pp-jok/IWIG.git
cd IWIG
python3 scripts/iwig.py setup
```

`setup` creates an isolated `~/.iwig/.venv` (override with `IWIG_HOME`) and installs the following Python dependencies:

| Dependency | Installed by `setup` | Purpose |
| --- | --- | --- |
| `httpx` | yes | Read public HTML and download publicly exposed media. |
| `Pillow` | yes | Perceptual hashes used for scene-change and frame selection. |
| `PyAV` (`av`) | yes | Read video metadata and extract keyframes. |
| `faster-whisper` | yes | Local, timestamped video transcription. Its model is downloaded on the first transcription run. |
| `jsonschema` | no | Not needed for personal use; IWIG uses its built-in validation. |
| Visual-language model | no | Deliberately not bundled; `--describe-visuals` only emits lightweight OCR-based labels. |

The first transcription can take longer because `faster-whisper` obtains its `small` model. No browser, login state, cookie, proxy, cloud OCR, or hosted AI service is installed or used.

## Use

```bash
~/.iwig/.venv/bin/python scripts/iwig.py capture --url 'https://www.xiaohongshu.com/explore/<NOTE_ID>' --keyframes --ocr
~/.iwig/.venv/bin/python scripts/iwig.py enrich ~/.iwig/output/<RUN_ID> --keyframes --ocr
~/.iwig/.venv/bin/python scripts/iwig.py enrich ~/.iwig/output/<RUN_ID> --transcribe --asr-model small --language zh
~/.iwig/.venv/bin/python scripts/iwig.py enrich ~/.iwig/output/<RUN_ID> --keyframes --ocr --json
~/.iwig/.venv/bin/python scripts/iwig.py enrich ~/.iwig/output/<RUN_ID> --keyframes --ocr --interpret
~/.iwig/.venv/bin/python scripts/iwig.py enrich ~/.iwig/output/<RUN_ID> --keyframes --ocr --interpret --describe-visuals
~/.iwig/.venv/bin/python scripts/iwig.py validate ~/.iwig/output/<RUN_ID>
~/.iwig/.venv/bin/python scripts/iwig.py reindex ~/.iwig/output/<RUN_ID>
```

Video capture transcribes the downloaded video locally by default. Use `capture --no-transcribe` only when a transcript is intentionally unnecessary. The first video capture can take longer while faster-whisper downloads its local `small` model. `capture --json` and `enrich --json` emit exactly one JSON document on stdout. It includes capture, processing and index statuses, `readiness`, active errors, and artifact paths. The content package is the stable machine interface; `report.md` is only a human-readable summary. See [data contract](docs/data-contract.md), [analysis index](docs/analysis-index.md), and [downstream handoff](docs/downstream-handoff.md).

## What one capture produces

Each run is a self-contained directory under `~/.iwig/output/<RUN_ID>/`. It is safe to archive the directory as a content snapshot. A video `capture` includes local transcription by default; use `enrich --transcribe` to resume a failed or previously skipped transcript without requesting the platform again. Image notes remain transcript-free.

| Path | When present | What it is for |
| --- | --- | --- |
| `content_package.json` | always | Authoritative machine-readable package: identity, public post facts, media records, processing state, completeness, hashes, limitations, and references to every local artifact. Start here when another Skill or script consumes a run. |
| `report.md` | always | Short human-readable overview of the post, media, capture status, processing status, and limitations. |
| `source/request.json` | capture succeeds | Redacted request/provenance record. |
| `source/page.html` | capture succeeds | Archived public HTML used as the original page evidence. |
| `source/initial_state.json` | exposed by page | Parsed public initial-state data used to extract fields; useful for reprocessing or debugging parser changes. |
| `source/selected_note.json` | note selected | The selected public note object after identity matching. |
| `source/media_candidates.json` | candidates exposed | Redacted media candidate list and the selection basis; diagnostic provenance, not a media download recipe. |
| `media/video.*` | video note and download succeeds | Local primary video. Its hash, size, duration, dimensions, and codecs are recorded in `content_package.json`. |
| `media/cover.*` | cover exposed and download succeeds | Best available public cover image. |
| `media/images/*` | image note and downloads succeed | All image pages in public order. The first page is the usable cover unless the page exposes a separate cover. |
| `derived/transcript_raw_segments.json` | video transcription succeeds | Original timestamped ASR segments, including model confidence fields when available. |
| `derived/transcript_segments.json` | video transcription succeeds | Normalized timestamped transcript for downstream use. |
| `derived/transcript.txt` / `derived/subtitles.srt` | video transcription succeeds | Readable transcript and subtitle interchange file. |
| `derived/keyframes/*.jpg` | `--keyframes` and video available | Locally extracted visual samples. Sampling adapts to video duration and is capped at 12 frames. |
| `derived/timeline.json` | local processing runs | Chronological union of transcript, frame, and scene events. |
| `derived/evidence_segments.json` | speech, scene, or OCR evidence available | Factual multimodal links between speech, representative frames, scene changes and text-change events; no content judgement. |
| `derived/image_pages.json` | image note | Ordered page-to-OCR references for an image note. |
| `derived/candidate_labels.json` | `--interpret` | Optional rule-based structural hints based on evidence segments; they are not final content analysis. |
| `derived/visual_descriptions.json` | `--describe-visuals` | Lightweight OCR-density labels such as `text_card` or `subtitle_overlay`; this is not person, product, or screen-recording recognition. |
| `derived/analysis_index.json` | index completes | Stable no-network downstream index. Its content hash lets `iwig validate` detect stale indexes. |
| `processing/validation.json` | `validate` | Latest package and artifact validation result. |

`content_package.json` distinguishes captured facts (`kind: "fact"`) from local inferences (`kind: "inference"`). `null` or a completeness state such as `not_exposed`, `not_run`, and `failed` means unknown or unavailable; it never means a metric is zero. A numeric `0` is represented separately as a real zero value.

## Status semantics

`status` is the compatible alias of `capture_status`: it describes only the public-page and primary-media capture. `processing_status` describes local ASR, OCR, frames, timeline, and index processing separately. A machine result can therefore be:

```json
{"capture_status":"completed","processing_status":"partial","analysis_index_status":"failed","analysis_index":null}
```

Exit code `2` means local processing is incomplete; it does not mean the collected public content is unusable. Downstream tools must consume `analysis_index` only when `analysis_index_status` is `completed`. Video breakdown additionally requires `readiness.transcript` to be `ready`; a failed or unavailable transcript must block spoken-content claims. `reindex` is local-only and never revisits the platform.

## Output and boundaries

Each snapshot contains a schema-validated `content_package.json`, derived transcript/frames/OCR/timeline, and a local `derived/analysis_index.json`. Default manifests redact token-like URLs and media signatures. Raw source or sensitive candidates require explicit diagnostic flags and must not be committed.

Public `source/page.html` and `source/initial_state.json` are archived by default. The capture manifest is written before ASR/OCR begins, so an interrupted local stage can be resumed with `enrich` without revisiting the public page.

When local enrichment is available, IWIG also writes these evidence-layer artifacts:

- Dense scan is local and adaptive: short videos scan no more frequently than once per second; long videos increase cadence to remain within the sample limit while retaining end coverage. Scan images are not saved.
- `derived/scene_change_events` records perceptual-hash changes with `scan_ref` and, when available, a mapped representative `frame_ref`. The legacy `scene_change_keyframes` field is read-compatible only.
- `derived/evidence_segments.json` links speech, frames, scene changes and OCR text-change events. Every reference is checked against the analysis-index evidence registry.
- OCR retains its provider text and line data; `filtered_text` is a reproducible view using lines with confidence at least `0.80`.
- `derived/candidate_labels.json` is created only by `enrich --interpret`. These are structural hints, include `evidence_refs`, and are not captured facts or final analysis.
- `derived/image_pages.json` preserves image-page order and page OCR references. `--describe-visuals` adds only rule-based visual inferences; it never changes captured facts.

If media, ASR, OCR, frames, or interpretation are unavailable, the package still preserves the completed stages and records the missing stage separately. Absence is never treated as a zero-valued public metric.

IWIG does not collect comment bodies, operate accounts, bypass access controls, construct media URLs, remove watermarks, or perform publishing actions. Follow platform terms, copyright, and applicable law.

## Development

```bash
python -m unittest discover -s tests -v
```

Live image-note validation is `pending_user_test`; IWIG never searches for validation posts on its own.
