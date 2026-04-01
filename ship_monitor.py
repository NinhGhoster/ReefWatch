#!/usr/bin/env python3
"""
SCS Ship Monitor — Vessel tracking via AIS web services and MarineTraffic URLs.

Generates MarineTraffic/VesselFinder monitoring URLs for all port features,
and optionally checks free AIS APIs for vessel data.

Usage:
    python3 ship_monitor.py                    # Generate URLs for all port features
    python3 ship_monitor.py --check            # Attempt free AIS API checks
    python3 ship_monitor.py --summary          # Show ship monitoring status
    python3 ship_monitor.py --urls-only        # Just regenerate ship_urls.json
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone

import requests

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
FEATURES_FILE = os.path.join(SCRIPT_DIR, "scs_features.json")
SHIP_URLS_FILE = os.path.join(SCRIPT_DIR, "ship_urls.json")
SHIPS_LOG = os.path.join(SCRIPT_DIR, "ships_log.jsonl")

# Free AIS API endpoints (may require registration or have limited coverage)
AIS_ENDPOINTS = [
    {
        "name": "AISHub",
        "url": "https://data.aishub.net/ws.php",
        "params_template": "{url}?username=YOUR_KEY&format=1&output=json&latmin={lamin}&latmax={lamax}&lonmin={lomin}&lonmax={lomax}",
        "note": "Requires free registration at aishub.net",
    },
]

RATE_LIMIT = 0.5


def load_features():
    """Load the features database."""
    with open(FEATURES_FILE) as f:
        return json.load(f)


def get_port_features(db):
    """Get all features that have ports."""
    features = []
    for group_key, group in db.get("island_groups", {}).items():
        for feat_key, feat in group.get("features", {}).items():
            if feat.get("port"):
                feat_copy = dict(feat)
                feat_copy["_key"] = feat_key
                feat_copy["_group"] = group_key
                features.append((feat_key, feat_copy))
    return features


def generate_urls(lat, lon, name):
    """Generate monitoring URLs for a feature."""
    return {
        "marinetraffic": f"https://www.marinetraffic.com/en/ais/index/center:{lon:.4f}/lat:{lat:.4f}/zoom:12",
        "vesselfinder": f"https://www.vesselfinder.com/?ll={lat:.4f},{lon:.4f}&z=12",
        "marinetraffic_area": f"https://www.marinetraffic.com/en/ais/details/ports/{name.replace(' ', '_')}",
    }


def build_ship_urls(db):
    """Build ship_urls.json for all port features."""
    port_features = get_port_features(db)
    urls = {}
    
    for feat_key, feat in port_features:
        lat, lon = feat["lat"], feat["lon"]
        name = feat.get("name", feat_key)
        urls[feat_key] = {
            "name": name,
            "lat": lat,
            "lon": lon,
            "country": feat.get("country", "unknown"),
            "group": feat.get("_group", "unknown"),
            "urls": generate_urls(lat, lon, name),
            "has_helipad": feat.get("helipad", False),
            "has_airport": bool(feat.get("airport")),
        }
    
    with open(SHIP_URLS_FILE, "w") as f:
        json.dump(urls, f, indent=2, ensure_ascii=False)
    
    return urls


def check_ais_api(lat, lon, radius_deg=0.15):
    """Try to query free AIS APIs for vessels near a location.
    
    Returns list of vessel dicts or empty list.
    This is a best-effort check — most free AIS APIs require keys.
    """
    # Try AISHub (will likely fail without key, but we try)
    url = (
        f"https://data.aishub.net/ws.php"
        f"?username=DEMO&format=1&output=json"
        f"&latmin={lat - radius_deg}&latmax={lat + radius_deg}"
        f"&lonmin={lon - radius_deg}&lonmax={lon + radius_deg}"
    )
    try:
        resp = requests.get(url, timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            if isinstance(data, list) and len(data) > 1:
                return data[1]  # AISHub returns [header, vessels]
        return []
    except Exception:
        return []


def try_opensky_nearby(lat, lon):
    """Check OpenSky for any aircraft near port (could be maritime patrol)."""
    API_URL = "https://opensky-network.org/api/states/all"
    params = {
        "lamin": lat - 0.2,
        "lomin": lon - 0.2,
        "lamax": lat + 0.2,
        "lomax": lon + 0.2,
    }
    try:
        resp = requests.get(API_URL, params=params, timeout=15)
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
        } for s in states]
    except Exception:
        return []


def run_ship_check(urls_data, check_api=False):
    """Run ship monitoring for all port features."""
    results = []
    
    for feat_key, info in urls_data.items():
        name = info["name"]
        lat, lon = info["lat"], info["lon"]
        
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "feature_key": feat_key,
            "feature_name": name,
            "country": info.get("country", "unknown"),
            "lat": lat,
            "lon": lon,
            "urls": info["urls"],
            "nearby_aircraft": [],
            "ais_vessels": [],
            "ais_available": False,
        }
        
        if check_api:
            # Check for nearby aircraft (maritime patrol, etc.)
            aircraft = try_opensky_nearby(lat, lon)
            entry["nearby_aircraft"] = aircraft
            
            # Try AIS
            vessels = check_ais_api(lat, lon)
            if vessels:
                entry["ais_vessels"] = vessels
                entry["ais_available"] = True
                print(f"  🚢 {name}: {len(vessels)} vessels via AIS")
            elif aircraft:
                print(f"  ✈️  {name}: {len(aircraft)} nearby aircraft (no AIS data)")
            else:
                print(f"  —  {name}: no data (check URLs manually)")
            
            time.sleep(RATE_LIMIT)
        else:
            print(f"  🔗 {name}: {info['urls']['marinetraffic']}")
        
        results.append(entry)
    
    return results


def append_log(results):
    """Append ship monitoring results to JSONL log."""
    with open(SHIPS_LOG, "a") as f:
        for r in results:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def show_summary():
    """Show summary of ship monitoring data."""
    if not os.path.isfile(SHIPS_LOG):
        print("No ship monitoring log found.")
        return
    
    latest = {}
    with open(SHIPS_LOG) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            key = rec.get("feature_key")
            if key:
                latest[key] = rec
    
    if not latest:
        print("No records found.")
        return
    
    print(f"\n{'Feature':<30} {'Country':<12} {'AIS':>5} {'Aircraft':>8} {'Last Check'}")
    print("-" * 80)
    for key in sorted(latest):
        rec = latest[key]
        ais = "✓" if rec.get("ais_available") else "—"
        aircraft = len(rec.get("nearby_aircraft", []))
        ts = rec.get("timestamp", "?")[:19]
        print(f"  {key:<28} {rec.get('country','?'):<12} {ais:>5} {aircraft:>8} {ts}")
    
    print(f"\nPort features monitored: {len(latest)}")


# ── Main ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="SCS Ship/Vessel Monitor")
    parser.add_argument("--check", action="store_true",
                        help="Attempt AIS API checks and OpenSky queries")
    parser.add_argument("--summary", action="store_true",
                        help="Show summary of ship monitoring data")
    parser.add_argument("--urls-only", action="store_true",
                        help="Only regenerate ship_urls.json")
    args = parser.parse_args()
    
    if args.summary:
        show_summary()
        sys.exit(0)
    
    db = load_features()
    
    print(f"SCS Ship Monitor — {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print("=" * 60)
    
    # Build/update URLs file
    urls_data = build_ship_urls(db)
    print(f"Ship URLs saved: {SHIP_URLS_FILE}")
    print(f"Port features: {len(urls_data)}")
    
    if args.urls_only:
        for feat_key, info in urls_data.items():
            print(f"  {info['name']}: {info['urls']['marinetraffic']}")
        sys.exit(0)
    
    print()
    results = run_ship_check(urls_data, check_api=args.check)
    append_log(results)
    
    if args.check:
        with_ais = sum(1 for r in results if r.get("ais_available"))
        with_ac = sum(1 for r in results if r.get("nearby_aircraft"))
        print(f"\n{'=' * 60}")
        print(f"Features checked: {len(results)}")
        print(f"With AIS data: {with_ais}")
        print(f"With nearby aircraft: {with_ac}")
        print(f"\nFor automated AIS, register at: https://www.aishub.net/")
    else:
        print(f"\n{'=' * 60}")
        print(f"URLs generated for {len(results)} port features.")
        print(f"Use --check to attempt AIS API queries.")
