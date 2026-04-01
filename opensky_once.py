#!/usr/bin/env python3
"""
Spratly Islands airspace monitor — single check.
Queries OpenSky Network API once for aircraft in the Spratly bounding box
and prints results to stdout.

Usage:  python3 opensky_once.py
"""

import json
import time
import requests

LAMIN, LOMIN, LAMAX, LOMAX = 7.0, 109.0, 12.0, 116.0
API_URL = "https://opensky-network.org/api/states/all"

def query_opensky():
    params = {"lamin": LAMIN, "lomin": LOMIN, "lamax": LAMAX, "lomax": LOMAX}
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
    print(f"Checking OpenSky — bounding box lat={LAMIN}-{LAMAX}, lon={LOMIN}-{LOMAX} ...")
    results = query_opensky()
    if not results:
        print("No aircraft detected.")
    else:
        print(f"Aircraft detected: {len(results)}\n")
        for r in results:
            print(json.dumps(r, ensure_ascii=False))
