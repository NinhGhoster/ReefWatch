#!/usr/bin/env python3
"""
Spratly Islands Aircraft Monitor
Fetches daily satellite imagery and detects changes (aircraft appearing/disappearing).
Run daily via cron or systemd timer.
"""

import urllib.request
import os
import json
import hashlib
from datetime import datetime, timedelta

BASE_DIR = os.path.dirname(__file__)
IMAGERY_DIR = os.path.join(BASE_DIR, "imagery")
HISTORY_DIR = os.path.join(BASE_DIR, "imagery_history")
LOG_FILE = os.path.join(BASE_DIR, "imagery_log.jsonl")
os.makedirs(IMAGERY_DIR, exist_ok=True)
os.makedirs(HISTORY_DIR, exist_ok=True)

LOCATIONS = [
    {"name": "fiery_cross_reef",    "lat": 9.53,  "lon": 112.88, "country": "China",       "runway": "3300m"},
    {"name": "subi_reef",           "lat": 10.88, "lon": 114.07, "country": "China",       "runway": "3000m"},
    {"name": "mischief_reef",       "lat": 9.90,  "lon": 115.52, "country": "China",       "runway": "2700m"},
    {"name": "taiping_island",      "lat": 10.38, "lon": 114.36, "country": "Taiwan",      "runway": "1200m"},
    {"name": "thitu_island",        "lat": 11.05, "lon": 114.28, "country": "Philippines", "runway": "1300m"},
    {"name": "spratly_island",      "lat": 8.64,  "lon": 111.92, "country": "Vietnam",     "runway": "1200m"},
    {"name": "swallow_reef",        "lat": 7.37,  "lon": 113.85, "country": "Malaysia",    "runway": "1367m"},
]

def fetch_image(loc, date_str):
    """Fetch NASA Worldview snapshot for a location and date."""
    lat, lon = loc["lat"], loc["lon"]
    bbox_half = 0.2
    
    url = (
        f"https://wvs.earthdata.nasa.gov/api/v1/snapshot?"
        f"REQUEST=GetSnapshot"
        f"&TIME={date_str}"
        f"&BBOX={lat - bbox_half},{lon - bbox_half},{lat + bbox_half},{lon + bbox_half}"
        f"&CRS=EPSG:4326"
        f"&LAYERS=MODIS_Terra_CorrectedReflectance_TrueColor"
        f"&WIDTH=1024&HEIGHT=1024"
        f"&FORMAT=image/png"
    )
    
    outfile = os.path.join(HISTORY_DIR, f"{loc['name']}_{date_str}.png")
    
    try:
        urllib.request.urlretrieve(url, outfile)
        size = os.path.getsize(outfile)
        if size > 10000:
            return outfile, size
        else:
            os.remove(outfile)
            return None, 0
    except:
        return None, 0

def file_hash(filepath):
    """Quick hash of file for change detection."""
    h = hashlib.md5()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()

def get_previous_image(loc_name):
    """Find the most recent previous image for this location."""
    prefix = f"{loc_name}_"
    files = sorted([
        f for f in os.listdir(HISTORY_DIR)
        if f.startswith(prefix) and f.endswith(".png")
    ], reverse=True)
    
    if len(files) >= 2:
        return os.path.join(HISTORY_DIR, files[1])  # Second newest = previous
    return None

def main():
    today = datetime.utcnow().strftime("%Y-%m-%d")
    
    print(f"Spratly Aircraft Monitor — {today}")
    print("=" * 60)
    
    results = []
    
    for loc in LOCATIONS:
        name = loc["name"]
        print(f"\n📍 {name} ({loc['country']}, runway: {loc['runway']})")
        
        # Fetch today's image
        outfile, size = fetch_image(loc, today)
        
        if not outfile:
            print(f"   ✗ No clear imagery today")
            # Try yesterday
            yesterday = (datetime.utcnow() - timedelta(days=1)).strftime("%Y-%m-%d")
            outfile, size = fetch_image(loc, yesterday)
            if not outfile:
                results.append({"name": name, "date": today, "status": "no_imagery"})
                continue
            today = yesterday
        
        print(f"   ✓ Image: {size} bytes")
        
        # Compare with previous
        prev = get_previous_image(name)
        changed = False
        if prev:
            curr_hash = file_hash(outfile)
            prev_hash = file_hash(prev)
            if curr_hash != prev_hash:
                changed = True
                print(f"   ⚠️  CHANGED since {os.path.basename(prev).split('_')[-1].replace('.png', '')}")
            else:
                print(f"   = No change from previous")
        else:
            print(f"   ℹ️  First image — no comparison available")
        
        # Also copy to latest for quick access
        latest = os.path.join(IMAGERY_DIR, f"{name}_{today}.png")
        if outfile != latest:
            import shutil
            shutil.copy2(outfile, latest)
        
        results.append({
            "name": name,
            "date": today,
            "status": "ok",
            "size": size,
            "changed": changed,
            "file": outfile,
        })
    
    # Log results
    log_entry = {
        "timestamp": datetime.utcnow().isoformat(),
        "date": today,
        "locations": results,
        "changes_detected": sum(1 for r in results if r.get("changed")),
        "total_images": sum(1 for r in results if r.get("status") == "ok"),
    }
    
    with open(LOG_FILE, "a") as f:
        f.write(json.dumps(log_entry) + "\n")
    
    print(f"\n{'=' * 60}")
    print(f"Images: {log_entry['total_images']}/{len(LOCATIONS)}")
    print(f"Changes: {log_entry['changes_detected']}")
    
    if log_entry["changes_detected"] > 0:
        print(f"\n⚠️  CHANGES DETECTED — check imagery_history/ for differences!")
        for r in results:
            if r.get("changed"):
                print(f"   - {r['name']}: changed since previous capture")

if __name__ == "__main__":
    main()
