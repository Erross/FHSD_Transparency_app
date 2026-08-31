"""List archive records that need disappearance/manual-review attention."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .io_utils import read_json

ROOT = Path(__file__).resolve().parents[1]
REVIEW_STATUSES = {"missing_once", "missing_recheck"}


def rows_for_target(target: str):
    path = ROOT / "data" / target / "state.json.gz"
    legacy = ROOT / "data" / target / "state.json"
    state = read_json(path) if path.exists() else (read_json(legacy) if legacy.exists() else None)
    if state is None:
        raise SystemExit(f"Target {target!r} has no ingested state")
    rows = []
    for entity in state.get("entities", {}).values():
        if entity.get("status") not in REVIEW_STATUSES:
            continue
        rows.append(
            {
                "entityId": entity.get("id", ""),
                "status": entity.get("status", ""),
                "missingCount": entity.get("missingCount", 0),
                "itemType": entity.get("itemType", ""),
                "author": entity.get("authorDisplayName") or entity.get("author", ""),
                "lastSeen": entity.get("lastSeen", ""),
                "permalink": entity.get("permalink") or entity.get("parentPostPermalink", ""),
                "text": entity.get("text", ""),
                "identityConfidence": entity.get("identityConfidence") or entity.get("identityQuality", ""),
            }
        )
    return sorted(rows, key=lambda r: (r["status"] != "missing_recheck", -int(r["missingCount"] or 0), r["lastSeen"]))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", required=True)
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON instead of a review table.")
    args = parser.parse_args()
    rows = rows_for_target(args.target)
    if args.json:
        print(json.dumps(rows, indent=2, ensure_ascii=False))
        return
    if not rows:
        print("No missing/recheck records currently need review.")
        return
    print(f"Manual review queue: {len(rows)} record(s)\n")
    for index, row in enumerate(rows, 1):
        print(f"[{index}] {row['status']} · missing x{row['missingCount']} · {row['itemType']} · {row['author']}")
        print(f"    entity: {row['entityId']}")
        print(f"    last seen: {row['lastSeen']}")
        if row["permalink"]:
            print(f"    source: {row['permalink']}")
        text = row["text"].replace("\n", " ")
        print(f"    text: {text[:240]}{'…' if len(text) > 240 else ''}")
        print("    confirm unavailable:")
        print(
            "      python -m scripts.verify_missing "
            f"--target {args.target} --entity {row['entityId']!r} --confirm-unavailable"
        )
        print("    confirm visible:")
        print(
            "      python -m scripts.verify_missing "
            f"--target {args.target} --entity {row['entityId']!r} --confirm-visible"
        )
        print()


if __name__ == "__main__":
    main()
