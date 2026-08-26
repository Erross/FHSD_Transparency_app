"""Backward-compatible enrichment for crawler schemas v6-v10.

The core archive engine deliberately keeps identity/diff logic small. This
module preserves richer observation metadata used by the public site without
making older crawler exports invalid.
"""
from __future__ import annotations

import re
from typing import Any
from urllib.parse import parse_qs, urlparse

from .core import normalize_space
from .coverage import resolve_content_date

_SEE_MORE = re.compile(r"(?:…|\.\.\.)?\s*See more\s*$", re.IGNORECASE)
_EDITED_UI = re.compile(r"LikeReplyEdited(?:\d+)?\s*$", re.IGNORECASE)


def _profile_id_from_url(url: str) -> str:
    try:
        parsed = urlparse(url or "")
        values = parse_qs(parsed.query).get("id", [])
        return values[0] if values else ""
    except ValueError:
        return ""


def _author_identity(item: dict[str, Any], normalized: dict[str, Any]) -> tuple[str, str, str, str]:
    display = normalize_space(item.get("authorDisplayName") or item.get("author") or normalized.get("author"))
    profile_url = normalize_space(item.get("authorProfileUrl"))
    profile_id = normalize_space(item.get("authorProfileId"))

    # Older page-post exports already expose the page profile id/url. Do not
    # reuse those fields for comments because they describe the tracked page,
    # not necessarily the commenter.
    if normalized.get("itemType") == "post":
        profile_id = profile_id or normalize_space(item.get("profileId"))
        page_url = normalize_space(item.get("pageUrl"))
        if not profile_url and profile_id and _profile_id_from_url(page_url) == profile_id:
            profile_url = page_url

    if not profile_id and profile_url:
        profile_id = _profile_id_from_url(profile_url)

    supplied_key = normalize_space(item.get("authorKey"))
    if supplied_key:
        author_key = supplied_key
    elif profile_id:
        author_key = f"facebook:{profile_id}"
    elif profile_url:
        author_key = f"facebook-url:{profile_url.casefold()}"
    else:
        author_key = f"name:{display.casefold()}" if display else "name:unknown"
    return display, profile_url, profile_id, author_key


def _published_metadata(item: dict[str, Any], normalized: dict[str, Any]) -> tuple[str, str, str, str]:
    published_at = normalize_space(item.get("publishedAt"))
    precision = normalize_space(item.get("publishedAtPrecision"))
    source = normalize_space(item.get("publishedAtSource"))

    # Older exports cannot always supply exact times, but coverage.py can still
    # recover a defensible content date from exact/relative Facebook labels.
    content_date, quality = resolve_content_date(normalized)
    published_date = content_date.isoformat() if content_date else ""

    if published_at and not precision:
        precision = "exact"
    if published_at and not source:
        source = "crawler"
    if not precision:
        precision = "day" if published_date else "unknown"
    if not source:
        source = quality if published_date else "unknown"
    return published_at, published_date, precision, source


def _plain_links(value: Any) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    if not isinstance(value, list):
        return out
    for link in value:
        if not isinstance(link, dict):
            continue
        href = normalize_space(link.get("href"))
        text = normalize_space(link.get("text"))
        if href or text:
            out.append({"href": href, "text": text})
    return out


def _plain_media(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    allowed = {"type", "url", "thumbnailUrl", "altText", "title", "domain", "outboundUrl"}
    out = []
    for media in value:
        if not isinstance(media, dict):
            continue
        record = {key: media.get(key) for key in allowed if media.get(key) not in (None, "")}
        if record:
            out.append(record)
    return out


def enrich_normalized(item: dict[str, Any], normalized: dict[str, Any], observed_at: str) -> dict[str, Any]:
    """Return normalized record enriched with optional crawler evidence fields."""
    out = dict(normalized)
    display, profile_url, profile_id, author_key = _author_identity(item, normalized)
    published_at, published_date, precision, published_source = _published_metadata(item, normalized)

    raw_observed = normalize_space(normalized.get("rawObservedText"))
    raw_complete = item.get("bodyComplete")
    body_complete = bool(raw_complete) if isinstance(raw_complete, bool) else normalized.get("contentCompleteness") == "full"
    had_see_more = item.get("hadSeeMore")
    if not isinstance(had_see_more, bool):
        had_see_more = bool(_SEE_MORE.search(raw_observed))

    facebook_edited = item.get("facebookEdited")
    if not isinstance(facebook_edited, bool):
        facebook_edited = True if _EDITED_UI.search(raw_observed) else None

    reply_comment_id = normalize_space(item.get("replyCommentId"))
    parent_post_entity_key = normalize_space(item.get("parentPostEntityKey")) or normalize_space(normalized.get("parentId"))

    out.update(
        {
            "authorDisplayName": display,
            "authorProfileUrl": profile_url,
            "authorProfileId": profile_id,
            "authorKey": author_key,
            "publishedAt": published_at,
            "publishedDate": published_date,
            "publishedAtPrecision": precision,
            "publishedAtSource": published_source,
            "identityMethod": normalize_space(item.get("identityMethod")) or (
                "facebook_id" if normalized.get("identityQuality") == "strong" else
                "canonical_permalink" if normalized.get("identityQuality") == "medium" else
                "fingerprint"
            ),
            "identityConfidence": normalize_space(item.get("identityConfidence")) or ({
                "strong": "high", "medium": "medium", "weak": "low"
            }.get(normalized.get("identityQuality"), "low")),
            "bodyComplete": body_complete,
            "hadSeeMore": had_see_more,
            "expansionAttempted": item.get("expansionAttempted"),
            "expansionAttempts": item.get("expansionAttempts"),
            "expansionResult": normalize_space(item.get("expansionResult")) or (
                "not_needed" if not had_see_more else ("expanded" if body_complete else "still_truncated")
            ),
            "facebookEdited": facebook_edited,
            "facebookEditedLabel": normalize_space(item.get("facebookEditedLabel")) or ("Edited" if facebook_edited else ""),
            "attachmentSummary": normalize_space(item.get("attachmentSummary")),
            "imageAlts": [normalize_space(v) for v in item.get("imageAlts", []) if normalize_space(v)] if isinstance(item.get("imageAlts"), list) else [],
            "links": _plain_links(item.get("links")),
            "media": _plain_media(item.get("media")),
            "isPinned": bool(item.get("isPinned", False)),
            "isFeatured": bool(item.get("isFeatured", False)),
            "sourceLinkRecoveredFrom": normalize_space(item.get("sourceLinkRecoveredFrom")),
            "replyCommentId": reply_comment_id,
            "parentPostEntityKey": parent_post_entity_key,
            "groupName": normalize_space(item.get("groupName")),
            "groupUrl": normalize_space(item.get("groupUrl")),
        }
    )
    return out
