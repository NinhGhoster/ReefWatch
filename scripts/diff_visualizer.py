#!/usr/bin/env python3
"""High-contrast difference heatmap and triptych comparison generator for ReefWatch.

Creates clear, self-explanatory change detection visualizations:
1. Filters out ocean wave noise (thresholding < 20 delta).
2. Applies a high-visibility thermal colormap (Red = High Change, Yellow = Moderate, Blue = Minor).
3. Generates a 3-panel composite (Before | After | Difference Heatmap).
4. Embeds clear metadata headers and visual color legends on the image.

Usage:
    from diff_visualizer import create_annotated_diff_triptych
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw, ImageFont


def load_rgb(image_input: str | np.ndarray | Image.Image) -> np.ndarray:
    """Normalize input into an (H, W, 3) uint8 numpy array."""
    if isinstance(image_input, (str, Path)):
        img = Image.open(image_input)
    elif isinstance(image_input, Image.Image):
        img = image_input
    elif isinstance(image_input, np.ndarray):
        if image_input.ndim == 2:
            return np.stack([image_input] * 3, axis=-1).astype(np.uint8)
        return image_input.astype(np.uint8)
    else:
        raise TypeError(f"Unsupported image type: {type(image_input)}")

    if img.mode != "RGB":
        img = img.convert("RGB")
    return np.array(img)


def generate_thermal_heatmap(
    rgb1: np.ndarray,
    rgb2: np.ndarray,
    noise_threshold: float = 22.0,
) -> np.ndarray:
    """Generate a high-contrast thermal change heatmap overlay on a muted background.

    Colors:
    - Delta < 22: Unchanged background (darkened base image for spatial reference)
    - 22 <= Delta < 50: Cyan/Blue (Minor surface change)
    - 50 <= Delta < 90: Bright Yellow/Amber (Moderate change)
    - Delta >= 90: High-visibility Crimson/Red (Major new construction / structural change)
    """
    h = min(rgb1.shape[0], rgb2.shape[0])
    w = min(rgb1.shape[1], rgb2.shape[1])
    rgb1 = rgb1[:h, :w].astype(np.float32)
    rgb2 = rgb2[:h, :w].astype(np.float32)

    # Compute mean channel delta
    diff = np.mean(np.abs(rgb2 - rgb1), axis=2)

    # Base: darkened grayscale/color background for geographical context
    base = (rgb2 * 0.45).astype(np.uint8)
    heatmap = base.copy()

    # Masks for different change tiers
    minor_mask = (diff >= noise_threshold) & (diff < 50.0)
    mod_mask = (diff >= 50.0) & (diff < 90.0)
    major_mask = diff >= 90.0

    # 1. Minor change (Cyan / Deep Blue: 0, 190, 255)
    heatmap[minor_mask] = [0, 190, 255]

    # 2. Moderate change (Bright Amber / Yellow: 255, 215, 0)
    heatmap[mod_mask] = [255, 215, 0]

    # 3. Major change (Neon Crimson / Red: 255, 30, 30)
    heatmap[major_mask] = [255, 30, 30]

    # Smooth blend on changed pixels to retain subtle texture
    changed_mask = diff >= noise_threshold
    alpha = np.clip((diff - noise_threshold) / 100.0, 0.4, 0.95)[:, :, np.newaxis]
    blended = (heatmap.astype(np.float32) * alpha + base.astype(np.float32) * (1.0 - alpha)).astype(np.uint8)
    
    result = base.copy()
    result[changed_mask] = blended[changed_mask]
    return result


def create_annotated_diff_triptych(
    img1_input: str | np.ndarray | Image.Image,
    img2_input: str | np.ndarray | Image.Image,
    output_path: str | Path,
    feature_name: str = "Disputed SCS Feature",
    date1: str = "Pass 1",
    date2: str = "Pass 2",
    ssim_score: float | None = None,
    pixel_diff_pct: float | None = None,
    classification: str | None = None,
    cloud_status: str | None = None,
) -> str:
    """Create a 3-panel composite image: [ BEFORE | AFTER | DIFFERENCE HEATMAP + LEGEND ]."""
    rgb1 = load_rgb(img1_input)
    rgb2 = load_rgb(img2_input)

    # Standardize individual panel size
    panel_size = 512
    img1_pil = Image.fromarray(rgb1).resize((panel_size, panel_size), Image.LANCZOS)
    img2_pil = Image.fromarray(rgb2).resize((panel_size, panel_size), Image.LANCZOS)

    rgb1_resized = np.array(img1_pil)
    rgb2_resized = np.array(img2_pil)

    # Generate thermal difference heatmap
    diff_rgb = generate_thermal_heatmap(rgb1_resized, rgb2_resized)
    diff_pil = Image.fromarray(diff_rgb)

    # Layout dimensions
    header_h = 70
    footer_h = 50
    margin = 10
    total_w = panel_size * 3 + margin * 4
    total_h = header_h + panel_size + footer_h + margin * 2

    # Canvas
    canvas = Image.new("RGB", (total_w, total_h), color=(15, 23, 42))  # Dark slate #0f172a
    draw = ImageDraw.Draw(canvas)

    # Paste 3 panels
    x1 = margin
    x2 = margin * 2 + panel_size
    x3 = margin * 3 + panel_size * 2
    y_panels = header_h + margin

    canvas.paste(img1_pil, (x1, y_panels))
    canvas.paste(img2_pil, (x2, y_panels))
    canvas.paste(diff_pil, (x3, y_panels))

    # Draw border around each panel
    border_color = (51, 65, 85)
    for px in [x1, x2, x3]:
        draw.rectangle([px - 1, y_panels - 1, px + panel_size, y_panels + panel_size], outline=border_color, width=1)

    # Header text
    title_text = f"REEFWATCH CHANGE DETECTION: {feature_name.upper().replace('_', ' ')}"
    draw.text((margin + 6, 12), title_text, fill=(255, 255, 255))

    meta_parts = []
    if ssim_score is not None:
        meta_parts.append(f"SSIM: {ssim_score:.4f}")
    if pixel_diff_pct is not None:
        meta_parts.append(f"Pixel Δ: {pixel_diff_pct:.2f}%")
    if classification:
        meta_parts.append(f"Class: {classification.upper().replace('_', ' ')}")
    if cloud_status:
        meta_parts.append(f"Clouds: {cloud_status}")

    meta_text = "  |  ".join(meta_parts)
    draw.text((margin + 6, 38), meta_text, fill=(148, 163, 184))

    # Panel Sub-Labels
    draw.rectangle([x1, y_panels, x1 + panel_size, y_panels + 24], fill=(0, 0, 0, 180))
    draw.text((x1 + 8, y_panels + 5), f"BEFORE (Pass: {date1})", fill=(255, 255, 255))

    draw.rectangle([x2, y_panels, x2 + panel_size, y_panels + 24], fill=(0, 0, 0, 180))
    draw.text((x2 + 8, y_panels + 5), f"AFTER (Pass: {date2})", fill=(255, 255, 255))

    draw.rectangle([x3, y_panels, x3 + panel_size, y_panels + 24], fill=(0, 0, 0, 180))
    draw.text((x3 + 8, y_panels + 5), "DIFFERENCE HEATMAP (Delta > 22)", fill=(255, 255, 255))

    # Footer Color Scale Legend
    legend_y = total_h - footer_h + 14
    draw.text((margin + 6, legend_y), "HEATMAP COLOR SCALE:", fill=(203, 213, 225))

    # Legend Items: (color, label, offset)
    items = [
        ((40, 50, 70), "■ Dark (No Change / Sea)", 190),
        ((0, 190, 255), "■ Blue (Minor Shift)", 400),
        ((255, 215, 0), "■ Yellow (Moderate Change)", 580),
        ((255, 30, 30), "■ RED (Major New Structure)", 820),
    ]

    for color, label, offset_x in items:
        draw.text((offset_x, legend_y), label, fill=color)

    # Save output
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output_path, quality=92)
    return str(output_path)
