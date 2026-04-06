# Planet Labs Satellite Imagery Guide

## Overview

Planet Labs provides 3-5m resolution optical imagery via their PSScene product (8-band multispectral).
For the current ReefWatch workflow, treat Planet as an **optional enrichment source** layered on top of free imagery.
The repo currently supports **search + thumbnail download** safely; do not assume full-resolution asset access.

**Current supported path in repo:**
- search PSScene scenes via Data API
- download thumbnail imagery when available
- run local change detection over saved thumbnails
- keep all auth local via environment or `.env` only

**API:** `https://api.planet.com/data/v1`
**Item type:** PSScene (3-5m, 8-band multispectral)
**Auth:** Basic auth with API key as username
**Cloud filter:** ≤ 20%

## Quick Start

```bash
# Fetch imagery for a single feature (last 14 days)
python3 scripts/planet_fetch.py --feature fiery_cross_reef --days 14

# Fetch all 77 features
python3 scripts/planet_fetch.py --all --days 30

# Custom location
python3 scripts/planet_fetch.py --lat 9.53 --lon 112.88 --name "Fiery Cross" --days 7

# Specific date range
python3 scripts/planet_fetch.py --feature woody_island --start-date 2026-03-01 --end-date 2026-03-31

# Resume interrupted download session
python3 scripts/planet_fetch.py --all --days 30 --resume

# Secret-safe config check (does not print the API key)
python3 scripts/planet_fetch.py --config-check
```

## Change Detection

```bash
# Compare all consecutive Planet image pairs
python3 scripts/planet_change_detection.py --all

# Compare for a specific feature
python3 scripts/planet_change_detection.py --feature fiery_cross_reef

# Compare two specific images
python3 scripts/planet_change_detection.py --image1 img1.png --image2 img2.png
```

### Output

- **SSIM score**: 1.0 = identical, lower = more change
- **Pixel diff %**: Mean absolute pixel difference
- **Brightness change %**: Overall brightness shift (cloud indicator)
- **Change types**: `new_construction`, `new_vessel`, `major_change`, `significant_change`, `cloud_interference`
- **Diff visualization**: Side-by-side [Before | After | Diff Heatmap] saved as PNG

### Change Classification

| Change Type | Trigger | Meaning |
|---|---|---|
| `new_construction` | Dark→light transitions, >10% pixel diff | New structures/buildings |
| `new_vessel` | Small bright spots in water areas | Ship/boat presence |
| `major_change` | >10% pixel diff, SSIM < 0.85 | Large structural change |
| `significant_change` | >3% pixel diff, SSIM < 0.92 | Notable change |
| `cloud_interference` | >15% brightness change, SSIM > 0.85 | Clouds (likely false positive) |

## Test Features

The 5 priority test features:

| Feature | Key | Lat | Lon |
|---|---|---|---|
| Fiery Cross Reef | `fiery_cross_reef` | 9.53 | 112.88 |
| Subi Reef | `subi_reef` | 10.88 | 114.07 |
| Mischief Reef | `mischief_reef` | 9.921 | 115.506 |
| Woody Island | `woody_island` | 16.83 | 112.33 |
| Thitu Island | `thitu_island` | 11.05 | 114.28 |

## API Workflow

### Current repo workflow (implemented)

1. **Search**: POST `/data/v1/quick-search` with geometry, date range, cloud filter, and optional quality-category filter
2. **Select**: Pick best image per day (prefer standard quality, then lowest cloud cover)
3. **Download thumbnail**: use the scene `_links.thumbnail` URL when present
4. **Save locally**: write `{feature_key}_planet_{date}.png` to `imagery_history/`
5. **Compare**: run `planet_change_detection.py` on saved thumbnails

### Deferred / plan-dependent workflow

Asset activation and full-resolution downloads should be treated as plan-dependent and not assumed by default.
If a higher-tier Planet plan is later confirmed, document that separately instead of overloading the thumbnail path.

## Rate Limits

- 1 second between all API requests
- Asset activation can take 1-5 minutes
- Respects 429 responses with automatic 10s backoff

## File Naming

- Planet images: `{feature_key}_planet_{date}.png` (e.g., `fiery_cross_reef_2026-03-15.png`)
- Diff visualizations: `diff_{img1_name}_to_{img2_name}.png`
- Fetch log: `planet_fetch_log.jsonl`
- Change log: `planet_changes.jsonl`

## Environment

- **API Key**: Set `PLANET_API_KEY` in the environment or a local `.env` file
- **Template**: Copy `.env.example` → `.env` and replace the placeholder with a real local key
- **Validation**: `planet_fetch.py` now rejects placeholder values like `your_planet_api_key_here` up front so auth failures are explicit
- **Quality control**: optional `PLANET_QUALITY=standard|test` is loaded from env or local `.env` and applied directly to Planet search filters
- **Security**: No real key should be committed to the repo; `.env` is gitignored
- **Operational rule**: secret/config health should only report whether a key is configured, never the key value itself
- **Export safety rule**: any app-facing export or debug payload derived from Planet logs must strip or redact auth-like fields (`api_key`, `authorization`, `token`, `secret`, etc.) before writing to `derived/`
- **Dependencies**: `requests`, `numpy`, `Pillow`, `scikit-image`

## Integration

Planet imagery stats appear in the daily report (`scripts/run_daily_report.py`) alongside
NASA Worldview and aircraft detections. Configuration is in `data/monitoring_config.json`
under `monitoring.imagery.sources.planet_labs`.

For the MVP app/export layer, run:

```bash
python3 scripts/export_mvp_snapshot.py
```

This emits `derived/source_health.json`, which reports Planet config status in a secret-safe way (`configured: true/false`) by checking the current environment and local `.env`, without ever writing the key value.
