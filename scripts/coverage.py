"""Date-coverage aware snapshot application.

A date-limited Facebook crawl is only evidence about entities that can be
placed inside that crawl's declared window. Items outside the window, or whose
content date cannot be resolved, must not become missing merely because they
were absent from the later export.
"""
from __future__ import annotations

import re
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterable

from .core import apply_snapshot, normalize_space

_MONTHS = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}
_ABSOLUTE = re.compile(
    r"^(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday\s+)?"
    r"(?P<day>\d{1,2})\s+(?P<month>[A-Za-z]+)\s+(?P<year>\d{4})"
    r"(?:\s+at\s+\d{1,2}:\d{2})?$",
    re.IGNORECASE,
)
_SHORT_RELATIVE = re.compile(r"^(?P<n>\d+)\s*(?P<unit>[smhdw])$", re.IGNORECASE)
_DAYS_AGO = re.compile(r"^(?P<n>\d+)\s+days?\s+ago$", re.IGNORECASE)


def _parse_iso_datetime(value: str) -> datetime | None:
    value = normalize_space(value)
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
    except ValueError:
        return None


def _parse_absolute_date(value: str) -> date | None:
    value = normalize_space(value)
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        pass
    match = _ABSOLUTE.match(value)
    if not match:
        return None
    month = _MONTHS.get(match.group("month").casefold())
    if not month:
        return None
    try:
        return date(int(match.group("year")), month, int(match.group("day")))
    except ValueError:
        return None


def resolve_content_date(entity: dict[str, Any]) -> tuple[date | None, str]:
    """Resolve an entity's content date without pretending unknown dates are known."""
    exact = _parse_absolute_date(normalize_space(entity.get("timestampExact")))
    if exact:
        return exact, "exact"

    timestamp_text = normalize_space(entity.get("timestampText"))
    absolute_text = _parse_absolute_date(timestamp_text)
    if absolute_text:
        return absolute_text, "absolute_text"

    reference = _parse_iso_datetime(
        normalize_space(entity.get("capturedAt") or entity.get("firstSeen") or entity.get("lastSeen"))
    )
    if not reference or not timestamp_text:
        return None, "unknown"

    lowered = timestamp_text.casefold()
    delta: timedelta | None = None
    if lowered in {"a day ago", "1 day ago", "yesterday"}:
        delta = timedelta(days=1)
    else:
        days = _DAYS_AGO.match(lowered)
        short = _SHORT_RELATIVE.match(lowered)
        if days:
            delta = timedelta(days=int(days.group("n")))
        elif short:
            n = int(short.group("n"))
            unit = short.group("unit").casefold()
            delta = {
                "s": timedelta(seconds=n),
                "m": timedelta(minutes=n),
                "h": timedelta(hours=n),
                "d": timedelta(days=n),
                "w": timedelta(weeks=n),
            }[unit]
    if delta is None:
        return None, "unknown"
    return (reference - delta).date(), "relative"


def declared_date_window(snapshot_meta: dict[str, Any], observed_at: str) -> tuple[date, date] | None:
    limit = snapshot_meta.get("collectionLimit") or {}
    if normalize_space(limit.get("mode")).casefold() != "date":
        return None
    start = _parse_absolute_date(normalize_space(limit.get("cutoffDate")))
    observed = _parse_iso_datetime(observed_at)
    if not start or not observed:
        return None
    return start, observed.date()


def _event(kind: str, observed_at: str, entity_id: str, entity: dict[str, Any], **extra: Any) -> dict[str, Any]:
    event = {
        "type": kind,
        "observedAt": observed_at,
        "entityId": entity_id,
        "itemType": entity.get("itemType", ""),
        "author": entity.get("author", ""),
        "parentId": entity.get("parentId", ""),
        "permalink": entity.get("permalink", ""),
    }
    event.update(extra)
    return event


