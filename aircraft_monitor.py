#!/usr/bin/env python3
"""
SCS Aircraft Monitor — Per-feature aircraft/helicopter detection.
Queries OpenSky Network API with tight bounding boxes for each feature
and logs any aircraft detected nearby.

Usage:
    python3 aircraft_monitor.py                    # Monitor all features
    python3 aircraft_monitor.py --feature woody_island  # Single feature
    python3 aircraft_monitor.py --summary          # Show detection summary
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
DETECTIONS_LOG = os.path.join(SCRIPT_DIR, "aircraft_detections.jsonl")
API_URL = "https://opensky-network.org/api/states/all"
RATE_LIMIT = 0.5  # seconds between API requests


def load_features():
    """Load the features database."""
    with open(FEATURES_FILE) as f:
        return json.load(f)


def get_all_features(db):
    """Extract all features as a flat list of (key, info) tuples."""
    features = []
    for group_key, group in db.get("island_groups", {}).items():
        for feat_key, feat in group.get("features", {}).items():
            feat_copy = dict(feat)
            feat_copy["_key"] = feat_key
            feat_copy["_group"] = group_key
            features.append((feat_key, feat_copy))
    return features


def query_opensky_bbox(lat, lon, delta=0.1):
    """Query OpenSky API for aircraft near a feature.
    
    Returns list of aircraft dicts or empty list on error/rate limit.
    """
    params = {
        "lamin": lat - delta,
        "lomin": lon - delta,
        "lamax": lat + delta,
        "lomax": lon + delta,
    }
    try:
        resp = requests.get(API_URL, params=params, timeout=30)
        if resp.status_code in (403, 429):
            print(f"    [WARN] OpenSky rate limited ({resp.status_code}), skipping")
            return []
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"    [ERROR] API request failed: {e}")
        return []

    data = resp.json()
    ts = data.get("time", int(time.time()))
    states = data.get("states") or []
    results = []
    for s in states:
        results.append({
            "timestamp": ts,
            "datetime_utc": datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(),
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
            "sensors": s[12],
        })
    return results


def haversine_km(lat1, lon1, lat2, lon2):
    """Calculate distance between two lat/lon points in km."""
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def monitor_feature(feat_key, feat, bbox_delta=0.1):
    """Monitor a single feature for aircraft.
    
    Returns dict with feature info and list of detections.
    """
    lat, lon = feat["lat"], feat["lon"]
    name = feat.get("name", feat_key)
    
    aircraft = query_opensky_bbox(lat, lon, delta=bbox_delta)
    
    # Enrich with distance from feature center
    for a in aircraft:
        if a["lat"] is not None and a["lon"] is not None:
            a["distance_km"] = round(haversine_km(lat, lon, a["lat"], a["lon"]), 2)
        else:
            a["distance_km"] = None
    
    result = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "feature_key": feat_key,
        "feature_name": name,
        "group": feat.get("_group", "unknown"),
        "country": feat.get("country", "unknown"),
        "lat": lat,
        "lon": lon,
        "has_airport": bool(feat.get("airport")),
        "has_helipad": feat.get("helipad", False),
        "aircraft_count": len(aircraft),
        "aircraft": aircraft,
    }
    return result


def append_detections(result):
    """Append a monitoring result to the JSONL log."""
    with open(DETECTIONS_LOG, "a") as f:
        f.write(json.dumps(result, ensure_ascii=False) + "\n")


def run_monitor(features, bbox_delta=0.1):
    """Run aircraft monitoring for a list of features.
    
    Returns list of result dicts.
    """
    results = []
    for i, (feat_key, feat) in enumerate(features):
        name = feat.get("name", feat_key)
        result = monitor_feature(feat_key, feat, bbox_delta=bbox_delta)
        
        count = result["aircraft_count"]
        if count > 0:
            callsigns = [a["callsign"] for a in result["aircraft"] if a["callsign"]]
            print(f"  ✈️  {name}: {count} aircraft — {', '.join(callsigns[:5])}")
        else:
            print(f"  —  {name}: clear")
        
        append_detections(result)
        results.append(result)
        
        # Rate limit between requests
        if i < len(features) - 1:
            time.sleep(RATE_LIMIT)
    
    return results


def show_summary():
    """Read aircraft_detections.jsonl and show latest status per feature."""
    if not os.path.isfile(DETECTIONS_LOG):
        print("No aircraft detection log found.")
        return
    
    latest = {}  # feature_key -> last detection record
    with open(DETECTIONS_LOG) as f:
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
        print("No detection records found.")
        return
    
    print(f"\n{'Feature':<30} {'Country':<12} {'Aircraft':>8} {'Last Check (UTC)'}")
    print("-" * 80)
    for key in sorted(latest):
        rec = latest[key]
        count = rec.get("aircraft_count", 0)
        ts = rec.get("timestamp", "?")[:19]
        country = rec.get("country", "?")
        marker = "✈️" if count > 0 else "  "
        print(f"{marker} {key:<28} {country:<12} {count:>8} {ts}")
    
    total_with = sum(1 for r in latest.values() if r.get("aircraft_count", 0) > 0)
    print(f"\nFeatures with aircraft: {total_with}/{len(latest)}")


# ── Main ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="SCS Aircraft/Helicopter Monitor")
    parser.add_argument("--feature", help="Monitor a single feature by key name")
    parser.add_argument("--summary", action="store_true", help="Show summary of all detections")
    parser.add_argument("--bbox", type=float, default=0.1,
                        help="Bounding box half-size in degrees (default: 0.1)")
    args = parser.parse_args()
    
    if args.summary:
        show_summary()
        sys.exit(0)
    
    db = load_features()
    all_features = get_all_features(db)
    
    if args.feature:
        features = [(k, f) for k, f in all_features if k == args.feature]
        if not features:
            print(f"Feature '{args.feature}' not found.")
            sys.exit(1)
    else:
        features = all_features
    
    print(f"SCS Aircraft Monitor — {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"Monitoring {len(features)} features (bbox: ±{args.bbox}°)")
    print("=" * 60)
    
    results = run_monitor(features, bbox_delta=args.bbox)
    
    total_aircraft = sum(r["aircraft_count"] for r in results)
    features_with = sum(1 for r in results if r["aircraft_count"] > 0)
    
    print(f"\n{'=' * 60}")
    print(f"Total aircraft detected: {total_aircraft}")
    print(f"Features with activity: {features_with}/{len(results)}")
    print(f"Log: {DETECTIONS_LOG}")
