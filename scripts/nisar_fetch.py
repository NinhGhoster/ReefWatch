#!/usr/bin/env python3
"""
NISAR L-band SAR Imagery Fetcher

Downloads NISAR GSLC (primary) and GCOV (secondary) products for SCS monitoring features
using earthaccess. Supports streaming downloads, resume, and per-feature orbit locking.

Usage:
    python3 nisar_fetch.py --feature fiery_cross_reef --days 14
    python3 nisar_fetch.py --all --days 30 --product gslc
    python3 nisar_fetch.py --feature woody_island --days 60 --resume --polarizations VV VH
    python3 nisar_fetch.py --config-check
"""

import argparse
import json
import os
import sys
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

import earthaccess

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(SCRIPT_DIR)
DATA_DIR = os.path.join(BASE_DIR, "data")
IMAGERY_DIR = os.path.join(BASE_DIR, "imagery_history")
FEATURES_FILE = os.path.join(DATA_DIR, "target_features.json")
CONFIG_FILE = os.path.join(DATA_DIR, "nisar_config.json")
LOG_FILE = os.path.join(BASE_DIR, "nisar_fetch_log.jsonl")

PROVISIONAL_GSLC = "NISAR_L2_GSLC_PROVISIONAL_V1"
PROVISIONAL_GCOV = "NISAR_L2_GCOV_PROVISIONAL_V1"

RATE_LIMIT = 2.0

os.makedirs(IMAGERY_DIR, exist_ok=True)


def load_config():
    """Load NISAR configuration."""
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE) as f:
            return json.load(f)
    return {}


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


def build_bbox(lat, lon, delta=0.05):
    """Build a bounding box around a point (±delta degrees)."""
    # earthaccess expects (lower_left_lon, lower_left_lat, upper_right_lon, upper_right_lat)
    return (
        round(lon - delta, 6),
        round(lat - delta, 6),
        round(lon + delta, 6),
        round(lat + delta, 6),
    )


def _get_umm(granule):
    """Extract UMM metadata from granule."""
    if hasattr(granule, 'umm'):
        return granule.umm
    # earthaccess returns dict-like objects with 'umm' key
    if isinstance(granule, dict):
        return granule.get('umm', {})
    # Try dict access
    return granule.get('umm', {}) if hasattr(granule, 'get') else {}


def _get_absolute_orbit(granule):
    """Extract absolute orbit number from granule."""
    umm = _get_umm(granule)
    orbit_domains = umm.get("OrbitCalculatedSpatialDomains", [])
    if orbit_domains:
        return orbit_domains[0].get("OrbitNumber")
    return None


def _get_relative_orbit(granule):
    """Compute relative orbit (1-175) from absolute orbit."""
    abs_orbit = _get_absolute_orbit(granule)
    if abs_orbit:
        return ((abs_orbit - 1) % 175) + 1
    return None


def _get_orbit_direction(granule):
    """Extract orbit direction (ASCENDING/DESCENDING) from granule."""
    umm = _get_umm(granule)
    attrs = umm.get("AdditionalAttributes", [])
    for attr in attrs:
        if attr.get("Name") == "ASCENDING_DESCENDING":
            vals = attr.get("Values", [])
            return vals[0] if vals else None
    return None


def _get_polarization(granule):
    """Extract polarization from granule."""
    umm = _get_umm(granule)
    attrs = umm.get("AdditionalAttributes", [])
    for attr in attrs:
        if attr.get("Name") == "FREQUENCY_A_POLARIZATION_CONCAT":
            vals = attr.get("Values", [])
            return vals[0] if vals else None
    return None


def _get_track_number(granule):
    """Extract track number from granule."""
    umm = _get_umm(granule)
    attrs = umm.get("AdditionalAttributes", [])
    for attr in attrs:
        if attr.get("Name") == "TRACK_NUMBER":
            vals = attr.get("Values", [])
            return vals[0] if vals else None
    return None


def _get_granule_id(granule):
    """Extract granule UR from granule."""
    umm = _get_umm(granule)
    return umm.get("GranuleUR", "unknown")


def _get_acquisition_time(granule):
    """Extract acquisition time from granule."""
    umm = _get_umm(granule)
    return umm.get("TemporalExtent", {}).get("RangeDateTime", {}).get("BeginningDateTime", "")


def get_preferred_orbit(feature_key, config):
    """Get the preferred relative orbit and direction for a feature."""
    feature_orbits = config.get("feature_orbits", {})
    return feature_orbits.get(feature_key, {})