def apply_coverage_snapshot(
    state: dict[str, Any],
    records: Iterable[dict[str, Any]],
    *,
    observed_at: str,
    snapshot_meta: dict[str, Any],
    complete: bool,
    target_config: dict[str, Any],
) -> dict[str, Any]:
    """Apply a snapshot, restricting negative inference to its date window."""
    window = declared_date_window(snapshot_meta, observed_at)
    if not complete or window is None:
        return apply_snapshot(
            state,
            records,
            observed_at=observed_at,
            snapshot_meta=snapshot_meta,
            complete=complete,
            target_config=target_config,
        )

    before = deepcopy(state)
    prior_ids = set(before.get("entities", {}))

    # Positive observations, edits, aliases, and reappearances are handled by the
    # core engine. We deliberately disable its global missing pass and apply the
    # narrower coverage-aware pass below.
    out = apply_snapshot(
        state,
        records,
        observed_at=observed_at,
        snapshot_meta=snapshot_meta,
        complete=False,
        target_config=target_config,
    )
    entities = out.setdefault("entities", {})
    events = out.setdefault("events", [])
    start, end = window

    eligible_ids: set[str] = set()
    unknown_date_ids: set[str] = set()
    outside_ids: set[str] = set()
    for rid in prior_ids:
        entity = before["entities"][rid]
        content_date, quality = resolve_content_date(entity)
        if content_date is None:
            unknown_date_ids.add(rid)
        elif start <= content_date <= end:
            eligible_ids.add(rid)
        else:
            outside_ids.add(rid)

    seen_prior_ids = {rid for rid in prior_ids if entities.get(rid, {}).get("lastSeen") == observed_at}
    absent_ids = eligible_ids - seen_prior_ids
    newly_absent: list[dict[str, Any]] = []

    for rid in sorted(absent_ids):
        entity = entities[rid]
        if entity.get("status") == "confirmed_unavailable":
            entity["missingCount"] = int(entity.get("missingCount", 0)) + 1
            continue
        count = int(entity.get("missingCount", 0)) + 1
        before_status = entity.get("status", "active")
        after = "missing_once" if count == 1 else "missing_recheck"
        entity["missingCount"] = count
        entity["status"] = after
        if before_status != after:
            events.append(
                _event(
                    after,
                    observed_at,
                    rid,
                    entity,
                    lastSeen=entity.get("lastSeen", ""),
                    missingCount=count,
                    text=entity.get("text", ""),
                    coverageStart=start.isoformat(),
                    coverageEnd=end.isoformat(),
                )
            )
        if count == 1:
            newly_absent.append(entity)

    crawl_cfg = target_config.get("crawl", {})
    absolute = max(1, int(crawl_cfg.get("bulkMissingAbsoluteThreshold", 5)))
    ratio_threshold = float(crawl_cfg.get("bulkMissingRatioThreshold", 0.1))
    eligible_total = max(1, len(eligible_ids))
    if len(newly_absent) >= absolute and len(newly_absent) / eligible_total >= ratio_threshold:
        events.append(
            {
                "type": "bulk_missing",
                "observedAt": observed_at,
                "count": len(newly_absent),
                "priorEntityCount": len(eligible_ids),
                "ratio": round(len(newly_absent) / eligible_total, 4),
                "entityIds": [entity["id"] for entity in newly_absent],
                "coverageStart": start.isoformat(),
                "coverageEnd": end.isoformat(),
                "note": "Previously observed entities dated inside this crawl's declared coverage window were absent; causation is not attributed.",
            }
        )

    thread_threshold = max(2, int(crawl_cfg.get("bulkThreadMissingAbsoluteThreshold", 3)))
    by_parent: dict[str, list[dict[str, Any]]] = {}
    for entity in newly_absent:
        parent_id = entity.get("parentId", "")
        if parent_id:
            by_parent.setdefault(parent_id, []).append(entity)
    for parent_id, group in sorted(by_parent.items()):
        if len(group) >= thread_threshold:
            events.append(
                {
                    "type": "bulk_missing_thread",
                    "observedAt": observed_at,
                    "parentId": parent_id,
                    "count": len(group),
                    "entityIds": [entity["id"] for entity in group],
                    "coverageStart": start.isoformat(),
                    "coverageEnd": end.isoformat(),
                    "note": "A cluster of previously observed comments/replies dated inside this crawl's declared coverage window was absent; causation is not attributed.",
                }
            )

    snapshot = out.setdefault("snapshots", [])[-1]
    snapshot["complete"] = True
    snapshot["coverageMode"] = "date_scoped_complete"
    snapshot["missingDetectionApplied"] = True
    snapshot["coverageStart"] = start.isoformat()
    snapshot["coverageEnd"] = end.isoformat()
    snapshot["coverageEligiblePriorEntities"] = len(eligible_ids)
    snapshot["coverageUnknownDatePriorEntities"] = len(unknown_date_ids)
    snapshot["coverageOutsidePriorEntities"] = len(outside_ids)
    snapshot["coverageAbsentEligibleEntities"] = len(absent_ids)
    return out
