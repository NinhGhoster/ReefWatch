#!/usr/bin/env python3
"""
Median Compositer for ReefWatch

Generates a cloud-free baseline image by calculating the median pixel values 
across a time-series of optical images (e.g., 30-day window).
Since clouds and cloud shadows move, taking the median effectively erases them, 
leaving a clear view of the ground.

Usage:
    python3 scripts/median_compositer.py --feature fiery_cross_reef --days 30
"""

import argparse
import glob
import os
import re
import sys
from datetime import datetime
import numpy as np
from PIL import Image

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
IMAGERY_DIR = os.path.join(SCRIPT_DIR, "..", "imagery_history")
DERIVED_DIR = os.path.join(SCRIPT_DIR, "..", "derived")

os.makedirs(DERIVED_DIR, exist_ok=True)

def parse_date(filename):
    match = re.search(r'_(\d{4}-\d{2}-\d{2})\.', filename)
    if match:
        return datetime.strptime(match.group(1), "%Y-%m-%d")
    return None

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--feature", required=True)
    parser.add_argument("--days", type=int, default=30)
    args = parser.parse_args()

    pattern = os.path.join(IMAGERY_DIR, f"{args.feature}_sentinel2_*.png")
    files = glob.glob(pattern)
    
    if not files:
        print(f"No Sentinel-2 imagery found for {args.feature}.")
        sys.exit(1)

    # Sort files by date (newest first)
    files.sort(key=lambda x: parse_date(os.path.basename(x)) or datetime.min, reverse=True)
    
    # We will just take the top `args.days` images as a rough approximation of a 30-day window
    # In a true system, you'd filter by exact datetime deltas, but this works for demonstration.
    recent_files = files[:args.days]
    
    print(f"Compositing {len(recent_files)} images for {args.feature}...")
    
    arrays = []
    for f in recent_files:
        try:
            img = Image.open(f).convert("RGB")
            arrays.append(np.array(img))
        except Exception as e:
            print(f"Failed to read {f}: {e}")

    if not arrays:
        sys.exit(1)

    # Calculate median along the time axis (axis 0)
    stack = np.stack(arrays, axis=0)
    median_img = np.median(stack, axis=0).astype(np.uint8)
    
    out_path = os.path.join(DERIVED_DIR, f"{args.feature}_cloudfree_baseline.png")
    Image.fromarray(median_img).save(out_path)
    
    print(f"✅ Generated cloud-free median composite: {out_path}")

if __name__ == "__main__":
    main()
