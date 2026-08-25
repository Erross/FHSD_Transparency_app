# Real-world snapshot validation — 25 August 2026

This note records the first two School Watchlist exports used to validate the archive/diff engine against real Facebook rendering behavior.

## Snapshot A — baseline

- Exported: `2026-08-25T17:31:58.041Z`
- Declared target: `School Watchlist`
- Collection mode: date cutoff `2024-01-25`
- Items: **1,291**
  - Posts: **238**
  - Comments/replies: **1,053**
- Original export SHA-256: `b3d2e2f2b61ff328ac5a8ea1bc980da53678a592679cb87a5b1c48d6b437abf5`
- Archive treatment: complete baseline; no `new` events generated for baseline contents.

## Snapshot B — later partial observation

- Exported: `2026-08-25T21:51:38.286Z`
- Declared target: `Greenwood for FHSD School Board`
- Observed page/profile: School Watchlist (`61581121856469`)
- Collection mode: date cutoff `2026-06-01`
- Items: **16**
  - Posts: **8**
  - Comments/replies: **8**
- Original export SHA-256: `da659421f29ddeb94f16483cdf64963f475d6a746179c6f8ea65a4cecb739f97`
- Archive treatment: **partial observation only**. The declared target does not match the observed School Watchlist page, so the ingest guard refuses to use this snapshot for missing/deletion inference.

## Observed A → B delta

After normalizing Facebook UI chrome and parent-post aliases:

- **2 genuinely first-observed entities** are added:
  1. School Watchlist post `122137527543037395`, beginning `URGENT: School Board Members Celebrating Calls for Violence Against a Parent`.
  2. Comment `1381832203395635` by Jen Olson, asking whether a post had been deleted.
- **0 confirmed authored-text edits** were detected among overlapping entities.
- Missing/deletion detection was **not run**, because Snapshot B is not a complete comparable crawl.

## Rendering noise found in the real pair

The first real comparison exposed several things that must not be mistaken for edits:

- relative comment ages changed (`17h` → `22h`, `16h` → `20h`);
- reaction totals changed (`LikeReply8` → `LikeReply9`);
- a full post body later appeared collapsed behind `… See more`;
- `See less` is Facebook UI chrome, not authored text.

The diff engine now strips/handles these before comparing authored content.

## Parent-post ID alias found

Two stable comments retained the same comment IDs across both exports:

- `1665841231926084`
- `2211878879545335`

But their parent thread changed from:

`pfbid0DsBdq1vRb3X1hjWAcFqnPCoi9D2VUBR4BJmge1XXXd13iFRTKKEu7jsTz5CuYmmVl`

to:

`pfbid02HEfpT3H3cZj7yuEVx6q5p8huLX6NSEiXLp1uFECYc5ggkC2RZQmxXf5hNswb62tfl`

The School Watchlist post text is the same schedule-change post. The archive therefore treats the later parent ID as an alias of the first-seen thread rather than creating a second thread.

## Design consequence

A Facebook `story_fbid` cannot be treated as perfectly immutable in this collection pipeline. Stable comment IDs are used as stronger cross-snapshot evidence when reconciling parent-thread aliases.

Likewise, an export is never eligible to mark previously seen records missing merely because it has a date cutoff. It must also pass target validation and be explicitly ingested as a complete comparable crawl.
