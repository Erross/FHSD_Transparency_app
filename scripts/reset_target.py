"""Reset generated archive/state for one target so snapshots can be re-ingested cleanly.

This is a development/repair utility. It intentionally deletes generated target
state and preserved raw snapshots for the selected target, then rebuilds public
indexes. Use it only when the original crawler exports are still available for
re-ingestion.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", required=True, help="Configured target slug, e.g. school-watchlist")
    parser.add_argument("--yes", action="store_true", help="Required confirmation for destructive reset")
    args = parser.parse_args()

    target_config = ROOT / "targets" / args.target / "target.json"
    if not target_config.exists():
        raise SystemExit(f"Unknown target {args.target!r}: {target_config} does not exist")
    if not args.yes:
        raise SystemExit(
            "Refusing destructive reset without --yes. This deletes generated state and archived raw snapshots "
            "for the selected target. Keep the original crawler JSONs before continuing."
        )

    paths = [
        ROOT / "data" / args.target,
        ROOT / "archive" / args.target,
        ROOT / "site" / "data" / "targets" / f"{args.target}.json",
    ]
    for path in paths:
        if path.is_dir():
            shutil.rmtree(path)
            print(f"Removed {path.relative_to(ROOT)}")
        elif path.exists():
            path.unlink()
            print(f"Removed {path.relative_to(ROOT)}")

    subprocess.run([sys.executable, "-m", "scripts.build_site"], cwd=ROOT, check=True)
    print(f"Reset complete for {args.target}. Re-add source JSONs to incoming/complete and run process_incoming.cmd.")


if __name__ == "__main__":
    main()
