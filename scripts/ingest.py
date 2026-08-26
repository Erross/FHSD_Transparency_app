"""Ingest one crawler export into the multi-target archive."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

from .core import initial_state, normalize_item, normalize_space, now_iso, summary
from .coverage import apply_coverage_snapshot
from .enrich import enrich_normalized
from .io_utils import read_json, write_json_gz, write_raw_gz
from .route_snapshot import configured_profile_ids, observed_profile_ids

ROOT = Path(__file__).resolve().parents[1]


def target_config(target_id):
    path = ROOT / "targets" / target_id / "target.json"
    if not path.exists():
        raise SystemExit(f"Unknown target {target_id!r}: {path} does not exist")
    return read_json(path)


def sanitize_timestamp(value):
    return re.sub(r"[^0-9A-Za-z._-]+", "-", value.strip()).strip("-") or "snapshot"


def preserve_raw(target_id, raw, exported_at):
    sha = hashlib.sha256(raw).hexdigest()
    folder = ROOT / "archive" / target_id / "raw"
    folder.mkdir(parents=True, exist_ok=True)
    dest = folder / f"{sanitize_timestamp(exported_at)}-{sha[:12]}.json.gz"
    if not dest.exists():
        write_raw_gz(dest, raw)
    dest.with_suffix(dest.suffix + ".sha256").write_text(f"{sha}  {dest.name}\n", encoding="utf-8")
    return dest, sha


def validate_export_target(config: dict, payload: dict) -> dict:
    aliases = {
        normalize_space(value).casefold()
        for value in config.get("authorAliases", []) + [config.get("displayName", "")]
        if normalize_space(value)
    }
    target = payload.get("target") if isinstance(payload.get("target"), dict) else {}
    declared = normalize_space(payload.get("targetAuthor") or target.get("displayName"))
    declared_match = not declared or declared.casefold() in aliases

    configured_ids = configured_profile_ids(config)
    observed_ids = observed_profile_ids(payload)
    source_match = not configured_ids or bool(configured_ids & observed_ids)

    warnings = []
    if not declared_match:
        warnings.append(
            {
                "code": "declared_target_mismatch",
                "message": f"Export targetAuthor {declared!r} does not match configured aliases for {config.get('displayName', config.get('id', 'target'))!r}.",
            }
        )
    if not source_match:
        warnings.append(
            {
                "code": "source_profile_not_observed",
                "message": "Configured Facebook profile ID was not observed in export page/profile metadata.",
            }
        )

    return {
        "declaredTargetAuthor": declared,
        "declaredTargetMatches": declared_match,
        "configuredProfileIds": sorted(configured_ids),
        "observedProfileIds": sorted(observed_ids),
        "sourceProfileMatches": source_match,
        "completeEligible": bool(declared_match and source_match),
        "warnings": warnings,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--target", required=True)
    parser.add_argument(
        "--complete",
        action="store_true",
        help="Declare a complete comparable snapshot; required for missing detection and rejected when target validation fails.",
    )
    args = parser.parse_args()

    config = target_config(args.target)
    raw = args.source.read_bytes()
    payload = json.loads(raw.decode("utf-8"))
    items = payload.get("items")
    if not isinstance(items, list):
        raise SystemExit("Export does not contain an items array")

    validation = validate_export_target(config, payload)
    if args.complete and not validation["completeEligible"]:
        details = "; ".join(warning["message"] for warning in validation["warnings"]) or "target validation failed"
        raise SystemExit(f"Refusing --complete snapshot: {details}")

    observed = str(payload.get("exportedAt") or now_iso())
    archived, sha = preserve_raw(args.target, raw, observed)
    folder = ROOT / "data" / args.target
    folder.mkdir(parents=True, exist_ok=True)
    state_path = folder / "state.json.gz"
    legacy = folder / "state.json"
    state = read_json(state_path) if state_path.exists() else (read_json(legacy) if legacy.exists() else initial_state(args.target))

    # Uploading the same raw export twice must not create another observation or
    # advance missing/recheck state. The immutable raw artifact is already
    # content-addressed by SHA, so duplicate ingestion is a clean no-op.
    if any(snapshot.get("rawSha256") == sha for snapshot in state.get("snapshots", [])):
        print(f"Duplicate snapshot SHA {sha}; already ingested for target {args.target}. No state change made.")
        return

    normalized = []
    for item in items:
        if not isinstance(item, dict):
            continue
        base = normalize_item(item, observed)
        normalized.append(enrich_normalized(item, base, observed))

    crawl_meta = payload.get("crawl") if isinstance(payload.get("crawl"), dict) else {}
    meta = {
        "sourceFile": archived.relative_to(ROOT).as_posix(),
        "rawSha256": sha,
        "exportSchemaVersion": payload.get("schemaVersion"),
        "exportedAt": observed,
        "targetAuthor": payload.get("targetAuthor", ""),
        "crawlScope": payload.get("crawlScope", ""),
        "declaredItemCount": payload.get("itemCount"),
        "collectionLimit": payload.get("collectionLimit", {}),
        "crawl": crawl_meta,
        "crawlerVersion": crawl_meta.get("crawlerVersion", payload.get("crawlerVersion", "")),
        "reachedHistoricalStart": crawl_meta.get("reachedHistoricalStart"),
        "completionReason": crawl_meta.get("completionReason", ""),
        "coverageMode": "complete" if args.complete else "partial",
        "targetValidation": validation,
    }
    state = apply_coverage_snapshot(
        state,
        normalized,
        observed_at=observed,
        snapshot_meta=meta,
        complete=args.complete,
        target_config=config,
    )
    write_json_gz(state_path, state)
    print(json.dumps(summary(state), indent=2))
    latest_snapshot = state.get("snapshots", [])[-1] if state.get("snapshots") else {}
    if latest_snapshot.get("coverageStart"):
        print(
            "Coverage window: "
            f"{latest_snapshot['coverageStart']} through {latest_snapshot['coverageEnd']} | "
            f"eligible prior entities={latest_snapshot.get('coverageEligiblePriorEntities', 0)} | "
            f"unknown-date prior entities={latest_snapshot.get('coverageUnknownDatePriorEntities', 0)}"
        )
    for warning in validation["warnings"]:
        print(f"WARNING [{warning['code']}]: {warning['message']}")
    if not args.complete:
        print("Missing-item detection was NOT run. This snapshot is stored as a partial observation.")


if __name__ == "__main__":
    main()
