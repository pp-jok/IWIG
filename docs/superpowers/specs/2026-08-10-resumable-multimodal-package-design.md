# Resumable Multimodal Content Package Design

## Goal

Make every IWIG public-note capture recoverable after interruption, default to preserving public source evidence, and add practical media, image-page, and visual-analysis inputs without mixing inference into captured facts.

## Scope

This design applies only to local files derived from public Xiaohongshu HTML and media already downloaded by IWIG. It does not add browser automation, login, private APIs, comment collection, cloud services, or hosted AI models.

## Architecture

### 1. Durable capture checkpoint

`capture_public_note` produces an initial valid `content_package.json` immediately after public HTML parsing, source archiving, and each successful media write. The capture package uses `capture_status: partial` until required primary media is available, then changes atomically to `completed`.

The default source artifacts are:

- `source/page.html` — response HTML as received.
- `source/initial_state.json` — parsed public initialization data.
- `source/selected_note.json` — selected note object used for field extraction.
- `source/request.json` and `source/media_candidates.json` — request provenance and sanitized candidates.

`--keep-raw-source` remains accepted as a no-op compatibility flag. No signed media URLs are persisted.

### 2. Resumable derived stages

Each stage persists its own artifacts and updates `processing.<stage>` before beginning the next stage. `iwig enrich` checks input hashes and output paths, reuses completed valid output, and only reruns missing, failed, or stale stages.

Stages are: `extract_keyframes`, `transcribe`, `ocr_cover`, `ocr_images`, `ocr_keyframes`, `describe_visuals`, `link_image_copy`, `build_evidence_segments`, `interpret_evidence`, `build_timeline`, and `analysis_index`.

Interruption must leave a readable content package. A stage left as `running` is normalized to `partial` with `interrupted_or_unfinished` on the next invocation, while all completed artifacts remain available.

### 3. Media metadata

Video records retain current file size, hash, duration, dimensions and video codec, and add frame rate, video bitrate, audio codec, audio bitrate, sample rate and channel count where exposed by PyAV. Missing streams use `null`, never an invented value.

### 4. Image-page evidence and weak copy links

For image notes, each downloaded image keeps page order, media metadata, OCR, and a factual page evidence record. A deterministic keyword overlap links OCR tokens to normalized post-description paragraphs. The result stores shared tokens and references only; it does not claim semantic intent.

### 5. Visual candidates and interpretations

Fixed-interval frames remain the durable visual baseline. Candidate records additionally state one or more explicit bases: `start`, `end`, `scene_change`, `ocr_novelty`, or `subtitle_change`. Visual type descriptions such as `talking_head`, `screen_recording`, `text_card`, `product`, and `unknown` are opt-in rule-based inferences with confidence, method and evidence references.

### 6. Facts versus inferences

`derived.evidence_segments`, page OCR and media metadata are factual records. Visual descriptions, structural labels and copy links that rely on heuristics are stored in `derived.interpretations` using `kind: "inference"`, `method`, `confidence`, and `evidence_refs`. Analysis indexes project both layers but never transform inference into fact.

## Error and completeness semantics

Each source and derived capability has a `completeness` entry that distinguishes `zero`, `not_exposed`, `not_run`, `partial`, `failed`, and `intentionally_omitted`. A missing page image, absent audio stream, unavailable OCR engine, or unsupported visual description must be reported independently. A capture with usable primary media remains `capture_status: completed` if a later local stage fails.

## Verification

- Unit tests cover checkpoint persistence, recovery after a `running` stage, media metadata with/without audio, page ordering, deterministic links, and facts/inferences separation.
- Existing public-video package is enriched after an artificial interruption and produces the same completed artifacts without a platform request.
- A real public image-note test validates all page-level artifacts when a user-provided public image note is available; until then fixture coverage is required and the capability is reported as unverified-live.
- Full `unittest` regression passes without `jsonschema`, Pillow, cloud OCR, or an LLM dependency.
