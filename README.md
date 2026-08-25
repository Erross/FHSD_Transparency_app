# Greenwood Repository

A multi-target public-record archive and change tracker for publicly visible social-media pages relevant to Francis Howell School District and related campaigns.

School Watchlist is the first configured target, but **nothing in the archive engine is hardcoded to that page**. Campaign pages, spin-off pages, PACs, public figures, or other public sources can be added through target configuration.

## What it does

- Preserves periodic raw crawler exports.
- SHA-256 hashes the original captured bytes.
- Normalizes posts, comments, and replies into stable entities.
- Stores every observed text version.
- Detects edits, disappearance/recheck states, reappearance, and bulk disappearance events.
- Refuses to infer who deleted something merely because Facebook stopped rendering it.
- Produces a readable static archive with search, filters, source links, change cards, and before/after edit views.

## Layout

```text
targets/                 target configuration
archive/<target>/raw/    immutable gzip snapshots + original-byte SHA-256
data/<target>/            compressed normalized state
scripts/                 ingestion, diff, verification, site build
site/                    static archive UI
tests/                   regression tests
.github/workflows/       CI validation
```

## First target

`targets/school-watchlist/target.json`

To add another source, create `targets/<slug>/target.json`; the ingest and site-build code will discover it automatically.

## Ingest a snapshot

```bash
python -m scripts.ingest --target school-watchlist path/to/facebook-export.json
```

That archives the source but **does not** infer disappearances. When a crawl is known to be a complete comparable pull:

```bash
python -m scripts.ingest --target school-watchlist --complete path/to/full-export.json
```

Missing detection is intentionally opt-in because Facebook comment rendering is not deterministic.

## Build/read the site

```bash
python -m scripts.build_site
python -m http.server 8000 -d site
```

Then open `http://localhost:8000`.

## Availability vocabulary

- `active` — observed in the latest complete snapshot.
- `missing_once` — absent from one later complete snapshot.
- `missing_recheck` — absent repeatedly.
- `confirmed_unavailable` — separately verified as unavailable.
- `reappeared` — previously missing and later observed again.

Use `scripts.verify_missing` to record a direct/manual confirmation with an optional evidence URL and note.

## Storage and evidentiary preservation

Raw captures are deterministically gzip-compressed for repository efficiency. The `.sha256` sidecar hashes the **original uncompressed export**, so the exact source bytes can be reconstructed and verified.

Never commit Facebook authentication cookies, browser profiles, credentials, access tokens, or private session material.

See `docs/ARCHITECTURE.md` for design rationale and the planned local Playwright collector.
