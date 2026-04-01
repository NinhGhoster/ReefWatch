#!/usr/bin/env python3
"""
SCS Monitor — Master orchestrator for South China Sea monitoring.

Coordinates aircraft, ship, and imagery monitoring across all 79 features.
Supports filtering by feature, monitoring type, and change-only output.

Usage:
    python3 scs_monitor.py                              # Full monitor all features
    python3 scs_monitor.py --type aircraft              # Only aircraft detection
    python3 scs_monitor.py --type ships                 # Only ship monitoring
    python3 scs_monitor.py --type imagery               # Only satellite imagery
    python3 scs_monitor.py --feature fiery_cross_reef   # Single feature
    python3 scs_monitor.py --changes                    # Show changes only
    python3 scs_monitor.py --summary                    # Show latest status
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
FEATURES_FILE = os.path.join(SCRIPT_DIR, "scs_features.json")
MONITOR_LOG = os.path.join(SCRIPT_DIR, "scs_monitor_log.jsonl")

# Import monitoring modules
sys.path.insert(0, SCRIPT_DIR)
import aircraft_monitor
import ship_monitor
import imagery_monitor


def load_features():
    """Load the features database."""
    with open(FEATURES_FILE) as f:
        return json.load(f)


def get_features_flat(db, feature_filter=None):
    """Get all features as a flat list, optionally filtered by key."""
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


def append_monitor_log(entry):
    """Append to the master monitor log."""
    with open(MONITOR_LOG, "a") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def run_aircraft_monitor(features):
    """Run aircraft monitoring for features."""
    print("\n" + "=" * 60)
    print("✈️  AIRCRAFT MONITOR")
    print("=" * 60)
    results = aircraft_monitor.run_monitor(features)
    total = sum(r["aircraft_count"] for r in results)
    active = sum(1 for r in results if r["aircraft_count"] > 0)
    return {
        "type": "aircraft",
        "features_checked": len(results),
        "features_with_activity": active,
        "total_detections": total,
        "results": results,
    }


def run_ship_monitor(db):
    """Run ship monitoring for port features."""
    print("\n" + "=" * 60)
    print("🚢 SHIP MONITOR")
    print("=" * 60)
    urls_data = ship_monitor.build_ship_urls(db)
    results = ship_monitor.run_ship_check(urls_data, check_api=True)
    ship_monitor.append_log(results)
    with_ais = sum(1 for r in results if r.get("ais_available"))
    return {
        "type": "ships",
        "features_checked": len(results),
        "with_ais_data": with_ais,
        "urls_generated": len(urls_data),
        "results": results,
    }


def run_imagery_monitor(features):
    """Run imagery monitoring for features."""
    print("\n" + "=" * 60)
    print("🛰️  IMAGERY MONITOR")
    print("=" * 60)
    results = []
    for i, (feat_key, feat) in enumerate(features):
        result = imagery_monitor.monitor_feature(feat_key, feat)
        name = feat.get("name", feat_key)
        
        if result["status"] == "ok":
            ch = result.get("change", {})
            if ch.get("changed"):
                print(f"  ⚠️  {name}: CHANGED (Δ{ch.get('size_change_ratio', 0):.1%})")
            else:
                print(f"  ✓  {name}: ok ({result['image_size']}B)")
        else:
            print(f"  ✗  {name}: no imagery")
        
        imagery_monitor.append_log(result)
        results.append(result)
        
        if i < len(features) - 1:
            time.sleep(1.0)  # Rate limit NASA requests
    
    ok = sum(1 for r in results if r["status"] == "ok")
    changed = sum(1 for r in results if r.get("change", {}).get("changed"))
    return {
        "type": "imagery",
        "features_checked": len(results),
        "images_captured": ok,
        "changes_detected": changed,
        "results": results,
    }


def show_summary():
    """Show latest status of all features across all monitoring types."""
    print(f"\nSCS Monitor Summary — {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print("=" * 90)
    
    db = load_features()
    all_features = get_features_flat(db)
    
    # Load latest aircraft data
    aircraft_latest = {}
    ac_log = os.path.join(SCRIPT_DIR, "aircraft_detections.jsonl")
    if os.path.isfile(ac_log):
        with open(ac_log) as f:
            for line in f:
                try:
                    rec = json.loads(line.strip())
                    key = rec.get("feature_key")
                    if key:
                        aircraft_latest[key] = rec
                except (json.JSONDecodeError, ValueError):
                    continue
    
    # Load latest imagery data
    imagery_latest = {}
    im_log = os.path.join(SCRIPT_DIR, "imagery_changes.jsonl")
    if os.path.isfile(im_log):
        with open(im_log) as f:
            for line in f:
                try:
                    rec = json.loads(line.strip())
                    key = rec.get("feature_key")
                    if key:
                        imagery_latest[key] = rec
                except (json.JSONDecodeError, ValueError):
                    continue
    
    # Load ship data
    ship_latest = {}
    sh_log = os.path.join(SCRIPT_DIR, "ships_log.jsonl")
    if os.path.isfile(sh_log):
        with open(sh_log) as f:
            for line in f:
                try:
                    rec = json.loads(line.strip())
                    key = rec.get("feature_key")
                    if key:
                        ship_latest[key] = rec
                except (json.JSONDecodeError, ValueError):
                    continue
    
    print(f"\n{'Feature':<28} {'Ctry':<8} {'✈️':>3} {'🚢':>3} {'🚁':>3} "
          f"{'Aircraft':>8} {'Imagery':<10} {'Changed':>7}")
    print("-" * 80)
    
    for feat_key, feat in all_features:
        name = feat_key[:27]
        country = feat.get("country", "?")[:7]
        has_ac = "✓" if feat.get("airport") else " "
        has_port = "✓" if feat.get("port") else " "
        has_heli = "✓" if feat.get("helipad") else " "
        
        ac_count = aircraft_latest.get(feat_key, {}).get("aircraft_count", 0)
        ac_str = f"{ac_count}" if feat_key in aircraft_latest else "—"
        
        im_rec = imagery_latest.get(feat_key, {})
        im_status = im_rec.get("status", "—")
        im_changed = "YES" if im_rec.get("change", {}).get("changed") else "—"
        
        print(f"  {name:<28} {country:<8} {has_ac:>3} {has_port:>3} {has_heli:>3} "
              f"{ac_str:>8} {im_status:<10} {im_changed:>7}")
    
    total = len(all_features)
    ac_active = sum(1 for r in aircraft_latest.values() if r.get("aircraft_count", 0) > 0)
    im_ok = sum(1 for r in imagery_latest.values() if r.get("status") == "ok")
    im_changed = sum(1 for r in imagery_latest.values() if r.get("change", {}).get("changed"))
    
    print(f"\n{'=' * 80}")
    print(f"Total features: {total}")
    print(f"Aircraft monitoring: {len(aircraft_latest)} checked, {ac_active} with activity")
    print(f"Imagery: {im_ok} captured, {im_changed} with changes")
    print(f"Ship monitoring: {len(ship_latest)} port features tracked")


def show_changes():
    """Show only features with changes since last check."""
    print(f"\nSCS Changes — {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print("=" * 60)
    
    found = False
    
    # Aircraft changes
    ac_log = os.path.join(SCRIPT_DIR, "aircraft_detections.jsonl")
    if os.path.isfile(ac_log):
        latest = {}
        with open(ac_log) as f:
            for line in f:
                try:
                    rec = json.loads(line.strip())
                    key = rec.get("feature_key")
                    if key:
                        latest[key] = rec
                except (json.JSONDecodeError, ValueError):
                    continue
        
        active = {k: v for k, v in latest.items() if v.get("aircraft_count", 0) > 0}
        if active:
            found = True
            print(f"\n✈️  Aircraft Activity ({len(active)} features):")
            for key in sorted(active):
                rec = active[key]
                callsigns = [a.get("callsign", "?") for a in rec.get("aircraft", [])]
                print(f"  {key}: {rec['aircraft_count']} aircraft — {', '.join(callsigns[:5])}")
    
    # Imagery changes
    im_log = os.path.join(SCRIPT_DIR, "imagery_changes.jsonl")
    if os.path.isfile(im_log):
        latest = {}
        with open(im_log) as f:
            for line in f:
                try:
                    rec = json.loads(line.strip())
                    key = rec.get("feature_key")
                    if key:
                        latest[key] = rec
                except (json.JSONDecodeError, ValueError):
                    continue
        
        changed = {k: v for k, v in latest.items() if v.get("change", {}).get("changed")}
        if changed:
            found = True
            print(f"\n🛰️  Imagery Changes ({len(changed)} features):")
            for key in sorted(changed):
                rec = changed[key]
                ch = rec.get("change", {})
                print(f"  {key}: changed (Δ{ch.get('size_change_ratio', 0):.1%})")
    
    if not found:
        print("\nNo changes detected since last monitoring run.")


# ── Main ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="SCS Master Monitor")
    parser.add_argument("--feature", help="Monitor a single feature by key name")
    parser.add_argument("--type", choices=["aircraft", "ships", "imagery"],
                        help="Run only one monitoring type")
    parser.add_argument("--summary", action="store_true",
                        help="Show latest status of all features")
    parser.add_argument("--changes", action="store_true",
                        help="Show only features with changes")
    args = parser.parse_args()
    
    if args.summary:
        show_summary()
        sys.exit(0)
    if args.changes:
        show_changes()
        sys.exit(0)
    
    db = load_features()
    all_features = get_features_flat(db, args.feature)
    
    if not all_features:
        print(f"Feature '{args.feature}' not found." if args.feature else "No features found.")
        sys.exit(1)
    
    ts = datetime.now(timezone.utc)
    print(f"SCS Monitor — {ts.strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"Features: {len(all_features)} | Type: {args.type or 'all'}")
    
    t0 = time.time()
    run_types = args.type or "all"
    run_entry = {
        "timestamp": ts.isoformat(),
        "feature_filter": args.feature,
        "type_filter": args.type,
        "features_count": len(all_features),
        "runs": {},
    }
    
    # Aircraft
    if run_types in ("all", "aircraft"):
        ac_features = [(k, f) for k, f in all_features
                       if f.get("airport") or f.get("helipad")]
        if ac_features:
            run_entry["runs"]["aircraft"] = run_aircraft_monitor(ac_features)
        else:
            print("\n  (No airport/helipad features to monitor)")
    
    # Ships
    if run_types in ("all", "ships"):
        if args.feature:
            # Build a filtered db for ship_monitor
            filtered_db = {"island_groups": {}}
            for group_key, group in db.get("island_groups", {}).items():
                for feat_key, feat in group.get("features", {}).items():
                    if feat_key == args.feature and feat.get("port"):
                        if group_key not in filtered_db["island_groups"]:
                            filtered_db["island_groups"][group_key] = {"features": {}}
                        filtered_db["island_groups"][group_key]["features"][feat_key] = feat
            if any(filtered_db["island_groups"].values()):
                run_entry["runs"]["ships"] = run_ship_monitor(filtered_db)
            else:
                print("\n  (No port features to monitor)")
        else:
            run_entry["runs"]["ships"] = run_ship_monitor(db)
    
    # Imagery
    if run_types in ("all", "imagery"):
        run_entry["runs"]["imagery"] = run_imagery_monitor(all_features)
    
    elapsed = time.time() - t0
    run_entry["elapsed_seconds"] = round(elapsed, 1)
    
    append_monitor_log(run_entry)
    
    print(f"\n{'=' * 60}")
    print(f"Complete in {elapsed:.1f}s")
    print(f"Log: {MONITOR_LOG}")
