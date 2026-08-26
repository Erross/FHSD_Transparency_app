# FHSD Transparency Archive

A multi-target public-record archive and change tracker for publicly visible social-media activity relevant to Francis Howell School District and its political/community sphere.

The repository is **`FHSD_Transparency_app`**. School Watchlist is the first configured tracked account, but nothing in the archive engine or site is hardcoded to that page. Additional campaign pages, advocacy pages, public figures, PACs, and other prominent public sources can be added through target configuration.

## MVP experience

The static site is designed to answer ordinary research questions without exposing raw crawler JSON:

- **What changed?** — latest snapshot delta with newly-published/first-observed, edited, missing/recheck, reappeared, and confirmed-unavailable events.
- **Account feed** — Facebook-like chronological cards with archive flags, source links, attachment summaries, and discussion counts.
- **Archived discussion** — individual post records with captured comments/replies and direct Facebook links where recovered.
- **People** — search public comment authors and view their captured commentary in context.
- **Search archive** — full-text search over posts, comments, authors, attachments, and archive IDs.
- **Version history** — substantive observed text versions with Facebook UI noise and `See more`/`See less` capture expansion filtered out.
- **Provenance** — first/last observed timestamps, identity confidence, capture completeness, status, source URL, and archive ID.

No production database server or API is required for the MVP.

## Evidence rules

The archive reports what was observed, not unsupported causation.

- `active` — observed in the latest comparable snapshot.
- `missing_once` — absent from one later complete crawl within applicable coverage.
- `missing_recheck` — absent repeatedly within applicable coverage.
- `confirmed_unavailable` — separately verified as unavailable.
- `reappeared` — previously missing and later observed again.

A post/comment absent from a later Facebook crawl is **not** labelled “deleted by” a person or page solely from that absence. Likewise, material newly recovered by a better crawl is not automatically described as newly published.

## Repository layout

```text
targets/                 tracked-account configuration
incoming/
  complete/              full comparable crawler exports
  partial/               incomplete/short crawler exports
  rejected/              quarantined routing/validation failures
archive/<target>/raw/    immutable gzip snapshots + original-byte SHA-256
data/<target>/            compressed canonical state and event history
scripts/                 routing, ingestion, enrichment, diff, verification, site build
site/                    static FHSD Transparency Archive UI
tests/                   regression tests
.github/workflows/       validation, automated ingest, optional Pages deployment
```

## Normal ingest workflow

**You do not create an incoming folder per target.** Put all complete snapshots together in:

```text
incoming/complete/
```

and all partial snapshots in:

```text
incoming/partial/
```

Example:

```text
incoming/complete/School_Watchlist_2024-01-01_2026-08-25_10-48-39.json
incoming/complete/School_Watchlist_2024-01-01_2026-08-26_10-52-12.json
incoming/complete/Greenwood_for_FHSD_School_Board_2025-01-01_2026-08-26_11-02-15.json
```

The inbox processor routes each file automatically using, in priority order:

1. explicit target ID when present;
2. stable Facebook profile ID/source URL in the export;
3. declared target author aliases;
4. configured filename aliases as fallback.

Conflicting or ambiguous files are moved to `incoming/rejected/` with a reason file instead of being guessed into an archive.

Multiple snapshots can be dropped in together. They are processed by their internal `exportedAt` value, oldest first, so an older snapshot becomes the baseline before a newer comparison is applied.

Run locally:

```bash
python -m scripts.ingest_inbox --consume
```

`--consume` removes successfully processed inbox copies after their immutable archived versions have been preserved. Duplicate raw snapshots are SHA-256 deduplicated and do not create another archive observation.

Then serve the generated site:

```bash
python -m http.server 8000 -d site
```

Open `http://localhost:8000`.

See `incoming/README.md` for routing/quarantine details.

## Direct/manual ingest

You can still bypass the auto-router when needed.

Partial observation:

```bash
python -m scripts.ingest --target school-watchlist path/to/facebook-export.json
```

Full comparable observation:

```bash
python -m scripts.ingest --target school-watchlist --complete path/to/full-export.json
```

Then rebuild:

```bash
python -m scripts.build_site
```

## Automated GitHub ingest

On `main`, the **Ingest uploaded snapshots** workflow watches only:

```text
incoming/complete/*.json
incoming/partial/*.json
```

It runs tests, routes/validates exports, archives and hashes originals, updates canonical state/change events, rebuilds site indexes, consumes successful inbox files, and commits the generated update. Quarantined JSON does not trigger the ingest workflow.

## Backward-compatible crawler ingestion

Historical crawler exports and future richer v10 exports are normalized through an enrichment layer. Where available the archive preserves:

- stable Facebook post/comment/reply IDs;
- canonical source/parent links;
- author display/profile identity;
- publication timestamps and precision;
- identity confidence;
- capture completeness and expansion state;
- Facebook-visible `Edited` state;
- attachment/image/media metadata.

Missing fields remain unknown/lower-confidence rather than invalidating older observations.

## Date/coverage-aware missing inference

For date-limited complete crawls, missing detection is scoped to comparable coverage.

- A prior post must have a resolvable content date inside the later crawl's coverage before its absence counts.
- A comment/reply is eligible only when its parent post was actually revisited in the later complete crawl.
- Unknown-date/out-of-coverage records remain preserved but are excluded from negative inference.

## Manual confirmation

Use `scripts.verify_missing` to record a direct/manual visibility check:

```bash
python -m scripts.verify_missing \
  --target school-watchlist \
  --entity 'comment:123456' \
  --confirm-unavailable \
  --evidence-url 'https://www.facebook.com/...' \
  --note 'Direct source checked in normal signed-in session.'
```

The opposite `--confirm-visible` action clears the missing count and records that the entity remained available.

## Add another tracked source

Create only:

```text
targets/<slug>/target.json
```

Give it source URLs/profile identity, author aliases, and useful `filenameAliases`. No new incoming directories are required.

## Static deployment

`.github/workflows/pages.yml` contains the opt-in GitHub Pages deployment. Set repository variable:

```text
ENABLE_PAGES=true
```

and enable GitHub Pages using **GitHub Actions** as its source.

## Storage and evidentiary preservation

Raw captures are deterministically gzip-compressed. Each `.sha256` sidecar hashes the **original uncompressed export**, allowing exact source bytes to be reconstructed and verified.

Never commit Facebook authentication cookies, browser profiles, credentials, access tokens, or private session material.

See `docs/ARCHITECTURE.md` and `docs/REAL_WORLD_VALIDATION_2026-08-25.md` for design rationale and real-corpus validation work.
