# IWIG analysis index

`derived/analysis_index.json` is a no-network projection of the content package. It contains normalized text, visual artifacts, scene/frame/OCR timeline events, provenance, completeness, evidence IDs, quality data, and readiness states. Its recorded source-package SHA-256 makes stale indexes detectable by `iwig validate`.

When rebuilding the index fails, IWIG preserves the capture package and records the problem as local processing state. It does not perform another public-page request. A stale index is quarantined as `derived/analysis_index.stale.json`, and machine-readable CLI output reports `analysis_index: null` until a valid index exists.
