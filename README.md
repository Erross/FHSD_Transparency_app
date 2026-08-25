# Greenwood Repository

A public-record archive and change-tracking system for publicly visible social-media pages relevant to Francis Howell School District and related campaigns.

The project is deliberately **multi-target**. School Watchlist is the first configured target, but the data model, ingestion pipeline, diff engine, and website are designed to track any number of pages or public figures without hardcoding one account.

## Goals

- Preserve periodic raw crawler exports without rewriting history.
- Normalize posts, comments, and replies into stable entities.
- Detect new, edited, missing, reappeared, and bulk-disappearance events.
- Avoid overclaiming: a missing comment is recorded as **no longer observed**, not as "deleted by" a particular person unless independent evidence establishes that.
- Provide a readable archive and visual change history rather than exposing users to raw JSON.
- Support multiple tracked targets with independent aliases, source URLs, and crawl settings.
- Keep deployment inexpensive: the website is static and can be hosted on GitHub Pages when the repository is made public or otherwise published through an appropriate static host.

## Initial architecture

```text
targets/                 Target configuration
archive/<target>/raw/    Immutable crawler exports (future snapshots)
data/                    Generated normalized data and event history
scripts/                 Ingestion / normalization / diff tooling
site/                    Static archive UI
.github/workflows/       Validation and site build workflows
tests/                   Regression tests for the diff engine
```

## First target

`school-watchlist` is configured as the first target. Additional targets can be added by copying its `target.json` and supplying a unique target ID, display name, aliases, source URLs, and crawler metadata.

## Status vocabulary

The archive distinguishes observation from attribution:

- `active` — seen in the latest successful snapshot.
- `missing_once` — absent in one successful later snapshot.
- `missing_recheck` — absent in multiple successful later snapshots but not yet confirmed by a direct check.
- `confirmed_unavailable` — repeated absence plus a configured confirmation rule.
- `reappeared` — previously unavailable but visible again.

The software should not label an item "deleted by page owner" solely from absence in a Facebook crawl.

## Local use

```bash
python -m scripts.ingest --target school-watchlist path/to/facebook-export.json
python -m scripts.build_site
python -m http.server 8000 -d site
```

The ingestion command writes generated target data under `data/` and preserves a timestamped raw copy under `archive/<target>/raw/`.

## Evidentiary preservation

Each raw snapshot is preserved byte-for-byte and accompanied by a SHA-256 manifest. Generated entity histories retain first-seen/last-seen metadata and every observed text version.

Do not commit Facebook authentication cookies, browser profiles, credentials, access tokens, or other private session material to this repository.
