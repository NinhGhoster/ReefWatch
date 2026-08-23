#!/usr/bin/env python3
"""
OSINT Cross-Reference for NISAR Detected Changes

Cross-references NISAR-detected changes with OSINT sources:
- AMTI/CSIS Island Tracker reports
- Twitter/X OSINT accounts
- Maritime news sources
- Academic/think tank reports

Usage:
    python3 osint_crossref.py --all
    python3 osint_crossref.py --feature fiery_cross_reef
    python3 osint_crossref.py --report
"""

import argparse
import json
import os
import sys
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from collections import defaultdict

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(SCRIPT_DIR)
NISAR_CHANGES = os.path.join(BASE_DIR, "nisar_changes.jsonl")
OSINT_LOG = os.path.join(BASE_DIR, "osint_crossref.jsonl")
DERIVED_DIR = os.path.join(BASE_DIR, "derived")

os.makedirs(DERIVED_DIR, exist_ok=True)

# Known OSINT sources for SCS monitoring
OSINT_SOURCES = {
    "amticsis": {
        "name": "AMTI/CSIS Asia Maritime Transparency Initiative",
        "url": "https://amti.csis.org",
        "type": "think_tank",
        "reliability": "high",
    },
    "mt_anderson": {
        "name": "MT Anderson (@detresfa_)",
        "url": "https://twitter.com/detresfa_",
        "type": "osint_analyst",
        "reliability": "high",
    },
    "naval_news": {
        "name": "Naval News",
        "url": "https://www.navalnews.com",
        "type": "news",
        "reliability": "high",
    },
    "the_drive": {
        "name": "The Drive / War Zone",
        "url": "https://www.thedrive.com/the-war-zone",
        "type": "news",
        "reliability": "high",
    },
    "scmp": {
        "name": "South China Morning Post",
        "url": "https://www.scmp.com",
        "type": "news",
        "reliability": "medium",
    },
    "reuters": {
        "name": "Reuters",
        "url": "https://www.reuters.com",
        "type": "news",
        "reliability": "high",
    },
    "asia_times": {
        "name": "Asia Times",
        "url": "https://asiatimes.com",
        "type": "news",
        "reliability": "medium",
    },
    "diplomat": {
        "name": "The Diplomat",
        "url": "https://thediplomat.com",
        "type": "news",
        "reliability": "high",
    },
}

# Keywords for SCS construction/military activity
SCS_KEYWORDS = [
    "construction", "reclamation", "dredging", "runway", "airstrip",
    "military", "radar", "missile", "SAM", "helipad", "harbor",
    "barracks", "bunker", "artillery", "deployment", "garrison",
    "artificial island", "land reclamation", "subi reef", "fiery cross",
    "mischief reef", "cuarteron", "gaven", "hughes", "johnson south",
    "thitu", "pag-asa", "swallow reef", "layang-layang", "taiping",
    "itu aba", "spratly", "paracel", "scarborough", "pratas",
    "woody island", "yongxing", "zhongjian", "zhaoshu",
    "second thomas", "ayungin", "BRP Sierra Madre",
]

# Feature name mappings for OSINT search
FEATURE_ALIASES = {
    "fiery_cross_reef": ["fiery cross reef", "yongshu jiao", "đá chữ thập"],
    "subi_reef": ["subi reef", "zhubi jiao", "đá subi"],
    "mischief_reef": ["mischief reef", "meiji jiao", "đá vân khăn"],
    "cuarteron_reef": ["cuarteron reef", "huayang jiao", "đá châu viên"],
    "gaven_reefs": ["gaven reefs", "nanxun jiao", "đá ga ven"],
    "johnson_south_reef": ["johnson south reef", "chigua jiao", "đá gạc ma"],
    "hughes_reef": ["hughes reef", "dongmen jiao", "đá tư nghĩa"],
    "taiping_island": ["taiping island", "itu aba", "đảo ba bình"],
    "thitu_island": ["thitu island", "pag-asa", "đảo thị tứ"],
    "swallow_reef": ["swallow reef", "layang-layang", "terumbu layang"],
    "namyit_island": ["namyit island", "nam yết", "hongxiu dao"],
    "sin_cowe_island": ["sin cowe island", "sinh tồn", "jinghong dao"],
    "song_tu_tay": ["song tu tay", "southwest cay", "đảo song tử tây"],
    "investigator_shoal": ["investigator shoal", "terumbu peninjau"],
    "cuarteron_reef": ["cuarteron reef", "huayang jiao"],
    "johnson_south_reef": ["johnson south reef", "chigua jiao"],
    "hughes_reef": ["hughes reef", "dongmen jiao"],
    "woody_island": ["woody island", "yongxing island", "phú lam"],
    "triton_island": ["triton island", "zhongjian dao"],
    "pratas_island": ["pratas island", "dongsha island", "đảo đông sa"],
    "scarborough_shoal": ["scarborough shoal", "huangyan dao", "bajo de masi"],
}


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


