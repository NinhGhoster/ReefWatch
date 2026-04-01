#!/usr/bin/env python3
"""
SCS Daily Report — Telegram-formatted daily monitoring summary.

Generates a daily summary of all monitoring activity including
aircraft detections, imagery changes, and notable events.

Usage:
    python3 run_daily_report.py                  # Today's report
    python3 run_daily_report.py --date 2026-03-31  # Specific date
    python3 run_daily_report.py --last 48        # Last 48 hours
"""

import argparse
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(SCRIPT_DIR)
IMAGERY_DIR = os.path.join(BASE_DIR, "imagery_history")
IMAGERY_CHANGES = os.path.join(BASE_DIR, "imagery_changes.jsonl")
AIRCRAFT_DETECTIONS = os.path.join(BASE_DIR, "aircraft_detections.jsonl")
ALERTS_LOG = os.path.join(BASE_DIR, "alerts_log.jsonl")
FEATURES_FILE = os.path.join(BASE_DIR, "data", "scs_features.json")


def load_jsonl(path, hours=None, date_filter=None):
    """Load JSONL file with optional time filtering."""
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

                if date_filter:
                    # Match records from a specific date
                    ts_str = rec.get("timestamp", "")
                    date_str = rec.get("date", rec.get("date_current", ""))
                    if date_filter not in ts_str and date_filter not in date_str:
                        continue

                records.append(rec)
            except (json.JSONDecodeError, ValueError):
                continue
    return records


def load_features():
    """Load features database."""
    if not os.path.isfile(FEATURES_FILE):
        return {}
    with open(FEATURES_FILE) as f:
        db = json.load(f)
    flat = {}
    for group in db.get("island_groups", {}).values():
        for key, feat in group.get("features", {}).items():
            flat[key] = feat
    return flat


def count_imagery_files(hours=24):
    """Count imagery files captured recently."""
    if not os.path.isdir(IMAGERY_DIR):
        return 0, 0
    cutoff = datetime.now() - timedelta(hours=hours)
    total = 0
    features = set()
    for f in os.listdir(IMAGERY_DIR):
        if f.endswith('_latest.png') or not f.endswith('.png'):
            continue
        path = os.path.join(IMAGERY_DIR, f)
        mtime = datetime.fromtimestamp(os.path.getmtime(path))
        if mtime > cutoff:
            total += 1
            # Extract feature name (everything before last _YYYY-MM-DD)
            parts = f.rsplit('_', 2)
            if len(parts) >= 2:
                features.add(parts[0])
    return total, len(features)


def generate_report(hours=24, date_filter=None):
    """Generate the daily monitoring report as Telegram-formatted text."""
    features_meta = load_features()
    now = datetime.now(timezone.utc)

    # Load data
    imagery = load_jsonl(IMAGERY_CHANGES, hours=hours, date_filter=date_filter)
    aircraft = load_jsonl(AIRCRAFT_DETECTIONS, hours=hours, date_filter=date_filter)
    alerts = load_jsonl(ALERTS_LOG, hours=hours, date_filter=date_filter)

    # Imagery analysis
    imagery_with_images = [r for r in imagery if r.get("image_captured") or r.get("status") == "ok"]
    changed_imagery = [r for r in imagery if r.get("changed")]
    cloud_affected = [r for r in imagery if r.get("cloud_interference")]

    # Aircraft analysis
    aircraft_features = defaultdict(int)
    aircraft_callsigns = set()
    for r in aircraft:
        feat = r.get("feature") or r.get("feature_key") or "unknown"
        aircraft_features[feat] += 1
        cs = r.get("callsign") or (r.get("aircraft", {}).get("callsign") if isinstance(r.get("aircraft"), dict) else None)
        if cs:
            aircraft_callsigns.add(cs.strip())

    # Alert analysis
    high_alerts = [a for a in alerts if a.get("severity") == "🔴"]
    med_alerts = [a for a in alerts if a.get("severity") == "🟡"]

    # Build report
    report_date = date_filter or now.strftime("%Y-%m-%d")
    lines = [
        f"📋 *SCS Daily Report — {report_date}*",
        f"━━━━━━━━━━━━━━━━━━━━",
        "",
    ]

    # Imagery section
    img_count = len(imagery_with_images)
    total_features = len(features_meta)
    lines.append(f"🛰️ *Imagery*")
    lines.append(f"• {img_count} features imaged")

    if changed_imagery:
        lines.append(f"• ⚠️ {len(changed_imagery)} with detected changes")
        for r in changed_imagery[:5]:
            name = r.get("feature", "?")
            meta = features_meta.get(name, {})
            display = meta.get("name", name.replace("_", " ").title())
            types = ", ".join(r.get("change_types", []))
            ssim = r.get("ssim_score", "?")
            lines.append(f"  └ {display} (SSIM: {ssim}, [{types}])")
        if len(changed_imagery) > 5:
            lines.append(f"  └ ...and {len(changed_imagery) - 5} more")
    else:
        lines.append(f"• ✅ No significant changes detected")

    if cloud_affected:
        lines.append(f"• ☁️ {len(cloud_affected)} features with cloud interference")

    lines.append("")

    # Aircraft section
    lines.append(f"✈️ *Aircraft Activity*")
    if aircraft_features:
        total_detections = sum(aircraft_features.values())
        lines.append(f"• {total_detections} detections across {len(aircraft_features)} features")
        for feat, count in sorted(aircraft_features.items(), key=lambda x: -x[1])[:5]:
            meta = features_meta.get(feat, {})
            display = meta.get("name", feat.replace("_", " ").title())
            lines.append(f"  └ {display}: {count}x")
        if aircraft_callsigns:
            cs_preview = ", ".join(sorted(aircraft_callsigns)[:5])
            lines.append(f"• 🆔 Callsigns: {cs_preview}")
    else:
        lines.append(f"• ✅ No aircraft activity recorded")
    lines.append("")

    # Alerts section
    lines.append(f"🔔 *Alerts*")
    if high_alerts:
        lines.append(f"• 🔴 {len(high_alerts)} HIGH priority")
    if med_alerts:
        lines.append(f"• 🟡 {len(med_alerts)} MEDIUM priority")
    low_count = len(alerts) - len(high_alerts) - len(med_alerts)
    if low_count:
        lines.append(f"• 🟢 {low_count} LOW priority")
    if not alerts:
        lines.append(f"• ✅ No alerts generated")
    lines.append("")

    # Summary line
    lines.append(f"━━━━━━━━━━━━━━━━━━━━")
    status_emoji = "🟢" if not high_alerts else "🔴"
    lines.append(f"{status_emoji} *Status: {'Elevated' if high_alerts else 'Normal'}*")
    if high_alerts:
        lines.append(f"⚠️ {len(high_alerts)} high-priority item(s) require attention")

    report_text = "\n".join(lines)

    # Ensure under 4096 chars (Telegram message limit)
    if len(report_text) > 4096:
        report_text = report_text[:4093] + "..."

    return report_text


# ── CLI ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="SCS Daily Monitoring Report")
    parser.add_argument("--date", help="Report for specific date (YYYY-MM-DD)")
    parser.add_argument("--last", type=int, default=24,
                        help="Hours to look back (default: 24)")
    args = parser.parse_args()

    hours = args.last
    if args.date:
        # For date mode, use 48h to catch all entries for that date
        hours = 48

    report = generate_report(hours=hours, date_filter=args.date)
    print(report)
