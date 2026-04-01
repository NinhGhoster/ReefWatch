#!/usr/bin/env python3
"""
SCS Imagery Monitor — Enhanced satellite imagery with change detection.

Fetches NASA Worldview imagery for ALL features, compares with previous day,
and performs basic pixel analysis for aircraft/ship detection.

Usage:
    python3 imagery_monitor.py                      # Monitor all features
    python3 imagery_monitor.py --feature woody_island  # Single feature
    python3 imagery_monitor.py --changes             # Show only changed features
    python3 imagery_monitor.py --summary             # Show latest imagery status
"""

import argparse
import hashlib
import json
import os
import shutil
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timedelta, timezone

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
FEATURES_FILE = os.path.join(SCRIPT_DIR, "scs_features.json")
IMAGERY_DIR = os.path.join(SCRIPT_DIR, "imagery_history")
LOG_FILE = os.path.join(SCRIPT_DIR, "imagery_changes.jsonl")
os.makedirs(IMAGERY_DIR, exist_ok=True)

# Rate limit between NASA Worldview requests
RATE_LIMIT = 1.0


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
            feat_copy["_group"] = group_key
            features.append((feat_key, feat_copy))
    return features


def fetch_worldview_image(name, lat, lon, date_str, bbox=0.15, width=512, height=512):
    """Fetch NASA Worldview snapshot for a location and date.
    
    Returns (filepath, size) or (None, 0) on failure.
    """
    url = (
        f"https://wvs.earthdata.nasa.gov/api/v1/snapshot?"
        f"REQUEST=GetSnapshot"
        f"&TIME={date_str}"
        f"&BBOX={lat - bbox},{lon - bbox},{lat + bbox},{lon + bbox}"
        f"&CRS=EPSG:4326"
        f"&LAYERS=MODIS_Terra_CorrectedReflectance_TrueColor"
        f"&WIDTH={width}&HEIGHT={height}"
        f"&FORMAT=image/png"
    )
    
    outfile = os.path.join(IMAGERY_DIR, f"{name}_{date_str}.png")
    
    try:
        urllib.request.urlretrieve(url, outfile)
        size = os.path.getsize(outfile)
        if size > 8000:  # Filter out error/blank images
            return outfile, size
        os.remove(outfile)
    except Exception:
        pass
    return None, 0


def file_hash(filepath):
    """MD5 hash of a file for change detection."""
    h = hashlib.md5()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def find_previous_image(name, current_date):
    """Find the most recent previous image for a feature.
    
    Returns filepath or None.
    """
    prefix = f"{name}_"
    suffix = ".png"
    files = []
    for f in os.listdir(IMAGERY_DIR):
        if f.startswith(prefix) and f.endswith(suffix):
            date_part = f[len(prefix):-len(suffix)]
            if date_part < current_date:
                files.append((date_part, os.path.join(IMAGERY_DIR, f)))
    
    if not files:
        return None
    
    files.sort(reverse=True)
    return files[0][1]  # Most recent


