#!/usr/bin/env python3
"""
Sentinel-2 Change Detection

Compares pairs of Sentinel-2 images for the same feature to detect changes.
Uses SSIM (structural similarity index) and NDVI for change scoring.

Usage:
    python3 sentinel2_change_detection.py --feature fiery_cross_reef
    python3 sentinel2_change_detection.py --image1 path/to/img1.png --image2 path/to/img2.png
    python3 sentinel2_change_detection.py --auto  # Compare all consecutive pairs
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from glob import glob

import numpy as np
from PIL import Image

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
IMAGERY_DIR = os.path.join(SCRIPT_DIR, "..", "imagery_history")
LOG_FILE = os.path.join(SCRIPT_DIR, "..", "sentinel2_changes.jsonl")
OUTPUT_DIR = os.path.join(SCRIPT_DIR, "..", "imagery_history")

os.makedirs(OUTPUT_DIR, exist_ok=True)


def load_image_as_gray(path, size=None):
    """Load image as grayscale numpy array, optionally resized."""
    img = Image.open(path).convert("L")
    if size:
        img = img.resize(size, Image.LANCZOS)
    return np.array(img, dtype=np.float64)


def load_image_as_rgb(path, size=None):
    """Load image as RGB numpy array, optionally resized."""
    img = Image.open(path).convert("RGB")
    if size:
        img = img.resize(size, Image.LANCZOS)
    return np.array(img, dtype=np.float64)


def compute_ssim(img1, img2):
    """
    Compute SSIM between two grayscale images.
    Returns SSIM score (1.0 = identical, lower = more different).
    Uses scikit-image if available, falls back to manual computation.
    """
    from skimage.metrics import structural_similarity as ssim

    # Ensure same dimensions
    h = min(img1.shape[0], img2.shape[0])
    w = min(img1.shape[1], img2.shape[1])
    img1 = img1[:h, :w]
    img2 = img2[:h, :w]

    score = ssim(img1, img2, data_range=255.0)
    return score


def compute_ndvi_proxy(rgb):
    """
    Compute a vegetation proxy from RGB (no NIR band available in RGB composite).
    Uses green channel relative to red as a rough approximation.
    Returns array of values roughly in [-1, 1] range.
    """
    red = rgb[:, :, 0].astype(np.float64)
    green = rgb[:, :, 1].astype(np.float64)
    # Green-Red difference ratio as vegetation proxy
    denominator = green + red + 1e-10
    ndvi_proxy = (green - red) / denominator
    return ndvi_proxy


def compute_ndvi_change(rgb1, rgb2):
    """Compute vegetation index change between two RGB images."""
    ndvi1 = compute_ndvi_proxy(rgb1)
    ndvi2 = compute_ndvi_proxy(rgb2)
    diff = np.abs(ndvi2 - ndvi1)
    return float(np.mean(diff))


def compute_pixel_change(img1, img2):
    """Compute mean absolute pixel difference as percentage."""
    h = min(img1.shape[0], img2.shape[0])
    w = min(img1.shape[1], img2.shape[1])
    img1 = img1[:h, :w]
    img2 = img2[:h, :w]
    diff = np.abs(img1.astype(np.float64) - img2.astype(np.float64))
    return float(np.mean(diff) / 255.0 * 100)


def create_diff_visualization(rgb1, rgb2, output_path):
    """Create a difference heatmap visualization."""
    h = min(rgb1.shape[0], rgb2.shape[0])
    w = min(rgb1.shape[1], rgb2.shape[1])
    rgb1 = rgb1[:h, :w]
    rgb2 = rgb2[:h, :w]

    # Compute per-pixel difference
    diff = np.mean(np.abs(rgb2 - rgb1), axis=2)

    # Normalize to 0-255
    if diff.max() > 0:
        diff_norm = (diff / diff.max() * 255).astype(np.uint8)
    else:
        diff_norm = np.zeros_like(diff, dtype=np.uint8)

    # Create heatmap using a simple red-yellow gradient
    heatmap = np.zeros((h, w, 3), dtype=np.uint8)
    heatmap[:, :, 0] = diff_norm  # Red channel = change intensity
    heatmap[:, :, 1] = (diff_norm * 0.6).astype(np.uint8)  # Some yellow
    heatmap[:, :, 2] = 0

    # Blend with original (60% original, 40% heatmap)
    blend = (rgb1 * 0.6 + heatmap * 0.4).astype(np.uint8)
    Image.fromarray(blend).save(output_path, quality=90)


def parse_date_from_filename(path):
    """Extract date from filename like feature_sentinel2_2026-03-28.png"""
    basename = os.path.basename(path)
    # Look for YYYY-MM-DD pattern in the filename
    import re
    match = re.search(r'(\d{4}-\d{2}-\d{2})', basename)
    if match:
        return match.group(1)
    return "unknown"


def compare_images(path1, path2, feature_key=None):
    """Compare two images and return change metrics."""
    date1 = parse_date_from_filename(path1)
    date2 = parse_date_from_filename(path2)

    print(f"  Comparing {date1} vs {date2}")

    # Load as RGB for visualization and NDVI
    target_size = (1024, 1024)  # Standard size for comparison
    rgb1 = load_image_as_rgb(path1, size=target_size)
    rgb2 = load_image_as_rgb(path2, size=target_size)

    # Load as grayscale for SSIM
    gray1 = load_image_as_gray(path1, size=target_size)
    gray2 = load_image_as_gray(path2, size=target_size)

    # Compute metrics
    ssim_score = compute_ssim(gray1, gray2)
    pixel_diff = compute_pixel_change(gray1, gray2)
    ndvi_change = compute_ndvi_change(rgb1, rgb2)

    # Classify change level
    if ssim_score > 0.95:
        change_level = "minimal"
    elif ssim_score > 0.85:
        change_level = "low"
    elif ssim_score > 0.70:
        change_level = "moderate"
    else:
        change_level = "significant"

    # Create visualization
    if feature_key:
        vis_path = os.path.join(OUTPUT_DIR, f"{feature_key}_diff_{date1}_vs_{date2}.png")
    else:
        vis_path = os.path.join(OUTPUT_DIR, f"diff_{date1}_vs_{date2}.png")

    create_diff_visualization(rgb1, rgb2, vis_path)

    result = {
        "image1": path1,
        "image2": path2,
        "date1": date1,
        "date2": date2,
        "feature": feature_key or "unknown",
        "ssim": round(ssim_score, 4),
        "pixel_diff_pct": round(pixel_diff, 2),
        "ndvi_change": round(ndvi_change, 4),
        "change_level": change_level,
        "visualization": vis_path,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    print(f"    SSIM: {ssim_score:.4f}")
    print(f"    Pixel diff: {pixel_diff:.2f}%")
    print(f"    NDVI change: {ndvi_change:.4f}")
    print(f"    Level: {change_level}")
    print(f"    Visualization: {vis_path}")

    return result


def log_result(result):
    """Append result to the changes JSONL log."""
    with open(LOG_FILE, "a") as f:
        f.write(json.dumps(result) + "\n")


def find_sentinel2_images(feature_key=None):
    """Find all Sentinel-2 PNG images, optionally filtered by feature."""
    pattern = os.path.join(IMAGERY_DIR, "*_sentinel2_*.png")
    files = sorted(glob(pattern))
    if feature_key:
        files = [f for f in files if f"/{feature_key}_sentinel2_" in f]
    return files


def auto_compare(feature_key=None):
    """Automatically compare all consecutive image pairs."""
    images = find_sentinel2_images(feature_key)
    if not images:
        print("No Sentinel-2 images found.")
        return []

    # Group by feature
    by_feature = {}
    for img in images:
        fname = os.path.basename(img)
        key = fname.split("_sentinel2_")[0]
        by_feature.setdefault(key, []).append(img)

    results = []
    for feat_key, paths in by_feature.items():
        paths = sorted(paths)
        if len(paths) < 2:
            print(f"Feature {feat_key}: only {len(paths)} image(s), skipping comparison")
            continue

        print(f"\nFeature: {feat_key} ({len(paths)} images)")
        for i in range(len(paths) - 1):
            result = compare_images(paths[i], paths[i + 1], feat_key)
            log_result(result)
            results.append(result)

    return results


def main():
    parser = argparse.ArgumentParser(description="Sentinel-2 change detection")
    parser.add_argument("--feature", help="Feature key to process")
    parser.add_argument("--auto", action="store_true", help="Auto-compare all consecutive pairs")
    parser.add_argument("--image1", help="First image path")
    parser.add_argument("--image2", help="Second image path")
    args = parser.parse_args()

    if args.image1 and args.image2:
        result = compare_images(args.image1, args.image2)
        log_result(result)
    elif args.auto or args.feature:
        results = auto_compare(args.feature)
        print(f"\nCompared {len(results)} pairs")
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
