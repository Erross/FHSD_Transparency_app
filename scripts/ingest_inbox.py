"""Ingest JSON files dropped into incoming/{complete,partial}/.

Target routing is resolved from the export itself, with filename aliases as a
fallback/cross-check. Previously unknown Facebook pages can be auto-configured
when the export supplies a declared page name and exactly one stable page/profile
ID. Files that still cannot be safely routed are quarantined under
incoming/rejected instead of contaminating a target archive.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from .ingest import target_config, validate_export_target
from .route_snapshot import (
    item_page_profile_ids,
    load_target_configs,
    resolve_target,
    top_level_profile_ids,
)

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


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")
    return slug or "facebook-page"


def _declared_page_name(payload: dict) -> str:
    target = payload.get("target") if isinstance(payload.get("target"), dict) else {}
    return str(payload.get("targetAuthor") or target.get("displayName") or "").strip()


def _auto_create_target(payload: dict, source: Path, configs: list[dict]) -> dict | None:
    """Create a conservative target config for a new Facebook page.

    Auto-creation is intentionally strict: we require a declared page name and
    exactly one observed Facebook profile/page ID. That lets a new crawler dump
    create its own archive namespace without guessing from filename text alone.
    """
    name = _declared_page_name(payload)
    if not name:
        return None

    strong_ids = top_level_profile_ids(payload)
    legacy_ids = item_page_profile_ids(payload)
    profile_ids = strong_ids or legacy_ids
    if len(profile_ids) != 1:
        return None
    profile_id = next(iter(profile_ids))

    # Do not manufacture a second target for an ID already owned by a config.
    for config in configs:
        urls = " ".join(str(url) for url in config.get("sourceUrls", []))
        if profile_id and profile_id in urls:
            return None

    target_id = _slug(name)
    target_dir = ROOT / "targets" / target_id
    if target_dir.exists():
        target_id = f"{target_id}-{profile_id[-6:]}"
        target_dir = ROOT / "targets" / target_id
        if target_dir.exists():
            return None

    filename_stem = source.stem
    filename_prefix = filename_stem.split("_202", 1)[0].strip("_ ") or name.replace(" ", "_")
    config = {
        "schemaVersion": 1,
        "id": target_id,
        "displayName": name,
        "description": f"Public archive of the {name} Facebook page and its visible discussion threads.",
        "platform": "facebook",
        "sourceUrls": [f"https://www.facebook.com/profile.php?id={profile_id}"],
        "authorAliases": [name],
        "filenameAliases": sorted({name, name.replace(" ", "_"), filename_prefix}),
        "crawl": {
            "comparisonMode": "full_snapshot",
            "requiresCompleteSnapshotForMissing": True,
            "missingRecheckThreshold": 2,
            "confirmationRequiresDirectCheck": True,
            "bulkMissingAbsoluteThreshold": 5,
            "bulkMissingRatioThreshold": 0.1,
            "bulkThreadMissingAbsoluteThreshold": 3,
        },
        "publicNotes": "The archive records what the collector observed. Absence from a later crawl is not attributed to a specific person without independent evidence.",
    }
    target_dir.mkdir(parents=True, exist_ok=False)
    (target_dir / "target.json").write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    print(
        f"AUTO-CREATED target {target_id!r} for {name!r} "
        f"(Facebook profile/page ID {profile_id})."
    )
    return config


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
            created = _auto_create_target(payload, source, configs)
            if created:
                configs.append(created)
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
