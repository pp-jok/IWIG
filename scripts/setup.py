#!/usr/bin/env python3
"""Create the isolated local runtime used by this Skill."""
import argparse
import os
import subprocess
import sys
from pathlib import Path


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--home", default=str(Path(os.environ.get("IWIG_HOME", str(Path.home() / ".iwig")))))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    if sys.version_info < (3, 9):
        raise SystemExit("Python 3.9 or newer is required.")
    home = Path(args.home).expanduser()
    venv = home / ".venv"
    if args.dry_run:
        print(f"Would create IWIG runtime at {home}")
        return 0
    home.mkdir(parents=True, exist_ok=True)
    subprocess.run([sys.executable, "-m", "venv", str(venv)], check=True)
    python = venv / "bin" / "python"
    root = Path(__file__).resolve().parents[1]
    subprocess.run([str(python), "-m", "pip", "install", "--upgrade", "pip"], check=True)
    subprocess.run([str(python), "-m", "pip", "install", "-r", str(root / "requirements.txt"), "-r", str(root / "requirements-local-asr.txt")], check=True)
    print(f"Setup complete. Run: {python} {root / 'scripts' / 'iwig.py'} capture --url '<XHS_NOTE_URL>'")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
