#!/usr/bin/env python3
"""
Spratly + Paracel Islands airspace monitor — single check.
Scans each feature individually with its own bounding box.

Usage:  python3 opensky_once.py
"""

import json
import os
import time
import requests

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
FEATURES_FILE = os.path.join(SCRIPT_DIR, "target_features.json")
BBOX_HALF = 0.15
API_URL = "https://opensky-network.org/api/states/all"

def query_opensky(bbox):
    params = {"lamin": bbox[0], "lomin": bbox[1], "lamax": bbox[2], "lomax": bbox[3]}
    try:
        resp = requests.get(API_URL, params=params, timeout=30)
        if resp.status_code == 403:
            print("Rate limited (403). Try again later.")
            return []
        if resp.status_code == 429:
            print("Too many requests (429). Try again later.")
            return []
        resp.raise_for_status()
    except requests.exceptions.RequestException as e:
        print(f"API error: {e}")
        return []
    data = resp.json()
    ts = data.get("time", int(time.time()))
    states = data.get("states") or []
    results = []
    for s in states:
        results.append({
            "timestamp": ts,
            "callsign": (s[1] or "").strip(),
            "lat": s[6],
            "lon": s[5],
            "altitude": s[13],   # geo_altitude (baro may be None)
            "heading": s[10],
            "velocity": s[9],
            "origin_country": s[2],
        })
    return results

if __name__ == "__main__":
    with open(FEATURES_FILE) as f:
        features = json.load(f)
    print(f"Checking OpenSky — {len(features)} features individually...")
    all_results = []
    api_calls = 0
    for feat in features:
        lat, lon = feat["lat"], feat["lon"]
        bbox = (lat - BBOX_HALF, lon - BBOX_HALF, lat + BBOX_HALF, lon + BBOX_HALF)
        results = query_opensky(bbox)
        for r in results:
            r["near_feature"] = feat["key"]
            r["near_feature_name"] = feat["name"]
        all_results.extend(results)
        api_calls += 1
        if results:
            print(f"  {feat['name']:30s} → {len(results)} aircraft")
        if api_calls % 20 == 0:
            print(f"  ... {api_calls}/{len(features)} scanned")
        time.sleep(1.0)

    print(f"\nScanned {api_calls} features. Total aircraft: {len(all_results)}")
    if all_results:
        for r in all_results:
            print(json.dumps(r, ensure_ascii=False))
