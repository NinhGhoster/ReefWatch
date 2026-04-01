#!/usr/bin/env python3
"""
SCS Alert Engine — Telegram-formatted alert generation.

Reads imagery changes and aircraft detections, generates severity-rated
alerts formatted for Telegram delivery.

Usage:
    python3 alert_engine.py                  # Generate alerts from latest data
    python3 alert_engine.py --print-only     # Print without saving
    python3 alert_engine.py --last 24        # Last 24 hours only
"""

import argparse
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(SCRIPT_DIR)
IMAGERY_CHANGES = os.path.join(BASE_DIR, "imagery_changes.jsonl")
AIRCRAFT_DETECTIONS = os.path.join(BASE_DIR, "aircraft_detections.jsonl")
ALERTS_LOG = os.path.join(BASE_DIR, "alerts_log.jsonl")
FEATURES_FILE = os.path.join(BASE_DIR, "data", "scs_features.json")

MAX_ALERT_LENGTH = 500

# Severity levels
HIGH = "🔴"
MEDIUM = "🟡"
LOW = "🟢"


def load_jsonl(path, hours=None):
    """Load JSONL file, optionally filtering to recent entries."""
    if not os.path.isfile(path):
        return []
    
    cutoff = None
    if hours:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    
    records = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
                if cutoff and "timestamp" in rec:
                    ts = datetime.fromisoformat(rec["timestamp"].replace("Z", "+00:00"))
                    if ts < cutoff:
                        continue
                records.append(rec)
            except json.JSONDecodeError:
                continue
    return records


def load_features():
    """Load features database for metadata."""
    if not os.path.isfile(FEATURES_FILE):
        return {}
    with open(FEATURES_FILE) as f:
        db = json.load(f)
    
    flat = {}
    for group in db.get("island_groups", {}).values():
        for key, feat in group.get("features", {}).items():
            flat[key] = feat
    return flat


def truncate(text, maxlen=MAX_ALERT_LENGTH):
    """Truncate text to max length."""
    if len(text) <= maxlen:
        return text
    return text[:maxlen - 3] + "..."


def format_imagery_alert(record, features_meta):
    """Generate Telegram alert for an imagery change."""
    feature = record.get("feature", "unknown")
    meta = features_meta.get(feature, {})
    name = meta.get("name", feature.replace("_", " ").title())
    country = meta.get("country", "unknown")
    
    change_types = record.get("change_types", [])
    ssim = record.get("ssim_score", "?")
    pixel_diff = record.get("pixel_diff_pct", "?")
    confidence = record.get("confidence", 0)
    date_prev = record.get("date_previous", "?")
    date_curr = record.get("date_current", "?")
    
    # Determine severity
    severity = LOW
    alert_type = "Imagery Change"
    
    if "new_construction" in change_types:
        severity = HIGH
        alert_type = "New Construction Detected"
    elif "new_vessel" in change_types:
        severity = MEDIUM
        alert_type = "New Vessel Detected"
    elif "major_change" in change_types:
        severity = HIGH
        alert_type = "Major Structural Change"
    elif "significant_change" in change_types:
        severity = MEDIUM
        alert_type = "Significant Imagery Change"
    elif record.get("cloud_interference"):
        severity = LOW
        alert_type = "Cloud Interference"
    
    # Military features get bumped up
    if meta.get("airport") or meta.get("sam") or meta.get("radar"):
        if severity == MEDIUM:
            severity = HIGH
    
    icons = ""
    if meta.get("airport"):
        icons += "✈️"
    if meta.get("port"):
        icons += "⚓"
    if meta.get("helipad"):
        icons += "🚁"
    
    lines = [
        f"{severity} *{alert_type}*",
        f"",
        f"📍 *{name}* ({country}) {icons}",
        f"📅 {date_prev} → {date_curr}",
        f"📊 SSIM: {ssim} | Pixel Δ: {pixel_diff}%",
        f"🎯 Confidence: {confidence:.0%}",
    ]
    
    if "new_construction" in change_types:
        lines.append(f"🏗️ Possible new construction activity")
    if "new_vessel" in change_types:
        lines.append(f"🚢 Possible new vessel(s) detected")
    if record.get("cloud_interference"):
        lines.append(f"☁️ Cloud cover may affect accuracy")
    
    return truncate("\n".join(lines)), severity


