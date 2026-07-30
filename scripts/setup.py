#!/usr/bin/env python3
"""Create the isolated local runtime used by this Skill."""
import argparse
import subprocess
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--home", default=str(Path.home() / ".xhs-url-video-capture"))
    args = parser.parse_args()
    if sys.version_info < (3, 9):
        raise SystemExit("Python 3.9 or newer is required.")
    home = Path(args.home).expanduser()
    venv = home / ".venv"
    home.mkdir(parents=True, exist_ok=True)
    subprocess.run([sys.executable, "-m", "venv", str(venv)], check=True)
    python = venv / "bin" / "python"
    root = Path(__file__).resolve().parents[1]
    subprocess.run([str(python), "-m", "pip", "install", "--upgrade", "pip"], check=True)
    subprocess.run([str(python), "-m", "pip", "install", "-r", str(root / "requirements.txt"), "-r", str(root / "requirements-local-asr.txt")], check=True)
    print(f"Setup complete. Run: {python} {root / 'scripts' / 'run_capture.py'} --url '<XHS_NOTE_URL>'")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
