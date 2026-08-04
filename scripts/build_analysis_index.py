#!/usr/bin/env python3
"""Create a strictly local, no-network analysis projection for a content package."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from content_package import validate_content_package


def validate_analysis_index(index: dict) -> list[str]:
    required = ("schema", "identity", "status", "post", "media", "timeline", "quality", "warnings")
    return [f"missing:{key}" for key in required if key not in index]


def build_analysis_index(run: Path) -> dict:
    package = json.loads((run / "content_package.json").read_text(encoding="utf-8"))
    package_errors = validate_content_package(package)
    timeline_path = run / "derived" / "timeline.json"
    timeline = json.loads(timeline_path.read_text(encoding="utf-8")) if timeline_path.is_file() else {"events": []}
    warnings = list(package.get("limitations") or []) + package_errors
    if not timeline["events"]:
        warnings.append("timeline_not_available")
    quality = {"package_valid": not package_errors,
               "transcript_segments": len(package.get("transcript") or []),
               "image_count": len(package.get("media", {}).get("images") or []),
               "keyframe_count": len((package.get("keyframes") or {}).get("frames") or []),
               "error_count": len(package.get("errors") or [])}
    return {"schema": {"name": "xhs-analysis-index", "version": "1.0.0"},
            "identity": package.get("source", {}), "status": package.get("status"),
            "post": package.get("post", {}), "media": package.get("media", {}),
            "timeline": timeline, "field_provenance": package.get("field_provenance", {}),
            "quality": quality, "warnings": warnings, "errors": package.get("errors", [])}


def main() -> int:
    parser = argparse.ArgumentParser(); parser.add_argument("--run-dir", required=True); args = parser.parse_args()
    run = Path(args.run_dir).expanduser().resolve(); index = build_analysis_index(run)
    errors = validate_analysis_index(index)
    if errors: raise SystemExit("invalid analysis index: " + ", ".join(errors))
    target = run / "derived" / "analysis_index.json"; target.parent.mkdir(exist_ok=True)
    target.write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"); print(target); return 0


if __name__ == "__main__": raise SystemExit(main())
