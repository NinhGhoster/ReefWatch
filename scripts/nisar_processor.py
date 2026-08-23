#!/usr/bin/env python3
"""
NISAR SAR Processor — Amplitude extraction, coherence, and change detection.

Processes NISAR GSLC (complex) and GCOV (calibrated backscatter) products
for change detection over SCS features.

Usage:
    python3 nisar_processor.py --feature fiery_cross_reef --product gslc
    python3 nisar_processor.py --all --product both --method amplitude
    python3 nisar_processor.py --batch --changelog
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import xarray as xr

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(SCRIPT_DIR)
IMAGERY_DIR = os.path.join(BASE_DIR, "imagery_history")
CHANGELOG_FILE = os.path.join(BASE_DIR, "nisar_changes.jsonl")
CONFIG_FILE = os.path.join(BASE_DIR, "data", "nisar_config.json")

AMPLITUDE_DB_THRESHOLD = 3.0
COHERENCE_THRESHOLD = 0.7
MIN_CHANGE_AREA_PIXELS = 9

os.makedirs(IMAGERY_DIR, exist_ok=True)


def load_config():
    """Load NISAR configuration."""
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE) as f:
            return json.load(f)
    return {}


def load_features():
    """Load the target features database."""
    features_file = os.path.join(BASE_DIR, "data", "target_features.json")
    with open(features_file) as f:
        return json.load(f)


def get_all_features(db, feature_filter=None):
    """Extract all features as a flat list."""
    features = []
    # target_features.json is a list of feature dicts
    for feat in db:
        feat_key = feat["key"]
        if feature_filter and feat_key != feature_filter:
            continue
        feat_copy = dict(feat)
        feat_copy["_key"] = feat_key
        # Extract group from group field
        feat_copy["_group"] = feat.get("group", "unknown")
        features.append((feat_key, feat_copy))
    return features


def parse_granule_filename(filename):
    """Extract feature, product, date from filename."""
    match = re.match(r'^(.+)_nisar_(gslc|gcov)_(\d{4}-\d{2}-\d{2})\.h5$', filename)
    if match:
        return match.group(1), match.group(2), match.group(3)
    return None, None, None


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


def extract_gslc_amplitude(h5_path, polarization="VV"):
    """Extract amplitude (dB) from GSLC product for a given polarization."""
    try:
        dt = xr.open_datatree(h5_path, engine="h5netcdf", phony_dims="sort")

        freq_a = dt["/science/LSAR/GSLC/grids/frequencyA"]
        if polarization not in freq_a:
            available = list(freq_a.data_vars.keys())
            print(f"    [WARN] Polarization {polarization} not found. Available: {available}")
            polarization = available[0] if available else "HH"

        dn_data = freq_a[polarization].values

        if np.iscomplexobj(dn_data):
            amplitude = np.abs(dn_data)
        else:
            amplitude = dn_data

        amplitude = np.where(amplitude > 0, amplitude, np.nan)

        # GSLC data is in beta0; convert to gamma0 if LUT available
        # For now, use amplitude directly
        gamma0 = amplitude

        db = 10 * np.log10(gamma0, where=gamma0 > 0)
        return db

    except Exception as e:
        print(f"    [ERROR] Failed to extract GSLC amplitude: {e}")
        return None


def extract_gcov_backscatter(h5_path, polarization="VV"):
    """Extract calibrated gamma-naught backscatter from GCOV product."""
    try:
        dt = xr.open_datatree(h5_path, engine="h5netcdf", phony_dims="sort")

        freq_a = dt["/science/LSAR/GCOV/grids/frequencyA"]

        pol_map = {"VV": "VVVV", "HH": "HHHH", "VH": "VHVH", "HV": "HVHV"}
        cov_var = pol_map.get(polarization, "VVVV")

        if cov_var not in freq_a:
            available = list(freq_a.data_vars.keys())
            print(f"    [WARN] {cov_var} not found. Available: {available}")
            cov_var = available[0] if available else "HHHH"

        gamma0 = freq_a[cov_var].values
        gamma0 = np.where(gamma0 > 0, gamma0, np.nan)

        db = 10 * np.log10(gamma0, where=gamma0 > 0)
        return db

    except Exception as e:
        print(f"    [ERROR] Failed to extract GCOV backscatter: {e}")
        return None


def compute_coherence(gslc1_path, gslc2_path, polarization="VV", window=5):
    """Compute interferometric coherence between two GSLC granules."""
    try:
        dt1 = xr.open_datatree(gslc1_path, engine="h5netcdf", phony_dims="sort")
        dt2 = xr.open_datatree(gslc2_path, engine="h5netcdf", phony_dims="sort")

        freq_a1 = dt1["/science/LSAR/GSLC/grids/frequencyA"]
        freq_a2 = dt2["/science/LSAR/GSLC/grids/frequencyA"]

        if polarization not in freq_a1 or polarization not in freq_a2:
            return None

        s1 = freq_a1[polarization].values
        s2 = freq_a2[polarization].values

        if not np.iscomplexobj(s1) or not np.iscomplexobj(s2):
            print("    [WARN] GSLC data not complex, cannot compute coherence")
            return None

        from scipy.ndimage import uniform_filter

        s1_conj = np.conj(s1)
        num = uniform_filter(s1_conj * s2, size=window)
        den1 = uniform_filter(np.abs(s1)**2, size=window)
        den2 = uniform_filter(np.abs(s2)**2, size=window)

        coherence = np.abs(num) / np.sqrt(den1 * den2 + 1e-10)
        coherence = np.clip(coherence, 0, 1)

        return coherence

    except Exception as e:
        print(f"    [ERROR] Coherence computation failed: {e}")
        return None


def detect_change_amplitude(db1, db2, threshold_db=AMPLITUDE_DB_THRESHOLD, include_arrays=False):
    """Detect changes using amplitude differencing in dB."""
    if db1 is None or db2 is None:
        return None

    if db1.shape != db2.shape:
        h, w = min(db1.shape[0], db2.shape[0]), min(db1.shape[1], db2.shape[1])
        db1 = db1[:h, :w]
        db2 = db2[:h, :w]

    diff = db2 - db1
    valid = ~(np.isnan(db1) | np.isnan(db2))
    diff = np.where(valid, diff, 0)

    increased = diff > threshold_db
    decreased = diff < -threshold_db

    change_map = np.zeros_like(diff, dtype=np.uint8)
    change_map[increased] = 1
    change_map[decreased] = 2

    change_pct = 100 * np.sum(change_map > 0) / np.sum(valid) if np.sum(valid) > 0 else 0

    result = {
        "change_percent": round(change_pct, 2),
        "mean_increase_db": round(np.nanmean(diff[increased]), 2) if np.any(increased) else 0,
        "mean_decrease_db": round(np.nanmean(diff[decreased]), 2) if np.any(decreased) else 0,
    }
    if include_arrays:
        result["diff_db"] = diff
        result["change_map"] = change_map
    return result


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
        "coherence_mean": round(np.nanmean(coherence), 3),
        "coherence_min": round(np.nanmin(coherence), 3),
        "decorrelated_percent": round(100 * np.sum(decorrelated) / coherence.size, 2),
        "significant_decorrelated_percent": round(change_pct, 2),
        "num_patches": int(num_features),
    }


def classify_sar_change(amp_result, coh_result, pol_diff=None):
    """Classify the type of SAR change detected."""
    changes = []

    if amp_result and amp_result["change_percent"] > 1.0:
        if amp_result["mean_increase_db"] > AMPLITUDE_DB_THRESHOLD:
            changes.append("new_construction")
        if amp_result["mean_decrease_db"] < -AMPLITUDE_DB_THRESHOLD:
            changes.append("structure_removal")

    if coh_result and coh_result["significant_decorrelated_percent"] > 2.0:
        changes.append("surface_disturbance")

    if coh_result and coh_result["coherence_mean"] < 0.3:
        changes.append("major_change")

    if pol_diff and np.any(np.abs(pol_diff) > 2.0):
        changes.append("scattering_mechanism_change")

    return changes


def compare_granules(path1, path2, product_type, polarization="VV"):
    """Full comparison of two SAR granules."""
    if product_type == "gslc":
        db1 = extract_gslc_amplitude(path1, polarization)
        db2 = extract_gslc_amplitude(path2, polarization)
        coherence = compute_coherence(path1, path2, polarization)
    elif product_type == "gcov":
        db1 = extract_gcov_backscatter(path1, polarization)
        db2 = extract_gcov_backscatter(path2, polarization)
        coherence = None
    else:
        return {"error": f"Unknown product type: {product_type}", "changed": None}

    if db1 is None or db2 is None:
        return {"error": "Failed to extract amplitude/backscatter", "changed": None}

    amp_result = detect_change_amplitude(db1, db2)
    coh_result = detect_change_coherence(coherence) if coherence is not None else None

    change_types = classify_sar_change(amp_result, coh_result)

    changed = len(change_types) > 0

    confidence = 0.5
    if changed:
        if amp_result and amp_result["change_percent"] > 5 and coh_result and coh_result["significant_decorrelated_percent"] > 5:
            confidence = 0.95
        elif amp_result and amp_result["change_percent"] > 3:
            confidence = 0.85
        elif coh_result and coh_result["significant_decorrelated_percent"] > 3:
            confidence = 0.80
    else:
        confidence = 0.90

    return {
        "product_type": product_type,
        "polarization": polarization,
        "amplitude_change": amp_result,
        "coherence_change": coh_result,
        "changed": changed,
        "confidence": round(confidence, 2),
        "change_types": change_types,
        "image1": os.path.basename(path1),
        "image2": os.path.basename(path2),
    }


def run_batch(feature_filter=None, product_type="gslc", polarization="VV", method="amplitude"):
    """Process all features, comparing consecutive granules."""
    if not os.path.isdir(IMAGERY_DIR):
        print(f"Imagery directory not found: {IMAGERY_DIR}")
        return []

    db = load_features()
    features = get_all_features(db, feature_filter)

    results = []
    for feat_key, feat in features:
        pairs = find_granule_pairs(feat_key, product_type)
        if len(pairs) < 1:
            continue

        latest_pair = pairs[-1]
        (date1, path1), (date2, path2) = latest_pair

        print(f"  Comparing {feat_key}: {date1} → {date2} ({product_type}, {polarization})")

        result = compare_granules(path1, path2, product_type, polarization)
        result["feature"] = feat_key
        result["feature_name"] = feat.get("name", feat_key)
        result["group"] = feat.get("_group", "unknown")
        result["country"] = feat.get("country", "unknown")
        result["date_previous"] = date1
        result["date_current"] = date2
        result["timestamp"] = datetime.now(timezone.utc).isoformat()

        status = "CHANGED" if result.get("changed") else "ok"
        types = ", ".join(result.get("change_types", []))
        conf = result.get("confidence", 0)

        print(f"    {status} (confidence: {conf}, types: [{types}])")

        results.append(result)

    return results


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


def append_to_changelog(results):
    """Append batch results to nisar_changes.jsonl."""
    with open(CHANGELOG_FILE, "a") as f:
        for r in results:
            serializable = _make_json_serializable(r)
            f.write(json.dumps(serializable, ensure_ascii=False) + "\n")


def run_changelog(feature_filter=None, product_type="gslc", polarization="VV"):
    """Detect and classify change types from latest granule pairs."""
    results = run_batch(feature_filter, product_type, polarization)
    changed = [r for r in results if r.get("changed") or r.get("change_types")]

    if not changed:
        print("\nNo significant SAR changes detected.")
        return

    print(f"\n{'='*60}")
    print(f"NISAR SAR Change Log: {len(changed)} features with activity")
    print(f"{'='*60}\n")

    for r in changed:
        types = r.get("change_types", [])
        amp = r.get("amplitude_change", {})
        coh = r.get("coherence_change", {})

        print(f"📍 {r['feature']} ({r['date_previous']} → {r['date_current']})")
        print(f"   Product: {r['product_type'].upper()}, Pol: {r['polarization']}")
        if amp:
            print(f"   Amplitude Δ: {amp['change_percent']}% (inc: {amp['mean_increase_db']}dB, dec: {amp['mean_decrease_db']}dB)")
        if coh:
            print(f"   Coherence: mean={coh['coherence_mean']}, decorr={coh['significant_decorrelated_percent']}%")
        if "new_construction" in types:
            print(f"   🏗️  New construction detected")
        if "structure_removal" in types:
            print(f"   🗑️  Structure removal detected")
        if "surface_disturbance" in types:
            print(f"   🌊 Surface disturbance (decorrelation)")
        if "major_change" in types:
            print(f"   ⚠️  Major change (very low coherence)")
        if "scattering_mechanism_change" in types:
            print(f"   📡 Scattering mechanism change")
        print()

    append_to_changelog(changed)


def main():
    parser = argparse.ArgumentParser(description="NISAR SAR Processor")
    parser.add_argument("--feature", help="Feature key to process")
    parser.add_argument("--all", action="store_true", help="Process all features")
    parser.add_argument("--product", choices=["gslc", "gcov", "both"], default="gslc",
                        help="Product type to process (default: gslc)")
    parser.add_argument("--polarization", default="VV", help="Polarization to use (default: VV)")
    parser.add_argument("--method", choices=["amplitude", "coherence", "both"], default="amplitude",
                        help="Change detection method (default: amplitude)")
    parser.add_argument("--batch", action="store_true", help="Process all features in batch")
    parser.add_argument("--changelog", action="store_true", help="Run changelog classification")
    args = parser.parse_args()

    if args.batch or args.changelog:
        products = ["gslc", "gcov"] if args.product == "both" else [args.product]
        for prod in products:
            print(f"\n--- Processing {prod.upper()} ---")
            if args.changelog:
                run_changelog(args.feature, prod, args.polarization)
            else:
                results = run_batch(args.feature, prod, args.polarization)
                append_to_changelog(results)
                changed = sum(1 for r in results if r.get("changed"))
                print(f"\nProcessed {len(results)} features, {changed} changed.")
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()