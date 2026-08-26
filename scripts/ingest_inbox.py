"""Ingest JSON files dropped into incoming/<target>/{complete,partial}/.

This is intentionally conservative: a file is only allowed to drive missing
inference when the user places it in the explicit ``complete`` directory.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def iter_inputs():
    incoming = ROOT / "incoming"
    if not incoming.exists():
        return
    for target_dir in sorted(path for path in incoming.iterdir() if path.is_dir()):
        for mode in ("complete", "partial"):
            folder = target_dir / mode
            if not folder.exists():
                continue
            for source in sorted(folder.glob("*.json")):
                yield target_dir.name, mode == "complete", source


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--consume", action="store_true", help="Delete successfully ingested inbox JSON files.")
    args = parser.parse_args()
    processed = 0
    for target, complete, source in list(iter_inputs() or []):
        command = [sys.executable, "-m", "scripts.ingest", "--target", target]
        if complete:
            command.append("--complete")
        command.append(str(source))
        print(f"Ingesting {source.relative_to(ROOT)} as {'complete' if complete else 'partial'} snapshot")
        subprocess.run(command, cwd=ROOT, check=True)
        processed += 1
        if args.consume:
            source.unlink()
    subprocess.run([sys.executable, "-m", "scripts.build_site"], cwd=ROOT, check=True)
    print(f"Processed {processed} incoming snapshot(s)")


if __name__ == "__main__":
    main()
