# IWIG downstream handoff

Use `iwig capture --json` or the run directory as the handoff boundary. The JSON result reports `capture_status`, `processing_status`, `analysis_index_status`, `active_errors`, `content_package`, `report`, and a valid `analysis_index` path when available.

Downstream Skills must read `derived/analysis_index.json` only when `analysis_index_status` is `completed`. Otherwise they must read `content_package.json`, use only available factual artifacts, and state the missing processing limitation rather than assuming a value is zero.

Recommended progression is `capture → enrich → validate/reindex → downstream handoff`. `capture` contains public facts and media. `enrich --transcribe`, `--keyframes`, and `--ocr` add optional local evidence. `validate` checks package paths and hashes; `reindex` makes no platform request.

Evidence is factual: post fields, source artifacts, media, frame timestamps, OCR, scene boundaries, text-change events, transcript spans, and evidence links. `interpretations` and visual labels are optional structural hints, not content analysis. IWIG does not use a visual-language model.

Built-in structural and path validation is always active. JSON Schema validation is an additional check only when the optional `jsonschema` package and shipped schemas are available.
