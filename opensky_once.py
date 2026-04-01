#!/usr/bin/env python3
"""
Spratly + Paracel Islands airspace monitor — single check.
Queries OpenSky Network API for aircraft in both zones.

Usage:  python3 opensky_once.py
"""

import json
import time
import requests

ZONES = [
    {"name": "spratly", "lamin": 7.0, "lomin": 109.0, "lamax": 12.0, "lomax": 116.0},
    {"name": "paracel", "lamin": 15.7, "lomin": 111.0, "lamax": 17.0, "lomax": 113.0},
]
API_URL = "https://opensky-network.org/api/states/all"

def query_opensky(zone):
    params = {"lamin": zone["lamin"], "lomin": zone["lomin"], "lamax": zone["lamax"], "lomax": zone["lomax"]}
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
    zone_names = "+".join(z["name"] for z in ZONES)
    print(f"Checking OpenSky — {zone_names} zones...")
    all_results = []
    for zone in ZONES:
        print(f"\n  [{zone['name']}] {zone['lamin']}-{zone['lamax']}°N, {zone['lomin']}-{zone['lomax']}°E")
        results = query_opensky(zone)
        for r in results:
            r["zone"] = zone["name"]
        all_results.extend(results)
        if results:
            print(f"    → {len(results)} aircraft")
        else:
            print(f"    → No aircraft")
        time.sleep(1)

    print(f"\nTotal: {len(all_results)} aircraft")
    if all_results:
        for r in all_results:
            print(json.dumps(r, ensure_ascii=False))
