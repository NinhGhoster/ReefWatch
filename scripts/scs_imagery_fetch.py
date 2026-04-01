#!/usr/bin/env python3
"""
South China Sea Comprehensive Imagery Fetcher
Fetches NASA Worldview satellite imagery for ALL monitored features.
"""

import urllib.request
import os
import json
import sys
from datetime import datetime, timedelta

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
IMAGERY_DIR = os.path.join(BASE_DIR, "imagery_history")
LOG_FILE = os.path.join(BASE_DIR, "imagery_log.jsonl")
FEATURES_FILE = os.path.join(BASE_DIR, "scs_features.json")
os.makedirs(IMAGERY_DIR, exist_ok=True)

def load_features():
    with open(FEATURES_FILE) as f:
        return json.load(f)

def fetch_image(name, lat, lon, date_str, bbox=0.15):
    """Fetch NASA Worldview snapshot."""
    url = (
        f"https://wvs.earthdata.nasa.gov/api/v1/snapshot?"
        f"REQUEST=GetSnapshot"
        f"&TIME={date_str}"
        f"&BBOX={lat-bbox},{lon-bbox},{lat+bbox},{lon+bbox}"
        f"&CRS=EPSG:4326"
        f"&LAYERS=MODIS_Terra_CorrectedReflectance_TrueColor"
        f"&WIDTH=512&HEIGHT=512"
        f"&FORMAT=image/png"
    )
    outfile = os.path.join(IMAGERY_DIR, f"{name}_{date_str}.png")
    try:
        urllib.request.urlretrieve(url, outfile)
        if os.path.getsize(outfile) > 8000:
            return outfile, os.path.getsize(outfile)
        os.remove(outfile)
    except:
        pass
    return None, 0

def main():
    db = load_features()
    today = datetime.utcnow().strftime("%Y-%m-%d")
    yesterday = (datetime.utcnow() - timedelta(days=1)).strftime("%Y-%m-%d")

    print(f"SCS Imagery Fetcher — {today}")
    print("=" * 60)

    results = []
    total = 0
    captured = 0

    for group_key, group in db.get("island_groups", {}).items():
        print(f"\n📍 {group['name']}")
        for feat_key, feat in group.get("features", {}).items():
            total += 1
            lat, lon = feat["lat"], feat["lon"]
            outfile, size = fetch_image(feat_key, lat, lon, today)
            if not outfile:
                outfile, size = fetch_image(feat_key, lat, lon, yesterday)
            
            if outfile:
                captured += 1
                has_airport = "✈️" if feat.get("airport") else "  "
                has_port = "🚢" if feat.get("port") else "  "
                has_heli = "🚁" if feat.get("helipad") else "  "
                print(f"   {has_airport}{has_port}{has_heli} {feat['name'][:40]:<40} {size:>7}B")
                results.append({
                    "name": feat_key,
                    "group": group_key,
                    "date": today,
                    "size": size,
                    "status": "ok"
                })
            else:
                print(f"   ❌ {feat['name'][:40]:<40} no imagery")
                results.append({
                    "name": feat_key,
                    "group": group_key,
                    "date": today,
                    "status": "no_imagery"
                })

    # Log
    log_entry = {
        "timestamp": datetime.utcnow().isoformat(),
        "date": today,
        "total_features": total,
        "images_captured": captured,
        "results": results
    }
    with open(LOG_FILE, "a") as f:
        f.write(json.dumps(log_entry) + "\n")

    print(f"\n{'=' * 60}")
    print(f"Captured: {captured}/{total} features")

if __name__ == "__main__":
    main()
