"""Apply explicit mixed-target repair manifests.

This is intentionally evidence-preserving: the original raw artifact remains in
its original target archive. Strongly foreign page-owned records are removed from
the declared target's canonical state, copied into a clean partial export for the
foreign target, and the public indexes are rebuilt.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from pathlib import Path
from typing import Any

from .build_site import main as build_site
from .core import initial_state, normalize_item, normalize_space, summary
from .coverage import apply_coverage_snapshot
from .enrich import enrich_normalized
from .ingest import preserve_raw, target_config, validate_export_target
from .io_utils import read_json, write_json_gz
from .ownership import split_obvious_foreign_target_items
from .relationships import repair_parent_relationships
from .route_snapshot import load_target_configs

ROOT = Path(__file__).resolve().parents[1]


def _read_raw(path: Path) -> tuple[bytes, dict[str, Any]]:
    raw = gzip.decompress(path.read_bytes()) if path.suffix == ".gz" else path.read_bytes()
    return raw, json.loads(raw.decode("utf-8"))


def _norm(value: Any) -> str:
    return normalize_space(value).casefold()


def _normalized_records(items: list[dict[str, Any]], observed: str):
    normalized = [enrich_normalized(item, normalize_item(item, observed), observed) for item in items]
    return repair_parent_relationships(normalized)


def _sanitize_source_state(
    source_target: str,
    raw_sha: str,
    foreign_items: list[dict[str, Any]],
    observed: str,
    foreign_target: str,
) -> dict[str, int]:
    state_path = ROOT / "data" / source_target / "state.json.gz"
    if not state_path.exists():
        return {"removedEntities": 0, "removedEvents": 0}
    state = read_json(state_path)

    # Derive canonical IDs using the same normalizer used at ingest. That lets us
    # surgically remove only records proven to have come from the foreign page,
    # while preserving legitimate comments made *by* that page on the source page.
    foreign_normalized, _ = _normalized_records(foreign_items, observed)
    foreign_ids = {record.get("id", "") for record in foreign_normalized if record.get("id")}
    foreign_post_ids = {
        record.get("id", "")
        for record in foreign_normalized
        if record.get("itemType") == "post" and record.get("id")
    }

    entities = state.get("entities", {})
    remove_ids = set(foreign_ids)
    # Also remove any previously ingested child records bound to a proven foreign
    # post, even if that child was not present in the repair export itself.
    for entity_id, entity in entities.items():
        if entity.get("itemType") != "post" and entity.get("parentId") in foreign_post_ids:
            remove_ids.add(entity_id)

    before_entities = len(entities)
    state["entities"] = {entity_id: entity for entity_id, entity in entities.items() if entity_id not in remove_ids}

    events = state.get("events", [])
    before_events = len(events)
    state["events"] = [
        event
        for event in events
        if event.get("entityId") not in remove_ids and event.get("parentId") not in foreign_post_ids
    ]

    for snapshot in state.get("snapshots", []):
        if snapshot.get("rawSha256") == raw_sha:
            snapshot["mixedTargetRepair"] = {
                "foreignTarget": foreign_target,
                "foreignItemsRecovered": len(foreign_items),
                "canonicalEntitiesRemoved": before_entities - len(state["entities"]),
                "note": "Original raw evidence retained; canonical state excludes records strongly owned by another configured Facebook page.",
            }

    write_json_gz(state_path, state)
    return {
        "removedEntities": before_entities - len(state["entities"]),
        "removedEvents": before_events - len(state["events"]),
    }


def _ingest_recovered_target(
    foreign_target: str,
    source_target: str,
    source_raw: Path,
    source_sha: str,
    payload: dict[str, Any],
    foreign_items: list[dict[str, Any]],
) -> dict[str, Any]:
    config = target_config(foreign_target)
    observed = str(payload.get("exportedAt") or "")

    recovered = dict(payload)
    recovered["targetAuthor"] = config["displayName"]
    recovered["targetId"] = foreign_target
    recovered["items"] = foreign_items
    recovered["itemCount"] = len(foreign_items)
    recovered["collectionLimit"] = {"mode": "recovered"}
    recovered["crawlScope"] = "page"
    recovered["crawl"] = {
        "crawlerVersion": (payload.get("crawl") or {}).get("crawlerVersion", payload.get("crawlerVersion", "")),
        "completionReason": "recovered_from_mixed_target_export",
        "reachedHistoricalStart": False,
        "requestedMode": "recovered",
        "repairSourceTarget": source_target,
        "repairSourceRaw": source_raw.relative_to(ROOT).as_posix(),
        "repairSourceSha256": source_sha,
        "recoveryNote": "Foreign-page records recovered from an immutable mixed export; this is a partial baseline and does not establish absence of uncaptured records.",
    }
    # Top-level source identity from the original School Watchlist crawl would
    # conflict with the Blair target. Remove it from the derived clean export.
    for key in ("profileId", "pageUrl", "sourceUrl", "target"):
        recovered.pop(key, None)

    recovered_raw = (json.dumps(recovered, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
    archived, recovered_sha = preserve_raw(foreign_target, recovered_raw, observed)

    state_path = ROOT / "data" / foreign_target / "state.json.gz"
    state = read_json(state_path) if state_path.exists() else initial_state(foreign_target)
    if any(snapshot.get("rawSha256") == recovered_sha for snapshot in state.get("snapshots", [])):
        return {"duplicate": True, "rawSha256": recovered_sha, "archive": archived.relative_to(ROOT).as_posix()}

    normalized, relationship_diagnostics = _normalized_records(foreign_items, observed)
    validation = validate_export_target(config, recovered)
    snapshot_meta = {
        "sourceFile": archived.relative_to(ROOT).as_posix(),
        "rawSha256": recovered_sha,
        "exportSchemaVersion": recovered.get("schemaVersion"),
        "exportedAt": observed,
        "targetAuthor": recovered.get("targetAuthor", ""),
        "crawlScope": recovered.get("crawlScope", ""),
        "declaredItemCount": len(foreign_items),
        "collectionLimit": recovered.get("collectionLimit", {}),
        "crawl": recovered.get("crawl", {}),
        "crawlerVersion": recovered.get("crawl", {}).get("crawlerVersion", ""),
        "reachedHistoricalStart": False,
        "completionReason": "recovered_from_mixed_target_export",
        "coverageMode": "partial",
        "targetValidation": validation,
        "relationshipDiagnostics": relationship_diagnostics,
        "recoveredFrom": {
            "target": source_target,
            "rawSha256": source_sha,
            "rawPath": source_raw.relative_to(ROOT).as_posix(),
        },
    }
    state = apply_coverage_snapshot(
        state,
        normalized,
        observed_at=observed,
        snapshot_meta=snapshot_meta,
        complete=False,
        target_config=config,
    )
    write_json_gz(state_path, state)
    return {
        "duplicate": False,
        "rawSha256": recovered_sha,
        "archive": archived.relative_to(ROOT).as_posix(),
        "summary": summary(state),
        "relationships": relationship_diagnostics,
    }


def apply_manifest(path: Path) -> dict[str, Any]:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    source_target = str(manifest["sourceTarget"])
    foreign_target = str(manifest["foreignTarget"])
    source_raw = ROOT / str(manifest["sourceRaw"])
    expected_sha = str(manifest.get("sourceRawSha256") or "")

    raw, payload = _read_raw(source_raw)
    source_sha = hashlib.sha256(raw).hexdigest()
    if expected_sha and source_sha != expected_sha:
        raise SystemExit(f"Repair source SHA mismatch: expected {expected_sha}, got {source_sha}")

    configs = load_target_configs(ROOT)
    source_config = target_config(source_target)
    items = payload.get("items") if isinstance(payload.get("items"), list) else []
    kept, foreign, diagnostics = split_obvious_foreign_target_items(items, source_config, configs)
    if not foreign:
        raise SystemExit("Repair manifest found no strongly foreign records; refusing to mutate archive state.")

    # Ensure every recovered record resolves specifically to the requested foreign
    # target. The helper's diagnostics make an accidental multi-page split visible.
    unexpected = {
        target: count
        for target, count in diagnostics.get("foreignByTarget", {}).items()
        if target != foreign_target
    }
    if unexpected:
        raise SystemExit(f"Repair also matched unexpected targets: {unexpected}")

    observed = str(payload.get("exportedAt") or "")
    source_repair = _sanitize_source_state(
        source_target,
        source_sha,
        foreign,
        observed,
        foreign_target,
    )
    foreign_result = _ingest_recovered_target(
        foreign_target,
        source_target,
        source_raw,
        source_sha,
        payload,
        foreign,
    )
    build_site()

    result = {
        "manifest": path.relative_to(ROOT).as_posix(),
        "sourceTarget": source_target,
        "foreignTarget": foreign_target,
        "sourceRawSha256": source_sha,
        "partition": diagnostics,
        "sourceRepair": source_repair,
        "foreignResult": foreign_result,
        "sourceItemsRetained": len(kept),
    }
    print(json.dumps(result, indent=2))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path, nargs="?", help="Repair manifest JSON. If omitted, process repairs/*.json.")
    args = parser.parse_args()
    paths = [args.manifest] if args.manifest else sorted((ROOT / "repairs").glob("*.json"))
    if not paths:
        print("No repair manifests found.")
        return
    for path in paths:
        apply_manifest(path if path.is_absolute() else ROOT / path)


if __name__ == "__main__":
    main()
