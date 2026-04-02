# AGENTS.md — Reefwatch

Instructions for AI agents working on the Reefwatch South China Sea monitoring project.

---

## Project Overview

Reefwatch monitors the Spratly and Paracel Islands (77 features, 5 claimant nations) using free OSINT sources:
- **Satellite imagery** — NASA Worldview (MODIS, 250m), Sentinel-2 (10m), Planet Labs (3-5m thumbnails)
- **Aircraft tracking** — OpenSky Network (per-feature bounding boxes)
- **Ship monitoring** — AIS URLs / Global Fishing Watch API (pending permissions)

All scripts are in `scripts/`. Configuration and data in `data/`. Documentation in `docs/`.

---

## Architecture

### Data Flow

```
NASA Worldview ──→ imagery_monitor.py ──→ imagery_history/*.png
                                              │
                                              ├── change_detection (MD5 + size)
                                              └── historical_imagery_log.jsonl

OpenSky API ────→ opensky_sweep.py ────→ detections.jsonl
                   (per-feature bbox)       │
                                            └── aircraft_detections.jsonl

AISHub API ────→ improved_ship_monitor.py ──→ ships_log.jsonl
```

### Key Files

| File | Purpose |
|------|---------|
| `data/scs_features.json` | Master database: 79 SCS features with lat/lon/country |
| `data/target_features.json` | Spratly + Paracel subset (77 features) for scanning |
| `data/monitoring_config.json` | Monitoring zones, bbox, active groups |
| `scripts/quick_check.py` | Fast aircraft scan (<30s, combined bbox) |
| `scripts/opensky_sweep.py` | Periodic sweep — per-feature bbox, 15min interval |
| `scripts/historical_imagery.py` | 90-day satellite imagery backfill with resume |
| `scripts/improved_aircraft_monitor.py` | Multi-source aircraft with dedup |

---

## OSINT Techniques (from ctf-osint skill)

When analyzing satellite imagery or investigating detected activity:

### Image Analysis
- **EXIF/metadata**: `exiftool image.png` for capture time, source
- **Change detection**: Compare images pixel-by-pixel or via MD5 hash
- **Brightness analysis**: `brightness_ratio` in logs indicates cloud cover vs clear imagery
- **Reverse image search**: Google Lens, TinEye for identifying structures
- **Geolocation**: Cross-reference with Google Earth, OpenStreetMap for feature identification

### Geolocation Verification
- Use Plus Codes: `https://plus.codes/` for precise coordinate verification
- Overpass Turbo (OpenStreetMap): Spatial queries for infrastructure
- Google Maps crowd-sourced photos near features
- MGRS coordinates when military references appear

### Social Media / OSINT Monitoring
- Track OSINT accounts on X/Twitter for SCS activity reports
- AMTI (Asia Maritime Transparency Initiative) for construction updates
- Wayback Machine for historical web pages about specific features

---

## Satellite Imagery Processing (from space-data-processing skill)

### Change Detection Pipeline

Follow this pattern when processing satellite imagery:

1. **Select bi-temporal images** — same feature, different dates
2. **Quality assessment** — check cloud cover via brightness_ratio
3. **Radiometric normalization** — compare file sizes as proxy (MODIS TOA)
4. **Apply change detection** — MD5 hash + file size difference
5. **Threshold to binary change** — significant size delta = potential change
6. **Post-processing** — verify changes aren't cloud/artifact

### Sharp Edges to Watch

- **Cloud contamination**: `brightness_ratio > 0.8` likely means clouds — mask or skip
- **No atmospheric correction**: We use Level 1 (TOA) data — surface analysis is approximate
- **Mixed sensors**: Don't compare MODIS Terra with MODIS Aqua without harmonization
- **Night passes**: Some imagery is from night passes — check `analyzable` flag
- **Resolution limits**: 250m MODIS — ships are ~2-4 pixels, aircraft barely visible

### Best Practices
- Always log `brightness_ratio` and `analyzable` status
- Compare same-feature images across dates, not cross-feature
- Use `_latest.png` symlinks for quick current-state checks
- Archive raw imagery — never delete, storage is cheap