def search_nisar(bbox, date_start, date_end, short_name, orbit_filter=None):
    """Search Earthdata for NISAR granules."""
    try:
        results = earthaccess.search_data(
            short_name=short_name,
            bounding_box=bbox,
            temporal=(date_start, date_end),
            cloud_hosted=True,
            count=200,
        )
    except Exception as e:
        print(f"  [ERROR] Search failed: {e}")
        return []

    if orbit_filter:
        filtered = []
        for r in results:
            rel_orbit = _get_relative_orbit(r)
            direction = _get_orbit_direction(r)
            if rel_orbit and orbit_filter.get("relative_orbit"):
                if str(rel_orbit) == str(orbit_filter["relative_orbit"]):
                    filtered.append(r)
            elif direction and orbit_filter.get("direction"):
                if direction.lower() == orbit_filter["direction"].lower():
                    filtered.append(r)
        return filtered

    return results


def pick_best_per_day(items, prefer_polarization="VV"):
    """Group items by date, pick best per day (lowest cloud not applicable for SAR)."""
    by_date = defaultdict(list)
    for item in items:
        dt = _get_acquisition_time(item)
        if dt:
            date_str = dt[:10]
            by_date[date_str].append(item)

    best = {}
    for date_str, day_items in by_date.items():
        day_items.sort(key=lambda x: (
            0 if prefer_polarization in str(_get_polarization(x)) else 1,
            _get_relative_orbit(x) or 9999
        ))
        best[date_str] = day_items[0]

    return best


def already_downloaded(feature_key, date_str, product_type):
    """Check if we already have this granule."""
    outfile = os.path.join(IMAGERY_DIR, f"{feature_key}_nisar_{product_type}_{date_str}.h5")
    return os.path.isfile(outfile) and os.path.getsize(outfile) > 1000000


def download_granule(granule, output_path, streaming=True):
    """Download a NISAR granule using earthaccess."""
    try:
        # Use earthaccess.download which handles both HTTPS and S3 with auth
        files = earthaccess.download([granule], local_path=os.path.dirname(output_path))
        if not files:
            print(f"    [ERROR] No files downloaded")
            return False

        # Find the .h5 file and rename to our output path
        downloaded = None
        for f in files:
            f_str = str(f)
            if f_str.endswith('.h5'):
                downloaded = f_str
                break
        
        if not downloaded:
            print(f"    [ERROR] No .h5 file found in download: {files}")
            return False

        if downloaded != output_path:
            os.rename(downloaded, output_path)

        size = os.path.getsize(output_path)
        print(f"    [OK] {output_path} ({size / 1024 / 1024:.1f} MB)")
        return True

    except Exception as e:
        print(f"    [ERROR] Download failed: {e}")
        if os.path.exists(output_path):
            os.remove(output_path)
        return False


def log_fetch(entry):
    """Append a fetch result to the JSONL log."""
    with open(LOG_FILE, "a") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def fetch_feature(feature, date_start, date_end, product_type, polarizations, resume, config):
    """Fetch NISAR imagery for a single feature by searching SCS region and clipping."""
    key = feature["key"]
    lat = feature["lat"]
    lon = feature["lon"]
    name = feature.get("name", key)

    print(f"\n📍 {name} ({lat}, {lon})")
    print(f"   Searching {date_start} to {date_end} for {product_type}...")

    # Search the full SCS region - granules are large and cover multiple features
    scs_bbox = (109.0, 7.0, 116.0, 17.0)
    # Disable orbit filter - rely on spatial clipping instead
    orbit_filter = None

    short_name = PROVISIONAL_GSLC if product_type == "gslc" else PROVISIONAL_GCOV

    items = search_nisar(scs_bbox, date_start, date_end, short_name, orbit_filter)
    if not items:
        print(f"   No {product_type} imagery found for this date range")
        return []

    # Filter items by feature coverage FIRST, then pick best per day
    covered_items = [item for item in items if granule_covers_feature(item, lat, lon)]
    if not covered_items:
        print(f"   No granules cover this feature")
        return []

    best = pick_best_per_day(covered_items, prefer_polarization=polarizations[0] if polarizations else "VV")
    print(f"   Found {len(items)} items → {len(covered_items)} cover feature → {len(best)} days with usable imagery")

    downloaded = []
    for date_str in sorted(best.keys()):
        item = best[date_str]
        item_id = _get_granule_id(item)

        if resume and already_downloaded(key, date_str, product_type):
            print(f"   ⏭️  {date_str}: already downloaded")
            continue

        print(f"   📥 {date_str}: downloading (orbit: {_get_relative_orbit(item) or '?'})...")

        outfile = os.path.join(IMAGERY_DIR, f"{key}_nisar_{product_type}_{date_str}.h5")

        success = download_granule(item, outfile)
        if success:
            downloaded.append((date_str, outfile))
            log_fetch({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "feature": key, "name": name, "date": date_str,
                "granule_id": item_id, "product_type": product_type,
                "orbit": _get_relative_orbit(item),
                "direction": _get_orbit_direction(item),
                "polarization": _get_polarization(item),
                "file": os.path.basename(outfile),
                "size": os.path.getsize(outfile),
                "status": "ok"
            })

            latest = os.path.join(IMAGERY_DIR, f"{key}_nisar_{product_type}_latest.h5")
            try:
                if os.path.islink(latest) or os.path.exists(latest):
                    os.remove(latest)
                os.symlink(os.path.basename(outfile), latest)
            except Exception:
                pass

        time.sleep(RATE_LIMIT)

    return downloaded


