# Snapshot inbox

The simplest production ingest workflow is to add crawler JSON exports here and commit them to `main`.

```text
incoming/
  school-watchlist/
    complete/   # full comparable page pulls; may drive missing detection
    partial/    # short/incomplete pulls; positive observations only
```

For example:

```text
incoming/school-watchlist/complete/School_Watchlist_2024-01-01_2026-08-26_10-48-39.json
```

The `Ingest uploaded snapshots` GitHub Action will:

1. validate the repository;
2. ingest each JSON;
3. preserve an immutable gzip copy and SHA-256 of the original bytes;
4. update canonical entities, versions, and change events;
5. rebuild static site indexes;
6. remove the inbox copy; and
7. commit the generated archive update.

Use `complete/` only when the file is intended to represent a complete comparable crawl. Facebook rendering is not deterministic, so partial pulls must go in `partial/` and cannot mark older records missing.

The same operation can be run locally:

```bash
python -m scripts.ingest_inbox --consume
```
