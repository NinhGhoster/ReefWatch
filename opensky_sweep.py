#!/usr/bin/env python3
"""
Spratly Islands airspace monitor — periodic sweep.
Queries OpenSky Network API every 15 minutes for aircraft in the Spratly
bounding box and appends detections to detections.jsonl.

Usage:
    python3 opensky_sweep.py          # run in loop (every 15 min)
    python3 opensky_sweep.py --summary  # show unique aircraft seen
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone

import requests

# ── Config ──────────────────────────────────────────────────────────────
# Target zones: Spratly + Paracel Islands
ZONES = [
    {"name": "spratly", "lamin": 7.0, "lomin": 109.0, "lamax": 12.0, "lomax": 116.0},
    {"name": "paracel", "lamin": 15.7, "lomin": 111.0, "lamax": 17.0, "lomax": 113.0},
]
INTERVAL = 900  # 15 minutes
API_URL = "https://opensky-network.org/api/states/all"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_FILE = os.path.join(SCRIPT_DIR, "detections.jsonl")

# OpenSky free tier: max 42 requests / 10s → cap at 4 req/s
MIN_GAP = 0.3  # seconds between requests (well under the limit)


# ── Helpers ─────────────────────────────────────────────────────────────

def query_opensky(zone):
    """Return list of aircraft dicts inside the bounding box."""
    params = {"lamin": zone["lamin"], "lomin": zone["lomin"], "lamax": zone["lamax"], "lomax": zone["lomax"]}
    try:
        resp = requests.get(API_URL, params=params, timeout=30)
        if resp.status_code in (403, 429):
            print(f"[WARN] OpenSky rate limited ({resp.status_code}), will retry next cycle")
            return []
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"[ERROR] API request failed: {e}")
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
            "lat": s[6],
            "lon": s[5],
            "altitude_m": s[13],      # geo_altitude in metres
            "heading": s[10],
            "velocity_ms": s[9],
            "origin_country": s[2],
        })
    return results


def append_detections(detections):
    """Append detections to the JSONL log file."""
    if not detections:
        return
    with open(LOG_FILE, "a") as f:
        for d in detections:
            f.write(json.dumps(d, ensure_ascii=False) + "\n")


def sweep_loop():
    """Main loop — query every INTERVAL seconds."""
    zone_names = "+".join(z["name"] for z in ZONES)
    print(f"[sweep] {zone_names} monitor started — interval {INTERVAL}s")
    print(f"[sweep] Log → {LOG_FILE}")
    while True:
        try:
            t0 = time.monotonic()
            all_results = []
            for zone in ZONES:
                results = query_opensky(zone)
                all_results.extend(results)
                time.sleep(1)  # rate limit between zones
            append_detections(all_results)
            ts_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
            if all_results:
                cs = sorted({r["callsign"] or "?" for r in all_results})
                print(f"[{ts_str}Z] {len(all_results)} aircraft — callsigns: {', '.join(cs)}")
            else:
                print(f"[{ts_str}Z] No aircraft.")
        except requests.RequestException as e:
            print(f"[ERROR] API request failed: {e}", file=sys.stderr)
        except Exception as e:
            print(f"[ERROR] {e}", file=sys.stderr)

        elapsed = time.monotonic() - t0
        time.sleep(max(1, INTERVAL - elapsed))


def show_summary():
    """Read detections.jsonl and print a summary of unique aircraft."""
    if not os.path.isfile(LOG_FILE):
        print("No detections file found.")
        return

    seen = {}  # callsign → list of detection dicts
    total_lines = 0
    with open(LOG_FILE) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            total_lines += 1
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            cs = d.get("callsign", "?")
            if cs not in seen:
                seen[cs] = d  # store first occurrence

    if not seen:
        print("Detections file is empty.")
        return

    print(f"Summary of detections.jsonl — {total_lines} total records, "
          f"{len(seen)} unique aircraft\n")
    print(f"{'Callsign':<12} {'Country':<20} {'First Seen (UTC)':<25} {'Lat':>8} {'Lon':>8} {'Alt(m)':>8}")
    print("-" * 85)
    for cs in sorted(seen):
        d = seen[cs]
        lat = d.get("lat")
        lon = d.get("lon")
        alt = d.get("altitude_m")
        print(f"{cs:<12} {d.get('origin_country','?'):<20} "
              f"{d.get('datetime_utc','?'):<25} "
              f"{lat if lat is not None else 'N/A':>8} "
              f"{lon if lon is not None else 'N/A':>8} "
              f"{alt if alt is not None else 'N/A':>8}")


# ── Entry ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Spratly Islands aircraft monitor")
    parser.add_argument("--summary", action="store_true",
                        help="Show summary of all unique aircraft detected")
    args = parser.parse_args()

    if args.summary:
        show_summary()
    else:
        sweep_loop()
