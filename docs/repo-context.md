# ReefWatch Repo Context

This is the shortest path to understanding what ReefWatch is, how the repo is organized, and what should stay stable while the product is still script-first.

## 1) Product Direction

ReefWatch is not trying to be a generic geospatial platform.

It should stay focused on:

- **feature-centric monitoring** of disputed South China Sea reefs / islands / outposts
- **change over time**, not one-off screenshots
- **reviewable evidence**, not black-box conclusions
- **optional commercial enrichment** (Planet), not hard dependency on paid access

The MVP should answer:

1. What changed?
2. Where did it change?
3. How confident are we that it matters?

Canonical product docs:

- `docs/product-direction.md`
- `docs/mvp-data-model-and-screens.md`

## 2) Current Repo Shape

The repo is still **script-first**.

### Inputs

- `data/target_features.json` — canonical monitored feature set
- `data/monitoring_config.json` — monitoring configuration
- `imagery_history/` — downloaded imagery artifacts (gitignored)
- `*_log.jsonl` / `*_detections.jsonl` — raw-ish collection outputs

### Bridge Layer

- `scripts/export_mvp_snapshot.py`
- `scripts/validate_mvp_snapshot.py`

These convert the current scripts into a stable app-facing contract in `derived/`.

### App-Facing Outputs

- `derived/features.jsonl`
- `derived/scenes.jsonl`
- `derived/changes.jsonl`
- `derived/traffic.jsonl`
- `derived/notes.jsonl`
- `derived/feature_status.jsonl`
- `derived/review_queue.json`
- `derived/overview.json`
- `derived/source_health.json`

If you change the bridge layer, preserve this contract unless you also update the docs intentionally.

## 3) MVP Screens To Keep Designing Around

1. **Overview / Daily Brief**
2. **Feature List**
3. **Feature Detail**
4. **Change Review Queue**
5. **Source Health / Ingest Status**

These are documented in `docs/mvp-data-model-and-screens.md` and should remain the north star for export/API work.

## 4) Planet Integration Rules

Planet is useful, but it should remain an **optional enrichment layer**.

### Allowed / expected

- search PSScene scenes
- download thumbnails when available
- run local change detection on saved thumbnails
- report only **secret-safe config health** in derived outputs

### Not safe to assume

- full-resolution asset access
- stable entitlement to paid Planet capabilities
- committing any Planet credential into the repo

### Secret-handling rules

- real `PLANET_API_KEY` must only live in local environment or local `.env`
- `.env` stays gitignored
- `.env.example` must stay placeholder-only
- reports / exports / validation output must never print the key

Useful commands:

```bash
python3 scripts/planet_fetch.py --config-check
python3 scripts/export_mvp_snapshot.py
python3 scripts/validate_mvp_snapshot.py
```

## 5) Recommended Near-Term Work

1. keep product/docs/repo context aligned
2. keep `derived/` stable for a future UI/API layer
3. improve analyst-review ergonomics before adding more sources
4. expand Planet only in ways that stay optional and secret-safe

## 6) Definition of “Good” For Now

A good ReefWatch run should leave behind:

- a current feature-centric snapshot
- a manageable review queue
- traceable source references
- no secret leakage
- enough context that someone can resume work quickly tomorrow
