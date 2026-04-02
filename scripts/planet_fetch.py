#!/usr/bin/env python3
"""
Planet Labs Satellite Imagery Fetcher

Downloads Planet PSScene (3-5m) visual imagery for SCS monitoring features
using the Planet Data API v1. Supports activation/download workflow with resume.

Usage:
    python3 planet_fetch.py --feature fiery_cross_reef --days 14
    python3 planet_fetch.py --all --days 30
    python3 planet_fetch.py --lat 9.53 --lon 112.88 --name "Fiery Cross" --days 7
    python3 planet_fetch.py --feature woody_island --days 30 --resume
    python3 planet_fetch.py --all --start-date 2026-03-01 --end-date 2026-03-31
"""

import argparse
import base64
import json
import os
import sys
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone

import requests

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(SCRIPT_DIR)
DATA_DIR = os.path.join(BASE_DIR, "data")
IMAGERY_DIR = os.path.join(BASE_DIR, "imagery_history")
FEATURES_FILE = os.path.join(DATA_DIR, "target_features.json")
LOG_FILE = os.path.join(BASE_DIR, "planet_fetch_log.jsonl")

# Planet API config
PLANET_API_KEY = os.environ.get("PLANET_API_KEY", "PLAKf11ab368d5e34e88a7fcd952ba811363")
PLANET_API_BASE = "https://api.planet.com/data/v1"
PLANET_SEARCH_URL = f"{PLANET_API_BASE}/quick-search"
ITEM_TYPE = "PSScene"
ASSET_TYPE = "visual"
CLOUD_MAX = 0.2
PREFER_QUALITY = os.environ.get("PLANET_QUALITY", "standard")  # standard or test
GEOMETRY_DELTA = 0.05  # ±0.05° around feature center

# Rate limit
RATE_LIMIT = 1.0

os.makedirs(IMAGERY_DIR, exist_ok=True)


def get_auth():
    """Build Basic auth tuple from API key."""
    return (PLANET_API_KEY, "")


def load_features():
    """Load the target features database."""
    with open(FEATURES_FILE) as f:
        return json.load(f)


def filter_features(features, feature_key=None, lat=None, lon=None, name=None):
    """Filter features list by key or custom lat/lon/name."""
    if feature_key:
        matched = [f for f in features if f["key"] == feature_key]
        if not matched:
            print(f"Feature '{feature_key}' not found in target_features.json")
            sys.exit(1)
        return matched
    if lat is not None and lon is not None:
        return [{"key": name or "custom", "name": name or "Custom Location",
                 "lat": lat, "lon": lon}]
    return features


def build_geometry(lat, lon):
    """Build a Polygon geometry around a point (±0.05°)."""
    return {
        "type": "Polygon",
        "coordinates": [[
            [lon - GEOMETRY_DELTA, lat - GEOMETRY_DELTA],
            [lon + GEOMETRY_DELTA, lat - GEOMETRY_DELTA],
            [lon + GEOMETRY_DELTA, lat + GEOMETRY_DELTA],
            [lon - GEOMETRY_DELTA, lat + GEOMETRY_DELTA],
            [lon - GEOMETRY_DELTA, lat - GEOMETRY_DELTA],
        ]]
    }


def build_search_filter(geometry, date_start, date_end):
    """Build the Planet API search filter."""
    return {
        "item_types": [ITEM_TYPE],
        "filter": {
            "type": "AndFilter",
            "config": [
                {
                    "type": "GeometryFilter",
                    "field_name": "geometry",
                    "config": geometry
                },
                {
                    "type": "DateRangeFilter",
                    "field_name": "acquired",
                    "config": {
                        "gte": date_start,
                        "lte": date_end
                    }
                },
                {
                    "type": "RangeFilter",
                    "field_name": "cloud_cover",
                    "config": {"lte": CLOUD_MAX}
                }
            ]
        }
    }


