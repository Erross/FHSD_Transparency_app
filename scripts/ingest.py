"""Ingest one crawler export into the multi-target archive."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .core import apply_snapshot, initial_state, normalize_item, normalize_space, now_iso, summary
from .io_utils import read_json, write_json_gz, write_raw_gz

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


def _profile_id(url: str) -> str:
    try:
        parsed = urlparse(url or "")
        values = parse_qs(parsed.query).get("id", [])
        return values[0] if values else ""
    except ValueError:
        return ""


def validate_export_target(config: dict, payload: dict) -> dict:
    aliases = {normalize_space(value).casefold() for value in config.get("authorAliases", []) if normalize_space(value)}
    declared = normalize_space(payload.get("targetAuthor"))
    declared_match = not declared or declared.casefold() in aliases

    configured_profile_ids = {_profile_id(url) for url in config.get("sourceUrls", [])}
    configured_profile_ids.discard("")
    observed_profile_ids = set()
    for item in payload.get("items", []):
        if not isinstance(item, dict):
            continue
        observed_profile_ids.add(normalize_space(item.get("profileId")))
        observed_profile_ids.add(_profile_id(normalize_space(item.get("pageUrl"))))
    observed_profile_ids.discard("")
    source_match = not configured_profile_ids or bool(configured_profile_ids & observed_profile_ids)

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
        "configuredProfileIds": sorted(configured_profile_ids),
        "observedProfileIds": sorted(observed_profile_ids),
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

    normalized = [normalize_item(item, observed) for item in items if isinstance(item, dict)]
    meta = {
        "sourceFile": archived.relative_to(ROOT).as_posix(),
        "rawSha256": sha,
        "exportSchemaVersion": payload.get("schemaVersion"),
        "exportedAt": observed,
        "targetAuthor": payload.get("targetAuthor", ""),
        "declaredItemCount": payload.get("itemCount"),
        "collectionLimit": payload.get("collectionLimit", {}),
        "coverageMode": "complete" if args.complete else "partial",
        "targetValidation": validation,
    }
    state = apply_snapshot(
        state,
        normalized,
        observed_at=observed,
        snapshot_meta=meta,
        complete=args.complete,
        target_config=config,
    )
    write_json_gz(state_path, state)
    print(json.dumps(summary(state), indent=2))
    for warning in validation["warnings"]:
        print(f"WARNING [{warning['code']}]: {warning['message']}")
    if not args.complete:
        print("Missing-item detection was NOT run. This snapshot is stored as a partial observation.")


if __name__ == "__main__":
    main()
