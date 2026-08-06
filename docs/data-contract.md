# IWIG data contract

`content_package.json` has the same top-level schema for completed, partial, and failed snapshots. Paths are POSIX paths relative to the run directory. `completeness` always records `status`, `count`, and `reason`; absence is never interpreted as zero. Run `python scripts/iwig.py validate <RUN_DIR>` before downstream use.

`status` and `capture_status` describe the public-page capture result only. `processing_status` describes local derived processing independently. A failed or stale `analysis_index` is recorded as `processing.analysis_index.status` plus a deduplicated `active_errors` entry; it never rewrites a successful capture as partial. Re-running `iwig reindex <RUN_DIR>` clears that active index error after a successful rebuild.
