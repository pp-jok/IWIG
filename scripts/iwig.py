#!/usr/bin/env python3
"""The single IWIG command line entrypoint."""
from __future__ import annotations
import argparse, contextlib, json, os, sys
from pathlib import Path
from build_analysis_index import build_analysis_index, validate_analysis_index_schema, write_analysis_index
from content_package import atomic_write_json, validate_content_package
import run_capture

HOME = Path(os.environ.get("IWIG_HOME", Path.home() / ".iwig"))

def _result(run: Path, status: str) -> dict: return {"status": status, "run_dir": str(run), "content_package": str(run / "content_package.json"), "analysis_index": str(run / "derived/analysis_index.json"), "report": str(run / "report.md")}
def validate(run: Path) -> dict:
    package = json.loads((run / "content_package.json").read_text()); errors = validate_content_package(package); warnings=[]
    index_path = run / "derived/analysis_index.json"
    if index_path.is_file():
        index=json.loads(index_path.read_text()); errors += validate_analysis_index_schema(index)
        from content_package import file_record
        if index.get("source_package",{}).get("sha256") != file_record(run / "content_package.json", run)["sha256"]: errors.append("analysis_index_stale")
    else: warnings.append("analysis_index_missing")
    output={"valid": not errors, "errors": errors, "warnings": warnings}; atomic_write_json(run / "processing/validation.json", output); return output
def main() -> int:
    parser=argparse.ArgumentParser(prog="iwig"); sub=parser.add_subparsers(dest="command", required=True)
    sub.add_parser("setup"); capture=sub.add_parser("capture"); capture.add_argument("--url", required=True); capture.add_argument("--output-dir", default=str(HOME / "output")); capture.add_argument("--keyframes",action="store_true"); capture.add_argument("--ocr",action="store_true"); capture.add_argument("--json",action="store_true")
    enrich=sub.add_parser("enrich"); enrich.add_argument("run_dir"); enrich.add_argument("--keyframes",action="store_true"); enrich.add_argument("--ocr",action="store_true")
    for name in ("reindex","validate"): sub.add_parser(name).add_argument("run_dir")
    migrate=sub.add_parser("migrate-legacy-home"); migrate.add_argument("--dry-run",action="store_true")
    args=parser.parse_args()
    if args.command=="setup": from setup import main as setup_main; return setup_main()
    if args.command=="migrate-legacy-home": print(json.dumps({"source": str(Path.home()/".xhs-url-video-capture"), "destination": str(HOME), "dry_run":args.dry_run, "action":"manual_copy_only"})); return 0
    if args.command=="validate": out=validate(Path(args.run_dir)); print(json.dumps(out)); return 0 if out["valid"] else 5
    if args.command=="reindex": target=write_analysis_index(Path(args.run_dir)); print(target); return 0
    if args.command=="enrich":
        code = run_capture.main(["--enrich-dir",args.run_dir]+(["--keyframes"] if args.keyframes else [])+(["--ocr"] if args.ocr else []))
        if code == 0: write_analysis_index(Path(args.run_dir))
        return code
    capture_args=["--url",args.url,"--output-dir",args.output_dir]+(["--keyframes"] if args.keyframes else [])+(["--ocr"] if args.ocr else [])
    with contextlib.redirect_stdout(sys.stderr if args.json else sys.stdout): code=run_capture.main(capture_args)
    runs=sorted(Path(args.output_dir).expanduser().glob("*/content_package.json")); run=runs[-1].parent if runs else Path(args.output_dir)
    if (run/"content_package.json").is_file(): write_analysis_index(run)
    if args.json: print(json.dumps(_result(run, "completed" if code==0 else "partial")))
    return 0 if code==0 else 2
if __name__=="__main__": raise SystemExit(main())
