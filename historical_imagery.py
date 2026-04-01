#!/usr/bin/env python3
"""
SCS Historical Imagery Collector
Fetches NASA Worldview satellite imagery for all 79 SCS features
from 2026-01-01 to 2026-04-01, with change detection.

Usage:
    python3 historical_imagery.py                    # Full run
    python3 historical_imagery.py --resume           # Skip already-fetched dates
    python3 historical_imagery.py --feature woody_island  # Single feature only
    python3 historical_imagery.py --priority-only    # Airport/helipad features first
    python3 historical_imagery.py --status           # Show progress summary
"""

import argparse
import hashlib
import json
import os
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
FEATURES_FILE = os.path.join(SCRIPT_DIR, "scs_features.json")
IMAGERY_DIR = os.path.join(SCRIPT_DIR, "imagery_history")
LOG_FILE = os.path.join(SCRIPT_DIR, "historical_imagery_log.jsonl")
PROGRESS_FILE = os.path.join(SCRIPT_DIR, "historical_progress.json")
os.makedirs(IMAGERY_DIR, exist_ok=True)

# Config
START_DATE = "2026-01-01"
END_DATE = "2026-04-01"
RATE_LIMIT = 1.5          # seconds between requests
MAX_RETRIES = 3
RETRY_BACKOFF = 5.0       # seconds, doubled each retry
MIN_IMAGE_SIZE = 8000      # bytes — filter blank/error images
BBOX_HALF = 0.15
IMG_WIDTH = 512
IMG_HEIGHT = 512


def load_features():
    with open(FEATURES_FILE) as f:
        return json.load(f)


def get_all_features(db, feature_filter=None):
    """Extract all features as a flat list, prioritized by strategic importance."""
    features = []
    for group_key, group in db.get("island_groups", {}).items():
        for feat_key, feat in group.get("features", {}).items():
            if feature_filter and feat_key != feature_filter:
                continue
            feat_copy = dict(feat)
            feat_copy["_key"] = feat_key
            feat_copy["_group"] = group_key
            features.append((feat_key, feat_copy))

    # Sort: airport features first, then helipad, then rest
    def priority(feat):
        _, f = feat
        if f.get("airport") and f["airport"] is not None:
            return 0
        if f.get("helipad"):
            return 1
        if f.get("radar") or f.get("sam"):
            return 1
        return 2

    features.sort(key=priority)
    return features


def date_range(start_str, end_str):
    """Generate dates from start (inclusive) to end (exclusive)."""
    start = datetime.strptime(start_str, "%Y-%m-%d")
    end = datetime.strptime(end_str, "%Y-%m-%d")
    dates = []
    while start < end:
        dates.append(start.strftime("%Y-%m-%d"))
        start += timedelta(days=1)
    return dates


def fetch_worldview_image(feat_key, lat, lon, date_str):
    """Fetch NASA Worldview snapshot. Returns (filepath, size) or (None, 0)."""
    url = (
        f"https://wvs.earthdata.nasa.gov/api/v1/snapshot?"
        f"REQUEST=GetSnapshot"
        f"&TIME={date_str}"
        f"&BBOX={lat - BBOX_HALF},{lon - BBOX_HALF},{lat + BBOX_HALF},{lon + BBOX_HALF}"
        f"&CRS=EPSG:4326"
        f"&LAYERS=MODIS_Terra_CorrectedReflectance_TrueColor"
        f"&WIDTH={IMG_WIDTH}&HEIGHT={IMG_HEIGHT}"
        f"&FORMAT=image/png"
    )

    outfile = os.path.join(IMAGERY_DIR, f"{feat_key}_{date_str}.png")

    if os.path.isfile(outfile) and os.path.getsize(outfile) >= MIN_IMAGE_SIZE:
        return outfile, os.path.getsize(outfile)

    for attempt in range(MAX_RETRIES):
        try:
            urllib.request.urlretrieve(url, outfile)
            size = os.path.getsize(outfile) if os.path.isfile(outfile) else 0
            if size >= MIN_IMAGE_SIZE:
                return outfile, size
            if os.path.isfile(outfile):
                os.remove(outfile)
            return None, 0
        except urllib.error.HTTPError as e:
            if e.code == 429:
                wait = RETRY_BACKOFF * (2 ** attempt)
                print(f"    ⏳ Rate limited, waiting {wait:.0f}s...")
                time.sleep(wait)
            elif e.code in (500, 502, 503):
                time.sleep(RETRY_BACKOFF * (2 ** attempt))
            else:
                return None, 0
        except Exception:
            time.sleep(RETRY_BACKOFF * (2 ** attempt))

    return None, 0


