#!/usr/bin/env python3
"""
NISAR GSLC Interferometric Coherence - Chunked Processing

Computes interferometric coherence between two GSLC granules using
chunked/windowed processing to avoid OOM on large 11GB files.

Usage:
    python3 nisar_coherence_chunked.py --feature fiery_cross_reef --polarization HH
    python3 nisar_coherence_chunked.py --feature investigator_shoal --polarization HH --tile-size 512
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone

import numpy as np
import xarray as xr
from scipy.ndimage import uniform_filter

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(SCRIPT_DIR)
IMAGERY_DIR = os.path.join(BASE_DIR, "imagery_history")
CHANGELOG_FILE = os.path.join(BASE_DIR, "nisar_changes.jsonl")

COHERENCE_THRESHOLD = 0.7
MIN_CHANGE_AREA_PIXELS = 9

os.makedirs(IMAGERY_DIR, exist_ok=True)


def load_features():
    """Load the target features database."""
    features_file = os.path.join(BASE_DIR, "data", "target_features.json")
    with open(features_file) as f:
        return json.load(f)


def get_all_features(db, feature_filter=None):
    """Extract all features as a flat list."""
    features = []
    for feat in db:
        feat_key = feat["key"]
        if feature_filter and feat_key != feature_filter:
            continue
        feat_copy = dict(feat)
        feat_copy["_key"] = feat_key
        feat_copy["_group"] = feat.get("group", "unknown")
        features.append((feat_key, feat_copy))
    return features


def find_granule_pairs(feature_key, product_type):
    """Find consecutive granule pairs for a feature."""
    prefix = f"{feature_key}_nisar_{product_type}_"
    suffix = ".h5"
    files = []
    for f in os.listdir(IMAGERY_DIR):
        if f.startswith(prefix) and f.endswith(suffix) and "_latest" not in f:
            date_part = f[len(prefix):-len(suffix)]
            files.append((date_part, os.path.join(IMAGERY_DIR, f)))

    files.sort()
    pairs = []
    for i in range(len(files) - 1):
        pairs.append((files[i], files[i + 1]))
    return pairs


def compute_local_coherence(s1_tile, s2_tile, window=5):
    """Compute interferometric coherence for a tile."""
    if not np.iscomplexobj(s1_tile) or not np.iscomplexobj(s2_tile):
        return None

    s1_conj = np.conj(s1_tile)
    num = uniform_filter(s1_conj * s2_tile, size=window)
    den1 = uniform_filter(np.abs(s1_tile)**2, size=window)
    den2 = uniform_filter(np.abs(s2_tile)**2, size=window)

    coherence = np.abs(num) / np.sqrt(den1 * den2 + 1e-10)
    coherence = np.clip(coherence, 0, 1)
    return coherence


def compute_coherence_chunked(path1, path2, polarization="HH", tile_size=1024, overlap=128):
    """Compute interferometric coherence using chunked processing with xarray."""
    print(f"  Opening {os.path.basename(path1)}...")
    dt1 = xr.open_datatree(path1, engine="h5netcdf", phony_dims="sort")
    print(f"  Opening {os.path.basename(path2)}...")
    dt2 = xr.open_datatree(path2, engine="h5netcdf", phony_dims="sort")

    # Extract polarization data from GSLC grids
    # Path: /science/LSAR/GSLC/grids/frequencyA/{polarization}
    try:
        s1_da = dt1["/science/LSAR/GSLC/grids/frequencyA"][polarization]
        s2_da = dt2["/science/LSAR/GSLC/grids/frequencyA"][polarization]
    except KeyError:
        available = list(dt1["/science/LSAR/GSLC/grids/frequencyA"].data_vars.keys())
        print(f"  [WARN] Polarization {polarization} not found. Available: {available}")
        return None

    # Get actual dimension names (they use 'xCoordinates' and 'yCoordinates')
    dim_y = 'yCoordinates'
    dim_x = 'xCoordinates'
    if dim_y not in s1_da.dims or dim_x not in s1_da.dims:
        print(f"  [ERROR] Unexpected dimensions: {s1_da.dims}")
        return None

    # Chunk the data using correct dimension names
    s1_chunked = s1_da.chunk({dim_x: tile_size, dim_y: tile_size})
    s2_chunked = s2_da.chunk({dim_x: tile_size, dim_y: tile_size})

    height, width = s1_chunked.sizes[dim_y], s1_chunked.sizes[dim_x]
    print(f"  Image size: {width}x{height}, tile_size={tile_size}, overlap={overlap}")

    # Initialize output array (use float32 to save memory)
    coherence_full = np.zeros((height, width), dtype=np.float32)
    count_full = np.zeros((height, width), dtype=np.uint16)

    # Process in tiles
    step = tile_size - overlap
    tiles_y = range(0, height, step)
    tiles_x = range(0, width, step)

    total_tiles = len(tiles_y) * len(tiles_x)
    print(f"  Processing {total_tiles} tiles...")

    tile_count = 0
    for y in tiles_y:
        y_end = min(y + tile_size, height)
        for x in tiles_x:
            x_end = min(x + tile_size, width)
            tile_count += 1

            if tile_count % 50 == 0:
                print(f"    Tile {tile_count}/{total_tiles} ({y}:{y_end}, {x}:{x_end})")

            # Load tile data (compute to load from disk)
            tile1 = s1_chunked.isel({dim_y: slice(y, y_end), dim_x: slice(x, x_end)}).compute().values
            tile2 = s2_chunked.isel({dim_y: slice(y, y_end), dim_x: slice(x, x_end)}).compute().values

            if tile1.size == 0 or tile2.size == 0:
                continue

            coh = compute_local_coherence(tile1, tile2)
            if coh is None:
                continue

            # Write to output (handle overlap by averaging)
            h, w = coh.shape
            coherence_full[y:y+h, x:x+w] += coh
            count_full[y:y+h, x:x+w] += 1

    # Average overlapping regions
    valid = count_full > 0
    coherence_full[valid] = coherence_full[valid] / count_full[valid]
    coherence_full[~valid] = np.nan

    return coherence_full


def detect_change_coherence(coherence, threshold=COHERENCE_THRESHOLD, min_area=MIN_CHANGE_AREA_PIXELS):
    """Detect changes using coherence loss."""
    if coherence is None:
        return None

    decorrelated = coherence < threshold

    from scipy.ndimage import label
    labeled, num_features = label(decorrelated)

    significant = np.zeros_like(decorrelated, dtype=bool)
    for i in range(1, num_features + 1):
        if np.sum(labeled == i) >= min_area:
            significant[labeled == i] = True

    change_pct = 100 * np.sum(significant) / coherence.size

    return {
        "coherence_mean": round(float(np.nanmean(coherence)), 3),
        "coherence_min": round(float(np.nanmin(coherence)), 3),
        "decorrelated_percent": round(100 * np.sum(decorrelated) / coherence.size, 2),
        "significant_decorrelated_percent": round(change_pct, 2),
        "num_patches": int(num_features),
    }


def classify_sar_change(amp_result, coh_result):
    """Classify the type of SAR change detected."""
    changes = []

    if amp_result and amp_result.get("change_percent", 0) > 1.0:
        if amp_result.get("mean_increase_db", 0) > 3.0:
            changes.append("new_construction")
        if amp_result.get("mean_decrease_db", 0) < -3.0:
            changes.append("structure_removal")

    if coh_result and coh_result.get("significant_decorrelated_percent", 0) > 2.0:
        changes.append("surface_disturbance")

    if coh_result and coh_result.get("coherence_mean", 1.0) < 0.3:
        changes.append("major_change")

    return changes


def _make_json_serializable(obj):
    """Convert numpy arrays and other non-serializable objects to JSON-serializable types."""
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, (np.integer, np.floating)):
        return obj.item()
    if isinstance(obj, dict):
        return {k: _make_json_serializable(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_make_json_serializable(v) for v in obj]
    return obj


def append_to_changelog(result):
    """Append result to nisar_changes.jsonl."""
    serializable = _make_json_serializable(result)
    with open(CHANGELOG_FILE, "a") as f:
        f.write(json.dumps(serializable, ensure_ascii=False) + "\n")


def run_changelog(feature_key, polarization="HH", tile_size=1024, overlap=128):
    """Run changelog for a single feature with chunked coherence."""
    db = load_features()
    features = get_all_features(db, feature_filter=feature_key)

    if not features:
        print(f"Feature {feature_key} not found")
        return

    feat_key, feat = features[0]
    pairs = find_granule_pairs(feat_key, "gslc")

    if len(pairs) < 1:
        print(f"No GSLC pairs found for {feat_key}")
        return

    # Use latest pair
    (date1, path1), (date2, path2) = pairs[-1]
    print(f"\n📍 {feat.get('name', feat_key)} ({date1} → {date2})")
    print(f"  Product: GSLC, Polarization: {polarization}")

    # Compute coherence (chunked)
    print(f"  Computing coherence (chunked)...")
    coherence = compute_coherence_chunked(path1, path2, polarization, tile_size, overlap)

    if coherence is None:
        print(f"  [ERROR] Failed to compute coherence")
        return

    # Compute amplitude change for comparison
    # (reuse existing GCOV amplitude if available, or extract GSLC amplitude)
    from nisar_processor import extract_gslc_amplitude, detect_change_amplitude

    print(f"  Extracting GSLC amplitude...")
    db1 = extract_gslc_amplitude(path1, polarization)
    db2 = extract_gslc_amplitude(path2, polarization)

    amp_result = None
    if db1 is not None and db2 is not None:
        amp_result = detect_change_amplitude(db1, db2)

    # Coherence change detection
    print(f"  Detecting coherence changes...")
    coh_result = detect_change_coherence(coherence)

    # Classification
    change_types = classify_sar_change(amp_result, coh_result)
    changed = len(change_types) > 0

    # Confidence
    confidence = 0.5
    if changed:
        if amp_result and amp_result.get("change_percent", 0) > 5 and coh_result and coh_result.get("significant_decorrelated_percent", 0) > 5:
            confidence = 0.95
        elif amp_result and amp_result.get("change_percent", 0) > 3:
            confidence = 0.85
        elif coh_result and coh_result.get("significant_decorrelated_percent", 0) > 3:
            confidence = 0.80
    else:
        confidence = 0.90

    result = {
        "product_type": "gslc",
        "polarization": polarization,
        "amplitude_change": amp_result,
        "coherence_change": coh_result,
        "changed": changed,
        "confidence": round(confidence, 2),
        "change_types": change_types,
        "image1": os.path.basename(path1),
        "image2": os.path.basename(path2),
        "feature": feat_key,
        "feature_name": feat.get("name", feat_key),
        "group": feat.get("_group", "unknown"),
        "country": feat.get("country", "unknown"),
        "date_previous": date1,
        "date_current": date2,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "processing": "chunked_coherence",
        "tile_size": tile_size,
        "overlap": overlap,
    }

    # Output
    status = "CHANGED" if changed else "ok"
    types = ", ".join(change_types)
    print(f"  {status} (confidence: {confidence}, types: [{types}])")

    if amp_result:
        print(f"  Amplitude Δ: {amp_result['change_percent']}% (inc: {amp_result['mean_increase_db']}dB, dec: {amp_result['mean_decrease_db']}dB)")
    if coh_result:
        print(f"  Coherence: mean={coh_result['coherence_mean']}, decorr={coh_result['significant_decorrelated_percent']}%")

    append_to_changelog(result)


def main():
    parser = argparse.ArgumentParser(description="NISAR GSLC Chunked Coherence Processor")
    parser.add_argument("--feature", help="Feature key to process (required unless --all)")
    parser.add_argument("--all", action="store_true", help="Process all features")
    parser.add_argument("--polarization", default="HH", help="Polarization (HH, HV, VV, VH)")
    parser.add_argument("--tile-size", type=int, default=1024, help="Tile size for chunked processing")
    parser.add_argument("--overlap", type=int, default=128, help="Overlap between tiles")
    parser.add_argument("--changelog", action="store_true", help="Run changelog classification")
    args = parser.parse_args()

    if not args.all and not args.feature:
        parser.error("--feature is required unless --all is specified")

    if args.changelog:
        if args.all:
            run_all_changelog(args.polarization, args.tile_size, args.overlap)
        else:
            run_changelog(args.feature, args.polarization, args.tile_size, args.overlap)
    else:
        parser.print_help()
        sys.exit(1)


def run_all_changelog(polarization, tile_size, overlap):
    """Run changelog for all features."""
    db = load_features()
    features = get_all_features(db)
    print(f"Processing {len(features)} features for coherence changelog...")
    for feat_key, feat_info in features:
        print(f"\n=== {feat_key} ===")
        run_changelog(feat_key, polarization, tile_size, overlap)


if __name__ == "__main__":
    main()