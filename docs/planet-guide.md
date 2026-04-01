# Planet Labs Satellite Imagery Guide

## Overview

Planet Labs provides 3-5m resolution optical imagery via their PSScene product (8-band multispectral).
The visual asset gives a ready-to-use PNG composite. Higher resolution than Sentinel-2 (10m) and
NASA Worldview (250m), making it ideal for detecting construction, vessels, and land reclamation.

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

1. **Search**: POST `/data/v1/quick-search` with geometry, date range, and cloud filter
2. **Select**: Pick best image per day (lowest cloud cover)
3. **Activate**: POST to asset's activate URL (visual asset)
4. **Wait**: Poll asset status until `active` (may take minutes)
5. **Download**: GET the asset location URL → save as PNG

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

- **API Key**: Set `PLANET_API_KEY` env var, or defaults to embedded key
- **Dependencies**: `requests`, `numpy`, `Pillow`, `scikit-image`

## Integration

Planet imagery stats appear in the daily report (`scripts/run_daily_report.py`) alongside
NASA Worldview and aircraft detections. Configuration is in `data/monitoring_config.json`
under `monitoring.imagery.sources.planet_labs`.
