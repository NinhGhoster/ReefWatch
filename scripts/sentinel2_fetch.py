#!/usr/bin/env python3
"""
Sentinel-2 L2A Imagery Fetcher

Downloads Sentinel-2 surface reflectance imagery from Earth Search STAC API
(free, no auth required) for South China Sea monitoring features.

Uses COG (Cloud Optimized GeoTIFF) windowed reads to efficiently extract
small regions without downloading entire tiles.

Usage:
    python3 sentinel2_fetch.py --feature fiery_cross_reef --days 7
    python3 sentinel2_fetch.py --all --days 30
    python3 sentinel2_fetch.py --lat 9.53 --lon 112.88 --name "Fiery Cross" --days 7
    python3 sentinel2_fetch.py --feature woody_island --days 30 --resume
"""

import argparse
import json
import math
import os
import sys
import time
from datetime import datetime, timedelta, timezone

import numpy as np
import requests
from PIL import Image

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(SCRIPT_DIR, "..", "data")
IMAGERY_DIR = os.path.join(SCRIPT_DIR, "..", "imagery_history")
FEATURES_FILE = os.path.join(DATA_DIR, "scs_features.json")
LOG_FILE = os.path.join(SCRIPT_DIR, "..", "sentinel2_fetch_log.jsonl")

STAC_URL = "https://earth-search.aws.element84.com/v1"
COLLECTION = "sentinel-2-l2a"

# Rate limit between API requests
RATE_LIMIT = 1.5

# Bands for true-color composite (B04=red, B03=green, B02=blue)
TRUE_COLOR_BANDS = ["red", "green", "blue"]

os.makedirs(IMAGERY_DIR, exist_ok=True)


def load_features():
    """Load the features database."""
    with open(FEATURES_FILE) as f:
        return json.load(f)


def get_all_features(db, feature_filter=None):
    """Extract all features as a flat list."""
    features = []
    for group_key, group in db.get("island_groups", {}).items():
        for feat_key, feat in group.get("features", {}).items():
            if feature_filter and feat_key != feature_filter:
                continue
            feat_copy = dict(feat)
            feat_copy["_key"] = feat_key
            features.append(feat_copy)
    return features


def make_bbox(lat, lon, km=5):
    """Create a small bounding box around a point (approx)."""
    dlat = km / 111.0
    dlon = km / (111.0 * math.cos(math.radians(lat)))
    return [
        round(lon - dlon, 6),
        round(lat - dlat, 6),
        round(lon + dlon, 6),
        round(lat + dlat, 6),
    ]