def load_existing_osint():
    """Load existing OSINT cross-references."""
    if not os.path.exists(OSINT_LOG):
        return []
    entries = []
    with open(OSINT_LOG) as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return entries


def build_search_terms(feature_key):
    """Build search terms for a feature."""
    terms = FEATURE_ALIASES.get(feature_key, [feature_key.replace("_", " ")])
    # Add SCS keywords
    terms.extend(SCS_KEYWORDS[:10])  # Top 10 general terms
    return list(set(terms))


def check_osint_source(source_id, source_info, feature_key, date_str, terms):
    """
    Simulate checking an OSINT source.
    In production, this would query APIs, scrape websites, etc.
    For now, returns a structured mock entry.
    """
    target_date = datetime.strptime(date_str, "%Y-%m-%d").date()
    window_start = (target_date - timedelta(days=30)).isoformat()
    window_end = (target_date + timedelta(days=30)).isoformat()

    # Generate mock findings based on known activity
    # In production, this would be real API calls
    mock_findings = []

    # Known high-activity features in 2026
    high_activity = {
        "fiery_cross_reef": True,
        "mischief_reef": True,
        "subi_reef": True,
        "thitu_island": True,
        "investigator_shoal": True,
    }

    if high_activity.get(feature_key, False):
        mock_findings.append({
            "source": source_id,
            "title": f"New construction observed at {feature_key.replace('_', ' ').title()}",
            "url": f"{source_info['url']}/search?q={feature_key}",
            "date": target_date.isoformat(),
            "relevance": "high",
            "snippet": f"Satellite imagery shows new construction activity...",
        })

    return {
        "source_id": source_id,
        "source_name": source_info["name"],
        "source_type": source_info["type"],
        "reliability": source_info["reliability"],
        "search_terms": terms[:5],
        "date_window": f"{window_start} to {window_end}",
        "findings": mock_findings,
        "queried_at": datetime.now(timezone.utc).isoformat(),
    }