def search_imagery(lat, lon, date_start, date_end):
    """Search Planet API for PSScene imagery.

    Returns list of item dicts with properties and _links.
    """
    geometry = build_geometry(lat, lon)
    search_body = build_search_filter(geometry, date_start, date_end)

    resp = requests.post(
        PLANET_SEARCH_URL,
        json=search_body,
        auth=get_auth(),
        timeout=30
    )

    if resp.status_code == 401:
        print("  ⚠️  Planet API auth failed — check API key")
        return []
    if resp.status_code == 429:
        print("  ⚠️  Rate limited by Planet API — waiting 10s")
        time.sleep(10)
        return search_imagery(lat, lon, date_start, date_end)
    resp.raise_for_status()

    data = resp.json()
    features = data.get("features", [])
    return features


def pick_best_per_day(items):
    """Group items by date, pick lowest cloud_cover per day.

    Returns dict: {date_str: item}
    """
    by_date = defaultdict(list)
    for item in items:
        acquired = item["properties"]["acquired"]
        date_str = acquired[:10]  # YYYY-MM-DD
        by_date[date_str].append(item)

    best = {}
    for date_str, day_items in by_date.items():
        # Prefer standard quality, then lowest cloud
        day_items.sort(key=lambda x: (
            0 if x["properties"].get("quality_category") == "standard" else 1,
            x["properties"]["cloud_cover"]
        ))
        best[date_str] = day_items[0]

    return best


def get_asset_status(item_id):
    """Check the visual asset status for an item.

    Returns dict with 'status' and 'location' (URL) if active,
    or 'status': 'unavailable' if no visual asset exists.
    """
    url = f"{PLANET_API_BASE}/item-types/{ITEM_TYPE}/items/{item_id}/assets"
    resp = requests.get(url, auth=get_auth(), timeout=30)
    resp.raise_for_status()
    assets = resp.json()
    visual = assets.get(ASSET_TYPE)
    if not visual:
        return {"status": "unavailable", "location": None, "expires_at": None}
    return {
        "status": visual.get("status", "unknown"),
        "location": visual.get("location"),
        "expires_at": visual.get("expires_at")
    }


def activate_asset(item_id):
    """Request activation of the visual asset."""
    url = f"{PLANET_API_BASE}/item-types/{ITEM_TYPE}/items/{item_id}/assets/{ASSET_TYPE}/activate"
    resp = requests.post(url, auth=get_auth(), timeout=30)
    if resp.status_code == 202:
        return True  # Accepted for activation
    if resp.status_code == 204:
        return True  # Already active
    resp.raise_for_status()
    return True


def wait_for_activation(item_id, max_wait=300, poll_interval=10):
    """Poll asset status until active or timeout.

    Returns download URL or None.
    """
    elapsed = 0
    while elapsed < max_wait:
        asset = get_asset_status(item_id)
        if asset["status"] == "active":
            return asset["location"]
        if asset["status"] == "unavailable":
            return None
        if asset["status"] == "activating":
            time.sleep(poll_interval)
            elapsed += poll_interval
            continue
        # status is "inactive" — activate it
        activate_asset(item_id)
        time.sleep(poll_interval)
        elapsed += poll_interval

    return None


def download_image(url, output_path):
    """Download image from Planet asset location URL."""
    resp = requests.get(url, stream=True, timeout=120)
    resp.raise_for_status()
    with open(output_path, "wb") as f:
        for chunk in resp.iter_content(chunk_size=8192):
            f.write(chunk)
    return os.path.getsize(output_path)


def safe_name(name):
    """Convert feature name to filesystem-safe slug."""
    return name.lower().replace(" ", "_").replace("/", "_").replace("(", "").replace(")", "")


def already_downloaded(feature_key, date_str):
    """Check if we already have this image."""
    outfile = os.path.join(IMAGERY_DIR, f"{feature_key}_planet_{date_str}.png")
    return os.path.isfile(outfile) and os.path.getsize(outfile) > 1000


