#!/usr/bin/env python3
"""
Sentinel-2 Correlation with NISAR Changes

Cross-references NISAR GCOV change detections with Sentinel-2 optical imagery
to validate/confirm SAR-detected changes with optical evidence.

Usage:
    python3 s2_correlation.py --all --window-days 7
    python3 s2_correlation.py --feature fiery_cross_reef --window-days 14
    python3 s2_correlation.py --changelog
"""

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
from PIL import Image

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(SCRIPT_DIR)
IMAGERY_DIR = os.path.join(BASE_DIR, "imagery_history")
DERIVED_DIR = os.path.join(BASE_DIR, "derived")
NISAR_CHANGES = os.path.join(BASE_DIR, "nisar_changes.jsonl")
CORRELATION_LOG = os.path.join(BASE_DIR, "s2_correlation.jsonl")

os.makedirs(IMAGERY_DIR, exist_ok=True)
os.makedirs(DERIVED_DIR, exist_ok=True)


def load_changes():
    """Load NISAR changes from JSONL."""
    changes = []
    if os.path.exists(NISAR_CHANGES):
        with open(NISAR_CHANGES) as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        changes.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
    return changes


def find_s2_images(feature_key, date_str, window_days=7):
    """Find Sentinel-2 images for a feature within ±window_days of date."""
    target_date = datetime.strptime(date_str, "%Y-%m-%d").date()
    start_date = target_date - timedelta(days=window_days)
    end_date = target_date + timedelta(days=window_days)

    s2_files = []
    prefix = f"{feature_key}_sentinel2_"
    suffix = ".png"

    for f in os.listdir(IMAGERY_DIR):
        if f.startswith(prefix) and f.endswith(suffix):
            date_part = f[len(prefix):-len(suffix)]
            try:
                img_date = datetime.strptime(date_part, "%Y-%m-%d").date()
                if start_date <= img_date <= end_date:
                    s2_files.append((img_date, os.path.join(IMAGERY_DIR, f)))
            except ValueError:
                continue

    s2_files.sort()
    return s2_files


def compare_s2_images(path1, path2):
    """Basic visual comparison of two Sentinel-2 images."""
    try:
        img1 = Image.open(path1).convert("RGB")
        img2 = Image.open(path2).convert("RGB")

        # Resize to same size if needed
        if img1.size != img2.size:
            img2 = img2.resize(img1.size, Image.LANCZOS)

        arr1 = np.array(img1, dtype=np.float32) / 255.0  # Normalize to [0, 1]
        arr2 = np.array(img2, dtype=np.float32) / 255.0

        # Compute difference
        diff = np.abs(arr1 - arr2)
        mean_diff = np.mean(diff)
        max_diff = np.max(diff)

        # Compute structural similarity using proper formula for RGB
        # Use skimage's structural_similarity if available, else proper implementation
        try:
            from skimage.metrics import structural_similarity as ssim
            ssim_score = ssim(arr1, arr2, channel_axis=2, data_range=1.0)
        except ImportError:
            # Proper SSIM implementation for RGB
            ssim_score = compute_ssim_rgb(arr1, arr2)

        return {
            "mean_pixel_diff": round(float(mean_diff * 255), 2),  # Back to 0-255 scale for interpretation
            "max_pixel_diff": round(float(max_diff * 255), 2),
            "ssim_score": round(float(ssim_score), 4),
            "changed": mean_diff > 0.02,  # Threshold ~2% pixel difference
        }
    except Exception as e:
        return {"error": str(e), "changed": None}


def compute_ssim_rgb(img1, img2):
    """Compute SSIM for RGB images (proper implementation)."""
    # SSIM parameters for 0-1 range
    c1 = (0.01 * 1.0) ** 2
    c2 = (0.03 * 1.0) ** 2

    # Compute per-channel SSIM and average
    ssim_channels = []
    for c in range(3):
        x = img1[:, :, c]
        y = img2[:, :, c]
        
        mu_x = np.mean(x)
        mu_y = np.mean(y)
        sigma_x = np.var(x)
        sigma_y = np.var(y)
        sigma_xy = np.mean((x - mu_x) * (y - mu_y))
        
        numerator = (2 * mu_x * mu_y + c1) * (2 * sigma_xy + c2)
        denominator = (mu_x**2 + mu_y**2 + c1) * (sigma_x + sigma_y + c2)
        
        if denominator != 0:
            ssim_channels.append(numerator / denominator)
        else:
            ssim_channels.append(0.0)
    
    return np.mean(ssim_channels)


