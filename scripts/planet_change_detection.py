#!/usr/bin/env python3
"""
Planet Labs Change Detection

Compares consecutive Planet PSScene images for the same feature to detect:
- New structures / construction
- Ship movements
- Land reclamation
- Other significant changes

Uses SSIM from scripts/change_detector.py for structural comparison.
Generates diff visualizations and logs to planet_changes.jsonl.

Usage:
    python3 planet_change_detection.py --feature fiery_cross_reef
    python3 planet_change_detection.py --all
    python3 planet_change_detection.py --image1 path/to/img1.png --image2 path/to/img2.png
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from glob import glob

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFont

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(SCRIPT_DIR)
IMAGERY_DIR = os.path.join(BASE_DIR, "imagery_history")
LOG_FILE = os.path.join(BASE_DIR, "planet_changes.jsonl")
OUTPUT_DIR = IMAGERY_DIR  # Diff visualizations saved alongside images

os.makedirs(OUTPUT_DIR, exist_ok=True)

# Import SSIM from existing change_detector
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)
from change_detector import (
    load_image,
    resize_to_match,
    calculate_ssim,
    calculate_pixel_diff,
    calculate_brightness_change,
    classify_change,
    SSIM_CHANGE_THRESHOLD,
    PIXEL_DIFF_THRESHOLD,
)


def find_planet_images(feature_key=None):
    """Find all Planet imagery files grouped by feature.

    Returns dict: {feature_key: [(date_str, filepath), ...]}
    """
    pattern = os.path.join(IMAGERY_DIR, "*_planet_*.png")
    files = sorted(glob(pattern))

    features = {}
    for fpath in files:
        fname = os.path.basename(fpath)
        # Parse: {key}_planet_{date}.png
        parts = fname.rsplit("_planet_", 1)
        if len(parts) != 2:
            continue
        fkey = parts[0]
        date_str = parts[1].replace(".png", "")

        if feature_key and fkey != feature_key:
            continue

        features.setdefault(fkey, []).append((date_str, fpath))

    # Sort each feature's images by date
    for fkey in features:
        features[fkey].sort()

    return features


def generate_diff_image(img1_path, img2_path, output_path, ssim_score, change_types):
    """Generate a diff visualization showing changes between two images.

    Creates a side-by-side: [Before | After | Diff Heatmap]
    """
    img1 = Image.open(img1_path).convert("RGB")
    img2 = Image.open(img2_path).convert("RGB")

    # Resize to match
    w = min(img1.width, img2.width)
    h = min(img1.height, img2.height)
    img1 = img1.resize((w, h), Image.LANCZOS)
    img2 = img2.resize((w, h), Image.LANCZOS)

    # Compute absolute difference
    diff = ImageChops.difference(img1, img2)
    diff_arr = np.array(diff, dtype=np.float64)

    # Amplify differences for visibility
    diff_amplified = np.clip(diff_arr * 3, 0, 255).astype(np.uint8)
    diff_img = Image.fromarray(diff_amplified)

    # Convert diff to heatmap (red = high change)
    gray_diff = np.mean(diff_amplified, axis=2)
    heatmap = np.zeros((h, w, 3), dtype=np.uint8)
    heatmap[:, :, 0] = np.clip(gray_diff * 2, 0, 255).astype(np.uint8)  # Red
    heatmap[:, :, 1] = np.clip(gray_diff * 0.5, 0, 255).astype(np.uint8)  # Green
    heatmap[:, :, 2] = np.clip(gray_diff * 0.3, 0, 255).astype(np.uint8)  # Blue
    heatmap_img = Image.fromarray(heatmap)

    # Create composite: Before | After | Heatmap
    padding = 4
    total_w = w * 3 + padding * 2
    total_h = h + 40  # Extra for labels
    composite = Image.new("RGB", (total_w, total_h), (30, 30, 30))
    composite.paste(img1, (0, 40))
    composite.paste(img2, (w + padding, 40))
    composite.paste(heatmap_img, (w * 2 + padding * 2, 40))

    # Add labels
    draw = ImageDraw.Draw(composite)
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 14)
    except (IOError, OSError):
        font = ImageFont.load_default()

    draw.text((10, 5), "BEFORE", fill=(200, 200, 200), font=font)
    draw.text((w + padding + 10, 5), "AFTER", fill=(200, 200, 200), font=font)
    draw.text((w * 2 + padding * 2 + 10, 5), "DIFF", fill=(200, 200, 200), font=font)

    # Change info at bottom of label area
    types_str = ", ".join(change_types) if change_types else "none"
    info = f"SSIM: {ssim_score:.4f} | Changes: {types_str}"
    draw.text((10, 22), info, fill=(255, 180, 100), font=font)

    composite.save(output_path, "PNG")
    return output_path


def compare_planet_images(img1_path, img2_path, generate_diff=True):
    """Compare two Planet images and return analysis results.

    Returns dict with SSIM, pixel diff, brightness change, change types, etc.
    """
    if not os.path.isfile(img1_path):
        return {"error": f"Image not found: {img1_path}", "changed": None}
    if not os.path.isfile(img2_path):
        return {"error": f"Image not found: {img2_path}", "changed": None}

    try:
        img1 = load_image(img1_path)
        img2 = load_image(img2_path)
        img1, img2 = resize_to_match(img1, img2)

        ssim_score = calculate_ssim(img1, img2)
        pixel_diff_pct = calculate_pixel_diff(img1, img2)
        brightness_change = calculate_brightness_change(img1, img2)

        # Determine if changed
        changed = (
            ssim_score < SSIM_CHANGE_THRESHOLD or
            pixel_diff_pct > PIXEL_DIFF_THRESHOLD
        )

        # Classify change types
        change_types = classify_change(img1, img2, ssim_score, pixel_diff_pct, brightness_change)

        # Cloud detection as reason for false positive
        is_cloud = "cloud_interference" in change_types
        actually_changed = changed and not is_cloud

        # Confidence
        confidence = 0.5
        if actually_changed:
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

        result = {
            "ssim_score": round(float(ssim_score), 4),
            "pixel_diff_pct": round(float(pixel_diff_pct), 2),
            "brightness_change": round(float(brightness_change), 2),
            "changed": actually_changed,
            "changed_raw": changed,
            "confidence": round(confidence, 2),
            "change_types": change_types,
            "cloud_interference": is_cloud,
            "image1": os.path.basename(img1_path),
            "image2": os.path.basename(img2_path),
        }

        # Generate diff visualization if changes detected
        if generate_diff and (actually_changed or change_types):
            basename1 = os.path.basename(img1_path).replace(".png", "")
            basename2 = os.path.basename(img2_path).replace(".png", "")
            diff_path = os.path.join(OUTPUT_DIR, f"diff_{basename1}_to_{basename2}.png")
            try:
                generate_diff_image(img1_path, img2_path, diff_path, ssim_score, change_types)
                result["diff_image"] = os.path.basename(diff_path)
            except Exception as e:
                result["diff_error"] = str(e)

        return result

    except Exception as e:
        return {"error": str(e), "changed": None}


def log_change(entry):
    """Append a change detection result to planet_changes.jsonl."""
    with open(LOG_FILE, "a") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def run_auto(feature_key=None):
    """Process all Planet images, comparing consecutive pairs.

    Returns list of result dicts.
    """
    features = find_planet_images(feature_key)

    if not features:
        print("No Planet imagery found in imagery_history/")
        print("Run planet_fetch.py first to download imagery.")
        return []

    results = []
    total_pairs = 0

    for fkey in sorted(features):
        images = features[fkey]
        if len(images) < 2:
            print(f"  {fkey}: only {len(images)} image(s), skipping")
            continue

        print(f"\n📍 {fkey}: {len(images)} images")

        for i in range(len(images) - 1):
            date1, path1 = images[i]
            date2, path2 = images[i + 1]
            total_pairs += 1

            result = compare_planet_images(path1, path2)
            result["feature"] = fkey
            result["date_previous"] = date1
            result["date_current"] = date2
            result["timestamp"] = datetime.now(timezone.utc).isoformat()

            status = "CHANGED" if result.get("changed") else "ok"
            if result.get("cloud_interference"):
                status = "CLOUD"
            types = ", ".join(result.get("change_types", []))

            print(f"  {date1} → {date2}: {status} "
                  f"(SSIM={result.get('ssim_score', '?')}, "
                  f"diff={result.get('pixel_diff_pct', '?')}%, "
                  f"types=[{types}])")

            if result.get("diff_image"):
                print(f"    🔍 Diff: {result['diff_image']}")

            log_change(result)
            results.append(result)

    return results


def print_summary(results):
    """Print a summary of change detection results."""
    if not results:
        return

    changed = [r for r in results if r.get("changed")]
    clouds = [r for r in results if r.get("cloud_interference")]

    print(f"\n{'='*60}")
    print(f"Planet Change Detection Summary")
    print(f"{'='*60}")
    print(f"Total comparisons: {len(results)}")
    print(f"Changes detected:  {len(changed)}")
    print(f"Cloud interference: {len(clouds)}")

    if changed:
        print(f"\n⚠️  Features with changes:")
        for r in changed:
            types = ", ".join(r.get("change_types", []))
            print(f"  • {r['feature']}: {r['date_previous']} → {r['date_current']} "
                  f"(SSIM={r['ssim_score']}, [{types}])")


# ── CLI ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Planet Labs Change Detection")
    parser.add_argument("--feature", help="Process specific feature")
    parser.add_argument("--all", action="store_true", help="Process all Planet imagery")
    parser.add_argument("--image1", help="First image for direct comparison")
    parser.add_argument("--image2", help="Second image for direct comparison")
    args = parser.parse_args()

    if args.image1 and args.image2:
        result = compare_planet_images(args.image1, args.image2)
        print(json.dumps(result, indent=2))
    elif args.feature or args.all:
        results = run_auto(args.feature)
        print_summary(results)
    else:
        parser.print_help()
        sys.exit(1)