def log_fetch(entry):
    """Append a fetch result to the JSONL log."""
    with open(LOG_FILE, "a") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def fetch_feature(feature, date_start, date_end, resume=False):
    """Fetch Planet imagery for a single feature.

    Returns list of (date_str, filepath, size) tuples for downloaded images.
    """
    key = feature["key"]
    lat = feature["lat"]
    lon = feature["lon"]
    name = feature.get("name", key)

    print(f"\n📍 {name} ({lat}, {lon})")
    print(f"   Searching {date_start} to {date_end}...")

    items = search_imagery(lat, lon, date_start, date_end)
    if not items:
        print(f"   No imagery found (cloud_cover ≤ {CLOUD_MAX})")
        return []

    best = pick_best_per_day(items)
    print(f"   Found {len(items)} items → {len(best)} days with usable imagery")

    downloaded = []
    for date_str in sorted(best.keys()):
        item = best[date_str]
        item_id = item["id"]
        cloud = item["properties"]["cloud_cover"]

        if resume and already_downloaded(key, date_str):
            print(f"   ⏭️  {date_str}: already downloaded (cloud={cloud:.0%})")
            continue

        print(f"   📥 {date_str}: activating asset (cloud={cloud:.0%})...")

        # Skip asset activation — thumbnails only with Education/Research plan
        # Try thumbnail directly
        thumb_url = item.get("_links", {}).get("thumbnail")
        if thumb_url:
            outfile = os.path.join(IMAGERY_DIR, f"{key}_planet_{date_str}.png")
            try:
                resp = requests.get(thumb_url, auth=get_auth(), stream=True, timeout=30)
                resp.raise_for_status()
                with open(outfile, "wb") as f:
                    for chunk in resp.iter_content(chunk_size=8192):
                        f.write(chunk)
                size = os.path.getsize(outfile)
                quality = item["properties"].get("quality_category", "?")
                print(f"   ✅ {date_str}: thumbnail ({size // 1024}KB, {quality})")
                downloaded.append((date_str, outfile, size))
                log_fetch({
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "feature": key, "name": name, "date": date_str,
                    "item_id": item_id, "cloud_cover": cloud,
                    "file": os.path.basename(outfile), "size": size,
                    "quality": quality,
                    "status": "ok_thumbnail"
                })
            except Exception as e:
                print(f"   ⚠️  {date_str}: thumbnail failed — {e}")
        else:
            print(f"   ⚠️  {date_str}: no thumbnail available")

        time.sleep(RATE_LIMIT)

    return downloaded


def main():
    parser = argparse.ArgumentParser(description="Planet Labs Imagery Fetcher")
    parser.add_argument("--feature", help="Feature key to fetch")
    parser.add_argument("--all", action="store_true", help="Fetch all features")
    parser.add_argument("--lat", type=float, help="Custom latitude")
    parser.add_argument("--lon", type=float, help="Custom longitude")
    parser.add_argument("--name", help="Custom location name")
    parser.add_argument("--days", type=int, default=30, help="Look back N days (default: 30)")
    parser.add_argument("--start-date", help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end-date", help="End date (YYYY-MM-DD)")
    parser.add_argument("--resume", action="store_true", help="Skip already downloaded images")
    args = parser.parse_args()

    # Determine date range
    if args.start_date and args.end_date:
        date_start = args.start_date + "T00:00:00Z"
        date_end = args.end_date + "T23:59:59Z"
    elif args.start_date:
        date_start = args.start_date + "T00:00:00Z"
        date_end = datetime.now(timezone.utc).strftime("%Y-%m-%dT23:59:59Z")
    elif args.end_date:
        date_end = args.end_date + "T23:59:59Z"
        date_start = (datetime.now(timezone.utc) - timedelta(days=args.days)).strftime("%Y-%m-%dT00:00:00Z")
    else:
        date_end = datetime.now(timezone.utc).strftime("%Y-%m-%dT23:59:59Z")
        date_start = (datetime.now(timezone.utc) - timedelta(days=args.days)).strftime("%Y-%m-%dT00:00:00Z")

    # Determine features
    features_db = load_features()
    if args.all:
        targets = features_db
    elif args.feature or (args.lat and args.lon):
        targets = filter_features(features_db, feature_key=args.feature,
                                  lat=args.lat, lon=args.lon, name=args.name)
    else:
        parser.print_help()
        sys.exit(1)

    print(f"🛰️  Planet Labs PSScene Imagery Fetcher")
    print(f"   Date range: {date_start} → {date_end}")
    print(f"   Features: {len(targets)}")
    print(f"   Cloud cover: ≤ {CLOUD_MAX:.0%}")

    total_downloaded = 0
    for feature in targets:
        dl = fetch_feature(feature, date_start, date_end, resume=args.resume)
        total_downloaded += len(dl)

    print(f"\n✅ Done. {total_downloaded} images downloaded.")


if __name__ == "__main__":
    main()
