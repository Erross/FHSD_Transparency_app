"""Core normalization and diff logic for the public archive.

Observation and attribution are deliberately separate: a later crawl can show
that an entity was not observed; it cannot, by itself, establish who removed it
or why.
"""
from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Iterable
from urllib.parse import parse_qs, urlparse

STATE_SCHEMA_VERSION = 1


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def normalize_space(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def digest(value: str, length: int = 24) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:length]


def _id_from_permalink(url: str, key: str) -> str:
    if not url:
        return ""
    try:
        values = parse_qs(urlparse(url).query).get(key, [])
        return values[0] if values else ""
    except ValueError:
        return ""


def resolve_post_id(item: dict[str, Any]) -> str:
    post_id = normalize_space(item.get("postId") or item.get("storyFbid"))
    if post_id:
        return post_id
    for candidate in (item.get("parentPostPermalink"), item.get("permalink")):
        candidate = normalize_space(candidate)
        for key in ("story_fbid", "fbid"):
            post_id = _id_from_permalink(candidate, key)
            if post_id:
                return post_id
    return ""


def entity_id(item: dict[str, Any]) -> str:
    item_type = normalize_space(item.get("itemType") or "item").lower()
    if item_type == "post":
        post_id = resolve_post_id(item)
        if post_id:
            return f"post:{post_id}"
        permalink = normalize_space(item.get("permalink") or item.get("parentPostPermalink"))
        if permalink:
            return f"post:url:{digest(permalink)}"
    else:
        comment_id = normalize_space(item.get("commentId") or item.get("replyCommentId"))
        if comment_id:
            return f"comment:{comment_id}"
        permalink = normalize_space(item.get("permalink"))
        if permalink and ("comment_id=" in permalink or "reply_comment_id=" in permalink):
            return f"comment:url:{digest(permalink)}"

    source_key = normalize_space(item.get("entityKey"))
    if source_key:
        return f"{item_type}:source:{digest(source_key)}"

    fingerprint = "|".join(
        [
            item_type,
            normalize_space(item.get("author")),
            normalize_space(item.get("timestampExact") or item.get("timestampText")),
            normalize_space(item.get("parentPostPermalink")),
            normalize_space(item.get("bodyText") or item.get("text")),
        ]
    )
    return f"{item_type}:fp:{digest(fingerprint)}"


def identity_quality(item: dict[str, Any]) -> str:
    item_type = normalize_space(item.get("itemType") or "item").lower()
    if item_type == "post" and resolve_post_id(item):
        return "strong"
    if item_type != "post" and normalize_space(item.get("commentId") or item.get("replyCommentId")):
        return "strong"
    if normalize_space(item.get("permalink") or item.get("parentPostPermalink")):
        return "medium"
    return "weak"


def parent_entity_id(item: dict[str, Any]) -> str:
    if normalize_space(item.get("itemType")).lower() == "post":
        return ""
    post_id = resolve_post_id(item)
    if post_id:
        return f"post:{post_id}"
    parent_link = normalize_space(item.get("parentPostPermalink"))
    return f"post:url:{digest(parent_link)}" if parent_link else ""


def normalize_item(item: dict[str, Any], observed_at: str) -> dict[str, Any]:
    text = normalize_space(item.get("bodyText") or item.get("text"))
    return {
        "id": entity_id(item),
        "identityQuality": identity_quality(item),
        "itemType": normalize_space(item.get("itemType") or "item").lower(),
        "author": normalize_space(item.get("author")),
        "text": text,
        "textHash": digest(text, 64),
        "timestampText": normalize_space(item.get("timestampText")),
        "timestampExact": normalize_space(item.get("timestampExact")),
        "permalink": normalize_space(item.get("permalink")),
        "parentPostPermalink": normalize_space(item.get("parentPostPermalink")),
        "parentId": parent_entity_id(item),
        "postId": resolve_post_id(item),
        "commentId": normalize_space(item.get("commentId") or item.get("replyCommentId")),
        "parentCommentId": normalize_space(item.get("parentCommentId")),
        "capturedAt": normalize_space(item.get("capturedAt")) or observed_at,
        "rawEntityKey": normalize_space(item.get("entityKey")),
        "rawId": normalize_space(item.get("id")),
    }


def initial_state(target_id: str) -> dict[str, Any]:
    return {"schemaVersion": STATE_SCHEMA_VERSION, "targetId": target_id, "entities": {}, "events": [], "snapshots": []}


def _version(record: dict[str, Any], observed_at: str) -> dict[str, Any]:
    return {
        "text": record["text"],
        "textHash": record["textHash"],
        "firstSeen": observed_at,
        "lastSeen": observed_at,
        "timestampText": record.get("timestampText", ""),
        "timestampExact": record.get("timestampExact", ""),
        "permalink": record.get("permalink", ""),
    }


def _event(kind: str, observed_at: str, record: dict[str, Any], **extra: Any) -> dict[str, Any]:
    event = {
        "type": kind,
        "observedAt": observed_at,
        "entityId": record.get("id", ""),
        "itemType": record.get("itemType", ""),
        "author": record.get("author", ""),
        "parentId": record.get("parentId", ""),
        "permalink": record.get("permalink", ""),
    }
    event.update(extra)
    return event


