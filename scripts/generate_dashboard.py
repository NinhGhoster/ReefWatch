#!/usr/bin/env python3
"""Generate a standalone interactive HTML analyst dashboard with visual evidence and raw data explorer.

Renders 6 core screens:
1. 📊 Overview & Daily Brief (KPIs, active alerts, optical confirmation rate)
2. 🏝️ Features Registry (77 features, strategic facilities, search/filter)
3. ⚡ Change Review Queue (interactive triage deck)
4. 🔬 Evidence & Telemetry Tracker (Raw optical SSIM matrix, SAR metrics, and audit ledger)
5. 🖼️ Visual Imagery & Diff Viewer (Before vs After optical scenes and diff heatmaps)
6. 🛰️ Source Health (secret-safe operational status of all sensor feeds)

Outputs to derived/dashboard.html (zero external JS/CSS dependencies).

Usage:
    python3 scripts/generate_dashboard.py
    python3 scripts/generate_dashboard.py --open  # Open in default browser
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import webbrowser
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent.parent
DERIVED_DIR = BASE_DIR / "derived"
IMAGERY_DIR = BASE_DIR / "imagery_history"
DASHBOARD_HTML = DERIVED_DIR / "dashboard.html"
ALERTS_LOG = BASE_DIR / "alerts_log.jsonl"
NISAR_CHANGES = BASE_DIR / "nisar_changes.jsonl"
S2_LOG = BASE_DIR / "s2_correlation.jsonl"
ANALYST_NOTES = BASE_DIR / "analyst_notes.jsonl"

if str(BASE_DIR / "scripts") not in sys.path:
    sys.path.insert(0, str(BASE_DIR / "scripts"))

from cloud_filter import calculate_cloud_cover


def load_json(path: Path) -> Any:
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return rows


def build_image_catalog() -> dict[str, list[dict[str, Any]]]:
    """Catalog all images in imagery_history/ grouped by feature with cloud cover analysis."""
    catalog: dict[str, list[dict[str, Any]]] = {}
    if not IMAGERY_DIR.exists():
        return catalog

    for p in IMAGERY_DIR.glob("*.png"):
        fname = p.name
        # Match pattern: {feature}_sentinel2_{date}.png or {feature}_diff_{date1}_vs_{date2}.png
        if "_sentinel2_" in fname:
            feature_key = fname.split("_sentinel2_")[0]
            date_str = fname.split("_sentinel2_")[1].replace(".png", "")
            cloud_pct = calculate_cloud_cover(str(p))
            catalog.setdefault(feature_key, []).append({
                "type": "sentinel2",
                "filename": fname,
                "path": f"../imagery_history/{fname}",
                "date": date_str,
                "label": f"Optical {date_str}",
                "cloudPct": cloud_pct,
                "isCloudy": cloud_pct > 30.0,
            })
        elif "_diff_" in fname:
            feature_key = fname.split("_diff_")[0]
            diff_part = fname.split("_diff_")[1].replace(".png", "")
            catalog.setdefault(feature_key, []).append({
                "type": "diff",
                "filename": fname,
                "path": f"../imagery_history/{fname}",
                "date": diff_part,
                "label": f"Diff Heatmap ({diff_part})",
                "cloudPct": None,
                "isCloudy": False,
            })

    # Sort each feature's images chronologically
    for fkey in catalog:
        catalog[fkey].sort(key=lambda x: x["date"], reverse=True)
    return catalog


def parse_optical_alerts(alerts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Extract structured data rows from alerts_log.jsonl to prove optical calculations."""
    parsed = []
    seen = set()
    for raw in alerts:
        text = raw.get("text", "")
        feature = raw.get("feature", "").replace("_sentinel2", "")
        # Parse SSIM, Pixel Δ, Dates from alert text
        dates = "Unknown"
        ssim = None
        pixel_diff = None
        cls_type = "Structural Change"

        lines = text.split("\n")
        for line in lines:
            line_str = line.strip()
            if "📅" in line_str:
                dates = line_str.replace("📅", "").strip()
            elif "SSIM:" in line_str:
                parts = line_str.split("|")
                for p in parts:
                    if "SSIM:" in p:
                        try:
                            ssim = float(p.split("SSIM:")[1].strip())
                        except ValueError:
                            pass
                    if "Pixel Δ:" in p:
                        try:
                            pixel_diff = float(p.split("Pixel Δ:")[1].replace("%", "").strip())
                        except ValueError:
                            pass
            elif "New Construction" in line_str:
                cls_type = "New Construction"
            elif "Major Structural Change" in line_str:
                cls_type = "Major Structural Change"

        dedup_key = (feature, dates, ssim)
        if dedup_key not in seen:
            seen.add(dedup_key)
            parsed.append({
                "feature": feature,
                "timestamp": raw.get("timestamp"),
                "dates": dates,
                "ssim": ssim,
                "pixelDiffPct": pixel_diff,
                "classification": cls_type,
                "severity": raw.get("severity", "🔴"),
            })
    return parsed


