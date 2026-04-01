# SCS Monitoring — Data Sources Report

**Date:** 2026-04-01  
**Status:** Evaluation complete — working scripts deployed

---

## Aircraft Tracking Sources

### ✅ OpenSky Network — WORKING (Primary Source)
- **Endpoint:** `https://opensky-network.org/api/states/all`
- **Coverage:** Excellent for SCS with wide bbox (5-25°N, 105-125°E)
- **Result:** **220 aircraft** detected in initial scan
- **Data:** ICAO24, callsign, country, lat/lon, altitude, speed, heading, squawk
- **Rate limit:** ~42 requests/10s (free tier), we use 1 req/s
- **Tracks:** `https://opensky-network.org/api/tracks/all` also works for individual aircraft
- **Historical:** NOT available on free tier (403 error)
- **Apt airports:** Arrivals/departures endpoints blocked on free tier
- **Best for:** Real-time aircraft positions in the entire SCS
- **Limitation:** Requires ADS-B transponder — military aircraft may not appear

### ⚠️ ADSB.fi (opendata) — Limited SCS Coverage
- **Endpoint:** `https://opendata.adsb.fi/api/v2/lat/{lat}/lon/{lon}/dist/{nm}`
- **Coverage:** Good in populated areas, **poor in SCS** (few receivers near Spratlys)
- **Result:** 0 aircraft detected at 6 SCS center points
- **Best for:** Backup source, may improve as receiver network grows
- **Note:** The code tries 6 points and works when data is available

### ❌ ADSB Exchange (Official API) — Paid Only
- **Status:** 402 — requires paid enterprise API
- **Free alternative:** `adsb.fi` open data above (community feed, same data type)

### ❌ Flightradar24 — Blocked
- **Status:** API endpoints return empty data or require browser cookies
- **Scraping:** Blocked by anti-bot protections

### ❌ AviationStack — Requires API Key
- **Status:** 401 without valid key; free tier requires registration
- **Free tier:** 100 requests/month (would be enough for monitoring)
- **Decision:** Not registering for external services per instructions

### ❌ RadarBox / Planespotters — Blocked
- **Status:** Both return 403 or redirect to login

---

## Ship Tracking Sources

### ❌ AISHub — Requires Free Registration
- **Endpoint:** `https://data.aishub.net/ws.php`
- **Status:** Returns empty body without valid username/key
- **Free tier:** Available after free registration at aishub.net
- **Coverage:** Community AIS receivers worldwide, good SCS coverage
- **Data:** MMSI, name, lat/lon, speed, heading, vessel type, dimensions, draught, destination
- **Action needed:** Register at https://www.aishub.net/ and configure `--aishub YOUR_KEY`
- **Best for:** Real-time AIS vessel positions

### ❌ MarineTraffic — Blocked/Paid
- **Website:** Blocked by Cloudflare (403)
- **API:** Requires paid API key (API calls: `DEMO` → 401 SERVICE KEY NOT FOUND)
- **Free features:** URL generation only (already implemented in ship_urls.json)
- **URLs generated:** Map views and density maps for 24 port/anchorage locations

### ❌ VesselFinder — Paid API
- **Website:** HTML loads but API endpoints return 404/require paid credits
- **API:** Credit-based system, no free tier
- **Free features:** URL generation for map views (implemented)

### ❌ Global Fishing Watch — Requires Auth
- **Status:** 401 without authorization token
- **Data available:** Fishing vessel tracks (good for monitoring Chinese fishing fleets in SCS)

### ❌ MyShipTracking — No Working API
- **Status:** API endpoint returns 404

---

## Working Scripts

### `improved_aircraft_monitor.py`
- Multi-source aircraft scan over wide SCS bbox
- OpenSky + ADSB.fi with deduplication
- Maps aircraft to nearest SCS feature (79 features)
- Flight track enrichment available (`--tracks` flag)
- Saves to `improved_aircraft_log.jsonl`
- Summary view: `--summary`
- **Tested:** ✅ Detected 220 aircraft, 3.8s scan time

### `improved_ship_monitor.py`
- Multi-source vessel tracking (AISHub + OpenSky aircraft near ports)
- Generates monitoring URLs for 24 SCS port/anchorage locations
- AISHub integration ready (just needs API key)
- Monitors for aircraft near port areas (maritime patrol detection)
- Saves to `improved_ship_log.jsonl`
- Summary view: `--summary`
- URL generation: `--urls`
- **Tested:** ✅ URLs generated, scan logic works, awaiting AISHub key for AIS data

### Original scripts (still work, unchanged)
- `aircraft_monitor.py` — Per-feature OpenSky checks
- `ship_monitor.py` — URL generation + AISHub check
- `quick_check.py` — Fast SCS aircraft scan with feature mapping
- `opensky_sweep.py` — Periodic aircraft sweep (every 15 min)
- `opensky_once.py` — Single Spratly bbox check

---

## Improvements Over Previous System

| Aspect | Before | After |
|--------|--------|-------|
| Aircraft bbox | 7-12°N, 109-116°E (Spratly only) | 5-25°N, 105-125°E (full SCS) |
| Aircraft detected | ~10-30 typical | **220** in initial scan |
| Data sources | OpenSky only | OpenSky + ADSB.fi (multi-source) |
| Deduplication | None | By ICAO24 across sources |
| Feature mapping | None | All 79 SCS features mapped |
| Ship URLs | Basic | 24 locations incl. 17 SCS anchorages |
| Ship AIS | AISHub demo (empty) | Ready for AISHub key |
| Flight tracks | Not available | Available via `--tracks` |
| Logging | Separate files | Unified improved_*_log.jsonl |

---

## Recommendations for Further Improvement

1. **Register AISHub** — Free, gives real AIS data in SCS. This is the single biggest ship tracking improvement.
2. **AviationStack free tier** — 100 req/month, gives flight status data for specific airports
3. **AIS receiver** — Deploy a Raspberry Pi + RTL-SDR dongle near the coast to capture local AIS
4. **ADS-B receiver** — Same hardware can also capture ADS-B aircraft data locally
5. **Sentinel Hub / Planet** — Satellite imagery for construction/military activity monitoring (already have imagery_monitor.py)
