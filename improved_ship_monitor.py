#!/usr/bin/env python3
"""
Improved SCS Ship Monitor — Multi-source vessel tracking over the South China Sea.

Approach:
1. AISHub free API (if key is configured) — best free AIS data source
2. MarineTraffic URL generation — for manual browser-based monitoring
3. VesselFinder URL generation — alternative vessel tracking
4. OpenSky aircraft near ports — detect maritime patrol aircraft
5. Port vicinity checking — wider search around port features

Sources evaluated (see data-sources-report.md for details):
- AISHub: free registration required, returns real AIS data
- MarineTraffic: blocked by Cloudflare, API requires paid key
- VesselFinder: blocked by anti-bot, API requires paid credits
- Global Fishing Watch: requires auth token
- MyShipTracking: no working free API found

Usage:
    python3 improved_ship_monitor.py                  # Full scan
    python3 improved_ship_monitor.py --urls           # Generate monitoring URLs
    python3 improved_ship_monitor.py --aishub KEY     # Use AISHub API key
    python3 improved_ship_monitor.py --summary        # Show monitoring summary
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
LOG_FILE = os.path.join(SCRIPT_DIR, "improved_ship_log.jsonl")
URLS_FILE = os.path.join(SCRIPT_DIR, "ship_urls.json")

# SCS bounding box for ship searches
SCS_LAMIN, SCS_LOMIN, SCS_LAMAX, SCS_LOMAX = 5.0, 105.0, 25.0, 125.0

RATE_LIMIT = 1.0

# ── AIS Sources ─────────────────────────────────────────────────────────

AISHUB_URL = "https://data.aishub.net/ws.php"

# Known SCS ports / anchorages for port-call style monitoring
SCS_PORTS = [
    {"name": "Spratly Island Anchorage", "lat": 10.0, "lon": 114.0, "radius": 0.5},
    {"name": "Thitu Island / Pag-asa", "lat": 11.05, "lon": 114.28, "radius": 0.3},
    {"name": "Scarborough Shoal", "lat": 15.13, "lon": 117.76, "radius": 0.3},
    {"name": "Cuarteron Reef", "lat": 8.88, "lon": 112.20, "radius": 0.3},
    {"name": "Johnson South Reef", "lat": 9.77, "lon": 114.28, "radius": 0.3},
    {"name": "Fiery Cross Reef", "lat": 9.54, "lon": 112.89, "radius": 0.3},
    {"name": "Subi Reef", "lat": 10.55, "lon": 114.07, "radius": 0.3},
    {"name": "Mischief Reef", "lat": 9.92, "lon": 115.52, "radius": 0.3},
    {"name": "Gaven Reefs", "lat": 10.21, "lon": 114.22, "radius": 0.3},
    {"name": "Hughes Reef", "lat": 9.84, "lon": 114.30, "radius": 0.3},
    {"name": "Eldad Reef", "lat": 10.34, "lon": 114.44, "radius": 0.3},
    {"name": "Lankiam Cay", "lat": 10.74, "lon": 115.82, "radius": 0.2},
    {"name": "Loaita Cay", "lat": 10.68, "lon": 114.40, "radius": 0.2},
    {"name": "Namyit Island", "lat": 10.18, "lon": 114.36, "radius": 0.2},
    {"name": "West London Reef", "lat": 8.92, "lon": 112.14, "radius": 0.2},
    {"name": "Pigeon Reef", "lat": 8.87, "lon": 112.34, "radius": 0.2},
    {"name": "Sin Cowe Island", "lat": 9.87, "lon": 114.33, "radius": 0.2},
]


def query_aishub(lat, lon, radius_deg=0.3, api_key="DEMO"):
    """Query AISHub for vessels near a location."""
    try:
        resp = requests.get(AISHUB_URL, params={
            "username": api_key,
            "format": "1",
            "output": "json",
            "latmin": lat - radius_deg,
            "latmax": lat + radius_deg,
            "lonmin": lon - radius_deg,
            "lonmax": lon + radius_deg,
        }, timeout=15)
        if resp.status_code != 200 or not resp.text.strip():
            return []
        data = resp.json()
        if isinstance(data, list) and len(data) > 1:
            vessels = data[1]
            if isinstance(vessels, list):
                return [{
                    "source": "aishub",
                    "mmsi": v.get("MMSI"),
                    "name": v.get("NAME"),
                    "lat": v.get("LAT"),
                    "lon": v.get("LON"),
                    "speed_kn": v.get("SPEED"),
                    "heading": v.get("HEADING"),
                    "course": v.get("COURSE"),
                    "status": v.get("STATUS"),
                    "status_text": v.get("STATUS_TEXT"),
                    "type": v.get("TYPE"),
                    "type_text": v.get("TYPE_TEXT"),
                    "length_m": v.get("LENGTH"),
                    "width_m": v.get("WIDTH"),
                    "draught_m": v.get("DRAUGHT"),
                    "destination": v.get("DESTINATION"),
                    "eta": v.get("ETA"),
                    "timestamp": v.get("TIME"),
                } for v in vessels]
        return []
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
                "has_helipad": feat.get("helipad", False),
                "has_port": feat.get("port", False),
            })
    return features


def get_port_features(db):
    """Get all features that have ports."""
    with open(FEATURES_FILE) as f:
        db = json.load(f)
    features = []
    for group_key, group in db.get("island_groups", {}).items():
        for feat_key, feat in group.get("features", {}).items():
            if feat.get("port"):
                features.append({
                    "key": feat_key,
                    "name": feat.get("name", feat_key),
                    "lat": feat["lat"],
                    "lon": feat["lon"],
                    "country": feat.get("country", "unknown"),
                    "group": group_key,
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


# ── URL generation ──────────────────────────────────────────────────────

def generate_urls(lat, lon, name):
    """Generate monitoring URLs for a location."""
    return {
        "marinetraffic": f"https://www.marinetraffic.com/en/ais/index/center:{lon:.4f}/lat:{lat:.4f}/zoom:12",
        "vesselfinder": f"https://www.vesselfinder.com/?ll={lat:.4f},{lon:.4f}&z=12",
        "marinetraffic_density": f"https://www.marinetraffic.com/en/ais/density/center:{lon:.4f}/lat:{lat:.4f}/zoom:8",
        "global_fishing_watch": f"https://globalfishingwatch.org/map/?lat={lat:.4f}&lng={lon:.4f}&zoom=8",
    }


def build_urls_file(features):
    """Build ship_urls.json with all port features + SCS anchorages."""
    port_features = get_port_features(features)
    urls = {}

    for feat in port_features:
        urls[feat["key"]] = {
            "name": feat["name"],
            "lat": feat["lat"],
            "lon": feat["lon"],
            "country": feat["country"],
            "urls": generate_urls(feat["lat"], feat["lon"], feat["name"]),
            "type": "port_feature",
        }

    # Add known anchorages
    for port in SCS_PORTS:
        key = port["name"].lower().replace(" ", "_").replace("/", "_")
        if key not in urls:
            urls[key] = {
                "name": port["name"],
                "lat": port["lat"],
                "lon": port["lon"],
                "country": "mixed",
                "urls": generate_urls(port["lat"], port["lon"], port["name"]),
                "type": "known_anchorage",
            }

    with open(URLS_FILE, "w") as f:
        json.dump(urls, f, indent=2, ensure_ascii=False)
    return urls


# ── Aircraft near ports ─────────────────────────────────────────────────

OPENSKY_URL = "https://opensky-network.org/api/states/all"


def check_aircraft_near_port(lat, lon, radius_deg=0.3):
    """Check for aircraft near a port (maritime patrol, helicopters)."""
    try:
        resp = requests.get(OPENSKY_URL, params={
            "lamin": lat - radius_deg,
            "lomin": lon - radius_deg,
            "lamax": lat + radius_deg,
            "lomax": lon + radius_deg,
        }, timeout=30)
        if resp.status_code in (403, 429):
            return []
        resp.raise_for_status()
        data = resp.json()
        states = data.get("states") or []
        return [{
            "callsign": (s[1] or "").strip(),
            "country": s[2],
            "lat": s[6],
            "lon": s[5],
            "alt_m": s[13],
            "on_ground": s[8],
            "velocity_ms": s[9],
        } for s in states]
    except Exception:
        return []


# ── Main monitor logic ──────────────────────────────────────────────────

def run_monitor(aishub_key=None, check_aircraft=True):
    """Run multi-source ship monitoring scan."""
    ts = datetime.now(timezone.utc).isoformat()
    features = load_features_flat()

    all_vessels = []
    all_aircraft = []
    source_counts = {"aishub": 0, "opensky_aircraft": 0}

    # Source 1: AISHub at key SCS anchorages
    if aishub_key:
        print(f"  [1/2] AISHub API scan ({len(SCS_PORTS)} anchorages)...")
        for port in SCS_PORTS:
            vessels = query_aishub(port["lat"], port["lon"],
                                   radius_deg=port["radius"], api_key=aishub_key)
            for v in vessels:
                v["checked_location"] = port["name"]
            all_vessels.extend(vessels)
            source_counts["aishub"] += len(vessels)
            if vessels:
                names = [v.get("name", "?") for v in vessels[:5]]
                print(f"    {port['name']}: {len(vessels)} vessels — {', '.join(names)}")
            time.sleep(RATE_LIMIT)
        print(f"        → {source_counts['aishub']} vessels from AISHub")
    else:
        print(f"  [1/2] AISHub: skipped (no API key — register free at aishub.net)")

    # Source 2: Aircraft near ports (potential maritime patrol)
    if check_aircraft:
        print(f"  [2/2] OpenSky aircraft near {len(SCS_PORTS)} port anchorages...")
        for port in SCS_PORTS[:10]:  # Limit to avoid rate limiting
            aircraft = check_aircraft_near_port(port["lat"], port["lon"], radius_deg=0.3)
            for ac in aircraft:
                ac["near_port"] = port["name"]
            all_aircraft.extend(aircraft)
            source_counts["opensky_aircraft"] += len(aircraft)
            if aircraft:
                callsigns = [a.get("callsign", "?") for a in aircraft[:3]]
                print(f"    {port['name']}: {len(aircraft)} aircraft — {', '.join(callsigns)}")
            time.sleep(0.5)
        print(f"        → {source_counts['opensky_aircraft']} aircraft near ports")

    # Deduplicate vessels by MMSI
    seen_mmsi = set()
    unique_vessels = []
    for v in all_vessels:
        mmsi = v.get("mmsi")
        if mmsi and mmsi not in seen_mmsi:
            seen_mmsi.add(mmsi)
            unique_vessels.append(v)
        elif not mmsi:
            unique_vessels.append(v)

    # Map vessels to nearest feature
    for v in unique_vessels:
        if v.get("lat") is not None and v.get("lon") is not None:
            nearest, dist = find_nearest_feature(v["lat"], v["lon"], features)
            v["nearest_feature"] = nearest["key"] if nearest else None
            v["nearest_feature_name"] = nearest["name"] if nearest else None
            v["distance_km"] = round(dist, 1)
        else:
            v["nearest_feature"] = None
            v["distance_km"] = None

    result = {
        "timestamp": ts,
        "scan_type": "multi_source_scs",
        "vessel_count": len(unique_vessels),
        "aircraft_count": len(all_aircraft),
        "sources": source_counts,
        "aishub_available": aishub_key is not None,
        "vessels": unique_vessels,
        "aircraft_near_ports": all_aircraft,
    }

    return result


def append_log(result):
    """Append result to JSONL log."""
    with open(LOG_FILE, "a") as f:
        f.write(json.dumps(result, ensure_ascii=False) + "\n")


def show_summary():
    """Show ship monitoring summary."""
    if not os.path.isfile(LOG_FILE):
        print("No improved ship log found.")
        return

    latest = None
    total_vessels = 0
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
            total_vessels += rec.get("vessel_count", 0)

    if not latest:
        print("No scan records found.")
        return

    print(f"\n  Improved Ship Monitor Summary")
    print(f"  Scans in log: {total_scans}")
    print(f"  Latest scan: {latest.get('timestamp', '?')}")
    print(f"  Vessels in latest scan: {latest.get('vessel_count', 0)}")
    print(f"  Aircraft near ports: {latest.get('aircraft_count', 0)}")
    print(f"  AISHub available: {latest.get('aishub_available', False)}")

    sources = latest.get("sources", {})
    if sources:
        print(f"\n  Sources (last scan):")
        for src, count in sources.items():
            print(f"    {src}: {count}")

    vessels = latest.get("vessels", [])
    if vessels:
        print(f"\n  Vessels detected:")
        print(f"  {'Name':<25} {'MMSI':<12} {'Speed':>6} {'Feature':<28} {'Dist(km)':>9}")
        print("  " + "-" * 85)
        for v in vessels[:20]:
            name = (v.get("name") or "?")[:24]
            mmsi = str(v.get("mmsi") or "?")[:11]
            spd = v.get("speed_kn")
            spd_str = f"{spd:.1f}kn" if spd is not None else "?"
            feat = (v.get("nearest_feature_name") or "?")[:27]
            dist = v.get("distance_km")
            dist_str = f"{dist:.1f}" if dist is not None else "?"
            print(f"  {name:<25} {mmsi:<12} {spd_str:>6} {feat:<28} {dist_str:>9}")
    else:
        print("\n  No vessels detected (AISHub key likely needed for real data).")

    aircraft = latest.get("aircraft_near_ports", [])
    if aircraft:
        print(f"\n  Aircraft near SCS ports (maritime patrol?):")
        for a in aircraft[:10]:
            cs = a.get("callsign") or "?"
            port = a.get("near_port", "?")
            alt = a.get("alt_m")
            alt_str = f"{alt:.0f}m" if alt is not None else "GND"
            print(f"    ✈️ {cs:<12} near {port} ({alt_str})")


# ── Entry point ─────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Improved SCS Ship Monitor")
    parser.add_argument("--urls", action="store_true",
                        help="Generate monitoring URLs only")
    parser.add_argument("--aishub", metavar="KEY",
                        help="AISHub API key (register free at aishub.net)")
    parser.add_argument("--summary", action="store_true",
                        help="Show monitoring summary")
    parser.add_argument("--no-aircraft", action="store_true",
                        help="Skip aircraft near port check")
    args = parser.parse_args()

    if args.summary:
        show_summary()
        sys.exit(0)

    ts_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    print(f"Improved SCS Ship Monitor — {ts_str}")
    print("=" * 60)

    # Always generate URLs
    features = load_features_flat()
    urls = build_urls_file(features)
    print(f"Monitoring URLs saved: {URLS_FILE}")
    print(f"Port/anchorage locations: {len(urls)}")

    if args.urls:
        print("\nURLs:")
        for key, info in sorted(urls.items()):
            print(f"  {info['name']:<30} → {info['urls']['marinetraffic']}")
        sys.exit(0)

    print()
    t0 = time.time()
    result = run_monitor(aishub_key=args.aishub, check_aircraft=not args.no_aircraft)
    elapsed = time.time() - t0

    append_log(result)

    print(f"\n{'=' * 60}")
    print(f"Vessels detected: {result['vessel_count']}")
    print(f"Aircraft near ports: {result['aircraft_count']}")
    print(f"Scan time: {elapsed:.1f}s")
    print(f"Log: {LOG_FILE}")

    if not args.aishub:
        print(f"\n💡 To get real AIS vessel data, register free at:")
        print(f"   https://www.aishub.net/")
        print(f"   Then run: python3 {os.path.basename(__file__)} --aishub YOUR_KEY")

    # MarineTraffic URLs for manual checking
    print(f"\nManual monitoring URLs:")
    for key in list(urls.keys())[:5]:
        info = urls[key]
        print(f"  {info['name']}: {info['urls']['marinetraffic']}")
