# IWIG Evidence and Interpretation Layer

## Goal

Turn a captured public note into traceable evidence for later breakdown without mixing public facts with model interpretation.

## Scope

### Evidence layer

- Keep fixed-interval keyframes and add scene-change candidates.
- Preserve raw OCR and produce confidence-filtered OCR text.
- Write `derived/evidence_segments.json`, keyed by transcript time ranges.
- Include supporting speech IDs, frame IDs, scene IDs, OCR IDs, and artifact paths.
- For image notes, retain page order, dimensions, OCR, and cover relationship.
- Project the new artifacts into `analysis_index.json`.

### Interpretation layer

- Write optional candidate segment labels: `hook`, `problem`, `case`, `method`, `result`, `call_to_action`, or `unknown`.
- Write optional short visual descriptions and image-to-copy candidate links.
- Every interpretation must include `kind: inference`, evidence IDs, and a confidence score.
- No interpretation may overwrite source fields, transcript text, OCR text, or public metadata.

## Data Contracts

`derived/evidence_segments.json` contains ordered segments with:

- `id`, `start_seconds`, `end_seconds`;
- `speech_ids`, `frame_ids`, `scene_ids`, `ocr_ids`;
- a compact `fact_summary` assembled only from linked transcript/OCR facts;
- optional `interpretation` records, each with `kind`, `label`, `confidence`, and `evidence_ids`.

OCR records retain `text`, `lines`, and add `filtered_text` built from lines at or above a documented confidence threshold. Empty filtered text is valid and does not discard raw OCR.

## Processing

1. Extract baseline keyframes and scene-change candidates.
2. OCR frames and images, then derive filtered OCR text.
3. Build time-bounded evidence segments from transcript ranges, associating overlapping frames, scenes, and OCR.
4. Optionally add rule-based candidate labels; they remain in the interpretation namespace.
5. Regenerate the analysis index from the updated package.

## Failure Behavior

- Missing video leaves video evidence and interpretation stages `not_run`; text evidence remains usable.
- Failed frame extraction records an explicit reason and preserves transcript, cover, and other artifacts.
- OCR failure preserves source images and raw evidence references.
- Interpretation failure never blocks evidence output.

## Verification

- Unit tests cover confidence filtering, time-overlap association, evidence ordering, dynamic-frame deduplication, and fact/inference separation.
- A real captured video is enriched without re-downloading; the resulting package must expose evidence segments and retain all previous artifacts.
