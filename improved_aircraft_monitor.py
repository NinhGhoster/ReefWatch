#!/usr/bin/env python3
"""
Improved SCS Aircraft Monitor — Multi-source aircraft tracking over the South China Sea.

Sources tried (in order):
1. OpenSky Network — wide SCS bbox (states/all) — PRIMARY, best free source
2. OpenSky per-feature bbox — secondary, catches near-feature aircraft
3. ADSB.fi opendata — tertiary, best-effort (limited SCS receiver coverage)
4. Individual OpenSky tracks — enrich detected aircraft with flight paths

Deduplicates by ICAO24 + callsign, resolves nearest SCS feature per aircraft.

Usage:
    python3 improved_aircraft_monitor.py                 # Full scan
    python3 improved_aircraft_monitor.py --wide-only     # Single wide SCS scan
    python3 improved_aircraft_monitor.py --summary       # Show detection summary
    python3 improved_aircraft_monitor.py --airports      # Also check SCS airports
"""

import argparse
import json
import math
import os
import sys
import time
from datetime import datetime, timezone

import requests

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
FEATURES_FILE = os.path.join(SCRIPT_DIR, "scs_features.json")
LOG_FILE = os.path.join(SCRIPT_DIR, "improved_aircraft_log.jsonl")

# Spratly Islands only — Ninh's target area (7-12°N, 109-116°E)
SCS_LAMIN, SCS_LOMIN, SCS_LAMAX, SCS_LOMAX = 7.0, 109.0, 12.0, 116.0
SPRATLY_LAMIN, SPRATLY_LOMIN, SPRATLY_LAMAX, SPRATLY_LOMAX = 7.0, 109.0, 12.0, 116.0

RATE_LIMIT = 1.0  # seconds between API calls

# ── Sources ─────────────────────────────────────────────────────────────

OPENSKY_URL = "https://opensky-network.org/api/states/all"
OPENSKY_TRACK_URL = "https://opensky-network.org/api/tracks/all"
ADSBFI_URL = "https://opendata.adsb.fi/api/v2/lat/{lat}/lon/{lon}/dist/{dist}"


def query_opensky(bbox):
    """Query OpenSky states/all endpoint.
    Returns list of aircraft dicts.
    """
    params = {
        "lamin": bbox[0], "lomin": bbox[1],
        "lamax": bbox[2], "lomax": bbox[3],
    }
    try:
        resp = requests.get(OPENSKY_URL, params=params, timeout=30)
        if resp.status_code in (403, 429):
            print(f"    [WARN] OpenSky rate limited ({resp.status_code})")
            return []
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"    [ERROR] OpenSky failed: {e}")
        return []

    data = resp.json()
    ts = data.get("time", int(time.time()))
    states = data.get("states") or []
    results = []
    for s in states:
        results.append({
            "source": "opensky",
            "timestamp": ts,
            "datetime_utc": datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(),
            "icao24": s[0],
            "callsign": (s[1] or "").strip(),
            "origin_country": s[2],
            "lon": s[5],
            "lat": s[6],
            "on_ground": s[8],
            "velocity_ms": s[9],
            "heading": s[10],
            "baro_altitude_m": s[7],
            "geo_altitude_m": s[13],
            "squawk": s[14],
            "spi": s[15] if len(s) > 15 else None,
        })
    return results


def query_opensky_track(icao24):
    """Get flight track for an aircraft. Returns path or empty list."""
    now = int(time.time())
    try:
        resp = requests.get(OPENSKY_TRACK_URL,
                           params={"icao24": icao24, "time": now},
                           timeout=30)
        if resp.status_code in (403, 429):
            return []
        resp.raise_for_status()
        data = resp.json()
        return data.get("path", [])
    except Exception:
        return []


def query_adsbfi(lat, lon, dist_nm=300):
    """Query ADSB.fi opendata API. Limited SCS coverage but worth trying."""
    url = ADSBFI_URL.format(lat=lat, lon=lon, dist=dist_nm)
    try:
        resp = requests.get(url, timeout=15)
        if resp.status_code != 200:
            return []
        data = resp.json()
        aircraft = data.get("aircraft", [])
        results = []
        for a in aircraft:
            results.append({
                "source": "adsbfi",
                "timestamp": time.time(),
                "datetime_utc": datetime.now(timezone.utc).isoformat(),
                "icao24": a.get("hex", ""),
                "callsign": (a.get("flight") or "").strip(),
                "origin_country": None,
                "lon": a.get("lon"),
                "lat": a.get("lat"),
                "on_ground": a.get("alt_baro") == "ground" if a.get("alt_baro") else False,
                "velocity_ms": round(a.get("gs", 0) * 0.514444, 1) if a.get("gs") else None,
                "heading": a.get("track"),
                "baro_altitude_m": round(a.get("alt_baro", 0) * 0.3048) if isinstance(a.get("alt_baro"), (int, float)) else None,
                "geo_altitude_m": round(a.get("alt_geom", 0) * 0.3048) if isinstance(a.get("alt_geom"), (int, float)) else None,
                "squawk": a.get("squawk"),
            })
        return results
    except Exception:
        return []


