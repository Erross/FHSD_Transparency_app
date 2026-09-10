"""Recover post publication chronology from preserved raw crawler exports.

Normalized archive state intentionally stores a compact record and older ingests
may not contain the crawler's dateEvidence object.  The immutable raw snapshots
still do.  This module rehydrates publication evidence at site-build time so a
Facebook label such as "2 hours ago" is useful for chronology without pretending
that Facebook supplied an exact timestamp.
"""
from __future__ import annotations

import gzip
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _iso_from_ms(value: Any) -> str:
    try:
        ms = int(value)
    except (TypeError, ValueError):
        return ""
    if ms <= 0:
        return ""
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def _read_raw_export(root: Path, source_file: str) -> dict[str, Any] | None:
    path = root / source_file
    if not path.exists():
        return None
    try:
        if path.suffix == ".gz":
            with gzip.open(path, "rt", encoding="utf-8") as handle:
                return json.load(handle)
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None


def _id_from_url(url: str) -> str:
    try:
        parsed = urlparse(url or "")
        query = parse_qs(parsed.query)
        return _clean((query.get("story_fbid") or query.get("fbid") or [""])[0])
    except (ValueError, IndexError):
        return ""


def _raw_post_keys(item: dict[str, Any]) -> set[str]:
    keys: set[str] = set()
    for field in ("postId", "storyFbid", "wrapperPostId", "entityKey", "id"):
        value = _clean(item.get(field))
        if value:
            keys.add(value)
            if value.startswith("post:id:"):
                keys.add(value[len("post:id:"):])
    for field in ("permalink", "parentPostPermalink", "wrapperPermalink"):
        value = _clean(item.get(field))
        if value:
            keys.add(value)
            url_id = _id_from_url(value)
            if url_id:
                keys.add(url_id)
    return keys


def _entity_keys(entity: dict[str, Any]) -> set[str]:
    keys: set[str] = set()
    for field in ("postId", "rawEntityKey", "rawId", "id", "permalink", "parentPostPermalink"):
        value = _clean(entity.get(field))
        if value:
            keys.add(value)
            if value.startswith("post:"):
                keys.add(value.split(":", 1)[1])
            if value.startswith("post:id:"):
                keys.add(value[len("post:id:"):])
            url_id = _id_from_url(value)
            if url_id:
                keys.add(url_id)
    return keys


def _evidence_row(item: dict[str, Any], observed_at: str) -> dict[str, Any] | None:
    exact = _clean(item.get("publishedAt"))
    if exact:
        return {
            "publishedAt": exact,
            "publishedAtPrecision": _clean(item.get("publishedAtPrecision")) or "exact",
            "publishedAtSource": _clean(item.get("publishedAtSource")) or "crawler",
            "publicationEvidenceObservedAt": observed_at,
        }

    evidence = item.get("dateEvidence") if isinstance(item.get("dateEvidence"), dict) else {}
    lower = _clean(item.get("publishedAtLowerBound")) or _iso_from_ms(evidence.get("lowerBoundMs"))
    upper = _clean(item.get("publishedAtUpperBound")) or _iso_from_ms(evidence.get("upperBoundMs"))
    if not lower and not upper:
        return None

    source = _clean(evidence.get("source") or item.get("publishedAtSource")) or "crawler-date-evidence"
    label = _clean(evidence.get("label") or item.get("timestampText"))
    precision = _clean(evidence.get("precision") or item.get("publishedAtPrecision")) or "bounded"

    # For Facebook relative labels ("2 hours ago", "15 hours ago", etc.), the
    # crawler's upper bound is reference-time minus the displayed age.  It is a
    # natural sortable estimate while lower/upper retain the honest rounding
    # interval.  Do not promote it to publishedAt/exact.
    estimate = upper or lower
    return {
        "publishedAtEstimated": estimate,
        "publishedAtLowerBound": lower,
        "publishedAtUpperBound": upper,
        "publishedAtEstimateSource": source,
        "publishedAtPrecision": precision,
        "publicationEvidenceLabel": label,
        "publicationEvidenceObservedAt": observed_at,
    }


def enrich_publication_evidence(
    root: Path,
    snapshots: list[dict[str, Any]],
    entities: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return entities enriched with the newest useful raw post date evidence."""
    posts = [entity for entity in entities if entity.get("itemType") == "post"]
    key_to_entity: dict[str, str] = {}
    for post in posts:
        entity_id = _clean(post.get("id"))
        if not entity_id:
            continue
        for key in _entity_keys(post):
            key_to_entity.setdefault(key, entity_id)

    recovered: dict[str, dict[str, Any]] = {}
    for snapshot in snapshots:  # caller supplies newest first
        source_file = _clean(snapshot.get("sourceFile"))
        if not source_file:
            continue
        payload = _read_raw_export(root, source_file)
        if not payload:
            continue
        observed_at = _clean(payload.get("exportedAt") or snapshot.get("observedAt"))
        for item in payload.get("items", []) or []:
            if not isinstance(item, dict) or _clean(item.get("itemType")).lower() != "post":
                continue
            entity_id = ""
            for key in _raw_post_keys(item):
                entity_id = key_to_entity.get(key, "")
                if entity_id:
                    break
            if not entity_id or entity_id in recovered:
                continue
            row = _evidence_row(item, observed_at)
            if row:
                recovered[entity_id] = row

    out: list[dict[str, Any]] = []
    for entity in entities:
        row = recovered.get(_clean(entity.get("id")))
        if not row:
            out.append(entity)
            continue
        enriched = dict(entity)
        # Raw crawler evidence is stronger than build-time comment inference,
        # but never replace an exact publication timestamp already in state.
        if not _clean(enriched.get("publishedAt")):
            for key, value in row.items():
                if value not in (None, ""):
                    enriched[key] = value
        out.append(enriched)
    return out