### Planet Labs Integration

**API Plan**: Education & Research Basic (thumbnail-only, 256×256)

- **Resolution**: 3-5m (PSScene) thumbnails at 256×256px
- **Search**: Per-feature bbox (±0.05°), cloud_cover < 20%, prefers standard quality
- **Download**: Direct thumbnail URL (no asset activation needed for this plan)
- **Change Detection**: SSIM comparison via `planet_change_detection.py`

**Classification Types** (from SSIM analysis):
- `new_construction` — New structures visible on previously empty ground
- `new_vessel` — Ship/vessel appeared where there was none
- `major_change` — Significant structural changes
- `cloud_interference` — Cloud contamination in comparison

**Note**: Full-resolution (3-5m PNG) requires Planet Analysis or Education Pro plan.

## Manual Download Workflow (Planet Explorer)

Due to Education & Research API plan limitations, full-resolution imagery must be downloaded via the Planet Explorer web UI.

### Current Status

| Feature | API Access | Web UI |
|---------|------------|--------|
| Search (find items) | ✅ Works | ✅ Works |
| Thumbnails (256×256) | ✅ Works | ✅ Works |
| Full-res download (3-5m) | ❌ No permission | ✅ Works |
| Orders API | ❌ No permission | N/A |

### Download Settings for Reefwatch

**Search coordinates (use in Planet Explorer):**

```
Woody Island (Paracel): 16.78-16.88°N, 112.29-112.39°E
Fiery Cross Reef (Spratly): 9.48-9.58°N, 112.83-112.93°E
```

**Recommended settings:**
- Item type: PSScene
- Date range: Last 30 days
- Cloud cover: ≤ 20%
- Product bundle: `visual` (RGB, GeoTIFF, 3-5m resolution)
- File size: ~10-20MB per scene

### Downloaded Files

Place downloaded images in: `imagery_history/`

Naming convention: `{feature_key}_{date}.png` or `{feature_key}_{date}.tif`
- Example: `woody_island_2026-04-02.tif`

### Processing

Once images are downloaded:
1. Run `scripts/planet_change_detection.py` for SSIM comparison
2. Run `scripts/change_detector.py` for broader analysis
3. Check `scripts/alert_engine.py` for notification setup

---



---

## Flight Tracking (from flightclaw skill)

When investigating aircraft near SCS features:

### Route Analysis
- Check IATA/ICAO codes: `https://openflights.org/` for airport lookup
- Flight routes: Use `search-flights.py` to check if a route is commercial
- Common SCS transit routes: Hong Kong ↔ Southeast Asia, China ↔ Australia

### Suspicious Indicators
- Military callsigns (no ICAO match, unusual patterns)
- Loitering patterns (multiple detections at same feature)
- Night operations (detections outside normal flight hours)
- No flight plan (callsign missing or generic)

### Key Airports Near SCS
- **ZGHK** — Woody Island (China-built, Paracel)
- **RPLM** — Mischief Reef (China-built, Spratly)
- **RPLN** — Thitu Island (Philippines)
- **VVTS** — Ho Chi Minh City (Vietnam, nearest major)
- **RPLL** — Manila (Philippines, nearest major)

---

## Monitoring Zones

### Bounding Boxes

```
Spratly Islands:  7.0-12.0°N, 109.0-116.0°E  (56 features)
Paracel Islands:  15.7-17.0°N, 111.0-113.0°E  (21 features)
Combined scan:    7.0-17.0°N, 109.0-116.0°E   (covers both)
```

### Per-Feature Scanning

Each feature gets its own ±0.15° (~16km) bounding box:

```python
bbox = (lat - 0.15, lon - 0.15, lat + 0.15, lon + 0.15)
```

This ensures precise detection — aircraft are attributed to specific islands/reefs.

### Feature Priority

Scan order (high to low strategic value):
1. **Airport features**: Woody, Fiery Cross, Subi, Mischief, Taiping, Thitu, Spratly, Swallow
2. **Helipad features**: Rocky, Cuarteron, Gaven, Hughes, etc.
3. **DK1 platforms**: Vietnam's offshore oil platforms
4. **Remaining features**: Smaller reefs, shoals

