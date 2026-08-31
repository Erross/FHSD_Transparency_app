"""Resolve an incoming crawler export to a configured archive target.

Routing prefers stable evidence from the export itself (target id/profile id),
then crawl-page context, declared author aliases, and finally filename aliases.
Per-item ``profileId`` values are deliberately NOT used for routing because
older crawler schemas may populate them with authors/pages merely appearing
inside the captured material.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[1]


def _norm(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value or "").casefold()).strip("_")


def _profile_id(url: str) -> str:
    try:
        values = parse_qs(urlparse(url or "").query).get("id", [])
        return values[0] if values else ""
    except ValueError:
        return ""


def load_target_configs(root: Path = ROOT) -> list[dict[str, Any]]:
    configs = []
    for path in sorted((root / "targets").glob("*/target.json")):
        config = json.loads(path.read_text(encoding="utf-8"))
        config["_path"] = path.as_posix()
        configs.append(config)
    return configs


def configured_profile_ids(config: dict[str, Any]) -> set[str]:
    ids = {_profile_id(str(url)) for url in config.get("sourceUrls", [])}
    ids.discard("")
    return ids


def observed_profile_ids(payload: dict[str, Any]) -> set[str]:
    """Return IDs that identify the crawl/page context, not incidental actors.

    v10-style target metadata is strongest. For older schemas, item ``pageUrl``
    is usable because it represents the page/thread context the crawler was
    visiting. ``item.profileId`` is intentionally ignored: historical exports
    use it for many actors appearing in posts/comments and it therefore cannot
    safely identify the target account.
    """
    ids: set[str] = set()
    target = payload.get("target") if isinstance(payload.get("target"), dict) else {}

    for value in (
        payload.get("profileId"),
        target.get("profileId"),
    ):
        if value:
            ids.add(str(value).strip())

    for value in (
        payload.get("pageUrl"),
        payload.get("sourceUrl"),
        target.get("sourceUrl"),
        target.get("url"),
    ):
        pid = _profile_id(str(value or ""))
        if pid:
            ids.add(pid)

    for item in payload.get("items", []):
        if not isinstance(item, dict):
            continue
        # pageUrl is crawl/thread context. Do not use item.profileId here.
        pid = _profile_id(str(item.get("pageUrl") or ""))
        if pid:
            ids.add(pid)

    return ids


def _filename_matches(config: dict[str, Any], filename: str) -> bool:
    stem = _norm(Path(filename).stem)
    aliases = list(config.get("filenameAliases", []))
    aliases += [config.get("displayName", ""), config.get("id", "")]
    aliases += list(config.get("authorAliases", []))
    for alias in aliases:
        token = _norm(alias)
        if token and (stem == token or stem.startswith(token + "_")):
            return True
    return False


def resolve_target(payload: dict[str, Any], filename: str, configs: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    configs = configs or load_target_configs()
    if not configs:
        return {"ok": False, "reason": "No target configurations exist."}

    target_obj = payload.get("target") if isinstance(payload.get("target"), dict) else {}
    explicit = str(payload.get("targetId") or target_obj.get("id") or "").strip()
    declared = str(payload.get("targetAuthor") or target_obj.get("displayName") or "").strip()
    observed_ids = observed_profile_ids(payload)

    by_id = [c for c in configs if explicit and c.get("id") == explicit]
    by_profile = [c for c in configs if configured_profile_ids(c) & observed_ids]
    by_author = [
        c for c in configs
        if declared and _norm(declared) in {_norm(v) for v in c.get("authorAliases", []) + [c.get("displayName", "")]}
    ]
    by_filename = [c for c in configs if _filename_matches(c, filename)]

    def unique(candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
        ids = {c.get("id") for c in candidates}
        return candidates[0] if len(ids) == 1 and candidates else None

    explicit_target = unique(by_id)
    profile_target = unique(by_profile)
    author_target = unique(by_author)
    filename_target = unique(by_filename)

    if len({c.get("id") for c in by_profile}) > 1:
        return {
            "ok": False,
            "reason": f"Crawl/page context matches multiple configured targets: {sorted(observed_ids)}",
        }
    if explicit and not explicit_target:
        return {"ok": False, "reason": f"Export declares unknown targetId {explicit!r}."}
    if explicit_target and profile_target and explicit_target["id"] != profile_target["id"]:
        return {"ok": False, "reason": "Export targetId conflicts with crawl/page profile identity."}

    # Prefer explicit schema identity, then page context, then legacy author name.
    chosen = explicit_target or profile_target or author_target or filename_target
    if not chosen:
        return {
            "ok": False,
            "reason": f"Could not identify a unique target from export metadata or filename {filename!r}.",
            "observedProfileIds": sorted(observed_ids),
            "declaredTargetAuthor": declared,
        }

    strong_target = explicit_target or profile_target
    if author_target and strong_target and author_target["id"] != strong_target["id"]:
        return {
            "ok": False,
            "reason": f"Declared target author suggests {author_target['id']!r} but crawl identity resolves to {strong_target['id']!r}.",
        }
    if filename_target and strong_target and filename_target["id"] != strong_target["id"]:
        return {
            "ok": False,
            "reason": f"Filename suggests {filename_target['id']!r} but export identity resolves to {strong_target['id']!r}.",
        }

    return {
        "ok": True,
        "targetId": chosen["id"],
        "method": (
            "target_id" if explicit_target else
            "page_profile_id" if profile_target else
            "author_alias" if author_target else
            "filename_alias"
        ),
        "observedProfileIds": sorted(observed_ids),
        "declaredTargetAuthor": declared,
        "filenameMatched": bool(filename_target),
    }