# ── Feature mapping ─────────────────────────────────────────────────────

def load_features_flat():
    """Load all features as a flat list."""
    with open(FEATURES_FILE) as f:
        db = json.load(f)
    features = []
    for group_key, group in db.get("island_groups", {}).items():
        for feat_key, feat in group.get("features", {}).items():
            features.append({
                "key": feat_key,
                "name": feat.get("name", feat_key),
                "lat": feat["lat"],
                "lon": feat["lon"],
                "country": feat.get("country", "unknown"),
                "group": group_key,
                "has_airport": bool(feat.get("airport")),
                "airport_icao": feat.get("airport"),
                "has_helipad": feat.get("helipad", False),
                "has_port": feat.get("port", False),
            })
    return features


def haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(dlon / 2) ** 2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def find_nearest_feature(lat, lon, features):
    best = None
    best_dist = float("inf")
    for f in features:
        d = haversine_km(lat, lon, f["lat"], f["lon"])
        if d < best_dist:
            best_dist = d
            best = f
    return best, best_dist


# ── Deduplication ───────────────────────────────────────────────────────

def deduplicate(all_aircraft):
    """Deduplicate aircraft by ICAO24, prefer OpenSky over ADSB.fi."""
    seen = {}
    for a in all_aircraft:
        key = a.get("icao24") or a.get("callsign") or f"{a['lat']},{a['lon']}"
        if key not in seen:
            seen[key] = a
        else:
            # Prefer OpenSky data (has country info)
            if a.get("source") == "opensky" and seen[key].get("source") == "adsbfi":
                seen[key] = a
    return list(seen.values())


# ── Main monitor logic ──────────────────────────────────────────────────

def run_full_scan(features, tracks=False):
    """Run multi-source aircraft scan over SCS."""
    ts = datetime.now(timezone.utc).isoformat()
    all_aircraft = []

    # Source 1: OpenSky wide SCS scan
    print(f"  [1/3] OpenSky wide SCS bbox ({SCS_LAMIN}-{SCS_LAMAX}°N, {SCS_LOMIN}-{SCS_LOMAX}°E)...")
    wide = query_opensky((SCS_LAMIN, SCS_LOMIN, SCS_LAMAX, SCS_LOMAX))
    print(f"        → {len(wide)} aircraft")
    all_aircraft.extend(wide)

    # Source 2: ADSB.fi points within Spratly bbox only
    print(f"  [2/3] ADSB.fi scan (Spratly area, 300nm radius)...")
    adsbfi_points = [
        (10.0, 112.0, "Spratly core"),
        (10.0, 114.0, "Central Spratly"),
        (8.0, 110.0, "South Spratly"),
        (12.0, 113.0, "North Spratly"),
    ]
    adsbfi_count = 0
    for lat, lon, label in adsbfi_points:
        result = query_adsbfi(lat, lon, dist_nm=300)
        adsbfi_count += len(result)
        all_aircraft.extend(result)
        time.sleep(0.3)
    print(f"        → {adsbfi_count} aircraft (across all points)")

    # Deduplicate
    unique = deduplicate(all_aircraft)
    print(f"  [3] Deduplication: {len(all_aircraft)} raw → {len(unique)} unique")

    # Map to features
    for a in unique:
        if a.get("lat") is not None and a.get("lon") is not None:
            nearest, dist = find_nearest_feature(a["lat"], a["lon"], features)
            a["nearest_feature"] = nearest["key"] if nearest else None
            a["nearest_feature_name"] = nearest["name"] if nearest else None
            a["nearest_country"] = nearest["country"] if nearest else None
            a["distance_km"] = round(dist, 1)
        else:
            a["nearest_feature"] = None
            a["distance_km"] = None

    # Optional: fetch tracks for aircraft near features
    if tracks:
        near_features = [a for a in unique if a.get("distance_km") and a["distance_km"] < 50 and a.get("icao24")]
        print(f"  [4] Fetching tracks for {len(near_features)} aircraft near features...")
        for a in near_features[:20]:  # Limit to avoid rate limiting
            path = query_opensky_track(a["icao24"])
            a["track_points"] = len(path) if path else 0
            if path:
                a["track_recent"] = path[-5:]  # Last 5 points
            time.sleep(0.5)

    # Build result
    result = {
        "timestamp": ts,
        "scan_type": "multi_source_scs",
        "bbox": {
            "lamin": SCS_LAMIN, "lomin": SCS_LOMIN,
            "lamax": SCS_LAMAX, "lomax": SCS_LOMAX,
        },
        "aircraft_count": len(unique),
        "sources_used": {
            "opensky": len(wide),
            "adsbfi": adsbfi_count,
            "deduplicated": len(unique),
        },
        "aircraft": unique,
    }

    return result


