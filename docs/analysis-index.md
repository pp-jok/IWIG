# IWIG analysis index

`derived/analysis_index.json` is a no-network projection of the content package. It contains normalized text, visual artifacts, scene/frame/OCR timeline events, provenance, completeness, evidence IDs, quality data, and readiness states. Its recorded source-package SHA-256 makes stale indexes detectable by `iwig validate`.

When rebuilding the index fails, IWIG preserves the capture package and records the problem as local processing state. It does not perform another public-page request. A stale index is quarantined with a timestamp under `derived/analysis_index.stale.<timestamp>.json`, and machine-readable CLI output reports `analysis_index: null` until a valid index exists. The index records a stable `source_package.content_sha256`, which excludes its own transient processing state and prevents a successful final status update from making the new index stale.