---

## Rate Limits

| Source | Limit | Strategy |
|--------|-------|----------|
| OpenSky | 42 req / 10s | 1.0s between feature scans |
| NASA Worldview | No hard limit | 1.5s between requests, exponential backoff |
| ADSB.fi | Unknown | Best-effort, no rate limit imposed |

---

## Adding New Features

To add a new feature to monitoring:

1. Add entry to `data/scs_features.json` under the correct island group
2. Run `python3 -c "import json; ..."` to regenerate `target_features.json`
3. Verify coordinates with satellite imagery
4. Test with `scripts/opensky_once.py` — should detect the new feature

---

## Output Formats

### JSONL Logs
All detection logs are newline-delimited JSON:
- `aircraft_detections.jsonl` — aircraft near features
- `ships_log.jsonl` — ship monitoring (URLs + AIS data)
- `imagery_changes.jsonl` — satellite imagery change events
- `historical_imagery_log.jsonl` — backfill progress

### Imagery
- `imagery_history/{feature}_{date}.png` — raw satellite image
- `imagery_history/{feature}_latest.png` — symlink to most recent

---

## Known Limitations

1. **Planet thumbnails**: Education plan only gives 256×256px — insufficient for detailed ship identification
2. **OpenSky free tier**: Rate-limited, limited military aircraft coverage over open ocean
3. **No satellite AIS**: Ship tracking requires paid API for open ocean coverage
4. **250m resolution**: Ships are 2-4 pixels; aircraft barely visible in MODIS imagery
5. **Cloud interference**: ~30% of imagery unusable due to clouds in tropics
6. **No night coverage**: MODIS Terra daytime pass only

---


---

## Complete Feature List (77 features)

### Paracel Islands (21) — All China

| Feature | Coordinates | Note |
|---------|-------------|------|
| North Reef | 17.07°N, 111.58°E | |
| Tree Island | 16.98°N, 112.27°E | |
| West Sand | 16.97°N, 112.20°E | |
| North Island | 16.96°N, 112.32°E | |
| Middle Island | 16.95°N, 112.25°E | |
| South Island | 16.95°N, 112.23°E | |
| South Sand | 16.95°N, 112.24°E | |
| Woody Island | 16.83°N, 112.34°E | ✈️ Airstrip |
| Rocky Island | 16.80°N, 112.30°E | |
| Robert Island | 16.77°N, 112.18°E | |
| Lincoln Island | 16.67°N, 112.72°E | |
| Drummond Island | 16.63°N, 111.75°E | |
| Yagong Island | 16.58°N, 111.73°E | |
| Observation Bank | 16.55°N, 111.68°E | |
| Quanfu Island | 16.55°N, 111.70°E | |
| Pattle Island | 16.54°N, 111.61°E | |
| Duncan Island | 16.45°N, 111.71°E | |
| Money Island | 16.45°N, 111.51°E | |
| Antelope Reef | 16.45°N, 111.61°E | |
| Bombay Reef | 16.02°N, 112.32°E | |
| Triton Island | 15.78°N, 111.20°E | ✈️ Airstrip |

### Spratly Islands (56)

#### China (7)
| Feature | Coordinates | Note |
|---------|-------------|------|
| Subi Reef | 10.88°N, 114.07°E | ✈️ Airstrip |
| Gaven Reefs | 10.21°N, 114.23°E | |
| Mischief Reef | 9.92°N, 115.51°E | ✈️ Airstrip |
| Hughes Reef | 9.91°N, 114.50°E | |
| Johnson South Reef | 9.72°N, 114.29°E | |
| Fiery Cross Reef | 9.53°N, 112.88°E | ✈️ Airstrip |
| Cuarteron Reef | 8.86°N, 112.83°E | |