def format_aircraft_alert(records, features_meta):
    """Generate Telegram alert for aircraft detections."""
    if not records:
        return None
    
    # Group by feature
    by_feature = defaultdict(list)
    for r in records:
        feat = r.get("feature") or r.get("feature_key") or "unknown"
        by_feature[feat].append(r)
    
    alerts = []
    for feat, recs in by_feature.items():
        meta = features_meta.get(feat, {})
        name = meta.get("name", feat.replace("_", " ").title())
        
        count = len(recs)
        callsigns = set()
        for r in recs:
            cs = r.get("callsign") or r.get("aircraft", {}).get("callsign")
            if cs:
                callsigns.add(cs.strip())
        
        # Severity based on context
        if count >= 3:
            severity = HIGH
            alert_type = "Multiple Aircraft Detected"
        elif count == 1 and not any(recs[0].get(f) for f in ["seen_recently", "routine"]):
            severity = MEDIUM
            alert_type = "New Aircraft Detected"
        else:
            severity = LOW
            alert_type = "Aircraft Activity"
        
        lines = [
            f"{severity} *{alert_type}*",
            f"",
            f"📍 *{name}*",
            f"✈️ {count} aircraft detected",
        ]
        
        if callsigns:
            cs_list = ", ".join(sorted(callsigns)[:5])
            lines.append(f"🆔 {cs_list}")
        
        lines.append(f"🕐 {recs[-1].get('timestamp', 'recent')[:16]}")
        
        text = truncate("\n".join(lines))
        alerts.append((text, severity))
    
    return alerts


def generate_all_alerts(hours=24, print_only=False):
    """Generate all alerts from recent data."""
    features_meta = load_features()
    
    # Load recent data
    imagery = load_jsonl(IMAGERY_CHANGES, hours=hours)
    aircraft = load_jsonl(AIRCRAFT_DETECTIONS, hours=hours)
    
    # Filter to only changed imagery
    changed_imagery = [
        r for r in imagery
        if r.get("changed") and not r.get("cloud_interference")
    ]
    
    all_alerts = []
    
    # Imagery alerts
    for rec in changed_imagery:
        text, severity = format_imagery_alert(rec, features_meta)
        if text:
            all_alerts.append({
                "text": text,
                "severity": severity,
                "type": "imagery",
                "feature": rec.get("feature", "unknown"),
                "timestamp": rec.get("timestamp", datetime.now(timezone.utc).isoformat()),
            })
    
    # Aircraft alerts
    aircraft_alerts = format_aircraft_alert(aircraft, features_meta)
    if aircraft_alerts:
        for alert_pair in aircraft_alerts:
            if alert_pair and len(alert_pair) == 2:
                text, severity = alert_pair
                all_alerts.append({
                    "text": text,
                    "severity": severity,
                    "type": "aircraft",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })
    
    # Sort by severity (HIGH first)
    severity_order = {HIGH: 0, MEDIUM: 1, LOW: 2}
    all_alerts.sort(key=lambda a: severity_order.get(a["severity"], 3))
    
    # Print
    if all_alerts:
        print(f"🔔 {len(all_alerts)} alert(s) generated\n")
        for i, alert in enumerate(all_alerts, 1):
            print(f"--- Alert {i} ---")
            print(alert["text"])
            print()
    else:
        print("✅ No alerts to generate — all clear.")
    
    # Save to log
    if not print_only and all_alerts:
        with open(ALERTS_LOG, "a") as f:
            for alert in all_alerts:
                entry = {
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "severity": alert["severity"],
                    "type": alert["type"],
                    "feature": alert.get("feature"),
                    "text": alert["text"],
                }
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        print(f"📝 {len(all_alerts)} alert(s) saved to {ALERTS_LOG}")
    
    return all_alerts


# ── CLI ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="SCS Telegram Alert Engine")
    parser.add_argument("--last", type=int, default=24,
                        help="Hours to look back (default: 24)")
    parser.add_argument("--print-only", action="store_true",
                        help="Print alerts without saving to log")
    args = parser.parse_args()
    
    generate_all_alerts(hours=args.last, print_only=args.print_only)
