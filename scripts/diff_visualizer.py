#!/usr/bin/env python3
"""Intelligent Cloud-Filtered Difference Heatmap & Triptych Generator for ReefWatch.

Addresses cloud contamination by:
1. Identifying and masking cloud bodies and cloud shadows in both bitemporal images.
2. Segmenting the reef platform/land zone of interest from deep open ocean.
3. Exclusively attributing red/yellow thermal highlights to genuine ground changes (construction, dredging, paving).
4. Clearly rendering cloud-masked regions in distinct translucent purple/slate so analysts know clouds were excluded.

Usage:
    from diff_visualizer import create_annotated_diff_triptych
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw, ImageFont

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from cloud_filter import (
    detect_cloud_mask,
    detect_cloud_shadow_mask,
    segment_reef_land_mask,
    load_rgb,
)


def generate_cloud_filtered_heatmap(
    rgb1: np.ndarray,
    rgb2: np.ndarray,
    noise_threshold: float = 22.0,
) -> tuple[np.ndarray, dict[str, float]]:
    """Generate a cloud-filtered, ground-focused difference heatmap.

    Returns:
        (heatmap_rgb, stats_dict)
    """
    h = min(rgb1.shape[0], rgb2.shape[0])
    w = min(rgb1.shape[1], rgb2.shape[1])
    rgb1 = rgb1[:h, :w].astype(np.float32)
    rgb2 = rgb2[:h, :w].astype(np.float32)

    # 1. Detect clouds and shadows in both passes
    cmask1 = detect_cloud_mask(rgb1.astype(np.uint8))
    cmask2 = detect_cloud_mask(rgb2.astype(np.uint8))
    smask1 = detect_cloud_shadow_mask(rgb1.astype(np.uint8))
    smask2 = detect_cloud_shadow_mask(rgb2.astype(np.uint8))

    cloud_shadow_mask = cmask1 | cmask2 | smask1 | smask2
    clear_mask = ~cloud_shadow_mask

    # 2. Segment reef platform / land AOI
    reef_mask1 = segment_reef_land_mask(rgb1.astype(np.uint8))
    reef_mask2 = segment_reef_land_mask(rgb2.astype(np.uint8))
    reef_aoi = (reef_mask1 | reef_mask2) & clear_mask

    # 3. Compute raw absolute pixel difference
    diff = np.mean(np.abs(rgb2 - rgb1), axis=2)

    # Base: darkened natural image for spatial orientation
    base = (rgb2 * 0.40).astype(np.uint8)
    heatmap = base.copy()

    # Ground change categories (ONLY applied on clear reef/land pixels!)
    ground_major = (diff >= 85.0) & reef_aoi
    ground_moderate = (diff >= 45.0) & (diff < 85.0) & reef_aoi
    ground_minor = (diff >= noise_threshold) & (diff < 45.0) & reef_aoi

    # Deep water vessel check (isolated bright clusters on open water)
    ocean_clear = (~reef_aoi) & clear_mask
    vessel_candidates = (diff >= 75.0) & ocean_clear

    # 4. Color Assignment
    # A. Minor Ground Shift (Cyan / Blue: 0, 190, 255)
    heatmap[ground_minor] = [0, 190, 255]

    # B. Moderate Ground Change (Bright Yellow: 255, 215, 0)
    heatmap[ground_moderate] = [255, 215, 0]

    # C. Major Ground Construction / Dredging (Neon Crimson Red: 255, 25, 25)
    heatmap[ground_major] = [255, 25, 25]

    # D. Vessel on Water (Neon Lime Green: 50, 255, 50)
    heatmap[vessel_candidates] = [50, 255, 50]

    # E. Cloud-Excluded Regions: Distinct translucent slate/purple tone (80, 60, 110)
    # This proves to the analyst that clouds were recognized and filtered out!
    cloud_color = np.array([80, 60, 110], dtype=np.uint8)
    heatmap[cloud_shadow_mask] = (base[cloud_shadow_mask] * 0.4 + cloud_color * 0.6).astype(np.uint8)

    # Smooth alpha blend on changed ground pixels
    changed_ground = ground_minor | ground_moderate | ground_major | vessel_candidates
    alpha = np.clip((diff - noise_threshold) / 90.0, 0.5, 0.95)[:, :, np.newaxis]
    blended = (heatmap.astype(np.float32) * alpha + base.astype(np.float32) * (1.0 - alpha)).astype(np.uint8)

    result = base.copy()
    result[cloud_shadow_mask] = heatmap[cloud_shadow_mask]
    result[changed_ground] = blended[changed_ground]

    stats = {
        "ground_major_pct": round(float(np.sum(ground_major) / diff.size * 100.0), 2),
        "ground_mod_pct": round(float(np.sum(ground_moderate) / diff.size * 100.0), 2),
        "cloud_excluded_pct": round(float(np.sum(cloud_shadow_mask) / diff.size * 100.0), 2),
        "clear_reef_area_pct": round(float(np.sum(reef_aoi) / diff.size * 100.0), 2),
    }

    return result, stats


def create_annotated_diff_triptych(
    img1_input: str | Path | np.ndarray | Image.Image,
    img2_input: str | Path | np.ndarray | Image.Image,
    output_path: str | Path,
    feature_name: str = "Disputed SCS Feature",
    date1: str = "Pass 1",
    date2: str = "Pass 2",
    ssim_score: float | None = None,
    pixel_diff_pct: float | None = None,
    classification: str | None = None,
    cloud_status: str | None = None,
) -> str:
    """Create a 3-panel composite image: [ BEFORE | AFTER | CLOUD-FILTERED GROUND HEATMAP ]."""
    rgb1 = load_rgb(img1_input)
    rgb2 = load_rgb(img2_input)

    panel_size = 512
    img1_pil = Image.fromarray(rgb1).resize((panel_size, panel_size), Image.LANCZOS)
    img2_pil = Image.fromarray(rgb2).resize((panel_size, panel_size), Image.LANCZOS)

    rgb1_resized = np.array(img1_pil)
    rgb2_resized = np.array(img2_pil)

    # Generate cloud-filtered ground change heatmap
    diff_rgb, stats = generate_cloud_filtered_heatmap(rgb1_resized, rgb2_resized)
    diff_pil = Image.fromarray(diff_rgb)

    # Layout dimensions
    header_h = 74
    footer_h = 56
    margin = 10
    total_w = panel_size * 3 + margin * 4
    total_h = header_h + panel_size + footer_h + margin * 2

    canvas = Image.new("RGB", (total_w, total_h), color=(15, 23, 42))  # Slate dark #0f172a
    draw = ImageDraw.Draw(canvas)

    x1 = margin
    x2 = margin * 2 + panel_size
    x3 = margin * 3 + panel_size * 2
    y_panels = header_h + margin

    canvas.paste(img1_pil, (x1, y_panels))
    canvas.paste(img2_pil, (x2, y_panels))
    canvas.paste(diff_pil, (x3, y_panels))

    border_color = (51, 65, 85)
    for px in [x1, x2, x3]:
        draw.rectangle([px - 1, y_panels - 1, px + panel_size, y_panels + panel_size], outline=border_color, width=1)

    # Header title & metrics
    title_text = f"REEFWATCH GROUND CHANGE DETECTION: {feature_name.upper().replace('_', ' ')}"
    draw.text((margin + 6, 12), title_text, fill=(255, 255, 255))

    meta_parts = []
    if ssim_score is not None:
        meta_parts.append(f"SSIM: {ssim_score:.4f}")
    if stats["ground_major_pct"] > 0:
        meta_parts.append(f"Major Ground Δ: {stats['ground_major_pct']}%")
    elif pixel_diff_pct is not None:
        meta_parts.append(f"Pixel Δ: {pixel_diff_pct:.2f}%")

    if classification:
        meta_parts.append(f"Class: {classification.upper().replace('_', ' ')}")
    if stats["cloud_excluded_pct"] > 0:
        meta_parts.append(f"☁️ Cloud Excluded: {stats['cloud_excluded_pct']}%")

    meta_text = "  |  ".join(meta_parts)
    draw.text((margin + 6, 40), meta_text, fill=(148, 163, 184))

    # Panel Sub-Labels
    draw.rectangle([x1, y_panels, x1 + panel_size, y_panels + 24], fill=(0, 0, 0, 190))
    draw.text((x1 + 8, y_panels + 5), f"BEFORE (Pass: {date1})", fill=(255, 255, 255))

    draw.rectangle([x2, y_panels, x2 + panel_size, y_panels + 24], fill=(0, 0, 0, 190))
    draw.text((x2 + 8, y_panels + 5), f"AFTER (Pass: {date2})", fill=(255, 255, 255))

    draw.rectangle([x3, y_panels, x3 + panel_size, y_panels + 24], fill=(0, 0, 0, 190))
    draw.text((x3 + 8, y_panels + 5), "GROUND CHANGE HEATMAP (Cloud-Filtered)", fill=(255, 255, 255))

    # Footer Color Scale Legend
    legend_y = total_h - footer_h + 16
    draw.text((margin + 6, legend_y), "GROUND HEATMAP KEY:", fill=(203, 213, 225))

    items = [
        ((255, 30, 30), "■ RED: Major Ground Construction", 185),
        ((255, 215, 0), "■ Yellow: Moderate Ground Alteration", 465),
        ((168, 85, 247), "■ Purple/Slate: ☁️ Cloud Excluded", 755),
        ((50, 255, 50), "■ Lime: 🚢 Vessel", 1020),
        ((70, 85, 110), "■ Dark: Baseline / Sea", 1180),
    ]

    for color, label, offset_x in items:
        draw.text((offset_x, legend_y), label, fill=color)

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output_path, quality=92)
    return str(output_path)
