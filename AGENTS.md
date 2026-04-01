# AGENTS.md — Reefwatch

Instructions for AI agents working on the Reefwatch South China Sea monitoring project.

---

## Project Overview

Reefwatch monitors the Spratly and Paracel Islands (79 features, 5 claimant nations) using free OSINT sources:
- **Satellite imagery** — NASA Worldview (MODIS Terra, 250m)
- **Aircraft tracking** — OpenSky Network (per-feature bounding boxes)
- **Ship monitoring** — AIS URL generation (AISHub when key available)

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

1. **OpenSky free tier**: Rate-limited, limited military aircraft coverage over open ocean
2. **No satellite AIS**: Ship tracking requires paid API for open ocean coverage
3. **250m resolution**: Ships are 2-4 pixels; aircraft barely visible in imagery
4. **Cloud interference**: ~30% of imagery unusable due to clouds in tropics
5. **No night coverage**: MODIS Terra daytime pass only

---

## Skills Installed

- **ctf-osint** — OSINT techniques for geolocation, image analysis, social media
- **flightclaw** — Flight price/route tracking for route verification
- **space-data-processing** — Satellite imagery pipelines, change detection, sharp edges

Consult these skills when working on specific domains within Reefwatch.
