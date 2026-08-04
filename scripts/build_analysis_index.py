#!/usr/bin/env python3
"""Create a no-network analysis index from an existing content package."""
import argparse
import json
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--run-dir", required=True)
args = parser.parse_args()
run = Path(args.run_dir).expanduser().resolve()
package = json.loads((run / "content_package.json").read_text(encoding="utf-8"))
timeline_path = run / "derived" / "timeline.json"
timeline = json.loads(timeline_path.read_text(encoding="utf-8")) if timeline_path.is_file() else {"events": []}
index = {"schema": {"name": "xhs-analysis-index", "version": "1.0.0"}, "identity": package.get("source", {}), "status": package.get("status"), "post": package.get("post", {}), "media": package.get("media", {}), "timeline": timeline, "field_provenance": package.get("field_provenance", {}), "limitations": package.get("limitations", []), "errors": package.get("errors", [])}
target = run / "derived" / "analysis_index.json"
target.parent.mkdir(exist_ok=True)
target.write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(target)
