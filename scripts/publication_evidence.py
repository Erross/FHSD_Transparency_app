"""Recover post chronology from preserved crawler exports.

Facebook relative labels such as "2 hours ago" are useful date evidence. We
retain a bounded interval and derive a sortable estimate from the crawl/capture
time without claiming Facebook supplied an exact publication timestamp.
"""
from __future__ import annotations

import gzip
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

_RELATIVE_SEARCH = re.compile(
    r"(?<!\w)(\d+)\s*(seconds?|secs?|s|minutes?|mins?|m|hours?|hrs?|h|days?|d|weeks?|w)\s*(?:ago)?(?!\w)",
    re.I,
)


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


def _relative_label(item: dict[str, Any], evidence: dict[str, Any]) -> str:
    """Recover Facebook's displayed age even when timestampText was blanked.

    Current crawler exports can preserve the visible label inside dateEvidence,
    but some older/edge captures only retain it in syntheticKey, e.g.
    `School Watchlist|2 hours ago|post text`. Search all safe observation fields.
    """
    direct = _clean(evidence.get("label") or item.get("timestampText"))
    if direct and _RELATIVE_SEARCH.search(direct):
        return _RELATIVE_SEARCH.search(direct).group(0).strip()
    for field in ("syntheticKey", "rawObservedText", "rawArticleText"):
        text = _clean(item.get(field))
        match = _RELATIVE_SEARCH.search(text)
        if match:
            return match.group(0).strip()
    return ""


def _relative_delta(label: str) -> tuple[timedelta, timedelta] | None:
    """Return displayed age and one-unit rounding width."""
    match = _RELATIVE_SEARCH.search(label or "")
    if not match:
        return None
    amount = int(match.group(1))
    unit = match.group(2).lower()
    if unit.startswith("s"):
        one = timedelta(seconds=1)
    elif unit.startswith("m"):
        one = timedelta(minutes=1)
    elif unit.startswith("h"):
        one = timedelta(hours=1)
    elif unit.startswith("d"):
        one = timedelta(days=1)
    else:
        one = timedelta(weeks=1)
    return one * amount, one


def _relative_bounds(label: str, reference: Any) -> tuple[str, str, str]:
    ref = _parse_iso(reference)
    parsed = _relative_delta(label)
    if not ref or not parsed:
        return "", "", ""
    age, rounding = parsed
    upper_dt = ref - age
    lower_dt = upper_dt - rounding
    estimate_dt = upper_dt
    to_iso = lambda dt: dt.isoformat().replace("+00:00", "Z")
    return to_iso(estimate_dt), to_iso(lower_dt), to_iso(upper_dt)


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
    label = _relative_label(item, evidence)

    # The per-item capture time is the best reference for a displayed relative
    # age. dateEvidence.referenceMs is equivalent when present. exportedAt is a
    # fallback only.
    reference = (
        _iso_from_ms(evidence.get("referenceMs"))
        or _clean(item.get("capturedAt"))
        or _clean(item.get("firstSeenAt"))
        or observed_at
    )

    lower = _clean(item.get("publishedAtLowerBound")) or _iso_from_ms(evidence.get("lowerBoundMs"))
    upper = _clean(item.get("publishedAtUpperBound")) or _iso_from_ms(evidence.get("upperBoundMs"))
    estimate = ""

    if label:
        derived_estimate, derived_lower, derived_upper = _relative_bounds(label, reference)
        estimate = derived_estimate
        lower = lower or derived_lower
        upper = upper or derived_upper

    if not estimate:
        estimate = upper or lower
    if not estimate and not lower and not upper:
        return None

    return {
        "publishedAtEstimated": estimate,
        "publishedAtLowerBound": lower,
        "publishedAtUpperBound": upper,
        "publishedAtEstimateSource": _clean(evidence.get("source") or item.get("publishedAtSource")) or "facebook-relative-label",
        "publishedAtPrecision": _clean(evidence.get("precision") or item.get("publishedAtPrecision")) or ("relative" if label else "bounded"),
        "publicationEvidenceLabel": label,
        "publicationEvidenceObservedAt": reference or observed_at,
    }


def _candidate_raw_files(root: Path, snapshots: list[dict[str, Any]]) -> list[str]:
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
