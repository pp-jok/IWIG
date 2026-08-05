# IWIG data contract

`content_package.json` has the same top-level schema for completed, partial, and failed snapshots. Paths are POSIX paths relative to the run directory. `completeness` always records `status`, `count`, and `reason`; absence is never interpreted as zero. Run `python scripts/iwig.py validate <RUN_DIR>` before downstream use.
