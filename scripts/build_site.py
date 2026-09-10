"""Build static JSON indexes consumed by the FHSD Transparency Archive."""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any

from .comment_visibility import latest_comment_visibility
from .core import dumps, initial_state, normalize_space, summary
from .io_utils import read_json
from .publication_evidence import enrich_publication_evidence
from .relationships import repair_parent_relationships

ROOT = Path(__file__).resolve().parents[1]


def _activity_key(entity: dict[str, Any]) -> str:
    return normalize_space(
        entity.get("publishedAt")
        or entity.get("publishedDate")
        or entity.get("timestampExact")
        or entity.get("publishedAtEstimated")
        or entity.get("publishedAtUpperBound")
        or entity.get("lastSeen")
        or entity.get("firstSeen")
    )


def _publication_key(entity: dict[str, Any]) -> str:
    """Return the strongest exact ISO-like publication value available."""
    return normalize_space(
        entity.get("publishedAt")
        or entity.get("publishedDate")
        or entity.get("timestampExact")
    )


def _infer_post_upper_bounds(entities: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Give otherwise-undated posts a conservative chronology from their earliest comment.

    Crawler-supplied exact or bounded relative publication evidence wins. A
    comment proves only that its parent post existed no later than the comment
    time, so comment-derived chronology remains an upper bound.
    """
    earliest_by_parent: dict[str, str] = {}
    for entity in entities:
        if entity.get("itemType") == "post":
            continue
        parent = normalize_space(entity.get("parentId"))
        if not parent:
            continue
        value = _publication_key(entity)
        if not value:
            continue
        current_value = earliest_by_parent.get(parent)
        if current_value is None or value < current_value:
            earliest_by_parent[parent] = value

    out: list[dict[str, Any]] = []
    for entity in entities:
        if (
            entity.get("itemType") != "post"
            or _publication_key(entity)
            or normalize_space(entity.get("publishedAtEstimated"))
            or normalize_space(entity.get("publishedAtUpperBound"))
        ):
            out.append(entity)
            continue
        inferred = earliest_by_parent.get(normalize_space(entity.get("id")))
        if not inferred:
            out.append(entity)
            continue
        enriched = dict(entity)
        enriched["publishedAtUpperBound"] = inferred
        enriched["publishedAtUpperBoundSource"] = "earliest-archived-comment"
        enriched["publishedAtPrecision"] = enriched.get("publishedAtPrecision") or "upper-bound"
        out.append(enriched)
    return out


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
        snaps = sorted(state.get("snapshots", []), key=lambda s: s.get("observedAt", ""), reverse=True)

        # Older normalized states can contain comments whose numeric postId does
        # not equal the page post's pfbid. Repair public-facing relationships
        # from strong captured source-link evidence at build time so existing
        # archives benefit immediately without rewriting immutable raw evidence.
        raw_entities = list(state.get("entities", {}).values())
        entities, relationship_diagnostics = repair_parent_relationships(raw_entities)

        # Rehydrate exact/bounded crawler date evidence from immutable raw
        # snapshots. This makes labels such as "2 hours ago" sortable relative
        # to the crawl observation time even when an older normalized state did
        # not retain dateEvidence.
        entities = enrich_publication_evidence(ROOT, snaps, entities)
        entities = _infer_post_upper_bounds(entities)
        entities = sorted(entities, key=_activity_key, reverse=True)

        events = sorted(state.get("events", []), key=lambda e: e.get("observedAt", ""), reverse=True)
        authors = _author_index(entities)
        discussions = _discussion_counts(entities)
        comment_visibility = latest_comment_visibility(ROOT, snaps, entities)
        public = {
            "target": cfg,
            "summary": summary(state),
            "entities": entities,
            "events": events,
            "snapshots": snaps,
            "authors": authors,
            "discussionCounts": discussions,
            "commentVisibility": comment_visibility,
            "relationshipDiagnostics": relationship_diagnostics,
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

        if relationship_diagnostics.get("totalComments"):
            print(
                f"{tid}: linked {relationship_diagnostics.get('linkedComments', 0)}/"
                f"{relationship_diagnostics.get('totalComments', 0)} comments to archived posts; "
                f"repaired {relationship_diagnostics.get('repairedComments', 0)} existing relationships; "
                f"unresolved {relationship_diagnostics.get('orphanComments', 0)}"
            )

    people = sorted(global_people.values(), key=lambda a: (a["comments"], a["posts"], a["latestActivity"]), reverse=True)
    (out / "catalog.json").write_text(dumps({"targets": catalog}), encoding="utf-8")
    (out / "people.json").write_text(dumps({"people": people}), encoding="utf-8")
    print(f"Built site indexes for {len(catalog)} target(s); {len(people)} observed authors")


if __name__ == "__main__":
    main()