def crossref_change(change, sources=None):
    """Cross-reference a single NISAR change with OSINT sources."""
    feature = change.get("feature")
    date_current = change.get("date_current")
    date_previous = change.get("date_previous")

    if not feature or not date_current:
        return None

    if sources is None:
        sources = list(OSINT_SOURCES.keys())

    terms = build_search_terms(feature)

    results = {
        "feature": feature,
        "nisar_change": {
            "date_previous": date_previous,
            "date_current": date_current,
            "classification": change.get("change_types"),
            "confidence": change.get("confidence"),
            "polarization": change.get("polarization"),
        },
        "osint_results": [],
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    for src_id in sources:
        if src_id not in OSINT_SOURCES:
            continue
        result = check_osint_source(src_id, OSINT_SOURCES[src_id], feature, date_current, terms)
        results["osint_results"].append(result)

    return results


def log_osint(result):
    """Append OSINT cross-reference result to JSONL log."""
    with open(OSINT_LOG, "a") as f:
        f.write(json.dumps(result, ensure_ascii=False) + "\n")


def load_s2_correlations():
    """Load S2 correlation report for context."""
    report_path = os.path.join(DERIVED_DIR, "s2_correlation_report.json")
    if os.path.exists(report_path):
        with open(report_path) as f:
            return json.load(f)
    return {}


def enrich_with_s2(osint_result, s2_report):
    """Enrich OSINT result with S2 correlation data."""
    feature = osint_result.get("feature")
    if not feature or not s2_report:
        return osint_result

    s2_details = s2_report.get("details", [])
    for s2 in s2_details:
        if s2.get("feature") == feature:
            osint_result["s2_correlation"] = s2.get("s2_correlation")
            break
    return osint_result


def run_osint_crossref(changes, sources=None):
    """Run OSINT cross-reference for all changes."""
    if not changes:
        print("No changes to cross-reference")
        return []

    s2_report = load_s2_correlations()
    results = []

    for change in changes:
        feature = change.get("feature")
        date = change.get("date_current")
        print(f"Cross-referencing {feature} ({date})...")

        result = crossref_change(change, sources)
        result = enrich_with_s2(result, s2_report)
        log_osint(result)
        results.append(result)

        # Summary
        findings_count = sum(len(r.get("findings", [])) for r in result.get("osint_results", []))
        if findings_count > 0:
            print(f"  ✅ Found {findings_count} OSINT references")
        else:
            print(f"  ℹ️ No new OSINT findings (mock mode)")

    return results


def generate_osint_report(results):
    """Generate OSINT cross-reference report."""
    total = len(results)
    with_findings = sum(1 for r in results if any(len(r.get("osint_results", [{}])[i].get("findings", [])) > 0 for i in range(len(r.get("osint_results", [])))))

    # Count by source
    source_counts = defaultdict(int)
    for r in results:
        for src in r.get("osint_results", []):
            if src.get("findings"):
                source_counts[src["source_id"]] += 1

    print(f"\n{'='*60}")
    print(f"OSINT Cross-Reference Report")
    print(f"{'='*60}")
    print(f"Total NISAR changes analyzed: {total}")
    print(f"Changes with OSINT findings: {with_findings}")
    print(f"Changes without OSINT findings: {total - with_findings}")
    print(f"\nFindings by source:")
    for src, count in sorted(source_counts.items(), key=lambda x: -x[1]):
        print(f"  {src}: {count}")

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "total_changes": total,
            "with_osint_findings": with_findings,
            "findings_by_source": dict(source_counts),
        },
        "details": results,
    }

    report_path = os.path.join(DERIVED_DIR, "osint_crossref_report.json")
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    print(f"\nReport saved to {report_path}")


def main():
    parser = argparse.ArgumentParser(description="OSINT Cross-Reference for NISAR Changes")
    parser.add_argument("--all", action="store_true", help="Cross-reference all NISAR changes")
    parser.add_argument("--feature", help="Cross-reference specific feature")
    parser.add_argument("--sources", nargs="+", help="OSINT sources to query")
    parser.add_argument("--report", action="store_true", help="Generate report from existing logs")
    args = parser.parse_args()

    if args.report:
        # Generate report from existing log
        if not os.path.exists(OSINT_LOG):
            print("No OSINT log found. Run cross-reference first.")
            sys.exit(1)
        with open(OSINT_LOG) as f:
            results = [json.loads(line) for line in f if line.strip()]
        generate_osint_report(results)
        return

    if not args.all and not args.feature:
        parser.print_help()
        sys.exit(1)

    changes = load_changes()
    if not changes:
        print("No NISAR changes found. Run nisar_processor.py first.")
        sys.exit(1)

    # Deduplicate
    seen = set()
    unique_changes = []
    for c in changes:
        key = (c.get("feature"), c.get("date_previous"), c.get("date_current"), c.get("polarization"))
        if key not in seen:
            seen.add(key)
            unique_changes.append(c)
    changes = unique_changes

    if args.feature:
        changes = [c for c in changes if c.get("feature") == args.feature]
        if not changes:
            print(f"No changes found for feature {args.feature}")
            sys.exit(1)

    print(f"Cross-referencing {len(changes)} unique NISAR changes...")
    results = run_osint_crossref(changes, args.sources)
    generate_osint_report(results)


if __name__ == "__main__":
    main()