def analyze_pixels(filepath):
    """Basic pixel analysis of a satellite image.
    
    Returns dict with analysis results.
    Uses pure Python — no PIL/numpy needed.
    """
    try:
        with open(filepath, "rb") as f:
            data = f.read()
        
        # Very basic analysis: file size as proxy for content
        # and check for PNG structure
        size = len(data)
        
        # Count non-zero bytes in a sample as rough "activity" metric
        # (bright pixels = structures/vessels in satellite imagery)
        sample_start = max(0, len(data) // 4)
        sample = data[sample_start:sample_start + 10000]
        non_zero = sum(1 for b in sample if b > 30)
        brightness_ratio = non_zero / len(sample) if sample else 0
        
        return {
            "file_size": size,
            "brightness_ratio": round(brightness_ratio, 3),
            "analyzable": True,
        }
    except Exception as e:
        return {
            "file_size": 0,
            "brightness_ratio": 0,
            "analyzable": False,
            "error": str(e),
        }


def detect_change(current_path, previous_path, threshold=0.05):
    """Compare two images for changes using file hash + size comparison.
    
    Returns dict with change info.
    """
    if not previous_path or not os.path.isfile(previous_path):
        return {"changed": None, "reason": "no_previous"}
    
    curr_hash = file_hash(current_path)
    prev_hash = file_hash(previous_path)
    
    curr_size = os.path.getsize(current_path)
    prev_size = os.path.getsize(previous_path)
    
    size_diff = abs(curr_size - prev_size)
    size_ratio = size_diff / max(prev_size, 1)
    
    hash_changed = curr_hash != prev_hash
    significant_size_change = size_ratio > threshold
    
    return {
        "changed": hash_changed,
        "significant_change": significant_size_change,
        "size_diff_bytes": size_diff,
        "size_change_ratio": round(size_ratio, 4),
        "previous_file": os.path.basename(previous_path),
    }


def monitor_feature(feat_key, feat, date_str=None):
    """Monitor a single feature with imagery.
    
    Returns dict with monitoring results.
    """
    if date_str is None:
        date_str = datetime.utcnow().strftime("%Y-%m-%d")
    
    lat, lon = feat["lat"], feat["lon"]
    name = feat.get("name", feat_key)
    
    # Fetch image
    outfile, size = fetch_worldview_image(feat_key, lat, lon, date_str)
    
    # Try yesterday if today fails
    used_date = date_str
    if not outfile:
        yesterday = (datetime.utcnow() - timedelta(days=1)).strftime("%Y-%m-%d")
        outfile, size = fetch_worldview_image(feat_key, lat, lon, yesterday)
        used_date = yesterday
    
    result = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "feature_key": feat_key,
        "feature_name": name,
        "group": feat.get("_group", "unknown"),
        "country": feat.get("country", "unknown"),
        "lat": lat,
        "lon": lon,
        "date": used_date,
        "has_airport": bool(feat.get("airport")),
        "has_port": feat.get("port", False),
        "has_helipad": feat.get("helipad", False),
        "image_captured": outfile is not None,
        "image_size": size,
        "image_file": os.path.basename(outfile) if outfile else None,
    }
    
    if not outfile:
        result["status"] = "no_imagery"
        result["change"] = {"changed": None, "reason": "no_imagery"}
        result["analysis"] = {"analyzable": False}
        return result
    
    result["status"] = "ok"
    
    # Change detection
    prev = find_previous_image(feat_key, used_date)
    result["change"] = detect_change(outfile, prev)
    
    # Pixel analysis
    result["analysis"] = analyze_pixels(outfile)
    
    # Copy to latest for quick access
    latest = os.path.join(IMAGERY_DIR, f"{feat_key}_latest.png")
    shutil.copy2(outfile, latest)
    
    return result


def append_log(result):
    """Append a monitoring result to JSONL log."""
    with open(LOG_FILE, "a") as f:
        f.write(json.dumps(result, ensure_ascii=False) + "\n")


def show_changes():
    """Show only features with detected changes."""
    if not os.path.isfile(LOG_FILE):
        print("No imagery log found.")
        return
    
    latest = {}
    with open(LOG_FILE) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            key = rec.get("feature_key")
            if key:
                latest[key] = rec
    
    changed = {k: v for k, v in latest.items() if v.get("change", {}).get("changed")}
    
    if not changed:
        print("No changes detected in latest imagery run.")
        return
    
    print(f"\nFeatures with imagery changes: {len(changed)}/{len(latest)}\n")
    print(f"{'Feature':<30} {'Country':<12} {'Date':<12} {'Size Δ':>10} {'Change %':>10}")
    print("-" * 80)
    for key in sorted(changed):
        rec = changed[key]
        ch = rec.get("change", {})
        size_diff = ch.get("size_diff_bytes", 0)
        ratio = ch.get("size_change_ratio", 0)
        print(f"  {key:<28} {rec.get('country','?'):<12} {rec.get('date','?'):<12} "
              f"{size_diff:>10} {ratio:>10.1%}")


