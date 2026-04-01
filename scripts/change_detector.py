#!/usr/bin/env python3
"""
SCS Change Detector — SSIM-based satellite imagery comparison.

Provides structural similarity analysis, pixel difference detection,
brightness change tracking, and changelog classification for satellite imagery.

Usage:
    python3 change_detector.py <image1> <image2>           # Compare two images
    python3 change_detector.py --batch                      # Process all features
    python3 change_detector.py --batch --feature woody_island  # Single feature batch
    python3 change_detector.py --changelog                  # Detect change types
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from PIL import Image
from skimage.metrics import structural_similarity as ssim

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(SCRIPT_DIR)
IMAGERY_DIR = os.path.join(BASE_DIR, "imagery_history")
CHANGELOG_FILE = os.path.join(BASE_DIR, "imagery_changes.jsonl")

# Thresholds
SSIM_CHANGE_THRESHOLD = 0.92     # Below this = significant change
PIXEL_DIFF_THRESHOLD = 3.0       # Above 3% = notable pixel diff
BRIGHTNESS_CHANGE_THRESHOLD = 15 # >15% brightness shift = cloud/obstruction
CONSTRUCTION_DARK_THRESHOLD = 80 # Mean pixel value shift indicating new structures
VESSEL_SPOT_THRESHOLD = 5        # Small bright regions suggesting vessels


def load_image(path):
    """Load image as numpy array, converting to RGB if needed."""
    img = Image.open(path)
    if img.mode == 'RGBA':
        img = img.convert('RGB')
    elif img.mode == 'L':
        # Convert grayscale to RGB by stacking
        arr = np.array(img)
        img = Image.fromarray(np.stack([arr] * 3, axis=-1))
    return np.array(img)


def resize_to_match(img1, img2):
    """Resize both images to the smaller common size."""
    h1, w1 = img1.shape[:2]
    h2, w2 = img2.shape[:2]
    target_h, target_w = min(h1, h2), min(w1, w2)

    if (h1, w1) != (target_h, target_w):
        img1 = np.array(Image.fromarray(img1).resize((target_w, target_h), Image.LANCZOS))
    if (h2, w2) != (target_h, target_w):
        img2 = np.array(Image.fromarray(img2).resize((target_w, target_h), Image.LANCZOS))

    return img1, img2


def calculate_ssim(img1, img2):
    """Calculate SSIM between two images."""
    # Convert to grayscale for SSIM
    if img1.ndim == 3:
        gray1 = np.mean(img1, axis=2).astype(np.uint8)
        gray2 = np.mean(img2, axis=2).astype(np.uint8)
    else:
        gray1, gray2 = img1, img2

    score = ssim(gray1, gray2)
    return round(float(score), 4)


def calculate_pixel_diff(img1, img2):
    """Calculate percentage of pixels that changed significantly."""
    diff = np.abs(img1.astype(np.float32) - img2.astype(np.float32))
    # A pixel is "changed" if any channel differs by more than 30
    if diff.ndim == 3:
        changed = np.any(diff > 30, axis=2)
    else:
        changed = diff > 30
    pct = 100.0 * np.sum(changed) / changed.size
    return round(pct, 2)


def calculate_brightness_change(img1, img2):
    """Calculate brightness change percentage between images."""
    bright1 = np.mean(img1)
    bright2 = np.mean(img2)
    if bright1 == 0:
        return 0.0
    change = abs(bright2 - bright1) / bright1 * 100
    return round(change, 2)


def classify_change(img1, img2, ssim_score, pixel_diff_pct, brightness_change):
    """Classify the type of change detected.

    Returns list of change types detected.
    """
    changes = []

    # Cloud interference: widespread brightness change with low structural change
    if brightness_change > BRIGHTNESS_CHANGE_THRESHOLD and ssim_score > 0.85:
        changes.append("cloud_interference")

    # Construction: dark-to-light transitions in specific areas
    if img1.ndim == 3:
        gray1 = np.mean(img1, axis=2)
        gray2 = np.mean(img2, axis=2)
    else:
        gray1, gray2 = img1.astype(float), img2.astype(float)

    # Find regions where pixels went from dark to light (construction indicator)
    dark_to_light = np.sum((gray1 < 80) & (gray2 > 150))
    total_dark = np.sum(gray1 < 80)
    if total_dark > 0:
        construction_ratio = dark_to_light / total_dark
        if construction_ratio > 0.1 and pixel_diff_pct > PIXEL_DIFF_THRESHOLD:
            changes.append("new_construction")

    # Vessel detection: small bright spots appearing
    # Look for new small bright regions (3x3 to 15x15 patches)
    bright_mask1 = gray1 > 200
    bright_mask2 = gray2 > 200
    new_bright = bright_mask2 & ~bright_mask1
    new_bright_count = np.sum(new_bright)

    # Count connected bright regions (approximate via count of bright pixels)
    if 5 < new_bright_count < 500:  # Small number of new bright pixels = vessel
        # Check if they're in water areas (blue/dark in satellite imagery)
        if img1.ndim == 3:
            # Water is typically dark blue/green
            water_mask = (img2[:,:,2] > img2[:,:,0]) & (np.mean(img2, axis=2) < 100)
            vessel_in_water = np.sum(new_bright & water_mask)
            if vessel_in_water > VESSEL_SPOT_THRESHOLD:
                changes.append("new_vessel")

    # Large structural change (general)
    if pixel_diff_pct > 10 and ssim_score < 0.85:
        changes.append("major_change")
    elif pixel_diff_pct > PIXEL_DIFF_THRESHOLD and ssim_score < SSIM_CHANGE_THRESHOLD:
        changes.append("significant_change")

    return changes


def compare_images(path1, path2):
    """Full comparison of two satellite images.

    Returns dict with all metrics and classification.
    """
    if not os.path.isfile(path1):
        return {"error": f"Image not found: {path1}", "changed": None}
    if not os.path.isfile(path2):
        return {"error": f"Image not found: {path2}", "changed": None}

    try:
        img1 = load_image(path1)
        img2 = load_image(path2)
        img1, img2 = resize_to_match(img1, img2)

        ssim_score = calculate_ssim(img1, img2)
        pixel_diff_pct = calculate_pixel_diff(img1, img2)
        brightness_change = calculate_brightness_change(img1, img2)

        # Determine if changed
        changed = (
            ssim_score < SSIM_CHANGE_THRESHOLD or
            pixel_diff_pct > PIXEL_DIFF_THRESHOLD
        )

        # Confidence based on agreement of metrics
        confidence = 0.5
        if changed:
            if ssim_score < 0.85 and pixel_diff_pct > 5:
                confidence = 0.95
            elif ssim_score < 0.90 and pixel_diff_pct > 3:
                confidence = 0.85
            elif ssim_score < SSIM_CHANGE_THRESHOLD:
                confidence = 0.70
        else:
            if ssim_score > 0.98 and pixel_diff_pct < 1:
                confidence = 0.95
            elif ssim_score > 0.95:
                confidence = 0.85

        # Classify change types
        change_types = classify_change(img1, img2, ssim_score, pixel_diff_pct, brightness_change)

        # Cloud detection as reason for false positive
        is_cloud = "cloud_interference" in change_types

        return {
            "ssim_score": ssim_score,
            "pixel_diff_pct": pixel_diff_pct,
            "brightness_change": brightness_change,
            "changed": changed and not is_cloud,
            "changed_raw": changed,
            "confidence": round(confidence, 2),
            "change_types": change_types,
            "cloud_interference": is_cloud,
            "image1": os.path.basename(path1),
            "image2": os.path.basename(path2),
        }
    except Exception as e:
        return {"error": str(e), "changed": None}


def find_previous_image(name, current_date):
    """Find the most recent previous image for a feature."""
    prefix = f"{name}_"
    suffix = ".png"
    files = []
    for f in os.listdir(IMAGERY_DIR):
        if f.startswith(prefix) and f.endswith(suffix) and "_latest" not in f:
            date_part = f[len(prefix):-len(suffix)]
            if date_part < current_date:
                files.append((date_part, os.path.join(IMAGERY_DIR, f)))

    if not files:
        return None

    files.sort(reverse=True)
    return files[0][1]


def parse_image_filename(filename):
    """Extract feature name and date from filename like 'woody_island_2026-03-15.png'."""
    match = re.match(r'^(.+)_(\d{4}-\d{2}-\d{2})\.png$', filename)
    if match:
        return match.group(1), match.group(2)
    return None, None


def run_batch(feature_filter=None):
    """Process all features in imagery_history, comparing consecutive images."""
    if not os.path.isdir(IMAGERY_DIR):
        print(f"Imagery directory not found: {IMAGERY_DIR}")
        return []

    # Group images by feature
    features = {}
    for f in sorted(os.listdir(IMAGERY_DIR)):
        if f.endswith('_latest.png') or not f.endswith('.png'):
            continue
        name, date = parse_image_filename(f)
        if name:
            if feature_filter and name != feature_filter:
                continue
            features.setdefault(name, []).append((date, os.path.join(IMAGERY_DIR, f)))

    results = []
    for name in sorted(features):
        images = sorted(features[name])
        if len(images) < 2:
            continue

        # Compare latest with previous
        latest_date, latest_path = images[-1]
        prev_date, prev_path = images[-2]

        result = compare_images(prev_path, latest_path)
        result["feature"] = name
        result["date_current"] = latest_date
        result["date_previous"] = prev_date
        result["timestamp"] = datetime.now(timezone.utc).isoformat()

        status = "CHANGED" if result.get("changed") else "ok"
        if result.get("cloud_interference"):
            status = "CLOUD"
        types = ", ".join(result.get("change_types", []))

        print(f"  {name}: {status} (SSIM={result.get('ssim_score', '?')}, "
              f"diff={result.get('pixel_diff_pct', '?')}%, types=[{types}])")

        results.append(result)

    return results


def append_to_changelog(results):
    """Append batch results to imagery_changes.jsonl."""
    with open(CHANGELOG_FILE, "a") as f:
        for r in results:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def run_changelog():
    """Detect and classify change types from the latest imagery pairs."""
    results = run_batch()
    changed = [r for r in results if r.get("changed") or r.get("change_types")]

    if not changed:
        print("\nNo significant changes detected.")
        return

    print(f"\n{'='*60}")
    print(f"Change Log: {len(changed)} features with activity")
    print(f"{'='*60}\n")

    for r in changed:
        types = r.get("change_types", [])
        print(f"📍 {r['feature']} ({r['date_previous']} → {r['date_current']})")
        print(f"   SSIM: {r['ssim_score']} | Pixel diff: {r['pixel_diff_pct']}% | "
              f"Brightness Δ: {r['brightness_change']}%")
        if "new_construction" in types:
            print(f"   🏗️  New construction detected")
        if "new_vessel" in types:
            print(f"   🚢 New vessel/objects detected")
        if "cloud_interference" in types:
            print(f"   ☁️  Cloud interference (may be false positive)")
        if "major_change" in types:
            print(f"   ⚠️  Major structural change")
        if "significant_change" in types:
            print(f"   📐 Significant change")
        print()

    append_to_changelog(changed)


# ── CLI ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="SCS SSIM Change Detector")
    parser.add_argument("image1", nargs="?", help="First image path")
    parser.add_argument("image2", nargs="?", help="Second image path")
    parser.add_argument("--batch", action="store_true", help="Process all features")
    parser.add_argument("--feature", help="Filter to single feature in batch mode")
    parser.add_argument("--changelog", action="store_true",
                        help="Run changelog classification")
    args = parser.parse_args()

    if args.batch or args.changelog:
        if args.changelog:
            run_changelog()
        else:
            results = run_batch(args.feature)
            append_to_changelog(results)
            changed = sum(1 for r in results if r.get("changed"))
            print(f"\nProcessed {len(results)} features, {changed} changed.")
    elif args.image1 and args.image2:
        result = compare_images(args.image1, args.image2)
        print(json.dumps(result, indent=2))
    else:
        parser.print_help()
        sys.exit(1)
