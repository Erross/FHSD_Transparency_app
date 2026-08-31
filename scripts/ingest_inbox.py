"""Ingest JSON files dropped into incoming/{complete,partial}/.

Target routing is resolved from the export itself, with filename aliases as a
fallback/cross-check. Files that cannot be safely routed are quarantined under
incoming/rejected instead of contaminating a target archive.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from .ingest import target_config, validate_export_target
from .route_snapshot import load_target_configs, resolve_target

ROOT = Path(__file__).resolve().parents[1]


def _parse_exported_at(payload: dict) -> datetime:
    value = str(payload.get("exportedAt") or "").strip()
    if value:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
        except ValueError:
            pass
    return datetime.max.replace(tzinfo=timezone.utc)


def iter_inputs():
    incoming = ROOT / "incoming"
    for mode in ("complete", "partial"):
        folder = incoming / mode
        if not folder.exists():
            continue
        for source in folder.glob("*.json"):
            yield mode == "complete", source


def quarantine(source: Path, reason: str) -> Path:
    rejected = ROOT / "incoming" / "rejected"
    rejected.mkdir(parents=True, exist_ok=True)
    destination = rejected / source.name
    if destination.exists():
        stem, suffix = source.stem, source.suffix
        index = 2
        while (rejected / f"{stem}-{index}{suffix}").exists():
            index += 1
        destination = rejected / f"{stem}-{index}{suffix}"
    shutil.move(str(source), str(destination))
    destination.with_suffix(destination.suffix + ".reason.txt").write_text(reason.strip() + "\n", encoding="utf-8")
    print(f"REJECTED {source.relative_to(ROOT)} -> {destination.relative_to(ROOT)}: {reason}")
    return destination


def prepare_inputs():
    configs = load_target_configs(ROOT)
    prepared = []
    rejected = 0
    for complete, source in list(iter_inputs() or []):
        try:
            payload = json.loads(source.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            quarantine(source, f"Invalid JSON export: {exc}")
            rejected += 1
            continue

        route = resolve_target(payload, source.name, configs)
        if not route.get("ok"):
            quarantine(source, route.get("reason", "Target routing failed."))
            rejected += 1
            continue

        target = route["targetId"]
        if complete:
            validation = validate_export_target(target_config(target), payload)
            if not validation["completeEligible"]:
                details = "; ".join(w["message"] for w in validation.get("warnings", [])) or "complete target validation failed"
                quarantine(source, f"Complete snapshot rejected for target {target!r}: {details}")
                rejected += 1
                continue

        prepared.append(
            {
                "target": target,
                "complete": complete,
                "source": source,
                "payload": payload,
                "exportedAt": _parse_exported_at(payload),
                "routeMethod": route.get("method", "unknown"),
            }
        )

    prepared.sort(key=lambda item: (item["exportedAt"], item["source"].name.casefold()))
    return prepared, rejected


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--consume", action="store_true", help="Delete successfully ingested inbox JSON files.")
    args = parser.parse_args()

    prepared, rejected = prepare_inputs()
    processed = 0
    for item in prepared:
        source = item["source"]
        target = item["target"]
        complete = item["complete"]
        command = [sys.executable, "-m", "scripts.ingest", "--target", target]
        if complete:
            command.append("--complete")
        command.append(str(source))
        print(
            f"Ingesting {source.relative_to(ROOT)} -> {target} as "
            f"{'complete' if complete else 'partial'} snapshot "
            f"(route={item['routeMethod']}, exportedAt={item['payload'].get('exportedAt', 'unknown')})"
        )
        subprocess.run(command, cwd=ROOT, check=True)
        processed += 1
        if args.consume and source.exists():
            source.unlink()

    subprocess.run([sys.executable, "-m", "scripts.build_site"], cwd=ROOT, check=True)
    print(f"Processed {processed} incoming snapshot(s); rejected {rejected}.")


if __name__ == "__main__":
    main()