def _richer(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    fields = ("text", "permalink", "timestampExact", "timestampText", "author", "commentId")
    left_score = sum(bool(left.get(key)) for key in fields) + len(left.get("text", "")) / 10000
    right_score = sum(bool(right.get(key)) for key in fields) + len(right.get("text", "")) / 10000
    return right if right_score > left_score else left


def apply_snapshot(
    state: dict[str, Any],
    records: Iterable[dict[str, Any]],
    *,
    observed_at: str,
    snapshot_meta: dict[str, Any],
    complete: bool,
    target_config: dict[str, Any],
) -> dict[str, Any]:
    out = deepcopy(state)
    entities = out.setdefault("entities", {})
    events = out.setdefault("events", [])

    current: dict[str, dict[str, Any]] = {}
    input_count = 0
    for record in records:
        input_count += 1
        rid = record["id"]
        current[rid] = _richer(current[rid], record) if rid in current else record

    seen_ids = set(current)
    prior_ids = set(entities)
    is_baseline = not prior_ids and not out.get("snapshots")

    for rid, record in current.items():
        existing = entities.get(rid)
        if existing is None:
            entities[rid] = {
                **record,
                "firstSeen": observed_at,
                "lastSeen": observed_at,
                "status": "active",
                "missingCount": 0,
                "versions": [_version(record, observed_at)],
                "observationCount": 1,
            }
            if not is_baseline:
                events.append(_event("new", observed_at, record, text=record["text"]))
            continue

        prior_status = existing.get("status", "active")
        if prior_status in {"missing_once", "missing_recheck", "confirmed_unavailable"}:
            existing["status"] = "reappeared"
            events.append(_event("reappeared", observed_at, record, text=record["text"], priorStatus=prior_status))
        else:
            existing["status"] = "active"

        versions = existing.setdefault("versions", [])
        if not versions or versions[-1].get("textHash") != record["textHash"]:
            before = versions[-1]["text"] if versions else ""
            versions.append(_version(record, observed_at))
            events.append(_event("edited", observed_at, record, beforeText=before, afterText=record["text"]))
        elif versions:
            versions[-1]["lastSeen"] = observed_at

        for key, value in record.items():
            if value not in (None, "") or not existing.get(key):
                existing[key] = value
        existing["lastSeen"] = observed_at
        existing["missingCount"] = 0
        existing["observationCount"] = int(existing.get("observationCount", 0)) + 1

    crawl_cfg = target_config.get("crawl", {})
    allow_missing = bool(complete)
    if allow_missing:
        newly_absent: list[dict[str, Any]] = []
        for rid in sorted(prior_ids - seen_ids):
            existing = entities[rid]
            if existing.get("status") == "confirmed_unavailable":
                existing["missingCount"] = int(existing.get("missingCount", 0)) + 1
                continue
            count = int(existing.get("missingCount", 0)) + 1
            existing["missingCount"] = count
            before = existing.get("status", "active")
            after = "missing_once" if count == 1 else "missing_recheck"
            existing["status"] = after
            if before != after:
                events.append(
                    _event(
                        after,
                        observed_at,
                        {**existing, "id": rid},
                        lastSeen=existing.get("lastSeen", ""),
                        missingCount=count,
                        text=existing.get("text", ""),
                    )
                )
            if count == 1:
                newly_absent.append(existing)

        absolute = max(1, int(crawl_cfg.get("bulkMissingAbsoluteThreshold", 5)))
        ratio_threshold = float(crawl_cfg.get("bulkMissingRatioThreshold", 0.1))
        prior_total = max(1, len(prior_ids))
        if len(newly_absent) >= absolute and len(newly_absent) / prior_total >= ratio_threshold:
            events.append(
                {
                    "type": "bulk_missing",
                    "observedAt": observed_at,
                    "count": len(newly_absent),
                    "priorEntityCount": len(prior_ids),
                    "ratio": round(len(newly_absent) / prior_total, 4),
                    "entityIds": [entity["id"] for entity in newly_absent],
                    "note": "Previously observed entities were absent from this complete snapshot; causation is not attributed.",
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
                        "note": "A cluster of previously observed comments/replies in one thread was absent from this complete snapshot; causation is not attributed.",
                    }
                )

    out.setdefault("snapshots", []).append(
        {
            **snapshot_meta,
            "observedAt": observed_at,
            "complete": bool(complete),
            "baseline": bool(is_baseline),
            "inputItemCount": input_count,
            "uniqueEntityCount": len(current),
            "duplicateEntityCount": input_count - len(current),
            "missingDetectionApplied": allow_missing,
        }
    )
    return out


def summary(state: dict[str, Any]) -> dict[str, int]:
    entities = list(state.get("entities", {}).values())
    return {
        "entities": len(entities),
        "posts": sum(e.get("itemType") == "post" for e in entities),
        "comments": sum(e.get("itemType") != "post" for e in entities),
        "active": sum(e.get("status") in {"active", "reappeared"} for e in entities),
        "missing": sum(e.get("status") in {"missing_once", "missing_recheck"} for e in entities),
        "confirmedUnavailable": sum(e.get("status") == "confirmed_unavailable" for e in entities),
        "editedEntities": sum(len(e.get("versions", [])) > 1 for e in entities),
        "events": len(state.get("events", [])),
        "snapshots": len(state.get("snapshots", [])),
    }


def dumps(data: Any) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"