def file_hash(filepath):
    h = hashlib.md5()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def detect_change(current_path, previous_path):
    """Compare two images. Returns change dict."""
    if not previous_path or not os.path.isfile(previous_path):
        return {"changed": None, "reason": "no_previous"}

    curr_hash = file_hash(current_path)
    prev_hash = file_hash(previous_path)
    curr_size = os.path.getsize(current_path)
    prev_size = os.path.getsize(previous_path)
    size_diff = abs(curr_size - prev_size)
    size_ratio = size_diff / max(prev_size, 1)

    return {
        "changed": curr_hash != prev_hash,
        "significant_change": size_ratio > 0.05,
        "size_diff_bytes": size_diff,
        "size_change_ratio": round(size_ratio, 4),
        "previous_file": os.path.basename(previous_path),
    }


def find_previous_image(feat_key, current_date):
    """Find most recent previous image for a feature."""
    prefix = f"{feat_key}_"
    best_date = None
    best_path = None
    for f in os.listdir(IMAGERY_DIR):
        if f.startswith(prefix) and f.endswith(".png"):
            date_part = f[len(prefix):-4]
            if date_part < current_date and (best_date is None or date_part > best_date):
                best_date = date_part
                best_path = os.path.join(IMAGERY_DIR, f)
    return best_path


def load_progress():
    """Load progress: set of (feature_key, date_str) already done."""
    if os.path.isfile(PROGRESS_FILE):
        with open(PROGRESS_FILE) as f:
            data = json.load(f)
            return set(tuple(x) for x in data.get("completed", []))
    return set()


def save_progress(completed):
    """Save progress to disk."""
    with open(PROGRESS_FILE, "w") as f:
        json.dump({
            "completed": list(completed),
            "count": len(completed),
            "updated": datetime.now(timezone.utc).isoformat(),
        }, f)


def append_log(result):
    with open(LOG_FILE, "a") as f:
        f.write(json.dumps(result, ensure_ascii=False) + "\n")


def show_status():
    """Show collection progress."""
    if not os.path.isfile(PROGRESS_FILE):
        print("No progress file found. Run the collector first.")
        return

    with open(PROGRESS_FILE) as f:
        data = json.load(f)

    db = load_features()
    all_features = get_all_features(db)
    dates = date_range(START_DATE, END_DATE)
    total = len(all_features) * len(dates)
    done = data.get("count", 0)

    print(f"\nHistorical Imagery Collection Status")
    print(f"{'=' * 50}")
    print(f"Date range:    {START_DATE} → {END_DATE} ({len(dates)} days)")
    print(f"Features:      {len(all_features)}")
    print(f"Total targets: {total}")
    print(f"Completed:     {done} ({done / total * 100:.1f}%)")
    print(f"Remaining:     {total - done}")
    print(f"Last updated:  {data.get('updated', '?')}")

    # Per-feature breakdown
    completed_set = set(tuple(x) for x in data.get("completed", []))
    print(f"\nPer-feature progress:")
    for feat_key, feat in all_features:
        feat_done = sum(1 for f, d in completed_set if f == feat_key)
        pct = feat_done / len(dates) * 100
        marker = "✈" if feat.get("airport") else ("🚁" if feat.get("helipad") else "  ")
        print(f"  {marker} {feat_key:<35} {feat_done:>3}/{len(dates)} ({pct:.0f}%)")


