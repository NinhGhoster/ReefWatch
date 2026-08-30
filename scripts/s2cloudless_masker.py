#!/usr/bin/env python3
"""
s2cloudless Mask Generator

Fetches 10 Sentinel-2 L1C spectral bands (B01, B02, B04, B05, B08, B8A, B09, B10, B11, B12)
via Cloud Optimized GeoTIFF (COG) windowed reads from Earth Search AWS,
and runs the LightGBM `s2cloudless` model to generate highly accurate cloud masks.

Usage:
    python3 scripts/s2cloudless_masker.py --feature fiery_cross_reef --date 2026-08-18
"""

import argparse
import os
import sys
import numpy as np
import requests
from PIL import Image

try:
    import rasterio
    from rasterio.windows import from_bounds
    from s2cloudless import S2PixelCloudDetector
except ImportError:
    print("Please install requirements: pip install s2cloudless lightgbm rasterio")
    sys.exit(1)

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
IMAGERY_DIR = os.path.join(SCRIPT_DIR, "..", "imagery_history")
DATA_DIR = os.path.join(SCRIPT_DIR, "..", "data")

STAC_URL = "https://earth-search.aws.element84.com/v1/search"
COLLECTION = "sentinel-2-l1c"

# s2cloudless requires these exact 10 bands in this order:
S2CLOUDLESS_BANDS = [
    "coastal",  # B01
    "blue",     # B02
    "red",      # B04
    "rededge1", # B05
    "nir",      # B08
    "nir08",    # B8A
    "nir09",    # B09
    "cirrus",   # B10
    "swir16",   # B11
    "swir22",   # B12
]

def load_feature(feature_key):
    import json
    with open(os.path.join(DATA_DIR, "scs_features.json")) as f:
        db = json.load(f)
    for g in db.get("island_groups", {}).values():
        if feature_key in g.get("features", {}):
            return g["features"][feature_key]
    return None

def make_bbox(lat, lon, km=5):
    import math
    dlat = km / 111.0
    dlon = km / (111.0 * math.cos(math.radians(lat)))
    return [
        round(lon - dlon, 6),
        round(lat - dlat, 6),
        round(lon + dlon, 6),
        round(lat + dlat, 6),
    ]

def read_cog_window(url, bbox, out_size=(512, 512)):
    from rasterio.warp import transform_bounds
    with rasterio.Env(AWS_NO_SIGN_REQUEST="YES", GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR"):
        with rasterio.open(url) as src:
            bounds = transform_bounds("EPSG:4326", src.crs, *bbox)
            window = from_bounds(*bounds, transform=src.transform)
            data = src.read(1, window=window, out_shape=out_size, resampling=rasterio.enums.Resampling.bilinear)
            return data

def fetch_l1c_stac_item(bbox, target_date):
    datetime_str = f"{target_date}T00:00:00Z/{target_date}T23:59:59Z"
    payload = {
        "collections": [COLLECTION],
        "bbox": bbox,
        "datetime": datetime_str,
        "limit": 1
    }
    resp = requests.post(STAC_URL, json=payload).json()
    items = resp.get("features", [])
    if not items:
        return None
    return items[0]

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--feature", required=True)
    parser.add_argument("--date", required=True)
    args = parser.parse_args()

    feat = load_feature(args.feature)
    if not feat:
        print(f"Feature {args.feature} not found.")
        sys.exit(1)

    bbox = make_bbox(feat["lat"], feat["lon"])
    
    print(f"🔍 Searching STAC for L1C item on {args.date}...")
    item = fetch_l1c_stac_item(bbox, args.date)
    if not item:
        print(f"❌ No Sentinel-2 L1C imagery found for {args.date}.")
        sys.exit(1)

    assets = item["assets"]
    bands_data = []
    
    print("📥 Downloading 10 spectral bands via COG window (this takes a moment)...")
    for b_name in S2CLOUDLESS_BANDS:
        if b_name not in assets:
            print(f"❌ Missing band {b_name} in STAC item.")
            sys.exit(1)
        url = assets[b_name]["href"]
        # print(f"  -> fetching {b_name}...")
        data = read_cog_window(url, bbox)
        bands_data.append(data)
    
    # Stack into (H, W, 10)
    img_stack = np.stack(bands_data, axis=-1).astype(np.float32)
    
    # Sentinel-2 L1C is typically scaled by 10000. s2cloudless expects TOA reflectance in [0, 1] (or 0-10000).
    # s2cloudless divides by 10000 internally if max > 1. 
    img_stack = np.expand_dims(img_stack / 10000.0, axis=0) # Shape: (1, H, W, 10)

    print("🧠 Running s2cloudless inference...")
    cloud_detector = S2PixelCloudDetector(threshold=0.4, average_over=4, dilation_size=2, all_bands=False)
    
    # Get probability mask
    cloud_mask = cloud_detector.get_cloud_masks(img_stack)[0] # Shape (H, W)
    
    # Save as PNG
    out_mask_path = os.path.join(IMAGERY_DIR, f"{args.feature}_s2cloudless_{args.date}.png")
    mask_img = (cloud_mask * 255).astype(np.uint8)
    Image.fromarray(mask_img).save(out_mask_path)
    
    cloud_pct = (np.sum(cloud_mask) / cloud_mask.size) * 100
    print(f"✅ Saved mask to {out_mask_path} (Cloud cover: {cloud_pct:.1f}%)")

if __name__ == "__main__":
    main()
