# FHSD Transparency Archive

A multi-target public-record archive and change tracker for publicly visible social-media activity relevant to Francis Howell School District and its political/community sphere.

The repository is still named `Greenwood_Repository`, but the product is deliberately broader: **School Watchlist is the first configured tracked account and nothing in the archive engine or site is hardcoded to that page.** Campaign pages, advocacy pages, public figures, PACs, and other prominent public sources can be added through target configuration.

## MVP experience

The static site is designed to answer ordinary research questions without exposing raw crawler JSON:

- **What changed?** — latest snapshot delta with first-observed, edited, missing/recheck, reappeared, and confirmed-unavailable events.
- **Account feed** — Facebook-like chronological cards for an archived account, with attachment summaries, archive flags, source links, and discussion counts.
- **Archived discussion** — individual post records with captured comments/replies and direct Facebook source links where recovered.
- **People** — search public comment authors and see their captured public commentary in context, including links back to the parent post and exact comment when available.
- **Search archive** — full-text search over post/comment text, author names, attachment summaries, and stable archive IDs.
- **Version history** — substantive text versions with Facebook UI noise and `See more`/`See less` capture expansion filtered out.
- **Provenance** — first/last observed timestamps, identity confidence, capture completeness, status, source URL, and archive ID.

The site is static: no production database server or API is required for the MVP.

## Evidence rules

The archive reports what was observed, not unsupported causation.

- `active` — observed in the latest comparable snapshot.
- `missing_once` — absent from one later complete crawl within applicable coverage.
- `missing_recheck` — absent repeatedly within applicable coverage.
- `confirmed_unavailable` — separately verified as unavailable.
- `reappeared` — previously missing and later observed again.

A post/comment absent from a later Facebook crawl is **not** labelled “deleted by” a person or page solely from that absence. Facebook comment rendering is not deterministic.

Likewise, something first recovered by the archive today is not automatically described as published today. Older material newly discovered by a deeper crawl remains a first-observed historical record unless its Facebook publication timestamp independently places it in the comparison window.

## Layout

```text
targets/                 tracked-account configuration
incoming/                easiest drop-JSON ingest path
archive/<target>/raw/    immutable gzip snapshots + original-byte SHA-256
data/<target>/            compressed canonical state and event history
scripts/                 ingestion, enrichment, coverage, diff, verification, site build
site/                    static FHSD Transparency Archive UI
tests/                   regression tests
.github/workflows/       validation, automated ingest, optional Pages deployment
```

## Easiest ingest: add JSON to Git

For a full comparable School Watchlist crawl, add the exported JSON to:

```text
incoming/school-watchlist/complete/
```

For an incomplete/short crawl that should only contribute positive observations, use:

```text
incoming/school-watchlist/partial/
```

On `main`, the **Ingest uploaded snapshots** GitHub Action will automatically:

1. run the regression suite;
2. ingest each JSON in chronological filename order;
3. validate that the export actually matches the configured target;
4. preserve a deterministic gzip copy of the original crawl;
5. calculate SHA-256 over the original uncompressed bytes;
6. normalize v6-v10 crawler fields into the canonical archive model;
7. update entities, version history, and change events;
8. apply missing inference only for explicitly complete/comparable coverage;
9. rebuild site indexes;
10. remove the temporary inbox JSON; and
11. commit the generated archive/state update.

This means the normal operating workflow can be as simple as **drag JSON into GitHub → commit**.

See `incoming/README.md` for the exact folder convention.

## Manual/local ingest

A partial observation:

```bash
python -m scripts.ingest --target school-watchlist path/to/facebook-export.json
```

A full comparable observation:

```bash
python -m scripts.ingest --target school-watchlist --complete path/to/full-export.json
```

Then rebuild the browser indexes:

```bash
python -m scripts.build_site
```

Or process the entire inbox locally:

```bash
python -m scripts.ingest_inbox --consume
```

## Run the site locally

```bash
python -m scripts.build_site
python -m http.server 8000 -d site
```

Open `http://localhost:8000`.

## Static deployment

`.github/workflows/pages.yml` contains an opt-in GitHub Pages deployment. Set the repository variable:

```text
ENABLE_PAGES=true
```

and enable GitHub Pages using **GitHub Actions** as its source. The Pages workflow also runs after the automated ingest workflow completes, so a new uploaded snapshot can flow from JSON to a rebuilt/deployed site without another manual build step.

If GitHub Pages is not available for the repository/account configuration, the generated `site/` directory can be served by any static host without changing the data model.

## Backward-compatible crawler ingestion

Current historical data includes older crawler schemas, while future crawls are expected to provide richer v10 metadata. The ingester therefore uses an enrichment adapter rather than requiring historical recrawls.

Where available it preserves:

- stable Facebook post/comment/reply IDs;
- canonical source/parent links;
- author display/profile identity;
- publication timestamps and precision;
- identity confidence;
- capture completeness and expansion state;
- Facebook-visible `Edited` state;
- links, attachment summaries, image alts, and structured media metadata.

Missing fields from older snapshots remain unknown/lower-confidence rather than invalidating the observation.

## Date/coverage-aware missing inference

For date-limited complete crawls, the archive scopes missing detection to the declared `collectionLimit.cutoffDate` through the export date.

- A previously captured post must have a resolvable content date inside the later crawl’s coverage before its absence counts.
- A comment/reply is eligible only when its parent post was actually revisited in the later complete crawl.
- Unknown-date/out-of-coverage records remain preserved but are excluded from negative inference.

This prevents a shallow or non-deterministic Facebook render from turning into a false mass-deletion claim.

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

## Multi-target expansion

`targets/school-watchlist/target.json` is target #1. To add another source, create:

```text
targets/<slug>/target.json
incoming/<slug>/complete/
incoming/<slug>/partial/
```

The ingest and site-build code discovers targets automatically.

## Storage and evidentiary preservation

Raw captures are deterministically gzip-compressed for repository efficiency. The `.sha256` sidecar hashes the **original uncompressed export**, so the exact captured bytes can be reconstructed and verified.

Never commit Facebook authentication cookies, browser profiles, credentials, access tokens, or private session material.

See `docs/ARCHITECTURE.md` for design rationale and `docs/REAL_WORLD_VALIDATION_2026-08-25.md` for the first real-corpus validation work.