#### Vietnam (30)
| Feature | Coordinates | Note |
|---------|-------------|------|
| Song Tu Tay | 11.42°N, 114.33°E | |
| South Reef | 11.40°N, 114.33°E | |
| DK1 - Alexandra Bank | 11.40°N, 112.60°E | Oil platform |
| Petley Reef | 10.42°N, 114.52°E | |
| Sand Cay | 10.37°N, 114.48°E | |
| DK1 - Grainger Bank | 10.33°N, 112.83°E | Oil platform |
| Lansdowne Reef | 10.25°N, 114.38°E | |
| Namyit Island | 10.17°N, 114.37°E | |
| Discovery Great Reef | 10.02°N, 113.85°E | |
| Grierson Reef | 9.90°N, 114.56°E | |
| Sin Cowe Island | 9.88°N, 114.33°E | |
| Alison Reef | 9.83°N, 114.28°E | |
| Collins Reef | 9.77°N, 114.22°E | |
| Pearson Reef A | 8.98°N, 113.71°E | |
| Pearson Reef B | 8.96°N, 113.65°E | |
| DK1 - Prince Consort | 8.95°N, 112.20°E | Oil platform |
| DK1 - Prince of Wales | 8.95°N, 112.83°E | Oil platform |
| Central London Reef | 8.93°N, 112.35°E | |
| East Reef | 8.83°N, 112.62°E | |
| West Reef | 8.83°N, 112.20°E | |
| Cornwallis South Reef | 8.73°N, 114.17°E | |
| Ladd Reef | 8.70°N, 111.70°E | |
| Spratly Island | 8.64°N, 111.92°E | ✈️ Airstrip |
| Barque Canada Reef | 8.10°N, 113.18°E | |
| DK1 - Rifleman Bank | 8.10°N, 111.83°E | Oil platform |
| Amboyna Cay | 7.92°N, 112.92°E | |
| Bombay Castle Shoal | 7.88°N, 111.75°E | |
| Orleana Shoal | 7.70°N, 111.75°E | |
| Kingston Shoal | 7.54°N, 111.55°E | |
| DK1 - Vanguard Bank | 7.33°N, 109.67°E | Oil platform |

#### Philippines (9)
| Feature | Coordinates | Note |
|---------|-------------|------|
| Parola Island | 11.45°N, 114.36°E | |
| Thitu Island | 11.05°N, 114.28°E | ✈️ Airstrip |
| West York Island | 11.03°N, 115.02°E | |
| Flat Island | 10.83°N, 115.83°E | |
| Lawak Island | 10.73°N, 115.80°E | |
| Loaita Cay | 10.67°N, 114.37°E | |
| Kota Island | 10.67°N, 114.42°E | |
| Second Thomas Shoal | 9.75°N, 115.83°E | |
| Maya-maya | 8.36°N, 115.24°E | |

#### Malaysia (9)
| Feature | Coordinates | Note |
|---------|-------------|------|
| Station Sierra Helipad | 8.10°N, 114.14°E | |
| Erica Reef | 8.10°N, 114.10°E | |
| Investigator Shoal | 8.08°N, 114.67°E | |
| Commodore Reef | 8.00°N, 114.17°E | |
| Station Mike Helipad | 7.97°N, 113.92°E | |
| Ardasier Reef | 7.62°N, 113.97°E | |
| Dallas Reef | 7.62°N, 113.85°E | |
| Mariveles Reef | 7.62°N, 113.53°E | |
| Swallow Reef | 7.37°N, 113.85°E | ✈️ Airstrip |

#### Taiwan (1)
| Feature | Coordinates | Note |
|---------|-------------|------|
| Taiping Island | 10.38°N, 114.36°E | ✈️ Airstrip |

### Airstrips (7 total)
- China: Fiery Cross, Subi, Mischief (3)
- Vietnam: Spratly Island (1)
- Philippines: Thitu Island (1)
- Malaysia: Swallow Reef (1)
- Taiwan: Taiping Island (1)
- Paracel: Woody Island, Triton Island (2)


## Skills Installed

- **ctf-osint** — OSINT techniques for geolocation, image analysis, social media
- **flightclaw** — Flight price/route tracking for route verification
- **space-data-processing** — Satellite imagery pipelines, change detection, sharp edges

Consult these skills when working on specific domains within Reefwatch.
