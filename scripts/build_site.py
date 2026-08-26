"""Build static JSON indexes consumed by the FHSD Transparency Archive."""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any

from .core import dumps, initial_state, normalize_space, summary
from .io_utils import read_json

ROOT = Path(__file__).resolve().parents[1]


def _activity_key(entity: dict[str, Any]) -> str:
    return normalize_space(
        entity.get("publishedAt")
        or entity.get("publishedDate")
        or entity.get("timestampExact")
        or entity.get("lastSeen")
        or entity.get("firstSeen")
    )


def _author_key(entity: dict[str, Any]) -> str:
    return normalize_space(entity.get("authorKey")) or f"name:{normalize_space(entity.get('author')).casefold()}"


def _author_index(entities: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[str, dict[str, Any]] = {}
    for entity in entities:
        key = _author_key(entity)
        if not key or key == "name:":
            continue
        author = groups.setdefault(
            key,
            {
                "key": key,
                "displayName": normalize_space(entity.get("authorDisplayName") or entity.get("author")) or "Unknown author",
                "profileUrl": normalize_space(entity.get("authorProfileUrl")),
                "profileId": normalize_space(entity.get("authorProfileId")),
                "posts": 0,
                "comments": 0,
                "latestActivity": "",
                "entityIds": [],
            },
        )
        if entity.get("itemType") == "post":
            author["posts"] += 1
        else:
            author["comments"] += 1
        author["entityIds"].append(entity.get("id", ""))
        activity = _activity_key(entity)
        if activity > author["latestActivity"]:
            author["latestActivity"] = activity
        if not author["profileUrl"] and entity.get("authorProfileUrl"):
            author["profileUrl"] = entity["authorProfileUrl"]
        if not author["profileId"] and entity.get("authorProfileId"):
            author["profileId"] = entity["authorProfileId"]
    return sorted(groups.values(), key=lambda a: (a["comments"], a["posts"], a["latestActivity"]), reverse=True)


def _discussion_counts(entities: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for entity in entities:
        if entity.get("itemType") == "post":
            continue
        parent = normalize_space(entity.get("parentId"))
        if parent:
            counts[parent] += 1
    return dict(counts)


def _latest_delta(events: list[dict[str, Any]], snapshots: list[dict[str, Any]]) -> dict[str, Any]:
    if not snapshots:
        return {"observedAt": "", "previousObservedAt": "", "counts": {}, "eventCount": 0}
    latest = snapshots[0].get("observedAt", "")
    previous = snapshots[1].get("observedAt", "") if len(snapshots) > 1 else ""
    latest_events = [event for event in events if event.get("observedAt") == latest]
    counts: dict[str, int] = defaultdict(int)
    for event in latest_events:
        counts[event.get("type", "unknown")] += 1
    return {
        "observedAt": latest,
        "previousObservedAt": previous,
        "counts": dict(counts),
        "eventCount": len(latest_events),
        "complete": bool(snapshots[0].get("complete")),
        "coverageStart": snapshots[0].get("coverageStart", ""),
        "coverageEnd": snapshots[0].get("coverageEnd", ""),
    }


def main():
    out = ROOT / "site" / "data"
    target_out = out / "targets"
    target_out.mkdir(parents=True, exist_ok=True)
    catalog = []
    global_people: dict[str, dict[str, Any]] = {}

    for path in sorted((ROOT / "targets").glob("*/target.json")):
        cfg = read_json(path)
        tid = cfg["id"]
        state_path = ROOT / "data" / tid / "state.json.gz"
        legacy = ROOT / "data" / tid / "state.json"
        state = read_json(state_path) if state_path.exists() else (read_json(legacy) if legacy.exists() else initial_state(tid))
        entities = sorted(state.get("entities", {}).values(), key=_activity_key, reverse=True)
        events = sorted(state.get("events", []), key=lambda e: e.get("observedAt", ""), reverse=True)
        snaps = sorted(state.get("snapshots", []), key=lambda s: s.get("observedAt", ""), reverse=True)
        authors = _author_index(entities)
        discussions = _discussion_counts(entities)
        public = {
            "target": cfg,
            "summary": summary(state),
            "entities": entities,
            "events": events,
            "snapshots": snaps,
            "authors": authors,
            "discussionCounts": discussions,
            "latestDelta": _latest_delta(events, snaps),
        }
        (target_out / f"{tid}.json").write_text(dumps(public), encoding="utf-8")
        catalog.append(
            {
                "id": tid,
                "displayName": cfg["displayName"],
                "description": cfg.get("description", ""),
                "platform": cfg.get("platform", ""),
                "sourceUrls": cfg.get("sourceUrls", []),
                "summary": public["summary"],
                "latestSnapshot": snaps[0].get("observedAt", "") if snaps else "",
            }
        )
        for author in authors:
            row = global_people.setdefault(
                author["key"],
                {
                    "key": author["key"],
                    "displayName": author["displayName"],
                    "profileUrl": author.get("profileUrl", ""),
                    "posts": 0,
                    "comments": 0,
                    "targets": [],
                    "latestActivity": "",
                },
            )
            row["posts"] += author["posts"]
            row["comments"] += author["comments"]
            if tid not in row["targets"]:
                row["targets"].append(tid)
            row["latestActivity"] = max(row["latestActivity"], author.get("latestActivity", ""))
            if not row["profileUrl"] and author.get("profileUrl"):
                row["profileUrl"] = author["profileUrl"]

    people = sorted(global_people.values(), key=lambda a: (a["comments"], a["posts"], a["latestActivity"]), reverse=True)
    (out / "catalog.json").write_text(dumps({"targets": catalog}), encoding="utf-8")
    (out / "people.json").write_text(dumps({"people": people}), encoding="utf-8")
    print(f"Built site indexes for {len(catalog)} target(s); {len(people)} observed authors")


if __name__ == "__main__":
    main()