def granule_covers_feature(granule, lat, lon):
    """Check if a granule's spatial extent covers the feature coordinates."""
    umm = _get_umm(granule)
    spatial = umm.get('SpatialExtent', {})
    gp = spatial.get('HorizontalSpatialDomain', {}).get('Geometry', {}).get('GPolygons', [])
    if not gp:
        return False
    pts = gp[0].get('Boundary', {}).get('Points', [])
    if not pts:
        return False
    lats = [p['Latitude'] for p in pts]
    lons = [p['Longitude'] for p in pts]
    return min(lats) <= lat <= max(lats) and min(lons) <= lon <= max(lons)


def main():
    parser = argparse.ArgumentParser(description="NISAR L-band SAR Imagery Fetcher")
    parser.add_argument("--feature", help="Feature key to fetch")
    parser.add_argument("--all", action="store_true", help="Fetch all features")
    parser.add_argument("--lat", type=float, help="Custom latitude")
    parser.add_argument("--lon", type=float, help="Custom longitude")
    parser.add_argument("--name", help="Custom location name")
    parser.add_argument("--days", type=int, default=14, help="Look back N days (default: 14)")
    parser.add_argument("--start-date", help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end-date", help="End date (YYYY-MM-DD)")
    parser.add_argument("--product", choices=["gslc", "gcov", "both"], default="gslc",
                        help="Product type to fetch (default: gslc)")
    parser.add_argument("--polarizations", nargs="+", default=["VV", "VH"],
                        help="Polarizations to prefer (default: VV VH)")
    parser.add_argument("--resume", action="store_true", help="Skip already downloaded granules")
    parser.add_argument("--config-check", action="store_true", help="Print config status and exit")
    args = parser.parse_args()

    config = load_config()

    if args.config_check:
        print("NISAR config status")
        print(f"- config file: {CONFIG_FILE} {'exists' if os.path.exists(CONFIG_FILE) else 'MISSING'}")
        print(f"- primary product: {config.get('products', {}).get('primary', PROVISIONAL_GSLC)}")
        print(f"- secondary product: {config.get('products', {}).get('secondary', PROVISIONAL_GCOV)}")
        print(f"- polarizations: {config.get('polarizations', ['VV', 'VH'])}")
        print(f"- orbit preference: {config.get('orbit_preference', 'descending')}")
        print(f"- feature orbits configured: {len(config.get('feature_orbits', {}))}")
        return

    try:
        auth = earthaccess.login()
        print("✅ Earthdata authentication successful")
    except Exception as e:
        print(f"❌ Earthdata authentication failed: {e}")
        print("   Run 'earthaccess login' or set EARTHDATA_USERNAME/EARTHDATA_PASSWORD")
        sys.exit(2)

    if args.start_date and args.end_date:
        date_start = args.start_date
        date_end = args.end_date
    elif args.start_date:
        date_start = args.start_date
        date_end = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    elif args.end_date:
        date_end = args.end_date
        date_start = (datetime.now(timezone.utc) - timedelta(days=args.days)).strftime("%Y-%m-%d")
    else:
        date_end = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        date_start = (datetime.now(timezone.utc) - timedelta(days=args.days)).strftime("%Y-%m-%d")

    features_db = load_features()
    if args.all:
        targets = features_db
    elif args.feature or (args.lat and args.lon):
        targets = filter_features(features_db, feature_key=args.feature,
                                  lat=args.lat, lon=args.lon, name=args.name)
    else:
        parser.print_help()
        sys.exit(1)

    print(f"\n🛰️  NISAR L-band SAR Fetcher")
    print(f"   Date range: {date_start} → {date_end}")
    print(f"   Features: {len(targets)}")
    print(f"   Product(s): {args.product}")
    print(f"   Polarizations: {args.polarizations}")

    products = ["gslc", "gcov"] if args.product == "both" else [args.product]
    total_downloaded = 0

    for product in products:
        print(f"\n{'='*60}")
        print(f"Fetching {product.upper()} product")
        print(f"{'='*60}")

        for feature in targets:
            dl = fetch_feature(feature, date_start, date_end, product,
                              args.polarizations, args.resume, config)
            total_downloaded += len(dl)

    print(f"\n✅ Done. {total_downloaded} granules downloaded.")


if __name__ == "__main__":
    main()