def build_dashboard_html() -> str:
    # Load all derived datasets
    overview = load_json(DERIVED_DIR / "overview.json")
    review_queue = load_json(DERIVED_DIR / "review_queue.json")
    source_health = load_json(DERIVED_DIR / "source_health.json")
    s2_report = load_json(DERIVED_DIR / "s2_correlation_report.json")
    osint_report = load_json(DERIVED_DIR / "osint_crossref_report.json")

    features = load_jsonl(DERIVED_DIR / "features.jsonl")
    feature_status = load_jsonl(DERIVED_DIR / "feature_status.jsonl")
    scenes = load_jsonl(DERIVED_DIR / "scenes.jsonl")
    changes = load_jsonl(DERIVED_DIR / "changes.jsonl")
    traffic = load_jsonl(DERIVED_DIR / "traffic.jsonl")
    notes = load_jsonl(DERIVED_DIR / "notes.jsonl")

    # Load raw telemetry / proof datasets
    raw_alerts = load_jsonl(ALERTS_LOG)
    optical_tracking = parse_optical_alerts(raw_alerts)
    raw_nisar = load_jsonl(NISAR_CHANGES)
    raw_notes = load_jsonl(ANALYST_NOTES)
    image_catalog = build_image_catalog()

    # Embed data as JSON payload
    data_payload = {
        "overview": overview,
        "reviewQueue": review_queue.get("items", []),
        "sourceHealth": source_health,
        "s2Report": s2_report,
        "osintReport": osint_report,
        "features": features,
        "featureStatus": feature_status,
        "scenes": scenes,
        "changes": changes,
        "traffic": traffic,
        "notes": notes,
        "rawNotes": raw_notes,
        "opticalTracking": optical_tracking,
        "rawNisar": raw_nisar,
        "imageCatalog": image_catalog,
        "totalImages": sum(len(v) for v in image_catalog.values()),
        "generatedAt": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
    }

    html = f"""<!DOCTYPE html>
<html lang="en" class="dark">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>ReefWatch — South China Sea Monitoring & Evidence Intelligence</title>
  <style>
    :root {{
      --bg: #0b0f19;
      --card-bg: #111827;
      --card-border: #1f2937;
      --card-hover: #1e293b;
      --text: #f3f4f6;
      --text-muted: #9ca3af;
      --primary: #3b82f6;
      --accent: #06b6d4;
      --success: #10b981;
      --warning: #f59e0b;
      --danger: #ef4444;
    }}
    * {{ box-sizing: border-box; margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; }}
    body {{ background: var(--bg); color: var(--text); min-height: 100vh; display: flex; flex-direction: column; }}
    
    /* Layout */
    header {{ background: #0f172a; border-bottom: 1px solid #1e293b; padding: 12px 24px; display: flex; justify-content: space-between; align-items: center; position: sticky; top: 0; z-index: 50; }}
    .logo {{ display: flex; align-items: center; gap: 10px; font-weight: 700; font-size: 1.2rem; color: #fff; }}
    .logo-badge {{ background: linear-gradient(135deg, #2563eb, #06b6d4); color: white; padding: 3px 8px; border-radius: 6px; font-size: 0.75rem; font-weight: 600; letter-spacing: 0.5px; }}
    nav {{ display: flex; gap: 6px; flex-wrap: wrap; }}
    .nav-btn {{ background: transparent; border: 1px solid transparent; color: var(--text-muted); padding: 8px 14px; border-radius: 8px; font-size: 0.85rem; font-weight: 500; cursor: pointer; transition: all 0.15s ease; display: flex; align-items: center; gap: 6px; }}
    .nav-btn:hover {{ background: #1e293b; color: #fff; }}
    .nav-btn.active {{ background: #1e293b; color: #60a5fa; border-color: #3b82f6; font-weight: 600; }}
    .badge {{ background: var(--primary); color: white; border-radius: 9999px; padding: 1px 7px; font-size: 0.75rem; font-weight: 700; }}
    
    main {{ flex: 1; padding: 24px; max-width: 1440px; margin: 0 auto; width: 100%; }}
    .screen {{ display: none; }}
    .screen.active {{ display: block; }}
    
    /* Typography & Utilities */
    h1 {{ font-size: 1.5rem; font-weight: 700; margin-bottom: 4px; }}
    h2 {{ font-size: 1.25rem; font-weight: 600; margin-bottom: 16px; }}
    h3 {{ font-size: 1.05rem; font-weight: 600; margin-bottom: 10px; }}
    .subtitle {{ color: var(--text-muted); font-size: 0.9rem; margin-bottom: 20px; }}
    
    /* Stats Row */
    .stats-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 16px; margin-bottom: 24px; }}
    .stat-card {{ background: var(--card-bg); border: 1px solid var(--card-border); padding: 16px; border-radius: 10px; cursor: pointer; transition: all 0.15s; }}
    .stat-card:hover {{ border-color: var(--primary); transform: translateY(-2px); }}
    .stat-card .label {{ color: var(--text-muted); font-size: 0.8rem; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px; }}
    .stat-card .value {{ font-size: 1.8rem; font-weight: 700; margin: 4px 0; color: #fff; }}
    .stat-card .subtext {{ font-size: 0.8rem; color: var(--text-muted); }}
    
    /* Cards & Containers */
    .card {{ background: var(--card-bg); border: 1px solid var(--card-border); border-radius: 10px; padding: 20px; margin-bottom: 20px; }}
    .grid-2 {{ display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }}
    @media (max-width: 900px) {{ .grid-2 {{ grid-template-columns: 1fr; }} }}
    
    /* Filters */
    .filter-bar {{ display: flex; flex-wrap: wrap; gap: 10px; margin-bottom: 16px; align-items: center; background: #0f172a; padding: 12px 16px; border-radius: 8px; border: 1px solid #1e293b; }}
    .search-input {{ background: #1e293b; border: 1px solid #334155; color: #fff; padding: 8px 12px; border-radius: 6px; font-size: 0.9rem; min-width: 240px; outline: none; }}
    .search-input:focus {{ border-color: var(--primary); }}
    .filter-select {{ background: #1e293b; border: 1px solid #334155; color: #fff; padding: 8px 12px; border-radius: 6px; font-size: 0.85rem; outline: none; cursor: pointer; }}
    .filter-chip {{ background: #1e293b; border: 1px solid #334155; color: var(--text-muted); padding: 6px 12px; border-radius: 20px; font-size: 0.8rem; cursor: pointer; transition: all 0.15s; }}
    .filter-chip.active {{ background: #2563eb; color: #fff; border-color: #3b82f6; }}
    
    /* Tables */
    .table-container {{ overflow-x: auto; background: var(--card-bg); border: 1px solid var(--card-border); border-radius: 10px; margin-bottom: 20px; }}
    table {{ width: 100%; border-collapse: collapse; text-align: left; font-size: 0.88rem; }}
    th {{ background: #172033; padding: 12px 16px; font-weight: 600; color: #cbd5e1; border-bottom: 1px solid var(--card-border); text-transform: uppercase; font-size: 0.75rem; letter-spacing: 0.5px; }}
    td {{ padding: 12px 16px; border-bottom: 1px solid #1e293b; color: #e2e8f0; vertical-align: middle; }}
    tr:hover td {{ background: var(--card-hover); }}
    
    /* Badges & Tags */
    .priority-badge {{ padding: 2px 8px; border-radius: 4px; font-size: 0.75rem; font-weight: 700; display: inline-block; }}
    .priority-1 {{ background: rgba(239, 68, 68, 0.2); color: #f87171; border: 1px solid rgba(239, 68, 68, 0.4); }}
    .priority-2 {{ background: rgba(245, 158, 11, 0.2); color: #fbbf24; border: 1px solid rgba(245, 158, 11, 0.4); }}
    .priority-3 {{ background: rgba(107, 114, 128, 0.2); color: #9ca3af; border: 1px solid rgba(107, 114, 128, 0.4); }}
    
    .tag {{ background: #1e293b; color: #94a3b8; border: 1px solid #334155; padding: 2px 6px; border-radius: 4px; font-size: 0.75rem; margin-right: 4px; }}
    .tag-airport {{ background: rgba(59, 130, 246, 0.2); color: #93c5fd; border-color: rgba(59, 130, 246, 0.4); }}
    .tag-sam {{ background: rgba(239, 68, 68, 0.2); color: #fca5a5; border-color: rgba(239, 68, 68, 0.4); }}
    .tag-radar {{ background: rgba(168, 85, 247, 0.2); color: #d8b4fe; border-color: rgba(168, 85, 247, 0.4); }}
    .tag-port {{ background: rgba(6, 182, 212, 0.2); color: #67e8f9; border-color: rgba(6, 182, 212, 0.4); }}
    
    .status-pill {{ display: inline-flex; align-items: center; gap: 6px; font-size: 0.8rem; font-weight: 600; padding: 3px 8px; border-radius: 6px; }}
    .status-confirmed {{ background: rgba(16, 185, 129, 0.2); color: #34d399; border: 1px solid rgba(16, 185, 129, 0.4); }}
    .status-deferred {{ background: rgba(245, 158, 11, 0.2); color: #fbbf24; border: 1px solid rgba(245, 158, 11, 0.4); }}
    .status-dismissed {{ background: rgba(107, 114, 128, 0.2); color: #9ca3af; border: 1px solid rgba(107, 114, 128, 0.4); }}
    .status-pending {{ background: rgba(239, 68, 68, 0.2); color: #f87171; border: 1px solid rgba(239, 68, 68, 0.4); }}
    
    /* Sub Tabs inside Evidence View */
    .sub-tabs {{ display: flex; gap: 10px; margin-bottom: 16px; border-bottom: 1px solid #1e293b; padding-bottom: 10px; }}
    .sub-tab-btn {{ background: #1e293b; border: 1px solid #334155; color: #cbd5e1; padding: 8px 16px; border-radius: 6px; font-size: 0.85rem; font-weight: 600; cursor: pointer; }}
    .sub-tab-btn.active {{ background: #2563eb; color: #fff; border-color: #3b82f6; }}
    
    /* Visual Comparison Cards */
    .gallery-grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 16px; }}
    .image-card {{ background: #0f172a; border: 1px solid #1e293b; border-radius: 8px; overflow: hidden; transition: all 0.15s; }}
    .image-card:hover {{ border-color: #3b82f6; }}
    .image-preview {{ width: 100%; height: 200px; object-fit: cover; background: #111827; cursor: pointer; display: block; }}
    .image-caption {{ padding: 12px; font-size: 0.85rem; }}
    
    /* Metric pill */
    .metric-chip {{ background: #1e293b; padding: 2px 8px; border-radius: 4px; font-size: 0.75rem; font-family: monospace; color: #60a5fa; }}
    
    /* Modal */
    .modal-overlay {{ display: none; position: fixed; inset: 0; background: rgba(0,0,0,0.8); z-index: 100; backdrop-filter: blur(4px); justify-content: center; align-items: center; padding: 20px; }}
    .modal-overlay.open {{ display: flex; }}
    .modal-content {{ background: var(--card-bg); border: 1px solid #334155; border-radius: 12px; width: 100%; max-width: 900px; max-height: 90vh; overflow-y: auto; padding: 24px; position: relative; }}
    .modal-close {{ position: absolute; top: 16px; right: 16px; background: transparent; border: none; color: #94a3b8; font-size: 1.5rem; cursor: pointer; }}
    
    /* Lightbox for full images */
    .lightbox-img {{ max-width: 100%; max-height: 70vh; object-fit: contain; margin: 0 auto; display: block; border-radius: 8px; }}
  </style>
</head>
<body>

  <header>
    <div class="logo">
      <span>ReefWatch</span>
      <span class="logo-badge">OSINT SCS INTELLIGENCE</span>
    </div>
    <nav>
      <button class="nav-btn active" onclick="switchScreen('overview')">📊 Overview</button>
      <button class="nav-btn" onclick="switchScreen('evidence')">🔬 Evidence & Proof Data <span class="badge" id="nav-evidence-badge">39</span></button>
      <button class="nav-btn" onclick="switchScreen('gallery')">🖼️ Imagery & Diff Maps <span class="badge" style="background:#059669;" id="nav-images-badge">1090</span></button>
      <button class="nav-btn" onclick="switchScreen('features')">🏝️ Features (77)</button>
      <button class="nav-btn" onclick="switchScreen('queue')">⚡ Triage Log</button>
      <button class="nav-btn" onclick="switchScreen('health')">🛰️ Source Health</button>
    </nav>
  </header>

  <main>
    <!-- SCREEN 1: OVERVIEW -->
    <section id="screen-overview" class="screen active">
      <h1>Intelligence Overview & Daily Brief</h1>
      <p class="subtitle" id="overview-timestamp">Operational situational brief</p>

      <div class="stats-grid">
        <div class="stat-card" onclick="switchScreen('features')">
          <div class="label">Monitored Features</div>
          <div class="value" id="stat-features">77</div>
          <div class="subtext">5 Claimant Nations →</div>
        </div>
        <div class="stat-card" onclick="switchScreen('evidence')">
          <div class="label">Optical Change Detections</div>
          <div class="value" id="stat-optical" style="color: var(--danger);">39</div>
          <div class="subtext">SSIM & Pixel Δ Proof Data →</div>
        </div>
        <div class="stat-card" onclick="switchScreen('gallery')">
          <div class="label">Satellite Images & Diffs</div>
          <div class="value" id="stat-images" style="color: #60a5fa;">1,090</div>
          <div class="subtext">Optical passes & difference masks →</div>
        </div>
        <div class="stat-card" onclick="switchScreen('evidence', 'tab-notes')">
          <div class="label">Analyst Audit Records</div>
          <div class="value" id="stat-notes" style="color: var(--success);">10</div>
          <div class="subtext">6 Confirmed, 4 Deferred →</div>
        </div>
      </div>

      <div class="grid-2">
        <div class="card">
          <h3>🎯 High-Confidence Activity (Multi-Sensor Confirmed)</h3>
          <p style="font-size: 0.85rem; color: var(--text-muted); margin-bottom: 12px;">SAR Backscatter Surge verified with Sentinel-2 10m Optical Passes</p>
          <div id="overview-confirmed-list" style="display: flex; flex-direction: column; gap: 10px;"></div>
        </div>

        <div class="card">
          <h3>🛰️ Verification Ratios & Sensor Breakdown</h3>
          <div style="background: #0f172a; padding: 14px; border-radius: 8px; border: 1px solid #1e293b; margin-bottom: 12px;">
            <div style="display: flex; justify-content: space-between; font-weight: 600; margin-bottom: 6px;">
              <span>Sentinel-2 Optical Confirmation Rate</span>
              <span style="color: var(--success);" id="s2-confirm-rate">81.8%</span>
            </div>
            <div style="font-size: 0.85rem; color: var(--text-muted);">9 of 11 NISAR SAR detections independently corroborated with 10m optical imagery.</div>
          </div>

          <div style="background: #0f172a; padding: 14px; border-radius: 8px; border: 1px solid #1e293b; margin-bottom: 12px;">
            <div style="display: flex; justify-content: space-between; font-weight: 600; margin-bottom: 6px;">
              <span>Optical SSIM Change Score Range</span>
              <span style="color: #fbbf24;">0.0223 – 0.4616</span>
            </div>
            <div style="font-size: 0.85rem; color: var(--text-muted);">Significant structural change threshold is SSIM &lt; 0.80.</div>
          </div>

          <button class="btn btn-outline" style="width: 100%;" onclick="switchScreen('evidence')">🔬 Inspect Raw Detection Telemetry & Evidence →</button>
        </div>
      </div>
    </section>

    <!-- SCREEN 2: EVIDENCE & RAW PROOF DATA -->
    <section id="screen-evidence" class="screen">
      <h1>Evidence & Detection Telemetry Tracker</h1>
      <p class="subtitle">Complete proof datasets: Optical SSIM matrix, SAR radar backscatter changes, and analyst decisions</p>

      <div class="sub-tabs">
        <button id="btn-tab-optical" class="sub-tab-btn active" onclick="switchEvidenceTab('tab-optical')">📸 Optical Detection Matrix (39)</button>
        <button id="btn-tab-sar" class="sub-tab-btn" onclick="switchEvidenceTab('tab-sar')">📡 Radar SAR Metrics (NISAR)</button>
        <button id="btn-tab-validation" class="sub-tab-btn" onclick="switchEvidenceTab('tab-validation')">🛰️ Multi-Sensor Correlation (81.8%)</button>
        <button id="btn-tab-notes" class="sub-tab-btn" onclick="switchEvidenceTab('tab-notes')">📝 Analyst Audit Trail (10)</button>
      </div>

      <!-- TAB 1: OPTICAL SSIM -->
      <div id="tab-optical" class="evidence-tab-pane">
        <div class="table-container">
          <table>
            <thead>
              <tr>
                <th>Severity</th>
                <th>Feature</th>
                <th>Comparison Dates</th>
                <th>SSIM Score</th>
                <th>Pixel Δ (%)</th>
                <th>Classification</th>
                <th>Visual Evidence</th>
              </tr>
            </thead>
            <tbody id="optical-table-body"></tbody>
          </table>
        </div>
      </div>

      <!-- TAB 2: SAR METRICS -->
      <div id="tab-sar" class="evidence-tab-pane" style="display: none;">
        <div class="table-container">
          <table>
            <thead>
              <tr>
                <th>Feature</th>
                <th>Pass Dates</th>
                <th>Product</th>
                <th>Pol</th>
                <th>Backscatter Inc. (dB)</th>
                <th>Backscatter Dec. (dB)</th>
                <th>Amplitude Δ (%)</th>
                <th>Coherence Decorr (%)</th>
                <th>Confidence</th>
              </tr>
            </thead>
            <tbody id="sar-table-body"></tbody>
          </table>
        </div>
      </div>

      <!-- TAB 3: VALIDATION MATRIX -->
      <div id="tab-validation" class="evidence-tab-pane" style="display: none;">
        <div class="table-container">
          <table>
            <thead>
              <tr>
                <th>Feature</th>
                <th>SAR Detection Date</th>
                <th>Optical Pass Date</th>
                <th>Optical SSIM</th>
                <th>Mean Pixel Δ</th>
                <th>Correlation Status</th>
              </tr>
            </thead>
            <tbody id="validation-table-body"></tbody>
          </table>
        </div>
      </div>

      <!-- TAB 4: AUDIT NOTES -->
      <div id="tab-notes" class="evidence-tab-pane" style="display: none;">
        <div class="table-container">
          <table>
            <thead>
              <tr>
                <th>Timestamp</th>
                <th>Feature</th>
                <th>Change ID</th>
                <th>Decision</th>
                <th>Analyst Note & Rationale</th>
              </tr>
            </thead>
            <tbody id="notes-table-body"></tbody>
          </table>
        </div>
      </div>
    </section>

    <!-- SCREEN 3: VISUAL IMAGERY & DIFF VIEWER -->
    <section id="screen-gallery" class="screen">
      <h1>Visual Imagery & Difference Heatmaps</h1>
      <div class="filter-bar">
        <input type="text" id="gallery-search" class="search-input" placeholder="🔍 Filter images by feature name..." oninput="renderImageGallery()">
        <select id="gallery-type-filter" class="filter-select" onchange="renderImageGallery()">
          <option value="all">All Image Types (Diff Maps + Optical)</option>
          <option value="diff">Difference Heatmaps Only</option>
          <option value="sentinel2">Sentinel-2 Optical Passes Only</option>
        </select>
        <select id="gallery-cloud-filter" class="filter-select" onchange="renderImageGallery()">
          <option value="all">☁️ All Cloud Levels</option>
          <option value="clear">☀️ Clear Only (&lt; 20% Cloud)</option>
          <option value="moderate">⛅ Low-to-Moderate (&lt; 35% Cloud)</option>
          <option value="obscured">☁️ Cloud Obscured (&gt; 35% Cloud)</option>
        </select>
      </div>

      <!-- HEATMAP INTERPRETATION & COLOR SCALE GUIDE -->
      <div style="background: #0f172a; border: 1px solid #1e293b; border-radius: 8px; padding: 14px 18px; margin-bottom: 16px;">
        <div style="font-weight: 700; font-size: 0.9rem; margin-bottom: 8px; display: flex; align-items: center; gap: 8px;">
          <span>🎨 How to Read Difference Heatmaps (What the Colors Mean):</span>
        </div>
        <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 12px; font-size: 0.82rem;">
          <div style="display: flex; align-items: center; gap: 8px;">
            <span style="display:inline-block; width: 14px; height: 14px; background: #ff1e1e; border-radius: 3px; box-shadow: 0 0 6px rgba(255,30,30,0.6);"></span>
            <span><strong>Red / Crimson (&Delta; &ge; 90)</strong>: Major New Construction, Runway Paving, Land Reclamation</span>
          </div>
          <div style="display: flex; align-items: center; gap: 8px;">
            <span style="display:inline-block; width: 14px; height: 14px; background: #ffd700; border-radius: 3px; box-shadow: 0 0 6px rgba(255,215,0,0.5);"></span>
            <span><strong>Yellow / Amber (50 &le; &Delta; &lt; 90)</strong>: Moderate Ground Alteration, Harbor/Seawall Shift</span>
          </div>
          <div style="display: flex; align-items: center; gap: 8px;">
            <span style="display:inline-block; width: 14px; height: 14px; background: #00beff; border-radius: 3px; box-shadow: 0 0 6px rgba(0,190,255,0.5);"></span>
            <span><strong>Cyan / Blue (22 &le; &Delta; &lt; 50)</strong>: Minor Surface Shift, Vegetation / Sand Motion</span>
          </div>
          <div style="display: flex; align-items: center; gap: 8px;">
            <span style="display:inline-block; width: 14px; height: 14px; background: #1e293b; border: 1px solid #475569; border-radius: 3px;"></span>
            <span><strong>Dark / Muted (&Delta; &lt; 22)</strong>: Unchanged Baseline (Reef, Deep Water, Stable Ground)</span>
          </div>
        </div>
      </div>

      <div class="gallery-grid" id="gallery-grid"></div>
    </section>

    <!-- SCREEN 4: FEATURE REGISTRY -->
    <section id="screen-features" class="screen">
      <h1>Monitored South China Sea Features</h1>
      <p class="subtitle">Canonical registry of 77 reefs, islands, cays, and platforms</p>

      <div class="filter-bar">
        <input type="text" id="feature-search" class="search-input" placeholder="🔍 Search features by name or country..." oninput="renderFeaturesTable()">
        <select id="group-filter" class="filter-select" onchange="renderFeaturesTable()">
          <option value="all">All Groups (77)</option>
          <option value="spratly">Spratly Islands</option>
          <option value="paracel">Paracel Islands</option>
        </select>
        <select id="claimant-filter" class="filter-select" onchange="renderFeaturesTable()">
          <option value="all">All Claimants</option>
          <option value="China">China</option>
          <option value="Vietnam">Vietnam</option>
          <option value="Philippines">Philippines</option>
          <option value="Malaysia">Malaysia</option>
          <option value="Taiwan">Taiwan</option>
        </select>
        <select id="priority-filter" class="filter-select" onchange="renderFeaturesTable()">
          <option value="all">All Priorities</option>
          <option value="1">Priority 1 (Airstrips)</option>
          <option value="2">Priority 2 (Helipads/Harbors)</option>
          <option value="3">Priority 3 (Reefs/DK1)</option>
        </select>
      </div>

      <div class="table-container">
        <table>
          <thead>
            <tr>
              <th>Priority</th>
              <th>Feature Name</th>
              <th>Group</th>
              <th>Claimant</th>
              <th>Strategic Facilities</th>
              <th>Latest Imagery</th>
              <th>Review Status</th>
              <th>Scenes</th>
            </tr>
          </thead>
          <tbody id="features-table-body"></tbody>
        </table>
      </div>
    </section>

    <!-- SCREEN 5: REVIEW / TRIAGE LOG -->
    <section id="screen-queue" class="screen">
      <h1>Analyst Triage & Decision Ledger</h1>
      <p class="subtitle">Chronological record of triaged change detections and analyst evaluations</p>

      <div class="triage-deck" id="triage-deck"></div>
    </section>

    <!-- SCREEN 6: SOURCE HEALTH -->
    <section id="screen-health" class="screen">
      <h1>Source Health & Ingestion Matrix</h1>
      <p class="subtitle">Secret-safe operational status of satellite and traffic telemetry pipelines</p>

      <div class="stats-grid" id="health-grid"></div>
    </section>
  </main>

  <!-- MODAL: FEATURE DETAIL & LIGHTBOX -->
  <div id="feature-modal" class="modal-overlay" onclick="closeModalOnBg(event)">
    <div class="modal-content">
      <button class="modal-close" onclick="closeModal()">&times;</button>
      <div id="modal-body"></div>
    </div>
  </div>

  <script>
    const DATA = {json.dumps(data_payload, ensure_ascii=False)};

    function switchScreen(screenId, subTabId) {{
      document.querySelectorAll('.screen').forEach(el => el.classList.remove('active'));
      document.querySelectorAll('.nav-btn').forEach(el => el.classList.remove('active'));
      
      const target = document.getElementById('screen-' + screenId);
      if (target) target.classList.add('active');
      
      const btn = Array.from(document.querySelectorAll('.nav-btn')).find(b => b.getAttribute('onclick')?.includes(screenId));
      if (btn) btn.classList.add('active');

      if (subTabId) {{
        switchEvidenceTab(subTabId);
      }}
    }}

    function switchEvidenceTab(tabId) {{
      document.querySelectorAll('.evidence-tab-pane').forEach(el => el.style.display = 'none');
      document.querySelectorAll('.sub-tab-btn').forEach(el => el.classList.remove('active'));
      
      const pane = document.getElementById(tabId);
      if (pane) pane.style.display = 'block';

      const btn = document.getElementById('btn-' + tabId);
      if (btn) btn.classList.add('active');
    }}

    function initDashboard() {{
      // Update header badges and counters
      document.getElementById('overview-timestamp').textContent = 'Snapshot generated: ' + DATA.generatedAt;
      document.getElementById('stat-features').textContent = DATA.features.length;
      document.getElementById('stat-optical').textContent = DATA.opticalTracking.length;
      document.getElementById('stat-images').textContent = DATA.totalImages.toLocaleString();
      document.getElementById('stat-notes').textContent = DATA.notes.length;
      document.getElementById('nav-evidence-badge').textContent = DATA.opticalTracking.length;
      document.getElementById('nav-images-badge').textContent = DATA.totalImages.toLocaleString();

      renderOverviewConfirmed();
      renderOpticalTable();
      renderSarTable();
      renderValidationTable();
      renderNotesTable();
      renderImageGallery();
      renderFeaturesTable();
      renderReviewQueue();
      renderHealthGrid();
    }}

    function renderOverviewConfirmed() {{
      const container = document.getElementById('overview-confirmed-list');
      container.innerHTML = '';

      const confirmedChanges = DATA.changes.filter(c => c.reviewStatus === 'confirmed');
      if (confirmedChanges.length === 0) {{
        container.innerHTML = '<div style="color: var(--text-muted);">No confirmed changes recorded yet.</div>';
        return;
      }}

      confirmedChanges.forEach(c => {{
        const div = document.createElement('div');
        div.style.cssText = 'background: #0f172a; padding: 12px; border-radius: 8px; border: 1px solid #1e293b; display: flex; justify-content: space-between; align-items: center;';
        const f = DATA.features.find(item => item.id === c.featureId) || {{ name: c.featureId }};
        div.innerHTML = `
          <div>
            <div style="font-weight: 700; font-size: 0.95rem;">${{f.name}} <span class="status-pill status-confirmed">✓ CONFIRMED</span></div>
            <div style="font-size: 0.8rem; color: var(--text-muted); margin-top: 4px;">
              ${{c.classification}} • Confidence: <strong>${{Math.round((c.confidence || 0.85) * 100)}}%</strong>
              ${{c.metrics?.amplitudeChangePct ? `• Backscatter Δ: <strong>+${{c.metrics.amplitudeChangePct}}%</strong>` : ''}}
            </div>
          </div>
          <button class="btn btn-outline" style="font-size: 0.75rem; padding: 4px 10px;" onclick="viewFeature('${{f.key}}')">View Proof</button>
        `;
        container.appendChild(div);
      }});
    }}

    function renderOpticalTable() {{
      const tbody = document.getElementById('optical-table-body');
      tbody.innerHTML = '';

      DATA.opticalTracking.forEach(row => {{
        const tr = document.createElement('tr');
        const ssimClass = (row.ssim !== null && row.ssim < 0.2) ? 'color: #f87171; font-weight:700;' : 'color: #fbbf24; font-weight:700;';
        
        tr.innerHTML = `
          <td style="font-size: 1.1rem;">${{row.severity}}</td>
          <td style="font-weight: 600; text-transform: capitalize;">${{row.feature.replace(/_/g, ' ')}}</td>
          <td>${{row.dates}}</td>
          <td style="${{ssimClass}}">${{row.ssim !== null ? row.ssim.toFixed(4) : 'N/A'}}</td>
          <td style="font-weight: 600;">${{row.pixelDiffPct !== null ? row.pixelDiffPct.toFixed(2) + '%' : 'N/A'}}</td>
          <td><span class="tag" style="color: #cbd5e1;">${{row.classification}}</span></td>
          <td><button class="btn btn-outline" style="font-size: 0.75rem; padding: 3px 8px;" onclick="openFeatureImages('${{row.feature}}')">Inspect Diffs →</button></td>
        `;
        tbody.appendChild(tr);
      }});
    }}

    function renderSarTable() {{
      const tbody = document.getElementById('sar-table-body');
      tbody.innerHTML = '';

      DATA.rawNisar.forEach(row => {{
        const tr = document.createElement('tr');
        const amp = row.amplitude_change || {{}};
        const coh = row.coherence_change || {{}};

        tr.innerHTML = `
          <td style="font-weight: 600;">${{row.feature_name || row.feature}}</td>
          <td>${{row.date_previous}} → ${{row.date_current}}</td>
          <td><span class="tag">${{row.product_type || 'GSLC'}}</span></td>
          <td><strong>${{row.polarization || 'HH'}}</strong></td>
          <td style="color: #34d399; font-weight: 700;">${{amp.mean_increase_db ? '+' + amp.mean_increase_db.toFixed(2) + ' dB' : '—'}}</td>
          <td style="color: #f87171;">${{amp.mean_decrease_db ? amp.mean_decrease_db.toFixed(2) + ' dB' : '—'}}</td>
          <td><strong>${{amp.change_percent ? amp.change_percent.toFixed(1) + '%' : '—'}}</strong></td>
          <td style="color: #60a5fa; font-weight: 700;">${{coh.significant_decorrelated_percent ? coh.significant_decorrelated_percent.toFixed(1) + '%' : '—'}}</td>
          <td>${{Math.round((row.confidence || 0.85) * 100)}}%</td>
        `;
        tbody.appendChild(tr);
      }});
    }}

    function renderValidationTable() {{
      const tbody = document.getElementById('validation-table-body');
      tbody.innerHTML = '';

      const details = DATA.s2Report?.details || [];
      details.forEach(item => {{
        const tr = document.createElement('tr');
        const nisar = item.nisar_change || {{}};
        const s2 = item.s2_correlation?.s2_comparison || {{}};
        const isCorrelated = item.correlated;

        tr.innerHTML = `
          <td style="font-weight: 600; text-transform: capitalize;">${{item.feature.replace(/_/g, ' ')}}</td>
          <td>${{nisar.date_previous || '—'}} → ${{nisar.date_current || '—'}}</td>
          <td>${{item.s2_correlation?.s2_previous_date || '—'}} → ${{item.s2_correlation?.s2_current_date || '—'}}</td>
          <td style="font-weight: 700; color: #fbbf24;">${{s2.ssim_score !== undefined ? s2.ssim_score.toFixed(4) : '—'}}</td>
          <td>${{s2.mean_pixel_diff !== undefined ? s2.mean_pixel_diff.toFixed(2) : '—'}}</td>
          <td>${{isCorrelated ? '<span class="status-pill status-confirmed">✓ Confirmed Optical</span>' : '<span class="status-pill status-dismissed">No Optical Δ</span>'}}</td>
        `;
        tbody.appendChild(tr);
      }});
    }}

    function renderNotesTable() {{
      const tbody = document.getElementById('notes-table-body');
      tbody.innerHTML = '';

      DATA.rawNotes.forEach(n => {{
        const tr = document.createElement('tr');
        const decisionClass = n.kind === 'confirmed' ? 'status-confirmed' : (n.kind === 'deferred' ? 'status-deferred' : 'status-dismissed');

        tr.innerHTML = `
          <td>${{n.createdAt.replace('T', ' ').replace('Z', '')}}</td>
          <td style="font-weight: 600; text-transform: capitalize;">${{(n.feature || '').replace(/_/g, ' ')}}</td>
          <td style="font-family: monospace; font-size: 0.75rem; color: #94a3b8;">${{n.relatedChangeId || '—'}}</td>
          <td><span class="status-pill ${{decisionClass}}">${{n.kind.toUpperCase()}}</span></td>
          <td>${{n.text}}</td>
        `;
        tbody.appendChild(tr);
      }});
    }}

    function renderImageGallery() {{
      const grid = document.getElementById('gallery-grid');
      grid.innerHTML = '';

      const query = (document.getElementById('gallery-search').value || '').toLowerCase();
      const typeFilter = document.getElementById('gallery-type-filter').value;
      const cloudFilter = document.getElementById('gallery-cloud-filter')?.value || 'all';

      let rendered = 0;
      for (const [featureKey, images] of Object.entries(DATA.imageCatalog)) {{
        if (query && !featureKey.toLowerCase().includes(query)) continue;

        images.forEach(img => {{
          if (typeFilter !== 'all' && img.type !== typeFilter) return;

          // Cloud filtering
          if (img.type === 'sentinel2' && img.cloudPct !== null) {{
            if (cloudFilter === 'clear' && img.cloudPct >= 20.0) return;
            if (cloudFilter === 'moderate' && img.cloudPct >= 35.0) return;
            if (cloudFilter === 'obscured' && img.cloudPct < 35.0) return;
          }}

          if (rendered >= 48) return; // limit to 48 images for high performance

          let cloudBadge = '';
          if (img.cloudPct !== null && img.cloudPct !== undefined) {{
            if (img.cloudPct < 20) {{
              cloudBadge = `<span style="background: rgba(16,185,129,0.2); color:#34d399; padding: 2px 6px; border-radius: 4px; font-size: 0.7rem;">☀️ ${{img.cloudPct}}% cloud</span>`;
            }} else if (img.cloudPct < 35) {{
              cloudBadge = `<span style="background: rgba(245,158,11,0.2); color:#fbbf24; padding: 2px 6px; border-radius: 4px; font-size: 0.7rem;">⛅ ${{img.cloudPct}}% cloud</span>`;
            }} else {{
              cloudBadge = `<span style="background: rgba(239,68,68,0.2); color:#f87171; padding: 2px 6px; border-radius: 4px; font-size: 0.7rem; font-weight:700;">☁️ ${{img.cloudPct}}% (OBSCURED)</span>`;
            }}
          }}

          const card = document.createElement('div');
          card.className = 'image-card';
          card.innerHTML = `
            <img src="${{img.path}}" alt="${{img.label}}" class="image-preview" onclick="openLightbox('${{img.path}}', '${{featureKey}} - ${{img.label}}')">
            <div class="image-caption">
              <div style="display: flex; justify-content: space-between; align-items: center;">
                <div style="font-weight: 700; text-transform: capitalize;">${{featureKey.replace(/_/g, ' ')}}</div>
                ${{cloudBadge}}
              </div>
              <div style="color: var(--text-muted); font-size: 0.75rem; margin-top: 4px;">${{img.label}}</div>
            </div>
          `;
          grid.appendChild(card);
          rendered++;
        }});
      }}
    }}

    function renderFeaturesTable() {{
      const tbody = document.getElementById('features-table-body');
      tbody.innerHTML = '';

      const query = (document.getElementById('feature-search').value || '').toLowerCase();
      const groupVal = document.getElementById('group-filter').value;
      const claimantVal = document.getElementById('claimant-filter').value;
      const priorityVal = document.getElementById('priority-filter').value;

      const statusMap = {{}};
      DATA.featureStatus.forEach(fs => {{ statusMap[fs.featureKey] = fs; }});

      const filtered = DATA.features.filter(f => {{
        if (query && !f.name.toLowerCase().includes(query) && !f.key.toLowerCase().includes(query) && !f.country.toLowerCase().includes(query)) return false;
        if (groupVal !== 'all' && f.group !== groupVal) return false;
        if (claimantVal !== 'all' && f.country !== claimantVal && f.claimant !== claimantVal) return false;
        if (priorityVal !== 'all' && f.priority != priorityVal) return false;
        return true;
      }});

      filtered.forEach(f => {{
        const status = statusMap[f.key] || {{}};
        const tr = document.createElement('tr');
        tr.onclick = () => viewFeature(f.key);

        let tagsHtml = '';
        if (f.tags?.includes('airstrip') || f.airport) tagsHtml += '<span class="tag tag-airport">✈️ Airstrip</span>';
        if (f.tags?.includes('sam') || f.sam) tagsHtml += '<span class="tag tag-sam">🚀 SAM</span>';
        if (f.tags?.includes('radar') || f.radar) tagsHtml += '<span class="tag tag-radar">📡 Radar</span>';
        if (f.tags?.includes('port') || f.port) tagsHtml += '<span class="tag tag-port">⚓ Port</span>';
        if (f.tags?.includes('helipad') || f.helipad) tagsHtml += '<span class="tag">🚁 Heli</span>';

        const sceneDate = status.latestScene?.capturedAt ? status.latestScene.capturedAt.split('T')[0] : '—';
        const reviewStatus = status.latestChange?.reviewStatus || 'clear';
        const statusBadge = reviewStatus === 'confirmed' ? '<span class="status-pill status-confirmed">✓ Confirmed</span>' : (reviewStatus === 'deferred' ? '<span class="status-pill status-deferred">⏳ Deferred</span>' : '<span class="status-pill status-dismissed">Normal</span>');

        tr.innerHTML = `
          <td><span class="priority-badge priority-${{f.priority}}">P${{f.priority}}</span></td>
          <td style="font-weight: 600;">${{f.name}}</td>
          <td style="text-transform: capitalize;">${{f.group}}</td>
          <td>${{f.country || f.claimant}}</td>
          <td>${{tagsHtml || '—'}}</td>
          <td>${{sceneDate}}</td>
          <td>${{statusBadge}}</td>
          <td>${{status.counts?.scenes || 0}}</td>
        `;
        tbody.appendChild(tr);
      }});
    }}

    function renderReviewQueue() {{
      const deck = document.getElementById('triage-deck');
      deck.innerHTML = '';

      DATA.changes.forEach(item => {{
        const card = document.createElement('div');
        card.style.cssText = 'background: #111827; border: 1px solid #1f293b; border-radius: 8px; padding: 16px; margin-bottom: 12px;';
        const f = DATA.features.find(feat => feat.id === item.featureId) || {{ name: item.featureId, key: '' }};
        const statusPill = item.reviewStatus === 'confirmed' ? '<span class="status-pill status-confirmed">✓ CONFIRMED</span>' : (item.reviewStatus === 'deferred' ? '<span class="status-pill status-deferred">⏳ DEFERRED</span>' : '<span class="status-pill status-dismissed">DISMISSED</span>');

        card.innerHTML = `
          <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
            <div style="font-weight: 700; font-size: 1.05rem;">${{f.name}} <span class="priority-badge priority-${{f.priority || 2}}">P${{f.priority || 2}}</span></div>
            ${{statusPill}}
          </div>
          <div style="font-size: 0.85rem; color: var(--text-muted); margin-bottom: 8px;">
            Change ID: <code style="color: #60a5fa;">${{item.id}}</code> • Detected: ${{item.detectedAt ? item.detectedAt.split('T')[0] : 'Recent'}}
          </div>
          <div style="background: #0f172a; padding: 10px; border-radius: 6px; font-size: 0.85rem; display: flex; gap: 16px; flex-wrap: wrap;">
            <div>Classification: <strong>${{item.classification}}</strong></div>
            <div>Confidence: <strong>${{Math.round((item.confidence || 0.85) * 100)}}%</strong></div>
            ${{item.metrics?.amplitudeChangePct ? `<div>Backscatter Δ: <strong>+${{item.metrics.amplitudeChangePct}}%</strong></div>` : ''}}
          </div>
        `;
        deck.appendChild(card);
      }});
    }}

    function renderHealthGrid() {{
      const grid = document.getElementById('health-grid');
      grid.innerHTML = '';
      const sources = DATA.sourceHealth?.sources || {{}};

      for (const [key, s] of Object.entries(sources)) {{
        const card = document.createElement('div');
        card.className = 'stat-card';
        card.innerHTML = `
          <div class="label">${{key.replace('_', ' ')}}</div>
          <div class="value" style="font-size: 1.3rem;">${{s.sceneCount ?? s.totalObservations ?? '—'}} Scenes</div>
          <div class="subtext">Status: <span style="color: #34d399; font-weight:700;">${{s.status}}</span> • Secret Safe: ✓</div>
        `;
        grid.appendChild(card);
      }}
    }}

    function viewFeature(featureKey) {{
      const feature = DATA.features.find(f => f.key === featureKey);
      if (!feature) return;

      const featureImages = DATA.imageCatalog[featureKey] || [];
      const featureNotes = DATA.rawNotes.filter(n => n.feature === featureKey || n.relatedChangeId?.includes(featureKey));

      const modalBody = document.getElementById('modal-body');
      modalBody.innerHTML = `
        <h2 style="margin-bottom: 4px;">${{feature.name}}</h2>
        <div style="color: var(--text-muted); font-size: 0.9rem; margin-bottom: 16px;">
          Claimant: <strong>${{feature.country || feature.claimant}}</strong> • Group: <strong>${{feature.group}}</strong> • Coordinates: ${{feature.lat}}°N, ${{feature.lon}}°E
        </div>

        <div style="background: #0f172a; padding: 14px; border-radius: 8px; border: 1px solid #1e293b; margin-bottom: 16px;">
          <h4 style="font-size: 0.85rem; color: #94a3b8; text-transform: uppercase; margin-bottom: 6px;">Strategic Attributes</h4>
          <div>${{feature.tags?.map(t => `<span class="tag">${{t}}</span>`).join('') || 'None listed'}}</div>
        </div>

        <h3>🖼️ Visual Evidence & Diff Maps (${{featureImages.length}} files)</h3>
        <div style="display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 10px; max-height: 280px; overflow-y: auto; background: #0f172a; padding: 12px; border-radius: 8px; margin-bottom: 16px;">
          ${{featureImages.map(img => `
            <div style="background: #111827; border-radius: 6px; overflow: hidden; border: 1px solid #1e293b;">
              <img src="${{img.path}}" alt="${{img.label}}" style="width:100%; height:120px; object-fit:cover; cursor:pointer;" onclick="openLightbox('${{img.path}}', '${{feature.name}} - ${{img.label}}')">
              <div style="padding: 6px; font-size: 0.75rem; text-align: center;">${{img.label}}</div>
            </div>
          `).join('') || '<div style="color: var(--text-muted); font-size: 0.85rem;">No visual images on disk.</div>'}}
        </div>

        <h3>📝 Analyst Decision History</h3>
        <div style="background: #0f172a; padding: 10px; border-radius: 8px;">
          ${{featureNotes.map(n => `
            <div style="font-size: 0.85rem; padding: 6px 0; border-bottom: 1px solid #1e293b;">
              <span style="color: #60a5fa;">[${{n.createdAt.split('T')[0]}}]</span> <strong>${{n.kind.toUpperCase()}}</strong>: ${{n.text}}
            </div>
          `).join('') || '<div style="color: var(--text-muted); font-size: 0.85rem;">No analyst notes recorded.</div>'}}
        </div>
      `;

      document.getElementById('feature-modal').classList.add('open');
    }}

    function openFeatureImages(featureKey) {{
      switchScreen('gallery');
      document.getElementById('gallery-search').value = featureKey;
      renderImageGallery();
    }}

    function openLightbox(imageSrc, caption) {{
      const modalBody = document.getElementById('modal-body');
      modalBody.innerHTML = `
        <h3 style="margin-bottom: 12px;">${{caption}}</h3>
        <img src="${{imageSrc}}" class="lightbox-img" alt="${{caption}}">
        <div style="margin-top: 14px; text-align: center; color: var(--text-muted); font-size: 0.85rem;">
          File location: <code style="color: #60a5fa;">${{imageSrc}}</code>
        </div>
      `;
      document.getElementById('feature-modal').classList.add('open');
    }}

    function closeModal() {{
      document.getElementById('feature-modal').classList.remove('open');
    }}

    function closeModalOnBg(e) {{
      if (e.target.id === 'feature-modal') closeModal();
    }}

    window.onload = initDashboard;
  </script>
</body>
</html>
"""

    DERIVED_DIR.mkdir(parents=True, exist_ok=True)
    with open(DASHBOARD_HTML, "w", encoding="utf-8") as f:
        f.write(html)

    return str(DASHBOARD_HTML)


def main():
    parser = argparse.ArgumentParser(description="Generate ReefWatch HTML Analyst Dashboard")
    parser.add_argument("--open", action="store_true", help="Open generated dashboard in default browser")
    args = parser.parse_args()

    out_path = build_dashboard_html()
    print(f"✅ ReefWatch HTML Dashboard generated at:\n   {out_path}")

    if args.open:
        webbrowser.open(f"file://{out_path}")


if __name__ == "__main__":
    main()
