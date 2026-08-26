"""Reconcile archived comments/replies to their parent Facebook posts.

Older crawler schemas can expose two identifiers for the same Facebook post:
page posts are often keyed by a ``pfbid...`` story id while comments sometimes
carry a numeric ``postId``.  The comment's captured source links frequently
contain the canonical ``story_fbid`` alongside that exact comment id.

This module uses only strong relationship evidence already present in a crawl.
It deliberately avoids fuzzy text/author matching so a discussion cannot be
silently attached to the wrong post.
"""
from __future__ import annotations

from collections import Counter
from typing import Any, Iterable
from urllib.parse import parse_qs, urlparse


def _norm(value: Any) -> str:
    return str(value or "").strip()


def _query_value(url: str, *keys: str) -> str:
    try:
        query = parse_qs(urlparse(_norm(url)).query)
    except ValueError:
        return ""
    for key in keys:
        values = query.get(key, [])
        if values:
            return _norm(values[0])
    return ""


def _story_id(url: str) -> str:
    return _query_value(url, "story_fbid", "fbid")


def _comment_ids(url: str) -> set[str]:
    values = {
        _query_value(url, "comment_id"),
        _query_value(url, "reply_comment_id"),
    }
    values.discard("")
    return values


def _post_alias_map(posts: Iterable[dict[str, Any]]) -> dict[str, str]:
    """Map every known Facebook post identifier to the archive post entity id."""
    aliases: dict[str, str] = {}
    for post in posts:
        entity_id = _norm(post.get("id"))
        if not entity_id:
            continue
        candidates = {
            _norm(post.get("postId")),
            _norm(post.get("observedPostId")),
        }
        candidates.update(_norm(value) for value in post.get("postIdAliases", []) if _norm(value))
        if entity_id.startswith("post:") and not entity_id.startswith("post:url:"):
            candidates.add(entity_id.removeprefix("post:"))
        for value in candidates:
            if value:
                aliases.setdefault(value, entity_id)
    return aliases


def _exact_source_story(entity: dict[str, Any]) -> str:
    """Find a story id from a link that points to this exact comment/reply."""
    comment_ids = {
        _norm(entity.get("commentId")),
        _norm(entity.get("replyCommentId")),
    }
    comment_ids.discard("")
    if not comment_ids:
        return ""

    for link in entity.get("links", []):
        if not isinstance(link, dict):
            continue
        href = _norm(link.get("href"))
        story = _story_id(href)
        if story and (_comment_ids(href) & comment_ids):
            return story
    return ""


def _relationship_candidates(entity: dict[str, Any]) -> list[tuple[str, str, str]]:
    """Return candidate post ids ordered from strongest to weakest evidence.

    Each tuple is ``(facebook_post_id, method, confidence)``.
    """
    candidates: list[tuple[str, str, str]] = []

    exact_story = _exact_source_story(entity)
    if exact_story:
        candidates.append((exact_story, "exact_comment_source_link", "high"))

    for field, method in (
        ("parentPostPermalink", "parent_post_permalink"),
        ("permalink", "comment_permalink"),
    ):
        story = _story_id(_norm(entity.get(field)))
        if story:
            candidates.append((story, method, "high"))

    existing_parent = _norm(entity.get("parentId"))
    if existing_parent.startswith("post:") and not existing_parent.startswith("post:url:"):
        candidates.append((existing_parent.removeprefix("post:"), "existing_parent_id", "medium"))

    for field in ("postId", "observedPostId"):
        value = _norm(entity.get(field))
        if value:
            candidates.append((value, field, "medium"))

    seen: set[str] = set()
    ordered: list[tuple[str, str, str]] = []
    for value, method, confidence in candidates:
        if value and value not in seen:
            seen.add(value)
            ordered.append((value, method, confidence))
    return ordered


def repair_parent_relationships(entities: Iterable[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Return entity copies with resolvable comment parent relationships repaired.

    A candidate is accepted only when its Facebook post id resolves to an
    archived post entity in the same target corpus. Existing state is therefore
    repairable at site-build time without rewriting the immutable raw crawl.
    """
    records = [dict(entity) for entity in entities]
    posts = [entity for entity in records if entity.get("itemType") == "post"]
    post_aliases = _post_alias_map(posts)
    post_entity_ids = {_norm(post.get("id")) for post in posts}

    diagnostics = Counter(totalComments=0, linkedComments=0, repairedComments=0, orphanComments=0)

    for entity in records:
        if entity.get("itemType") == "post":
            continue
        diagnostics["totalComments"] += 1
        original_parent = _norm(entity.get("parentId"))

        resolved_entity_id = ""
        resolved_post_id = ""
        method = ""
        confidence = ""

        if original_parent in post_entity_ids:
            resolved_entity_id = original_parent
            resolved_post_id = _norm(entity.get("postId"))
            method = "existing_parent_id"
            confidence = "high"
        else:
            for candidate, candidate_method, candidate_confidence in _relationship_candidates(entity):
                archive_post_id = post_aliases.get(candidate, "")
                if archive_post_id:
                    resolved_entity_id = archive_post_id
                    resolved_post_id = candidate
                    method = candidate_method
                    confidence = candidate_confidence
                    break

        if resolved_entity_id:
            diagnostics["linkedComments"] += 1
            if resolved_entity_id != original_parent:
                diagnostics["repairedComments"] += 1
                entity["observedParentId"] = original_parent
            entity["parentId"] = resolved_entity_id
            if resolved_post_id:
                old_post_id = _norm(entity.get("postId"))
                if old_post_id and old_post_id != resolved_post_id:
                    entity["observedPostId"] = old_post_id
                entity["postId"] = resolved_post_id
            entity["parentRelationshipMethod"] = method
            entity["parentRelationshipConfidence"] = confidence
        else:
            diagnostics["orphanComments"] += 1
            entity["parentRelationshipMethod"] = "unresolved"
            entity["parentRelationshipConfidence"] = "unknown"

    return records, dict(diagnostics)
