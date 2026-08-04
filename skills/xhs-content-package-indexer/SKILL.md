---
name: xhs-content-package-indexer
description: Build an analysis-ready index from an existing XHS public content package without accessing Xiaohongshu.
---

# XHS Content Package Indexer

Use this Skill after `xhs-url-video-capture` has produced a content package.
It must not fetch URLs, download media, or infer unavailable facts.

## Input

One run directory containing `content_package.json` and optional `derived/timeline.json`.

## Output

Write `derived/analysis_index.json` with package identity, content status,
field provenance, timeline event references, media references, and limitations.

## Command

```bash
python3 scripts/build_analysis_index.py --run-dir <RUN_DIRECTORY>
```