def correlate_change(change, window_days=7):
    """Correlate a NISAR change with Sentinel-2 imagery."""
    feature = change.get("feature")
    date_current = change.get("date_current")
    date_previous = change.get("date_previous")

    if not feature or not date_current or not date_previous:
        return None

    # Find S2 images around both dates
    s2_current = find_s2_images(feature, date_current, window_days)
    s2_previous = find_s2_images(feature, date_previous, window_days)

    if not s2_current or not s2_previous:
        return {
            "feature": feature,
            "nisar_change": change,
            "s2_correlation": "insufficient_data",
            "s2_current_count": len(s2_current),
            "s2_previous_count": len(s2_previous),
        }

    # Find best pair (closest to NISAR dates)
    # For simplicity, use the closest S2 to each NISAR date
    target_current = datetime.strptime(date_current, "%Y-%m-%d").date()
    target_previous = datetime.strptime(date_previous, "%Y-%m-%d").date()

    best_current = min(s2_current, key=lambda x: abs((x[0] - target_current).days))
    best_previous = min(s2_previous, key=lambda x: abs((x[0] - target_previous).days))

    days_diff_current = abs((best_current[0] - target_current).days)
    days_diff_previous = abs((best_previous[0] - target_previous).days)

    # Compare the two S2 images
    comparison = compare_s2_images(best_previous[1], best_current[1])

    return {
        "feature": feature,
        "nisar_change": {
            "date_previous": date_previous,
            "date_current": date_current,
            "classification": change.get("change_types"),
            "confidence": change.get("confidence"),
            "polarization": change.get("polarization"),
        },
        "s2_correlation": {
            "s2_previous_date": best_previous[0].isoformat(),
            "s2_current_date": best_current[0].isoformat(),
            "days_from_nisar_previous": days_diff_previous,
            "days_from_nisar_current": days_diff_current,
            "s2_comparison": comparison,
        },
        "correlated": comparison.get("changed", False) if "changed" in comparison else None,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def _make_json_serializable(obj):
    """Convert numpy types and other non-serializable objects to JSON-serializable types."""
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, (np.integer, np.floating)):
        return obj.item()
    if isinstance(obj, np.bool_):
        return bool(obj)
    if isinstance(obj, dict):
        return {k: _make_json_serializable(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_make_json_serializable(v) for v in obj]
    return obj


def log_correlation(result):
    """Append correlation result to JSONL log."""
    serializable = _make_json_serializable(result)
    with open(CORRELATION_LOG, "a") as f:
        f.write(json.dumps(serializable, ensure_ascii=False) + "\n")


def run_correlation(changes, window_days=7):
    """Run correlation for all changes."""
    results = []
    for change in changes:
        print(f"Correlating {change.get('feature')} ({change.get('date_current')})...")
        result = correlate_change(change, window_days)
        if result:
            log_correlation(result)
            results.append(result)

            if "s2_correlation" in result and isinstance(result["s2_correlation"], dict):
                corr = result["s2_correlation"]
                if "s2_comparison" in corr:
                    comp = corr["s2_comparison"]
                    if comp.get("changed"):
                        print(f"  ✅ S2 confirms change (SSIM: {comp.get('ssim_score')}, Δ: {comp.get('mean_pixel_diff')})")
                    else:
                        print(f"  ⚠️ S2 does not show clear change (SSIM: {comp.get('ssim_score')})")
                else:
                    print(f"  ⚠️ {corr}")
            else:
                print(f"  ❌ No S2 data available")

    return results


def generate_report(results):
    """Generate summary report of correlations."""
    total = len(results)
    confirmed = 0
    insufficient = 0
    no_change = 0

    for r in results:
        s2_corr = r.get("s2_correlation")
        if s2_corr == "insufficient_data":
            insufficient += 1
        elif isinstance(s2_corr, dict):
            if s2_corr.get("s2_comparison", {}).get("changed"):
                confirmed += 1
            else:
                no_change += 1
        else:
            insufficient += 1

    print(f"\n{'='*60}")
    print(f"S2 Correlation Report")
    print(f"{'='*60}")
    print(f"Total NISAR changes: {total}")
    print(f"S2 confirms change: {confirmed}")
    print(f"S2 shows no change: {no_change}")
    print(f"Insufficient S2 data: {insufficient}")
    print(f"Confirmation rate: {confirmed/total*100:.1f}%" if total > 0 else "N/A")

    # Save report
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "total_changes": total,
            "confirmed": confirmed,
            "no_change": no_change,
            "insufficient_data": insufficient,
            "confirmation_rate": confirmed/total if total > 0 else 0,
        },
        "details": results,
    }
    # Save report
    report_path = os.path.join(DERIVED_DIR, "s2_correlation_report.json")
    report = _make_json_serializable(report)
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    print(f"\nReport saved to {report_path}")


def main():
    parser = argparse.ArgumentParser(description="Sentinel-2 Correlation with NISAR Changes")
    parser.add_argument("--all", action="store_true", help="Correlate all NISAR changes")
    parser.add_argument("--feature", help="Correlate changes for specific feature")
    parser.add_argument("--window-days", type=int, default=7, help="S2 search window (±days)")
    parser.add_argument("--changelog", action="store_true", help="Run correlation and generate report")
    args = parser.parse_args()

    if not args.changelog:
        parser.print_help()
        sys.exit(1)

    changes = load_changes()
    if not changes:
        print("No NISAR changes found. Run nisar_processor.py first.")
        sys.exit(1)

    if args.feature:
        changes = [c for c in changes if c.get("feature") == args.feature]
        if not changes:
            print(f"No changes found for feature {args.feature}")
            sys.exit(1)

    # Deduplicate changes (same feature/dates may appear multiple times from different runs)
    seen = set()
    unique_changes = []
    for c in changes:
        key = (c.get("feature"), c.get("date_previous"), c.get("date_current"), c.get("polarization"))
        if key not in seen:
            seen.add(key)
            unique_changes.append(c)
    changes = unique_changes

    print(f"Processing {len(changes)} unique NISAR changes...")
    results = run_correlation(changes, args.window_days)
    generate_report(results)


if __name__ == "__main__":
    main()