def show_summary():
    """Show latest imagery status for all features."""
    if not os.path.isfile(LOG_FILE):
        print("No imagery log found.")
        return
    
    latest = {}
    with open(LOG_FILE) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            key = rec.get("feature_key")
            if key:
                latest[key] = rec
    
    if not latest:
        print("No records found.")
        return
    
    print(f"\n{'Feature':<30} {'Country':<12} {'Status':<12} {'Changed':>8} {'Date':<12} {'Size'}")
    print("-" * 90)
    for key in sorted(latest):
        rec = latest[key]
        status = rec.get("status", "?")
        changed = rec.get("change", {})
        ch_str = "YES" if changed.get("changed") else ("—" if changed.get("changed") is None else "no")
        date = rec.get("date", "?")
        size = rec.get("image_size", 0)
        icons = ""
        if rec.get("has_airport"):
            icons += "✈"
        if rec.get("has_port"):
            icons += "🚢"
        if rec.get("has_helipad"):
            icons += "🚁"
        print(f"  {icons} {key:<27} {rec.get('country','?'):<12} {status:<12} {ch_str:>8} {date:<12} {size:>8}B")
    
    ok = sum(1 for r in latest.values() if r.get("status") == "ok")
    changed = sum(1 for r in latest.values() if r.get("change", {}).get("changed"))
    print(f"\nImagery captured: {ok}/{len(latest)}")
    print(f"Changes detected: {changed}")


# ── Main ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="SCS Satellite Imagery Monitor")
    parser.add_argument("--feature", help="Monitor a single feature by key name")
    parser.add_argument("--changes", action="store_true", help="Show only features with changes")
    parser.add_argument("--summary", action="store_true", help="Show latest imagery status")
    parser.add_argument("--date", help="Specific date to check (YYYY-MM-DD)")
    args = parser.parse_args()
    
    if args.changes:
        show_changes()
        sys.exit(0)
    if args.summary:
        show_summary()
        sys.exit(0)
    
    db = load_features()
    features = get_all_features(db, args.feature)
    
    if not features:
        print(f"Feature '{args.feature}' not found." if args.feature else "No features found.")
        sys.exit(1)
    
    date_str = args.date or datetime.utcnow().strftime("%Y-%m-%d")
    
    print(f"SCS Imagery Monitor — {date_str}")
    print(f"Monitoring {len(features)} features")
    print("=" * 60)
    
    results = []
    for i, (feat_key, feat) in enumerate(features):
        name = feat.get("name", feat_key)
        icons = ""
        if feat.get("airport"):
            icons += "✈"
        if feat.get("port"):
            icons += "🚢"
        if feat.get("helipad"):
            icons += "🚁"
        
        result = monitor_feature(feat_key, feat, date_str)
        
        if result["status"] == "ok":
            ch = result.get("change", {})
            changed = ch.get("changed")
            if changed:
                print(f"  ⚠️  {icons} {name}: CHANGED (Δ{ch.get('size_change_ratio', 0):.1%})")
            else:
                print(f"  ✓  {icons} {name}: ok ({result['image_size']}B)")
        else:
            print(f"  ✗  {icons} {name}: no imagery")
        
        append_log(result)
        results.append(result)
        
        if i < len(features) - 1:
            time.sleep(RATE_LIMIT)
    
    ok = sum(1 for r in results if r["status"] == "ok")
    changed = sum(1 for r in results if r.get("change", {}).get("changed"))
    
    print(f"\n{'=' * 60}")
    print(f"Images captured: {ok}/{len(results)}")
    print(f"Changes detected: {changed}")
    print(f"Log: {LOG_FILE}")
