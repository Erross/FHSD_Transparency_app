"""Derive per-post Facebook reported-vs-visible comment metrics from raw crawler exports.

The crawler's headline count is treated as a reported count only. A lower
visible count does not establish deletion or its cause; it records what the
crawl could actually see after exhausting the visible discussion surface.
"""
from __future__ import annotations

import gzip
import json
import re
from pathlib import Path
from typing import Any


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _thread_keys(thread: dict[str, Any]) -> set[str]:
    keys: set[str] = set()
    for field in ("threadKey", "postEntityKey", "postId", "permalink"):
        value = _clean(thread.get(field))
        if value:
            keys.add(value)
            if value.startswith("post:id:"):
                keys.add(value[len("post:id:"):])
    for value in thread.get("threadAliasesV11014", []) or []:
        value = _clean(value)
        if value:
            keys.add(value)
            if value.startswith("post:id:"):
                keys.add(value[len("post:id:"):])
    return keys


def _post_keys(post: dict[str, Any]) -> set[str]:
    keys: set[str] = set()
    for field in ("postId", "rawEntityKey", "rawId", "permalink", "parentPostPermalink"):
        value = _clean(post.get(field))
        if value:
            keys.add(value)
            if value.startswith("post:id:"):
                keys.add(value[len("post:id:"):])
    pid = _clean(post.get("postId"))
    if pid:
        keys.add(f"post:id:{pid}")
    return keys


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


def latest_comment_visibility(
    root: Path,
    snapshots: list[dict[str, Any]],
    entities: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Return latest available per-post reported/visible metrics.

    We walk snapshots newest-first and take the first raw crawler export that
    contains threadMetadata. Metrics are attached only when a thread can be
    matched to an archived post by a stable ID, permalink, or source key.
    """
    payload: dict[str, Any] | None = None
    observed_at = ""
    for snapshot in snapshots:
        source_file = _clean(snapshot.get("sourceFile"))
        if not source_file:
            continue
        candidate = _read_raw_export(root, source_file)
        if candidate and isinstance(candidate.get("threadMetadata"), list):
            payload = candidate
            observed_at = _clean(candidate.get("exportedAt") or snapshot.get("observedAt"))
            break
    if payload is None:
        return {}

    post_rows = [entity for entity in entities if entity.get("itemType") == "post"]
    key_to_post: dict[str, str] = {}
    for post in post_rows:
        pid = _clean(post.get("id"))
        if not pid:
            continue
        for key in _post_keys(post):
            key_to_post.setdefault(key, pid)

    out: dict[str, dict[str, Any]] = {}
    for thread in payload.get("threadMetadata", []):
        if not isinstance(thread, dict):
            continue
        post_id = ""
        for key in _thread_keys(thread):
            post_id = key_to_post.get(key, "")
            if post_id:
                break
        if not post_id:
            continue

        reported = max(
            int(thread.get("reportedCommentCount") or 0),
            int(thread.get("facebookDisplayedCommentCount") or 0),
            int(thread.get("expectedDisplayedCommentCount") or 0),
        )
        visible = max(
            int(thread.get("visibleCommentCount") or 0),
            int(thread.get("capturedCommentCount") or 0),
        )
        gap = max(0, reported - visible)
        current = out.get(post_id)
        row = {
            "reported": reported,
            "visible": visible,
            "gap": gap,
            "status": _clean(thread.get("completionStatus") or thread.get("status")),
            "observedAt": observed_at,
            "interpretation": (
                "Facebook reports more comments than were visible to this crawl. "
                "Deletion, hiding, moderation, privacy settings, or other visibility limits may explain the difference; the archive does not infer a cause."
                if gap > 0
                else "Facebook's reported count does not exceed the comments visible to this crawl."
            ),
        }
        if current is None or (row["visible"], row["reported"]) > (current["visible"], current["reported"]):
            out[post_id] = row
    return out
