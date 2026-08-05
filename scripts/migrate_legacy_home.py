#!/usr/bin/env python3
"""Copy legacy IWIG predecessor data only when explicitly requested."""
from __future__ import annotations
import argparse, os, shutil
from pathlib import Path
def main():
    parser=argparse.ArgumentParser(); parser.add_argument("--dry-run", action="store_true"); args=parser.parse_args()
    source=Path.home()/".xhs-url-video-capture"; target=Path(os.environ.get("IWIG_HOME", Path.home()/".iwig")); conflicts=[]; count=0
    if source.is_dir():
        for item in source.rglob("*"):
            relative=item.relative_to(source); destination=target/relative
            if destination.exists(): conflicts.append(relative.as_posix()); continue
            if item.is_file(): count+=1; 
            if not args.dry_run:
                destination.parent.mkdir(parents=True, exist_ok=True)
                if item.is_file(): shutil.copy2(item,destination)
    print({"source":str(source),"destination":str(target),"dry_run":args.dry_run,"files":count,"conflicts":conflicts})
if __name__=="__main__": main()