def query_stac(bbox, date_start, date_end):
    """Query Earth Search STAC API for Sentinel-2 L2A items."""
    datetime_str = f"{date_start}T00:00:00Z/{date_end}T23:59:59Z"
    params = {
        "collections": COLLECTION,
        "bbox": ",".join(str(x) for x in bbox),
        "datetime": datetime_str,
        "limit": 50,
        "sortby": "-properties.eo:cloud_cover",
    }
    try:
        resp = requests.get(f"{STAC_URL}/search", params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as e:
        print(f"  [ERROR] STAC query failed: {e}")
        return []

    items = data.get("features", [])
    # Sort ascending by cloud cover
    items.sort(key=lambda x: x.get("properties", {}).get("eo:cloud_cover", 100))
    return items


def read_cog_window(url, bbox, out_size=(512, 512)):
    """
    Read a window from a Cloud Optimized GeoTIFF using rasterio,
    without downloading the entire file. Handles CRS reprojection.
    """
    import rasterio
    from rasterio.warp import transform_bounds
    from rasterio.windows import from_bounds

    with rasterio.open(url) as src:
        # Transform WGS84 bbox to raster CRS if needed
        if src.crs and src.crs.to_epsg() != 4326:
            left, bottom, right, top = transform_bounds("EPSG:4326", src.crs, *bbox)
        else:
            left, bottom, right, top = bbox

        window = from_bounds(left, bottom, right, top, transform=src.transform)
        # Clamp window to raster bounds
        window = window.intersection(rasterio.windows.Window(0, 0, src.width, src.height))

        data = src.read(
            window=window,
            out_shape=(src.count, out_size[1], out_size[0]),
            resampling=rasterio.enums.Resampling.bilinear,
        )
        return data  # shape: (bands, height, width)


def normalize_band(band):
    """Normalize a band to 0-255 using percentile stretch."""
    if band.max() == band.min():
        return np.zeros_like(band, dtype=np.uint8)
    valid = band[band > 0]
    if len(valid) == 0:
        return np.zeros_like(band, dtype=np.uint8)
    p2, p98 = np.percentile(valid, [2, 98])
    if p98 <= p2:
        return np.zeros_like(band, dtype=np.uint8)
    clipped = np.clip(band, p2, p98)
    return ((clipped - p2) / (p98 - p2 + 1e-10) * 255).astype(np.uint8)


def download_thumbnail(url, output_path):
    """Download a thumbnail image."""
    try:
        resp = requests.get(url, stream=True, timeout=60)
        resp.raise_for_status()
        with open(output_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                f.write(chunk)
        return True
    except requests.RequestException as e:
        print(f"  [ERROR] Thumbnail download failed: {e}")
        return False


def safe_name(name):
    """Convert feature name to safe filename."""
    return name.lower().replace(" ", "_").replace("(", "").replace(")", "").replace("/", "_").replace("'", "")


def download_single_item(item, feat_key, bbox, output_dir):
    """Download true-color image for a single STAC item."""
    item_id = item.get("id", "unknown")
    date_str = item.get("properties", {}).get("datetime", "")[:10]
    cloud = item.get("properties", {}).get("eo:cloud_cover", -1)
    assets = item.get("assets", {})

    png_path = os.path.join(output_dir, f"{feat_key}_sentinel2_{date_str}.png")
    if os.path.exists(png_path):
        return png_path

    # Strategy 1: Try COG windowed read of individual bands
    band_urls = {}
    for band_name in TRUE_COLOR_BANDS:
        if band_name in assets:
            band_urls[band_name] = assets[band_name].get("href")

    if len(band_urls) == 3:
        try:
            print(f"  Reading bands via COG windowed access...")
            bands = []
            for band_name in TRUE_COLOR_BANDS:
                data = read_cog_window(band_urls[band_name], bbox)
                bands.append(data[0])  # First (only) band

            rgb = np.stack([normalize_band(b) for b in bands], axis=-1)
            img = Image.fromarray(rgb)
            img.save(png_path, quality=90)
            print(f"  [OK] {png_path} (cloud: {cloud:.1f}%)")
            return png_path
        except Exception as e:
            print(f"  [WARN] COG windowed read failed: {e}, trying thumbnail...")

    # Strategy 2: Fallback to thumbnail
    thumb_url = assets.get("thumbnail", {}).get("href")
    if thumb_url:
        print(f"  Downloading thumbnail...")
        if download_thumbnail(thumb_url, png_path):
            print(f"  [OK] {png_path} (thumbnail, cloud: {cloud:.1f}%)")
            return png_path

    print(f"  [WARN] No usable assets for {item_id}")
    return None


def log_entry(entry):
    """Append an entry to the fetch log."""
    with open(LOG_FILE, "a") as f:
        f.write(json.dumps(entry) + "\n")


def fetch_feature(feature, days=7, resume=False, date=None):
    """Fetch Sentinel-2 imagery for a single feature."""
    feat_key = feature["_key"]
    name = feature.get("name", feat_key)
    lat = feature["lat"]
    lon = feature["lon"]

    print(f"\n{'='*60}")
    print(f"Feature: {name} ({lat}, {lon})")
    print(f"{'='*60}")

    if date:
        end_date = datetime.strptime(date, "%Y-%m-%d").date()
    else:
        end_date = datetime.now(timezone.utc).date()
    start_date = end_date - timedelta(days=days - 1)

    bbox = make_bbox(lat, lon)
    print(f"  Bbox: {bbox}")
    print(f"  Date range: {start_date} to {end_date}")

    # Query STAC
    print(f"  Querying STAC API...")
    items = query_stac(bbox, str(start_date), str(end_date))

    if not items:
        print(f"  [INFO] No Sentinel-2 imagery found for this date range.")
        log_entry({
            "feature": feat_key,
            "name": name,
            "date_range": f"{start_date}/{end_date}",
            "items_found": 0,
            "status": "no_data",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        return []

    print(f"  Found {len(items)} items (sorted by cloud cover)")

    # Group by date, take best (lowest cloud) per day
    by_date = {}
    for item in items:
        dt = item.get("properties", {}).get("datetime", "")[:10]
        if dt and dt not in by_date:
            by_date[dt] = item

    print(f"  Unique dates with imagery: {len(by_date)}")

    downloaded = []
    for dt, item in sorted(by_date.items()):
        output_path = os.path.join(IMAGERY_DIR, f"{feat_key}_sentinel2_{dt}.png")
        if resume and os.path.exists(output_path):
            print(f"  [SKIP] {dt} (exists, --resume)")
            downloaded.append(output_path)
            continue

        cloud = item.get("properties", {}).get("eo:cloud_cover", -1)
        print(f"\n  Processing {dt} (cloud: {cloud:.1f}%):")
        result = download_single_item(item, feat_key, bbox, IMAGERY_DIR)
        if result:
            downloaded.append(result)
            log_entry({
                "feature": feat_key,
                "name": name,
                "date": dt,
                "cloud_cover": cloud,
                "file": result,
                "status": "ok",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
        else:
            log_entry({
                "feature": feat_key,
                "name": name,
                "date": dt,
                "cloud_cover": cloud,
                "status": "download_failed",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })

        time.sleep(RATE_LIMIT)

    print(f"\n  Downloaded: {len(downloaded)}/{len(by_date)}")
    return downloaded


def main():
    parser = argparse.ArgumentParser(description="Fetch Sentinel-2 L2A imagery via Earth Search STAC")
    parser.add_argument("--feature", help="Feature key from scs_features.json")
    parser.add_argument("--all", action="store_true", help="Fetch all features")
    parser.add_argument("--lat", type=float, help="Custom latitude")
    parser.add_argument("--lon", type=float, help="Custom longitude")
    parser.add_argument("--name", default="custom", help="Custom feature name")
    parser.add_argument("--days", type=int, default=7, help="Number of days back to search")
    parser.add_argument("--date", help="End date (YYYY-MM-DD), default: today")
    parser.add_argument("--resume", action="store_true", help="Skip already downloaded files")
    args = parser.parse_args()

    if args.feature:
        db = load_features()
        features = get_all_features(db, feature_filter=args.feature)
        if not features:
            print(f"Feature '{args.feature}' not found in {FEATURES_FILE}")
            sys.exit(1)
    elif args.all:
        db = load_features()
        features = get_all_features(db)
    elif args.lat and args.lon:
        features = [{"_key": safe_name(args.name), "name": args.name, "lat": args.lat, "lon": args.lon}]
    else:
        parser.print_help()
        sys.exit(1)

    total = 0
    for feat in features:
        downloaded = fetch_feature(feat, days=args.days, resume=args.resume, date=args.date)
        total += len(downloaded)
        time.sleep(RATE_LIMIT)

    print(f"\nDone. Total images downloaded: {total}")


if __name__ == "__main__":
    main()
