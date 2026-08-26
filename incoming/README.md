# Snapshot inbox

Drop crawler JSON exports into one of two shared folders. **Do not create a folder per target.**

```text
incoming/
  complete/   # full comparable pulls; may drive missing detection
  partial/    # short/incomplete pulls; positive observations only
  rejected/   # quarantine for files that cannot be safely routed/validated
```

For example:

```text
incoming/complete/School_Watchlist_2024-01-01_2026-08-26_10-48-39.json
incoming/complete/Greenwood_for_FHSD_School_Board_2025-01-01_2026-08-26_11-02-15.json
```

The inbox processor determines the target automatically. Routing priority is:

1. explicit target ID in the export, when present;
2. stable Facebook profile ID / source URL found in the export;
3. declared target author matched against configured aliases;
4. configured filename aliases as fallback.

Filename evidence never overrides conflicting Facebook/profile identity. Ambiguous, malformed, or conflicting files are moved to `incoming/rejected/` with a `.reason.txt` sidecar rather than contaminating an archive.

Files are processed by the export's `exportedAt` timestamp, oldest first. This means multiple snapshots can be dropped into the inbox together; the baseline and later deltas are applied in chronological order.

The `Ingest uploaded snapshots` GitHub Action will:

1. run regression tests;
2. auto-route each JSON to its configured target;
3. validate complete snapshots before allowing missing inference;
4. preserve an immutable gzip copy and SHA-256 of the original bytes;
5. update canonical entities, versions, and change events;
6. rebuild static site indexes;
7. remove successfully processed inbox copies; and
8. commit the generated archive update.

Uploading the exact same raw snapshot twice is safe: duplicate SHA-256 snapshots are a no-op for archive state.

Use `complete/` only when the file represents a complete comparable crawl. Facebook rendering is not deterministic, so partial pulls belong in `partial/` and cannot mark older records missing.

Run the same operation locally with:

```bash
python -m scripts.ingest_inbox --consume
```

After it finishes, serve the rebuilt site with:

```bash
python -m http.server 8000 -d site
```
