# Architecture

## Product boundary

This repository is the **archive / normalization / change-detection / presentation layer**. It does not need to own Facebook authentication or crawling.

The current source collector is a separate Chrome/Edge MV3 extension that exports content legitimately rendered in the user's current signed-in Facebook session. The archive accepts those exports as observations and deliberately keeps collection replaceable.

```text
browser collector
  "what is visible right now?"
          ↓
immutable raw snapshot
          ↓
archive ingest / enrichment
          ↓
canonical entities + versions
          ↓
coverage-aware change engine
          ↓
manual/direct review when needed
          ↓
static FHSD Transparency Archive
```

This separation is intentional: if Facebook changes its DOM or the collector improves, old snapshots can be re-normalized without rewriting the original capture.

## Multi-target model

The repository tracks a set of independent **targets**. A target can be a public Facebook page, campaign page, spin-off page, public figure, PAC, or another prominent public source. The diff engine contains no School Watchlist-specific behavior.

Each target has:

- a unique slug (`school-watchlist`);
- one or more source URLs;
- known author aliases;
- crawl/comparison rules;
- its own immutable raw snapshots;
- its own normalized state and event history.

## Data flow

```text
collector export (v6-v10+)
   ↓
scripts.ingest
   ├── validate configured target
   ├── SHA-256 original bytes
   ├── deterministic gzip raw snapshot
   ├── normalize stable entities
   ├── enrich optional crawler evidence
   └── compare against prior target state
          ↓
    entity state + event/version history
          ↓
    scripts.build_site
          ↓
    static browser indexes/UI
```

`incoming/<target>/complete|partial/` and `scripts.ingest_inbox` provide the operational wrapper for simply dropping exported JSON into Git.

## Canonical identity

The archive uses the strongest identity available rather than relying on body text alone.

Posts prefer:

1. Facebook post/story ID;
2. canonical permalink;
3. crawler entity key;
4. conservative fingerprint fallback.

Comments/replies prefer:

1. Facebook comment/reply ID;
2. exact comment permalink;
3. crawler entity key;
4. fingerprint fallback.

An identity-quality/confidence field is preserved so the public/archive logic can distinguish a stable Facebook identity from a weaker historical match.

Stable comment IDs also help reconcile cases where Facebook/crawler URL recovery returns a different `story_fbid` for the same discussion in a later observation.

## Content versions

Facebook interface text is not authored content. Before comparing versions, the normalizer removes known presentation noise such as:

- relative-age prefixes;
- Like/Reply UI labels;
- changing reaction/count chrome;
- `See more` / `See less` controls.

A truncated `See more` capture later becoming fully expanded is treated as capture enrichment, not an authored edit.

Future v10 crawler fields such as `bodyComplete`, expansion results, `facebookEdited`, publication precision, and structured media are preserved by the enrichment adapter but are not required for older snapshots.

## Safe disappearance detection

A post/comment missing from one Facebook render is not sufficient evidence that the page owner removed it. Missing detection is disabled unless ingestion is explicitly marked `--complete`.

For complete comparable snapshots, the lifecycle is:

1. `active`
2. `missing_once`
3. `missing_recheck`
4. `confirmed_unavailable` only after a separate direct/manual verification

If an item returns, the system emits `reappeared`.

The public interface never substitutes `deleted by <person>` for these observation states without independent evidence.

## Date/coverage safety

A declared date cutoff defines only the region a complete crawl was expected to cover.

For date-scoped complete comparisons:

- a prior post is eligible for missing inference only when its content date is resolvable and falls inside the later crawl's window;
- a prior comment/reply is eligible only when its parent post was actually observed in the later complete crawl;
- unknown-date posts, out-of-window posts, and comments whose parents were not revisited are deferred rather than marked missing.

This is necessary because Facebook comment rendering is non-deterministic and because a crawler can improve between snapshots.

## First observed vs newly published

The archive keeps two separate concepts:

- **archive observation time** — when our collector first captured the entity;
- **publication evidence** — the Facebook date/time available for the underlying content.

A record newly recovered by a deeper crawl is therefore not automatically described as newly published. The public site only elevates a record to a stronger "newly published" presentation when publication evidence supports that conclusion; otherwise it remains "first observed".

## Public authors / people index

The public people index is derived only from authors already present in captured public material.

Where Facebook/crawler evidence supplies a stable profile/page ID, it is preferred over display-name strings. This is especially important for page attribution variants such as `School Watchlist is with ...`, which should remain one page identity.

The archive does not infer ideology, private contact details, or other personal attributes from ordinary commenters.

## Storage

Raw exports are stored as deterministic `.json.gz` files. The accompanying `.sha256` records the hash of the **original uncompressed bytes**, so decompression can reconstruct the exact captured export while keeping Git storage substantially smaller.

Normalized target state is also stored as gzip. The website build expands state into static browser-facing JSON; those generated presentation indexes are reproducible derivatives, not the evidentiary original.

## Static site

The MVP needs no production database server or API. `scripts.build_site` generates browser-consumable indexes for:

- tracked targets;
- canonical entities;
- event history;
- snapshot history;
- per-post discussion counts;
- public-author/comment indexes;
- latest comparison summary.

The site can be served by GitHub Pages or any ordinary static host.

## Manual/direct verification

`python -m scripts.verify_missing` records a separate visibility check for a candidate missing entity. This audit event is what permits the stronger `confirmed_unavailable` public status.

The intended future collector-side Verification Mode can accept a small list of canonical Facebook URLs and return `VISIBLE / UNAVAILABLE / ACCESS_DENIED / UNKNOWN`; normal history crawls should not repeatedly reopen every old permalink because that would destroy performance.