def append_log(result):
    """Append result to JSONL log."""
    with open(LOG_FILE, "a") as f:
        f.write(json.dumps(result, ensure_ascii=False) + "\n")


def show_summary():
    """Show detection summary from log."""
    if not os.path.isfile(LOG_FILE):
        print("No improved aircraft log found.")
        return

    latest = None
    all_unique = {}  # callsign/icao24 -> aircraft info
    total_scans = 0

    with open(LOG_FILE) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            total_scans += 1
            latest = rec
            for a in rec.get("aircraft", []):
                key = a.get("callsign") or a.get("icao24")
                if key and key not in all_unique:
                    all_unique[key] = a

    if not latest:
        print("No scan records found.")
        return

    print(f"\n  Improved Aircraft Monitor Summary")
    print(f"  Scans in log: {total_scans}")
    print(f"  Latest scan: {latest.get('timestamp', '?')}")
    print(f"  Aircraft in latest scan: {latest.get('aircraft_count', 0)}")
    print(f"  Unique aircraft ever seen: {len(all_unique)}")

    sources = latest.get("sources_used", {})
    if sources:
        print(f"\n  Sources (last scan):")
        for src, count in sources.items():
            print(f"    {src}: {count}")

    print(f"\n  Aircraft in last scan:")
    aircraft = latest.get("aircraft", [])
    aircraft.sort(key=lambda x: x.get("distance_km") or 9999)

    print(f"\n  {'Callsign':<14} {'Country':<18} {'Alt(m)':>8} {'Feature':<28} {'Dist(km)':>9} {'Source'}")
    print("  " + "-" * 100)
    for a in aircraft[:30]:
        cs = (a.get("callsign") or "?")[:13]
        country = (a.get("origin_country") or "?")[:17]
        alt = a.get("geo_altitude_m") or a.get("baro_altitude_m")
        alt_str = f"{alt:.0f}" if alt is not None else ("GND" if a.get("on_ground") else "?")
        feat = (a.get("nearest_feature_name") or "?")[:27]
        dist = a.get("distance_km")
        dist_str = f"{dist:.1f}" if dist is not None else "?"
        src = a.get("source", "?")
        print(f"  {cs:<14} {country:<18} {alt_str:>8} {feat:<28} {dist_str:>9} {src}")

    # Features with nearby aircraft
    nearby = [a for a in aircraft if a.get("distance_km") is not None and a["distance_km"] < 30]
    if nearby:
        print(f"\n  Aircraft within 30km of a feature ({len(nearby)}):")
        for a in nearby:
            print(f"    ✈️ {a.get('callsign','?')} — {a.get('nearest_feature_name','?')} ({a['distance_km']}km)")


# ── Entry point ─────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Improved SCS Aircraft Monitor")
    parser.add_argument("--wide-only", action="store_true",
                        help="Only run the wide SCS scan (skip per-feature)")
    parser.add_argument("--summary", action="store_true",
                        help="Show detection summary")
    parser.add_argument("--tracks", action="store_true",
                        help="Also fetch flight tracks for nearby aircraft")
    args = parser.parse_args()

    if args.summary:
        show_summary()
        sys.exit(0)

    features = load_features_flat()
    ts_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    print(f"Improved SCS Aircraft Monitor — {ts_str}")
    print(f"Sources: OpenSky (wide bbox) + ADSB.fi (6 center points)")
    print(f"SCS bbox: {SCS_LAMIN}-{SCS_LAMAX}°N, {SCS_LOMIN}-{SCS_LOMAX}°E")
    print("=" * 60)

    t0 = time.time()
    result = run_full_scan(features, tracks=args.tracks)
    elapsed = time.time() - t0

    # Save
    append_log(result)

    # Display
    print(f"\n{'=' * 60}")
    print(f"Aircraft detected: {result['aircraft_count']}")
    print(f"Sources: OpenSky={result['sources_used']['opensky']}, "
          f"ADSBfi={result['sources_used']['adsbfi']}, "
          f"Unique={result['sources_used']['deduplicated']}")
    print(f"Scan time: {elapsed:.1f}s")
    print(f"Log: {LOG_FILE}")

    # Show nearby features
    nearby = [a for a in result["aircraft"]
              if a.get("distance_km") is not None and a["distance_km"] < 50]
    if nearby:
        print(f"\nAircraft within 50km of a monitored feature:")
        for a in sorted(nearby, key=lambda x: x.get("distance_km") or 9999):
            print(f"  ✈️ {a.get('callsign','?'):<12} "
                  f"{a.get('nearest_feature_name','?'):<28} "
                  f"{a.get('distance_km','?'):>6}km "
                  f"alt={a.get('geo_altitude_m','?')}m "
                  f"src={a.get('source','?')}")
    else:
        print("\nNo aircraft within 50km of any monitored feature.")
