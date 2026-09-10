"""Recover post chronology from preserved crawler exports.

Facebook relative labels such as "2 hours ago" are useful date evidence.  We
retain their bounded interval and use the displayed-age subtraction as a
sortable estimate without claiming an exact publication timestamp.
"""
from __future__ import annotations

import gzip
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

_RELATIVE = re.compile(r"^\s*(\d+)\s*(?:hour|hours|hr|hrs|h|day|days|d|minute|minutes|min|mins|m)\s+ago\s*$", re.I)


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


def _parse_iso(value: Any) -> datetime | None:
    text = _clean(value)
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except ValueError:
        return None


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
        query = parse_qs(urlparse(url or "").query)
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
        if not value:
            continue
        keys.add(value)
        if value.startswith("post:id:"):
            keys.add(value[len("post:id:"):])
        elif value.startswith("post:"):
            keys.add(value[len("post:"):])
        url_id = _id_from_url(value)
        if url_id:
            keys.add(url_id)
    return keys


def _relative_estimate(label: str, reference: Any) -> str:
    """Return reference time minus a Facebook displayed relative age."""
    match = _RELATIVE.match(label or "")
    ref = _parse_iso(reference)
    if not match or not ref:
        return ""
    amount = int(match.group(1))
    unit = re.sub(r"[^a-z]", "", match.group(0).lower().split("ago")[0]).strip()
    # Unit is easier/safer to infer from the original label than the normalized text.
    lower_label = label.lower()
    if "hour" in lower_label or re.search(r"\b\d+\s*h\s+ago", lower_label):
        delta = timedelta(hours=amount)
    elif "day" in lower_label or re.search(r"\b\d+\s*d\s+ago", lower_label):
        delta = timedelta(days=amount)
    else:
        delta = timedelta(minutes=amount)
    return (ref - delta).isoformat().replace("+00:00", "Z")


def evidence_from_item(item: dict[str, Any], observed_at: str) -> dict[str, Any] | None:
    exact = _clean(item.get("publishedAt"))
    if exact:
        return {
            "publishedAt": exact,
            "publishedAtPrecision": _clean(item.get("publishedAtPrecision")) or "exact",
            "publishedAtSource": _clean(item.get("publishedAtSource")) or "crawler",
            "publicationEvidenceObservedAt": observed_at,
        }

    evidence = item.get("dateEvidence") if isinstance(item.get("dateEvidence"), dict) else {}
    label = _clean(evidence.get("label") or item.get("timestampText"))
    lower = _clean(item.get("publishedAtLowerBound")) or _iso_from_ms(evidence.get("lowerBoundMs"))
    upper = _clean(item.get("publishedAtUpperBound")) or _iso_from_ms(evidence.get("upperBoundMs"))
    reference = _iso_from_ms(evidence.get("referenceMs")) or observed_at or _clean(item.get("capturedAt"))
    estimate = _relative_estimate(label, reference) if label else ""
    if not estimate:
        estimate = upper or lower
    if not estimate and not lower and not upper:
        return None

    return {
        "publishedAtEstimated": estimate,
        "publishedAtLowerBound": lower,
        "publishedAtUpperBound": upper,
        "publishedAtEstimateSource": _clean(evidence.get("source") or item.get("publishedAtSource")) or "crawler-date-evidence",
        "publishedAtPrecision": _clean(evidence.get("precision") or item.get("publishedAtPrecision")) or "bounded",
        "publicationEvidenceLabel": label,
        "publicationEvidenceObservedAt": reference or observed_at,
    }


def _candidate_raw_files(root: Path, snapshots: list[dict[str, Any]]) -> list[str]:
    """Use state references first, then scan the same raw archive directory.

    The directory fallback repairs older state whose snapshot metadata is
    incomplete while preserving newest-first behavior.
    """
    files: list[str] = []
    raw_dirs: set[Path] = set()
    for snapshot in snapshots:
        source = _clean(snapshot.get("sourceFile"))
        if source:
            files.append(source)
            raw_dirs.add((root / source).parent)
    for folder in raw_dirs:
        if folder.exists():
            for path in sorted(folder.glob("*.json.gz"), reverse=True):
                rel = path.relative_to(root).as_posix()
                if rel not in files:
                    files.append(rel)
    return files


def enrich_publication_evidence(root: Path, snapshots: list[dict[str, Any]], entities: list[dict[str, Any]]) -> list[dict[str, Any]]:
    posts = [entity for entity in entities if entity.get("itemType") == "post"]
    key_to_entity: dict[str, str] = {}
    for post in posts:
        entity_id = _clean(post.get("id"))
        if entity_id:
            for key in _entity_keys(post):
                key_to_entity.setdefault(key, entity_id)

    recovered: dict[str, dict[str, Any]] = {}
    snapshot_observed = {_clean(s.get("sourceFile")): _clean(s.get("observedAt")) for s in snapshots}
    for source_file in _candidate_raw_files(root, snapshots):
        payload = _read_raw_export(root, source_file)
        if not payload:
            continue
        observed_at = _clean(payload.get("exportedAt") or snapshot_observed.get(source_file))
        for item in payload.get("items", []) or []:
            if not isinstance(item, dict) or _clean(item.get("itemType")).lower() != "post":
                continue
            entity_id = next((key_to_entity[k] for k in _raw_post_keys(item) if k in key_to_entity), "")
            if not entity_id or entity_id in recovered:
                continue
            row = evidence_from_item(item, observed_at)
            if row:
                recovered[entity_id] = row

    out: list[dict[str, Any]] = []
    for entity in entities:
        row = recovered.get(_clean(entity.get("id")))
        if not row or _clean(entity.get("publishedAt")):
            out.append(entity)
            continue
        enriched = dict(entity)
        for key, value in row.items():
            if value not in (None, ""):
                enriched[key] = value
        out.append(enriched)
    return out