def main():
    parser = argparse.ArgumentParser(description="SCS Historical Imagery Collector")
    parser.add_argument("--resume", action="store_true", help="Skip already-fetched dates")
    parser.add_argument("--feature", help="Collect for single feature only")
    parser.add_argument("--priority-only", action="store_true", help="Only airport/helipad features")
    parser.add_argument("--status", action="store_true", help="Show progress summary")
    parser.add_argument("--rate-limit", type=float, default=RATE_LIMIT, help="Seconds between requests")
    args = parser.parse_args()

    if args.status:
        show_status()
        sys.exit(0)

    rate_limit = args.rate_limit

    db = load_features()
    all_features = get_all_features(db, args.feature)

    if args.priority_only:
        all_features = [
            (k, f) for k, f in all_features
            if f.get("airport") or f.get("helipad")
        ]

    dates = date_range(START_DATE, END_DATE)
    completed = load_progress() if args.resume else set()

    total_targets = len(all_features) * len(dates)
    already_done = len(completed)
    to_do = total_targets - already_done

    print(f"SCS Historical Imagery Collector")
    print(f"{'=' * 60}")
    print(f"Date range:   {START_DATE} → {END_DATE} ({len(dates)} days)")
    print(f"Features:     {len(all_features)}")
    print(f"Total fetches: {total_targets}")
    if args.resume:
        print(f"Resuming:     {already_done} already done, {to_do} remaining")
    print(f"Rate limit:   {rate_limit}s between requests")
    print(f"Est. time:    ~{to_do * rate_limit / 3600:.1f} hours (with retries)")
    print(f"Log:          {LOG_FILE}")
    print(f"{'=' * 60}\n")

    stats = {"ok": 0, "no_imagery": 0, "skipped": 0, "changed": 0, "errors": 0}
    batch_count = 0

    for feat_idx, (feat_key, feat) in enumerate(all_features):
        name = feat.get("name", feat_key)
        lat, lon = feat["lat"], feat["lon"]
        icons = ""
        if feat.get("airport"):
            icons += "✈"
        if feat.get("helipad"):
            icons += "🚁"
        if feat.get("radar"):
            icons += "📡"

        print(f"[{feat_idx + 1}/{len(all_features)}] {icons} {name}")

        for date_idx, date_str in enumerate(dates):
            # Check resume
            if (feat_key, date_str) in completed:
                stats["skipped"] += 1
                continue

            # Fetch
            outfile, size = fetch_worldview_image(feat_key, lat, lon, date_str)

            if outfile:
                # Change detection vs previous day
                prev = find_previous_image(feat_key, date_str)
                change = detect_change(outfile, prev)

                result = {
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "feature_key": feat_key,
                    "feature_name": name,
                    "group": feat.get("_group", "unknown"),
                    "country": feat.get("country", "unknown"),
                    "lat": lat,
                    "lon": lon,
                    "date": date_str,
                    "has_airport": bool(feat.get("airport")),
                    "has_helipad": feat.get("helipad", False),
                    "image_size": size,
                    "image_file": os.path.basename(outfile),
                    "status": "ok",
                    "change": change,
                }

                if change.get("changed"):
                    stats["changed"] += 1

                stats["ok"] += 1
            else:
                result = {
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "feature_key": feat_key,
                    "feature_name": name,
                    "group": feat.get("_group", "unknown"),
                    "country": feat.get("country", "unknown"),
                    "lat": lat,
                    "lon": lon,
                    "date": date_str,
                    "status": "no_imagery",
                    "change": {"changed": None, "reason": "no_imagery"},
                }
                stats["no_imagery"] += 1

            append_log(result)
            completed.add((feat_key, date_str))
            batch_count += 1

            # Save progress every 20 fetches
            if batch_count % 20 == 0:
                save_progress(completed)
                done_count = stats["ok"] + stats["no_imagery"]
                print(f"  Progress: {done_count}/{to_do} fetched | "
                      f"ok={stats['ok']} no_img={stats['no_imagery']} "
                      f"changed={stats['changed']}")

            time.sleep(rate_limit)

        # Save progress after each feature
        save_progress(completed)

    # Final save and summary
    save_progress(completed)

    print(f"\n{'=' * 60}")
    print(f"Historical Collection Complete")
    print(f"  Images captured:  {stats['ok']}")
    print(f"  No imagery:       {stats['no_imagery']}")
    print(f"  Skipped (resume): {stats['skipped']}")
    print(f"  Changes detected: {stats['changed']}")
    print(f"  Errors:           {stats['errors']}")
    print(f"  Log: {LOG_FILE}")
    print(f"  Progress: {PROGRESS_FILE}")


if __name__ == "__main__":
    main()
