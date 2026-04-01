# Sentinel-2 Satellite Imagery Guide

## Overview

Sentinel-2 provides 10m resolution optical imagery (4× sharper than MODIS 250m).
Data is free from ESA via the Earth Search STAC API — no auth required.

**API:** `https://earth-search.aws.element84.com/v1`
**Collection:** `sentinel-2-l2a` (surface reflectance, atmospherically corrected)
**Revisit time:** ~5 days (not every day has imagery)
**Resolution:** 10m (red, green, blue, NIR), 20m (red edge, SWIR)

## Quick Start

```bash
# Fetch imagery for a single feature (last 7 days)
python3 scripts/sentinel2_fetch.py --feature fiery_cross_reef

# Fetch all features
python3 scripts/sentinel2_fetch.py --all --days 30

# Custom location
python3 scripts/sentinel2_fetch.py --lat 9.53 --lon 112.88 --name "Fiery Cross" --days 14

# Resume interrupted download
python3 scripts/sentinel2_fetch.py --feature woody_island --days 30 --resume
```

## Change Detection

```bash
# Auto-compare all consecutive image pairs
python3 scripts/sentinel2_change_detection.py --auto

# Compare specific feature
python3 scripts/sentinel2_change_detection.py --feature fiery_cross_reef

# Compare two specific images
python3 scripts/sentinel2_change_detection.py --image1 img1.png --image2 img2.png
```

### Output

- **SSIM score**: 1.0 = identical, lower = more change
- **Pixel diff %**: Mean absolute pixel difference
- **NDVI change**: Vegetation index proxy from RGB
- **Change level**: minimal (>0.95), low (0.85-0.95), moderate (0.70-0.85), significant (<0.70)
- **Visualization**: Diff heatmap overlay saved as PNG

## How It Works

### Fetch Script (`sentinel2_fetch.py`)

1. Queries Earth Search STAC API by bbox + date range
2. Groups results by date, picks lowest cloud cover per day
3. Uses **COG windowed reads** — reads only the area of interest (~5km bbox) directly from S3-hosted Cloud Optimized GeoTIFFs. No full tile download needed.
4. Falls back to thumbnail if COG read fails
5. Saves 512×512 RGB composite PNGs to `imagery_history/`

### Change Detection (`sentinel2_change_detection.py`)

1. Loads two PNGs resized to 1024×1024
2. Computes SSIM via scikit-image
3. Computes NDVI proxy (green-red ratio from RGB, since NIR band isn't in RGB composites)
4. Generates blended diff heatmap visualization
5. Logs to `sentinel2_changes.jsonl`

## Output Files

- `imagery_history/{feature}_sentinel2_{date}.png` — RGB composites
- `imagery_history/{feature}_diff_{date1}_vs_{date2}.png` — Change heatmaps
- `sentinel2_fetch_log.jsonl` — Fetch log
- `sentinel2_changes.jsonl` — Change detection log

## Dependencies

```
pip3 install pystac-client rasterio scikit-image pillow numpy requests pyproj
```

## Limitations

- ~5-day revisit: some dates have no coverage
- Cloud cover: many scenes >80% cloudy (tropics)
- RGB composites don't include NIR directly (use separate NIR band for true NDVI)
- COG windowed reads require network bandwidth (~few MB per band for small windows)
- Thumbnail fallback is low resolution

## API Details

No authentication needed. Rate limits are generous. The STAC API supports:
- Bounding box search
- Date range filtering
- Cloud cover sorting
- Collection filtering

Example STAC query:
```
GET https://earth-search.aws.element84.com/v1/search
  ?collections=sentinel-2-l2a
  &bbox=112.83,9.48,112.93,9.58
  &datetime=2026-03-26/2026-04-01
  &limit=10
```

## Sentinel-2 Bands (L2A)

| Band | Name | Resolution | Use |
|------|------|-----------|-----|
| B02 | Blue | 10m | True color |
| B03 | Green | 10m | True color, vegetation |
| B04 | Red | 10m | True color, NDVI |
| B08 | NIR | 10m | NDVI, vegetation |
| B05-B07 | Red Edge | 20m | Vegetation classification |
| B11-B12 | SWIR | 20m | Water, burn scars |

## Adding New Features

Edit `data/scs_features.json` — the fetch script auto-discovers all features with lat/lon coordinates.
