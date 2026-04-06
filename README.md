# 🏝️ Reefwatch

South China Sea satellite monitoring system — tracking construction, aircraft, and vessel activity across the Spratly and Paracel Islands using free open-source intelligence.

## Features

- **Satellite Imagery** — NASA Worldview (MODIS Terra, 250m) with daily change detection
- **Aircraft Tracking** — OpenSky Network multi-source with per-feature bounding boxes
- **Ship Monitoring** — AIS URL generation for MarineTraffic/VesselFinder
- **Historical Backfill** — 90-day imagery archive (Jan–Apr 2026) for all 79 SCS features
- **Per-Feature Scanning** — Each island/reef gets its own bounding box for precise detection

## Data Sources

| Source | Type | Cost |
|--------|------|------|
| NASA Worldview | Satellite imagery | Free |
| OpenSky Network | Aircraft positions | Free (rate limited) |
| ADSB.fi | Aircraft positions | Free (limited SCS coverage) |
| AISHub | Ship AIS data | Free (registration required) |

## Product Direction

ReefWatch should be treated as a **feature-centric monitoring workflow** for South China Sea change detection:
- prioritize strategic features over map-wide bulk noise
- keep imagery, traffic observations, and analyst notes tied to each feature
- make Planet imagery optional, higher-resolution enrichment rather than a hard dependency

See:
- `docs/product-direction.md`
- `docs/mvp-data-model-and-screens.md`

## Quick Start

```bash
# Aircraft check (Spratly + Paracel)
python3 scripts/quick_check.py

# Full multi-source aircraft scan (per-feature)
python3 scripts/improved_aircraft_monitor.py

# Daily imagery check
python3 scripts/daily_imagery_check.py

# Ship monitoring (generates AIS URLs)
python3 scripts/improved_ship_monitor.py

# Historical imagery status
python3 scripts/historical_imagery.py --status
```

## Project Structure

```
reefwatch/
├── scripts/              # All monitoring scripts
│   ├── quick_check.py           # Fast aircraft scan (<30s)
│   ├── improved_aircraft_monitor.py  # Multi-source aircraft tracking
│   ├── improved_ship_monitor.py      # Ship/AIS monitoring
│   ├── imagery_monitor.py           # Satellite imagery change detection
│   ├── daily_imagery_check.py       # Daily Spratly imagery
│   ├── historical_imagery.py        # 90-day imagery backfill
│   ├── opensky_once.py              # Single OpenSky scan
│   ├── opensky_sweep.py             # Periodic OpenSky sweep
│   └── ...
├── data/                 # Configuration and feature database
│   ├── scs_features.json          # 79-feature database
│   ├── target_features.json       # Spratly+Paracel target list
│   ├── monitoring_config.json     # Monitoring configuration
│   └── ship_urls.json             # Ship monitoring URLs
├── docs/                 # Documentation
│   ├── data-sources-report.md     # Source evaluation
│   ├── osint-sources.md           # OSINT references
│   └── ...
├── imagery_history/      # Historical satellite images (gitignored)
└── README.md
```

## Monitoring Target

**Spratly + Paracel Islands** — 77 features across 5 claimants:
- 🇨🇳 China (28 features)
- 🇻🇳 Vietnam (30 features)  
- 🇵🇭 Philippines (9 features)
- 🇲🇾 Malaysia (9 features)
- 🇹🇼 Taiwan (2 features)

## Limitations

- OpenSky free tier: rate-limited (42 requests/10s), limited military coverage
- ADSB.fi: sparse receivers over open ocean
- Ships: requires paid AIS API for live data
- Free imagery sources are lower resolution than commercial tasking products
- Planet integration requires a locally configured `PLANET_API_KEY` and should never rely on committed secrets

## License

MIT
