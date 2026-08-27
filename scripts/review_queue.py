#!/usr/bin/env python3
"""Analyst Review Queue CLI for ReefWatch.

Provides an interactive CLI for human analysts to review candidate change detections,
confirm or dismiss observations, add assessments, and manage the review workflow.

Decisions and analyst notes are recorded to analyst_notes.jsonl, and the normalized
MVP snapshot is automatically refreshed.

Usage:
    python3 scripts/review_queue.py --list
    python3 scripts/review_queue.py --view change:fiery_cross_reef:2026-06-25:2026-06-27
    python3 scripts/review_queue.py --confirm change:... --note "Confirmed runway extension"
    python3 scripts/review_queue.py --dismiss change:... --note "Cloud artifact"
    python3 scripts/review_queue.py --defer change:... --note "Need clear optical pass"
    python3 scripts/review_queue.py --interactive
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent.parent
DERIVED_DIR = BASE_DIR / "derived"
REVIEW_QUEUE_FILE = DERIVED_DIR / "review_queue.json"
ANALYST_NOTES_LOG = BASE_DIR / "analyst_notes.jsonl"
S2_REPORT_FILE = DERIVED_DIR / "s2_correlation_report.json"
OSINT_REPORT_FILE = DERIVED_DIR / "osint_crossref_report.json"

if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_review_queue() -> list[dict[str, Any]]:
    if not REVIEW_QUEUE_FILE.exists():
        return []
    try:
        with open(REVIEW_QUEUE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("items", [])
    except Exception as e:
        print(f"Error loading review queue: {e}", file=sys.stderr)
        return []


def load_all_notes() -> list[dict[str, Any]]:
    if not ANALYST_NOTES_LOG.exists():
        return []
    notes = []
    with open(ANALYST_NOTES_LOG, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    notes.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return notes


def append_analyst_note(
    change_id: str,
    feature_key: str,
    action: str,
    text: str,
    author: str = "analyst",
) -> dict[str, Any]:
    timestamp = now_iso()
    note_id = f"note:{feature_key}:{timestamp[:10]}:{int(datetime.now(timezone.utc).timestamp())}"
    
    note_entry = {
        "id": note_id,
        "featureId": f"feature:{feature_key}",
        "feature": feature_key,
        "relatedChangeId": change_id,
        "createdAt": timestamp,
        "author": author,
        "kind": action,  # confirmation, dismissal, deferral, assessment
        "reviewStatus": action if action in ("confirmed", "dismissed", "deferred") else "pending",
        "text": text,
        "source": "cli_review_queue",
    }
    
    with open(ANALYST_NOTES_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(note_entry, ensure_ascii=False) + "\n")
    
    return note_entry


def refresh_snapshot():
    """Run export_mvp_snapshot.py to sync derived state."""
    import export_mvp_snapshot
    export_mvp_snapshot.main()


def list_queue():
    items = load_review_queue()
    if not items:
        print("✅ Review queue is clean! No items pending review.")
        return

    print(f"\n📋 ReefWatch Pending Review Queue ({len(items)} items)")
    print("=" * 80)
    print(f"{'#':<3} {'PRI':<4} {'FEATURE':<22} {'CLASSIFICATION':<20} {'CONF':<6} {'CHANGE ID'}")
    print("-" * 80)
    
    for idx, item in enumerate(items, 1):
        pri = f"P{item.get('priority', 3)}"
        name = item.get("featureKey", "")[:21]
        cls_name = item.get("classification", "")[:19]
        conf = f"{item.get('confidence', 0):.0%}" if item.get("confidence") is not None else "N/A"
        cid = item.get("changeId", "")
        print(f"{idx:<3} {pri:<4} {name:<22} {cls_name:<20} {conf:<6} {cid}")
    print("=" * 80)
    print("Use: python3 scripts/review_queue.py --view <change_id> or --interactive\n")


def view_change(change_id: str):
    items = load_review_queue()
    matched = [item for item in items if item.get("changeId") == change_id]
    if not matched:
        # Check if it was already reviewed in derived/changes.jsonl
        changes_file = DERIVED_DIR / "changes.jsonl"
        if changes_file.exists():
            for line in open(changes_file):
                c = json.loads(line)
                if c.get("id") == change_id:
                    matched = [c]
                    break
    
    if not matched:
        print(f"❌ Change not found: {change_id}")
        return

    item = matched[0]
    print(f"\n🔍 Change Details: {change_id}")
    print("=" * 70)
    print(f"Feature:        {item.get('featureName', item.get('featureKey', ''))} ({item.get('featureKey', '')})")
    print(f"Claimant:       {item.get('claimant', 'Unknown')} | Priority: P{item.get('priority', 3)}")
    print(f"Classification: {item.get('classification', 'Unknown')}")
    print(f"Confidence:     {item.get('confidence', 'N/A')}")
    print(f"Detected At:    {item.get('detectedAt', 'N/A')}")
    print(f"Review Status:  {item.get('reviewStatus', 'pending')}")

    metrics = item.get("metrics", {})
    if metrics:
        print("\n📊 Detection Metrics:")
        for k, v in metrics.items():
            if v is not None:
                print(f"   • {k}: {v}")

    before_scene = item.get("beforeScene", {})
    after_scene = item.get("afterScene", {})
    print("\n🛰️ Scene Evidence:")
    print(f"   Before: {before_scene.get('capturedAt', 'N/A')} ({before_scene.get('source', 'N/A')}) -> {before_scene.get('path', 'N/A')}")
    print(f"   After:  {after_scene.get('capturedAt', 'N/A')} ({after_scene.get('source', 'N/A')}) -> {after_scene.get('path', 'N/A')}")

    # Prior analyst notes
    all_notes = load_all_notes()
    change_notes = [n for n in all_notes if n.get("relatedChangeId") == change_id]
    if change_notes:
        print("\n📝 Analyst History:")
        for n in change_notes:
            print(f"   [{n.get('createdAt')}] ({n.get('author')}) [{n.get('kind')}]: {n.get('text')}")
    print("=" * 70 + "\n")


def apply_decision(change_id: str, action: str, note_text: str = "", author: str = "analyst"):
    items = load_review_queue()
    feature_key = "unknown"
    for item in items:
        if item.get("changeId") == change_id:
            feature_key = item.get("featureKey", "unknown")
            break
    
    if feature_key == "unknown":
        # Extract feature from change_id pattern (e.g. change:fiery_cross_reef:...)
        parts = change_id.split(":")
        if len(parts) >= 2:
            feature_key = parts[1]

    note = append_analyst_note(change_id, feature_key, action, note_text, author)
    print(f"✅ Recorded {action.upper()} for {change_id}")
    if note_text:
        print(f"   Note: \"{note_text}\"")

    refresh_snapshot()
    print("🔄 Derived snapshot refreshed.")


def run_interactive():
    items = load_review_queue()
    if not items:
        print("✅ No pending items to review.")
        return

    print(f"\n🚀 Interactive Review Mode ({len(items)} items)")
    print("Keys: [c]onfirm, [d]ismiss, [w]ait/defer, [a]nnotate, [s]kip, [q]uit\n")

    for idx, item in enumerate(items, 1):
        cid = item.get("changeId")
        print("-" * 70)
        print(f"[{idx}/{len(items)}] P{item.get('priority', 3)} | {item.get('featureName', item.get('featureKey'))}")
        print(f"Classification: {item.get('classification')} | Conf: {item.get('confidence', 'N/A')}")
        metrics = item.get("metrics", {})
        metric_str = ", ".join(f"{k}={v}" for k, v in metrics.items() if v is not None)
        print(f"Metrics: {metric_str}")
        print(f"Before: {item.get('beforeScene', {}).get('capturedAt')} ({item.get('beforeScene', {}).get('source')})")
        print(f"After:  {item.get('afterScene', {}).get('capturedAt')} ({item.get('afterScene', {}).get('source')})")

        try:
            choice = input("\nAction [c/d/w/a/s/q]: ").strip().lower()
        except (KeyboardInterrupt, EOFError):
            print("\nExiting.")
            break

        if choice == "q":
            print("Exiting interactive review.")
            break
        elif choice == "s":
            continue
        elif choice in ("c", "confirm"):
            note = input("Add note (optional): ").strip()
            apply_decision(cid, "confirmed", note or "Analyst confirmed change.")
        elif choice in ("d", "dismiss"):
            note = input("Reason/note (optional): ").strip()
            apply_decision(cid, "dismissed", note or "Analyst dismissed as noise/cloud.")
        elif choice in ("w", "defer", "wait"):
            note = input("Reason/note (optional): ").strip()
            apply_decision(cid, "deferred", note or "Deferred for follow-up imagery.")
        elif choice in ("a", "annotate"):
            note = input("Assessment note: ").strip()
            if note:
                apply_decision(cid, "assessment", note)
        else:
            print("Invalid input, skipping.")

    print("\nReview session complete.")


def main():
    parser = argparse.ArgumentParser(description="ReefWatch Analyst Review Queue")
    parser.add_argument("-l", "--list", action="store_true", help="List all pending review items")
    parser.add_argument("-v", "--view", help="View full details of a specific change ID")
    parser.add_argument("--confirm", help="Confirm a change ID as true detection")
    parser.add_argument("--dismiss", help="Dismiss a change ID as false positive")
    parser.add_argument("--defer", help="Defer a change ID for follow-up")
    parser.add_argument("--annotate", help="Add an assessment note to a change ID")
    parser.add_argument("-n", "--note", default="", help="Note text to attach with decision")
    parser.add_argument("-i", "--interactive", action="store_true", help="Run interactive review triage")

    args = parser.parse_args()

    if args.list:
        list_queue()
    elif args.view:
        view_change(args.view)
    elif args.confirm:
        apply_decision(args.confirm, "confirmed", args.note or "Confirmed by analyst")
    elif args.dismiss:
        apply_decision(args.dismiss, "dismissed", args.note or "Dismissed by analyst")
    elif args.defer:
        apply_decision(args.defer, "deferred", args.note or "Deferred by analyst")
    elif args.annotate:
        apply_decision(args.annotate, "assessment", args.note)
    elif args.interactive:
        run_interactive()
    else:
        list_queue()


if __name__ == "__main__":
    main()
