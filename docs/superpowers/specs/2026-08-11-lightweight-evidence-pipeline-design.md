# Lightweight Evidence Pipeline Design

## Goal

Make IWIG a reliable local public-content collector and evidence preprocessor. It must remain usable on a low-performance personal computer and must not install or invoke a visual-language model.

## Scope and boundaries

IWIG captures public HTML and directly exposed media, produces local ASR/OCR/frame evidence, and prepares a versioned handoff for downstream analysis Skills. It does not use browser automation, login state, private APIs, cloud services, hosted AI, or any visual model. It does not make final content, audience, product, person, or narrative judgements.

The only visual operations are local and deterministic: PyAV decoding, low-resolution image hashing, macOS Vision OCR, and bounded frame export. `candidate_labels` are structural hints, never final analysis.

## Architecture

### Capture and source evidence

`capture` is limited to public page facts, downloaded media, and durable source evidence. It always archives `source/page.html` and `source/initial_state.json`, alongside redacted request, selected-note, and media-candidate provenance. The obsolete `--keep-raw-source` flag is removed.

Every page and media redirect is requested with `follow_redirects=False`. IWIG validates the initial URL and every resolved `Location` before opening the next hop, rejects local/private targets, and limits the chain to five redirects.

### Optional local enrichment

`capture` never loads an ASR model. `enrich` receives explicit local stages: `--transcribe`, `--keyframes`, and `--ocr`. Transcription accepts model and language settings, with a personal-machine default of `small`, Chinese, CPU, and int8. A missing model, unsupported OCR runtime, or failed enrichment creates a stage-specific result without changing a completed capture.

### Bounded two-stage visual evidence

For a video, IWIG first scans low-resolution frames at a bounded adaptive cadence and stores only scan metadata: timestamp, perceptual hash, and OCR-derived text signature when OCR is requested. Scene boundaries arise only from non-semantic visual change signals. IWIG then exports a separately bounded set of representative JPEG frames for the start/end, each detected scene, and high-value OCR changes.

Scan cadence and maximum scan samples are independent from the maximum saved representative frames. No scan frame is retained merely because it was scanned.

### Timeline and evidence segments

The timeline contains normalized event records for `speech`, `frame`, `scene_boundary`, and `text_change`. `text_change` records OCR text appearance, replacement, or disappearance with references to the before/after frame and no semantic conclusion.

Multimodal evidence segments are deterministic time ranges built from whichever evidence exists. With ASR, speech spans anchor the range. Without ASR, scene boundaries, frame coverage, and OCR text-change events provide the ranges. Each segment lists evidence references and availability; it does not infer meaning.

### Image notes and handoff

Image-note processing preserves page order, file metadata, dimensions, OCR and filtered OCR, text density, and artifact references. The versioned analysis index is the no-network handoff. Its `readiness` states tell a downstream Skill which artifacts are usable; a consumer must only use `analysis_index.json` when `analysis_index_status` is `completed`, otherwise it must use the content package and state the limitation.

### Validation and labels

Built-in validation is always available. JSON Schema validation is an optional strengthening when `jsonschema` and the shipped schema files are present; documentation must not claim it is always active. Existing `interpretations` are renamed in documentation and output semantics to `candidate_labels` or `structural_hints`, remain opt-in, and may be removed if they provide no downstream value.

## Error semantics

`capture_status` describes only public capture; `processing_status` aggregates local stages; `analysis_index_status` describes the handoff index. `not_run`, `not_exposed`, `partial`, `failed`, and numeric zero must remain distinguishable. A downstream consumer receives the three statuses, `readiness`, `active_errors`, and the authoritative artifact paths in every JSON result.

## Verification

- Unit tests cover every redirect hop for pages and media, source-archive default behavior, and removal of the obsolete option.
- Tests prove capture does not import ASR and enrichment respects model/language configuration.
- Synthetic-video tests cover bounded scan metadata, representative-frame selection, scene boundaries, OCR appearance/change/disappearance, timeline ordering, and evidence without speech.
- Fixture image-note tests cover page order, OCR records, dimensions, text density, and handoff readiness.
- Recovery and compatibility tests prove completed capture survives interrupted enrichment and older packages remain readable.
