"""Conservative item-level ownership checks for mixed Facebook exports.

Routing identifies the export's declared target. This module handles the narrower
problem where a cumulative/shared-content crawl accidentally leaves records from
another *configured* Facebook page in the same items array. We suppress posts
when route/owner evidence or an exact configured page-author match identifies
another target. A commenter merely having another page's name does not make that
comment foreign.
"""
from __future__ import annotations

import re
from collections import Counter
from typing import Any
from urllib.parse import parse_qs, urlparse

from .route_snapshot import configured_profile_ids, load_target_configs

_GENERIC_FACEBOOK_PATHS = {
    "",
    "photo",
    "photos",
    "reel",
    "reels",
    "watch",
    "groups",
    "events",
    "share",
    "story.php",
    "permalink.php",
    "profile.php",
}


def _norm(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").casefold())


def _facebook_identity(url: str) -> tuple[str, str]:
    """Return (numeric profile/page id, page slug) when a URL exposes one."""
    try:
        parsed = urlparse(str(url or ""))
    except ValueError:
        return "", ""
    host = parsed.netloc.casefold()
    if "facebook.com" not in host:
        return "", ""
    query_id = (parse_qs(parsed.query).get("id") or [""])[0].strip()
    parts = [part for part in parsed.path.split("/") if part]
    first = parts[0] if parts else ""
    slug = ""
    if first.casefold() not in _GENERIC_FACEBOOK_PATHS and not first.casefold().startswith("pfbid"):
        slug = first.casefold()
    return query_id, slug


def _config_identities(config: dict[str, Any]) -> tuple[set[str], set[str]]:
    profile_ids = configured_profile_ids(config)
    slugs: set[str] = set()
    for url in config.get("sourceUrls", []):
        _, slug = _facebook_identity(str(url))
        if slug:
            slugs.add(slug)
    return profile_ids, slugs


def _config_author_aliases(config: dict[str, Any]) -> set[str]:
    return {
        _norm(value)
        for value in config.get("authorAliases", []) + [config.get("displayName", "")]
        if _norm(value)
    }


def _item_route_identities(item: dict[str, Any]) -> tuple[set[str], set[str]]:
    profile_ids: set[str] = set()
    slugs: set[str] = set()
    for field in (
        "pageUrl",
        "parentPostPermalink",
        "wrapperPermalink",
        "threadRoutePermalink",
        "permalink",
    ):
        pid, slug = _facebook_identity(str(item.get(field) or ""))
        if pid:
            profile_ids.add(pid)
        if slug:
            slugs.add(slug)

    evidence = item.get("dateEvidence") if isinstance(item.get("dateEvidence"), dict) else {}
    owner_id = str(evidence.get("ownerId") or "").strip()
    if owner_id:
        profile_ids.add(owner_id)
    return profile_ids, slugs


def _matched_target_ids(item: dict[str, Any], configs: list[dict[str, Any]]) -> set[str]:
    item_ids, item_slugs = _item_route_identities(item)
    matches: set[str] = set()
    for config in configs:
        config_ids, config_slugs = _config_identities(config)
        if (config_ids & item_ids) or (config_slugs & item_slugs):
            matches.add(str(config.get("id") or ""))
    matches.discard("")
    return matches


def _post_author_target_ids(item: dict[str, Any], configs: list[dict[str, Any]]) -> set[str]:
    """Resolve an exact post author to configured page targets.

    This evidence is used only for top-level posts. It is deliberately not used
    for comments/replies because a page account can legitimately comment on
    another page without owning that discussion thread.
    """
    if str(item.get("itemType") or "").casefold() != "post":
        return set()
    author = _norm(item.get("authorDisplayName") or item.get("author"))
    if not author:
        return set()
    matches = {
        str(config.get("id") or "")
        for config in configs
        if author in _config_author_aliases(config)
    }
    matches.discard("")
    return matches


def split_obvious_foreign_target_items(
    items: list[Any],
    current_config: dict[str, Any],
    configs: list[dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    """Split records strongly owned by another configured page from a target export.

    A top-level post is foreign when either route/owner evidence or its exact
    configured page-author identity resolves uniquely to another target and no
    evidence resolves it to the current target. Comments/replies are foreign only
    when their route resolves that way or when they are explicitly bound to a post
    already classified as foreign. Shared-source metadata alone never causes
    suppression.
    """
    configs = configs or load_target_configs()
    current_id = str(current_config.get("id") or "")
    current_aliases = _config_author_aliases(current_config)

    foreign_parent_ids: set[str] = set()
    foreign_parent_keys: set[str] = set()
    foreign_parent_urls: set[str] = set()
    foreign_target_by_object: dict[int, str] = {}

    # First pass: identify top-level posts that clearly belong to a different
    # configured page. Exact configured page-author identity is strong evidence
    # for posts, even when Facebook emits a generic photo/permalink route.
    for raw in items:
        if not isinstance(raw, dict) or str(raw.get("itemType") or "").casefold() != "post":
            continue
        route_matches = _matched_target_ids(raw, configs)
        author_matches = _post_author_target_ids(raw, configs)
        matches = route_matches | author_matches
        foreign_matches = sorted(match for match in matches if match != current_id)
        author = _norm(raw.get("authorDisplayName") or raw.get("author"))

        if current_id in route_matches:
            # A record explicitly routed on the current page is a current-page
            # wrapper even when it shares content authored elsewhere.
            continue
        if author and author in current_aliases:
            continue
        if len(foreign_matches) != 1:
            continue

        target_id = foreign_matches[0]
        foreign_target_by_object[id(raw)] = target_id
        for field in ("postId", "wrapperPostId", "parentPostId"):
            value = str(raw.get(field) or "").strip()
            if value:
                foreign_parent_ids.add(value)
        for field in ("entityKey", "parentPostEntityKey"):
            value = str(raw.get(field) or "").strip()
            if value:
                foreign_parent_keys.add(value)
        for field in ("permalink", "wrapperPermalink", "parentPostPermalink", "pageUrl"):
            value = str(raw.get(field) or "").strip()
            if value:
                foreign_parent_urls.add(value)

    kept: list[dict[str, Any]] = []
    foreign: list[dict[str, Any]] = []
    foreign_counts: Counter[str] = Counter()

    for raw in items:
        if not isinstance(raw, dict):
            continue
        target_id = foreign_target_by_object.get(id(raw), "")
        is_foreign = bool(target_id)

        if not is_foreign and str(raw.get("itemType") or "").casefold() != "post":
            matches = _matched_target_ids(raw, configs)
            foreign_matches = sorted(match for match in matches if match != current_id)
            if current_id not in matches and len(foreign_matches) == 1:
                target_id = foreign_matches[0]
                is_foreign = True
            else:
                parent_ids = {
                    str(raw.get("parentPostId") or "").strip(),
                    str(raw.get("wrapperPostId") or "").strip(),
                    str(raw.get("postId") or "").strip(),
                }
                parent_keys = {
                    str(raw.get("parentPostEntityKey") or "").strip(),
                    str(raw.get("entityKey") or "").strip(),
                }
                parent_urls = {
                    str(raw.get("parentPostPermalink") or "").strip(),
                    str(raw.get("wrapperPermalink") or "").strip(),
                    str(raw.get("pageUrl") or "").strip(),
                }
                if (
                    (parent_ids - {""}) & foreign_parent_ids
                    or (parent_keys - {""}) & foreign_parent_keys
                    or (parent_urls - {""}) & foreign_parent_urls
                ):
                    target_id = foreign_matches[0] if len(foreign_matches) == 1 else "foreign-parent"
                    is_foreign = True

        if is_foreign:
            foreign.append(raw)
            foreign_counts[target_id or "foreign"] += 1
        else:
            kept.append(raw)

    diagnostics = {
        "inputItems": sum(1 for item in items if isinstance(item, dict)),
        "keptItems": len(kept),
        "foreignItems": len(foreign),
        "foreignByTarget": dict(sorted(foreign_counts.items())),
    }
    return kept, foreign, diagnostics
