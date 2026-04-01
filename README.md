# 🏝️ Reefwatch

South China Sea satellite monitoring system — tracking construction, aircraft, and vessel activity across the Spratly Islands using free open-source intelligence.

## Features

- **Satellite Imagery** — NASA Worldview (MODIS Terra, 250m) with daily change detection
- **Aircraft Tracking** — OpenSky Network + ADSB.fi multi-source deduplication
- **Ship Monitoring** — AIS URL generation for MarineTraffic/VesselFinder (AISHub ready)
- **Historical Backfill** — 90-day imagery archive (Jan–Apr 2026) for all 79 SCS features
- **Spratly Focus** — Bbox: 7–12°N, 109–116°E

## Data Sources

| Source | Type | Cost |
|--------|------|------|
| NASA Worldview | Satellite imagery | Free |
| OpenSky Network | Aircraft positions | Free (rate limited) |
| ADSB.fi | Aircraft positions | Free (limited SCS coverage) |
| AISHub | Ship AIS data | Free (registration required) |

## Quick Start

```bash
# Aircraft check
python3 quick_check.py

# Full multi-source aircraft scan
python3 improved_aircraft_monitor.py

# Daily imagery check
python3 daily_imagery_check.py

# Ship monitoring (generates AIS URLs)
python3 improved_ship_monitor.py

# Historical imagery status
python3 historical_imagery.py --status
```

## Monitoring Target

**Spratly Islands** (7–12°N, 109–116°E) — 56 features across 5 claimants:
- 🇨🇳 China (28 features)
- 🇻🇳 Vietnam (30 features)  
- 🇵🇭 Philippines (9 features)
- 🇲🇾 Malaysia (9 features)
- 🇹🇼 Taiwan (2 features)

## Scripts

| Script | Purpose |
|--------|---------|
| `quick_check.py` | Fast aircraft scan (<30s) |
| `improved_aircraft_monitor.py` | Multi-source aircraft tracking |
| `improved_ship_monitor.py` | Ship/AIS monitoring |
| `imagery_monitor.py` | Satellite imagery change detection |
| `daily_imagery_check.py` | Daily Spratly imagery |
| `historical_imagery.py` | 90-day imagery backfill |
| `scs_features.json` | 79-feature database |
| `monitoring_config.json` | Monitoring configuration |

## Limitations

- OpenSky free tier: rate-limited, limited military coverage
- ADSB.fi: sparse receivers over open ocean
- Ships: requires paid AIS API for live data
- Imagery: 250m resolution (ships visible as dots, not identifiable)

## License

MIT
