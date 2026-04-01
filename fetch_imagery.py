#!/usr/bin/env python3
"""
Spratly Islands Satellite Imagery Fetcher
Pulls latest cloud-free imagery from NASA Worldview for each Spratly airport.
"""

import urllib.request
import os
import json
from datetime import datetime, timedelta

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "imagery")
os.makedirs(OUTPUT_DIR, exist_ok=True)

# Spratly airport locations (name, lat, lon, bbox_half)
LOCATIONS = [
    ("fiery_cross_reef", 9.53, 112.88, 0.2),    # China - 3300m runway
    ("subi_reef", 10.88, 114.07, 0.2),            # China - 3000m runway
    ("mischief_reef", 9.90, 115.52, 0.2),         # China - 2700m runway
    ("taiping_island", 10.38, 114.36, 0.15),      # Taiwan - 1200m runway
    ("thitu_island", 11.05, 114.28, 0.15),        # Philippines - 1300m runway
    ("spratly_island", 8.64, 111.92, 0.15),       # Vietnam - 1200m runway
    ("swallow_reef", 7.37, 113.85, 0.15),         # Malaysia - 1367m runway
]

def fetch_nasa_snapshot(name, lat, lon, bbox_half):
    """Fetch NASA Worldview snapshot for a location."""
    south = lat - bbox_half
    north = lat + bbox_half
    west = lon - bbox_half
    east = lon + bbox_half
    
    # Try last 7 days to find cloud-free imagery
    for days_ago in range(7):
        date = (datetime.utcnow() - timedelta(days=days_ago)).strftime("%Y-%m-%d")
        
        url = (
            f"https://wvs.earthdata.nasa.gov/api/v1/snapshot?"
            f"REQUEST=GetSnapshot"
            f"&TIME={date}"
            f"&BBOX={south},{west},{north},{east}"
            f"&CRS=EPSG:4326"
            f"&LAYERS=MODIS_Terra_CorrectedReflectance_TrueColor"
            f"&WIDTH=1024&HEIGHT=1024"
            f"&FORMAT=image/png"
        )
        
        outfile = os.path.join(OUTPUT_DIR, f"{name}_{date}.png")
        
        try:
            urllib.request.urlretrieve(url, outfile)
            size = os.path.getsize(outfile)
            if size > 10000:  # Skip tiny error responses
                print(f"  ✓ {name}: {date} ({size} bytes)")
                return {"name": name, "date": date, "file": outfile, "size": size}
            else:
                os.remove(outfile)
        except Exception as e:
            pass
    
    print(f"  ✗ {name}: no clear imagery in last 7 days")
    return None

def main():
    print(f"Spratly Islands Satellite Imagery Fetcher")
    print(f"Time: {datetime.utcnow().isoformat()}Z")
    print(f"Output: {OUTPUT_DIR}\n")
    
    results = []
    for name, lat, lon, bbox in LOCATIONS:
        result = fetch_nasa_snapshot(name, lat, lon, bbox)
        if result:
            results.append(result)
    
    # Save metadata
    meta_file = os.path.join(OUTPUT_DIR, "latest_fetch.json")
    with open(meta_file, "w") as f:
        json.dump({
            "timestamp": datetime.utcnow().isoformat(),
            "locations_checked": len(LOCATIONS),
            "images_found": len(results),
            "results": results
        }, f, indent=2)
    
    print(f"\nDone: {len(results)}/{len(LOCATIONS)} locations with imagery")

if __name__ == "__main__":
    main()
