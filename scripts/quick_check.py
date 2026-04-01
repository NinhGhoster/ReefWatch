#!/usr/bin/env python3
"""
SCS Quick Check — Fast single-pass aircraft scan over the entire South China Sea.

Queries OpenSky once for the full SCS bounding box and maps any aircraft
to the nearest monitored feature. Designed to complete in under 30 seconds.

Usage:
    python3 quick_check.py              # Scan and display results
    python3 quick_check.py --json       # Output as JSON
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

# Spratly + Paracel Islands (combined bbox)
SCS_LAMIN, SCS_LOMIN, SCS_LAMAX, SCS_LOMAX = 7.0, 109.0, 17.0, 116.0

API_URL = "https://opensky-network.org/api/states/all"


def load_features_flat():
    """Load all features as a flat list with coordinates."""
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


def haversine_km(lat1, lon1, lat2, lon2):
    """Calculate distance between two lat/lon points in km."""
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(dlon / 2) ** 2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def find_nearest_feature(lat, lon, features):
    """Find the nearest feature to a lat/lon point."""
    best = None
    best_dist = float("inf")
    for f in features:
        d = haversine_km(lat, lon, f["lat"], f["lon"])
        if d < best_dist:
            best_dist = d
            best = f
    return best, best_dist


def query_scs():
    """Query OpenSky for all aircraft in the SCS bounding box."""
    params = {
        "lamin": SCS_LAMIN,
        "lomin": SCS_LOMIN,
        "lamax": SCS_LAMAX,
        "lomax": SCS_LOMAX,
    }
    try:
        resp = requests.get(API_URL, params=params, timeout=30)
        if resp.status_code in (403, 429):
            print(f"[WARN] OpenSky rate limited ({resp.status_code})")
            return []
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"[ERROR] API request failed: {e}")
        return []

    data = resp.json()
    ts = data.get("time", int(time.time()))
    states = data.get("states") or []
    
    aircraft = []
    for s in states:
        aircraft.append({
            "timestamp": ts,
            "datetime_utc": datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(),
            "callsign": (s[1] or "").strip(),
            "origin_country": s[2],
            "lon": s[5],
            "lat": s[6],
            "baro_altitude_m": s[7],
            "on_ground": s[8],
            "velocity_ms": s[9],
            "heading": s[10],
            "geo_altitude_m": s[13],
            "squawk": s[14],
        })
    return aircraft


def print_table(aircraft, features):
    """Print aircraft in a nice table with nearest feature mapping."""
    if not aircraft:
        print("\n  No aircraft detected in SCS bounding box.")
        return
    
    # Map each aircraft to nearest feature
    mapped = []
    for a in aircraft:
        if a["lat"] is not None and a["lon"] is not None:
            nearest, dist = find_nearest_feature(a["lat"], a["lon"], features)
            a["nearest_feature"] = nearest["key"] if nearest else "?"
            a["nearest_feature_name"] = nearest["name"] if nearest else "?"
            a["nearest_country"] = nearest["country"] if nearest else "?"
            a["distance_km"] = round(dist, 1)
        else:
            a["nearest_feature"] = "?"
            a["nearest_feature_name"] = "?"
            a["nearest_country"] = "?"
            a["distance_km"] = None
        mapped.append(a)
    
    # Sort by distance to nearest feature
    mapped.sort(key=lambda x: x.get("distance_km") or 9999)
    
    print(f"\n  {'Callsign':<12} {'Country':<15} {'Alt(m)':>8} {'Speed':>8} "
          f"{'Nearest Feature':<28} {'Dist(km)':>9}")
    print("  " + "-" * 88)
    
    for a in mapped:
        callsign = a.get("callsign") or "?"
        country = a.get("origin_country", "?")[:14]
        alt = a.get("geo_altitude_m")
        alt_str = f"{alt:.0f}" if alt is not None else ("GND" if a.get("on_ground") else "?")
        vel = a.get("velocity_ms")
        vel_str = f"{vel:.0f}m/s" if vel is not None else "?"
        feat = a.get("nearest_feature_name", "?")[:27]
        dist = a.get("distance_km")
        dist_str = f"{dist:.1f}" if dist is not None else "?"
        
        print(f"  {callsign:<12} {country:<15} {alt_str:>8} {vel_str:>8} "
              f"{feat:<28} {dist_str:>9}")


def print_summary_stats(aircraft, features):
    """Print summary statistics."""
    if not aircraft:
        return
    
    # Group by nearest feature
    by_feature = {}
    for a in aircraft:
        if a["lat"] is not None and a["lon"] is not None:
            nearest, dist = find_nearest_feature(a["lat"], a["lon"], features)
            key = nearest["key"] if nearest else "unknown"
            if key not in by_feature:
                by_feature[key] = {"name": nearest["name"] if nearest else "?", "count": 0, "closest_km": dist}
            by_feature[key]["count"] += 1
            by_feature[key]["closest_km"] = min(by_feature[key]["closest_km"], dist)
    
    if by_feature:
        print(f"\n  Aircraft by nearest feature:")
        print(f"  {'Feature':<30} {'Count':>5} {'Closest (km)':>13}")
        print("  " + "-" * 50)
        for key in sorted(by_feature, key=lambda k: by_feature[k]["count"], reverse=True):
            info = by_feature[key]
            print(f"  {info['name'][:29]:<30} {info['count']:>5} {info['closest_km']:>13.1f}")


# ── Main ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="SCS Quick Aircraft Check")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()
    
    ts_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    
    if not args.json:
        print(f"SCS Quick Check — {ts_str}")
        print(f"Bounding box: {SCS_LAMIN}°N-{SCS_LAMAX}°N, {SCS_LOMIN}°E-{SCS_LOMAX}°E")
        print("Querying OpenSky Network...")
    
    features = load_features_flat()
    t0 = time.time()
    aircraft = query_scs()
    elapsed = time.time() - t0
    
    if args.json:
        # Map to features
        for a in aircraft:
            if a["lat"] is not None and a["lon"] is not None:
                nearest, dist = find_nearest_feature(a["lat"], a["lon"], features)
                a["nearest_feature"] = nearest["key"] if nearest else None
                a["nearest_feature_name"] = nearest["name"] if nearest else None
                a["nearest_country"] = nearest["country"] if nearest else None
                a["distance_km"] = round(dist, 1)
            else:
                a["nearest_feature"] = None
                a["distance_km"] = None
        print(json.dumps({"timestamp": ts_str, "query_seconds": round(elapsed, 1),
                          "aircraft_count": len(aircraft), "aircraft": aircraft},
                         indent=2, ensure_ascii=False))
    else:
        print(f"Query completed in {elapsed:.1f}s — {len(aircraft)} aircraft detected")
        print_table(aircraft, features)
        print_summary_stats(aircraft, features)
        
        print(f"\n{'=' * 92}")
        print(f"Total aircraft: {len(aircraft)} | Query time: {elapsed:.1f}s | Timestamp: {ts_str}")
