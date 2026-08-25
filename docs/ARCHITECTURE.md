# Architecture

## Multi-target model

The repository tracks a set of independent **targets**. A target can be a public Facebook page, campaign page, spin-off page, or other public source. The diff engine contains no School Watchlist-specific behavior.

Each target has:

- a unique slug (`school-watchlist`);
- one or more source URLs;
- known author aliases;
- crawl/comparison rules;
- its own immutable raw snapshots;
- its own normalized state and event history.

## Data flow

```text
collector export
   ↓
scripts.ingest
   ├── SHA-256 original bytes
   ├── deterministic gzip raw snapshot
   ├── normalize stable entities
   └── compare against prior target state
          ↓
    event history + version history
          ↓
    scripts.build_site
          ↓
    static browser UI
```

## Safe disappearance detection

A post/comment missing from one Facebook render is not sufficient evidence that the page owner removed it. Missing detection is therefore disabled unless the ingestion is explicitly marked `--complete`.

For complete snapshots the state progresses through:

1. `active`
2. `missing_once`
3. `missing_recheck`
4. `confirmed_unavailable` only after a separate verification step

If an item returns, the system emits `reappeared`.

The public interface never substitutes `deleted by <person>` for these observation states without separate evidence.

## Storage

Raw exports are stored as deterministic `.json.gz` files. The accompanying `.sha256` records the hash of the **original uncompressed bytes**, so decompression can reconstruct the exact captured export while keeping Git storage substantially smaller.

Normalized target state is also stored as gzip. The website build expands state into static browser-facing JSON at build time; generated browser data need not be treated as the evidentiary original.

## Future collector

The recommended automatic collector is a local, persistent authenticated Chromium/Playwright session rather than a datacenter-hosted Facebook login. That collector should emit the same exporter schema already accepted by `scripts.ingest`, making collection replaceable without changing archive semantics.
