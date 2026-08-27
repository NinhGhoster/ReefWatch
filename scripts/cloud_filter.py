#!/usr/bin/env python3
"""Optical Cloud Detection and Filtering for ReefWatch.

Provides pixel-level cloud masking, cloud cover percentage calculation,
and cloud interference rejection for Sentinel-2, Planet, and MODIS optical imagery.

In tropical maritime environments (South China Sea), passing cumulus clouds
and cloud shadows cause false positive structural changes and SSIM drops.
This module filters out cloud-obscured scenes and evaluates true ground changes.

Usage:
    from cloud_filter import detect_cloud_mask, calculate_cloud_cover, assess_cloud_interference
"""

from __future__ import annotations

import numpy as np
from PIL import Image
from skimage.metrics import structural_similarity as ssim

# Standard threshold: scenes with > 30% cloud cover over the feature bbox are flagged as obscured
DEFAULT_CLOUD_MAX_PCT = 30.0

# Pixel-level cloud identification thresholds (RGB)
CLOUD_MIN_INTENSITY = 175
CLOUD_MEAN_INTENSITY = 185
CLOUD_MAX_COLOR_DELTA = 35  # Low chroma/saturation = white/gray cloud


def load_rgb(image_input: str | np.ndarray | Image.Image) -> np.ndarray:
    """Normalize input into an (H, W, 3) uint8 numpy array."""
    if isinstance(image_input, (str, bytes)):
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


def detect_cloud_mask(rgb: np.ndarray) -> np.ndarray:
    """Generate a boolean mask where True indicates a cloud pixel.

    Algorithm detects high-reflectance, low-saturation (white/gray) cloud signatures.
    """
    rgb = load_rgb(rgb)
    r = rgb[:, :, 0].astype(np.int16)
    g = rgb[:, :, 1].astype(np.int16)
    b = rgb[:, :, 2].astype(np.int16)

    mean_val = (r + g + b) / 3.0
    max_val = np.maximum(np.maximum(r, g), b)
    min_val = np.minimum(np.minimum(r, g), b)
    color_spread = max_val - min_val

    # Cloud criteria: bright in all bands + neutral/low chroma + high average intensity
    is_cloud = (
        (r >= CLOUD_MIN_INTENSITY)
        & (g >= CLOUD_MIN_INTENSITY)
        & (b >= CLOUD_MIN_INTENSITY)
        & (color_spread <= CLOUD_MAX_COLOR_DELTA)
        & (mean_val >= CLOUD_MEAN_INTENSITY)
    )
    return is_cloud


def calculate_cloud_cover(rgb: np.ndarray) -> float:
    """Calculate the cloud cover percentage of an optical image (0.0 to 100.0%)."""
    mask = detect_cloud_mask(rgb)
    if mask.size == 0:
        return 0.0
    cloud_pct = float(np.sum(mask) / mask.size * 100.0)
    return round(cloud_pct, 2)


def assess_cloud_interference(
    img1: str | np.ndarray | Image.Image,
    img2: str | np.ndarray | Image.Image,
    max_allowed_cloud_pct: float = DEFAULT_CLOUD_MAX_PCT,
) -> dict[str, any]:
    """Assess whether a bitemporal comparison is compromised by cloud cover.

    Returns detailed diagnostic dictionary including individual cloud percentages,
    combined clear view fraction, and actionable triage recommendations.
    """
    rgb1 = load_rgb(img1)
    rgb2 = load_rgb(img2)

    # Resize to common dimensions if needed
    h = min(rgb1.shape[0], rgb2.shape[0])
    w = min(rgb1.shape[1], rgb2.shape[1])
    rgb1 = rgb1[:h, :w]
    rgb2 = rgb2[:h, :w]

    mask1 = detect_cloud_mask(rgb1)
    mask2 = detect_cloud_mask(rgb2)

    cloud_pct1 = round(float(np.sum(mask1) / mask1.size * 100.0), 2)
    cloud_pct2 = round(float(np.sum(mask2) / mask2.size * 100.0), 2)

    # Either image exceeding threshold impairs comparison reliability
    is_obscured = (cloud_pct1 > max_allowed_cloud_pct) or (cloud_pct2 > max_allowed_cloud_pct)

    # Combined cloud mask (pixels cloudy in either image)
    combined_cloud_mask = mask1 | mask2
    clear_pixels = np.sum(~combined_cloud_mask)
    usable_clear_pct = round(float(clear_pixels / combined_cloud_mask.size * 100.0), 2)

    if cloud_pct1 > 50.0 or cloud_pct2 > 50.0 or usable_clear_pct < 25.0:
        recommendation = "cloud_obscured_skip"
        status_label = "☁️ Heavy Cloud Obscuration (Skip / Inconclusive)"
    elif is_obscured:
        recommendation = "moderate_clouds_caution"
        status_label = "⛅ Moderate Clouds (Use Caution)"
    else:
        recommendation = "clear"
        status_label = "☀️ Clear / Low Cloud Interference"

    return {
        "cloud_pct_image1": cloud_pct1,
        "cloud_pct_image2": cloud_pct2,
        "max_cloud_pct": max(cloud_pct1, cloud_pct2),
        "usable_clear_pct": usable_clear_pct,
        "is_cloud_obscured": is_obscured,
        "recommendation": recommendation,
        "status_label": status_label,
    }


def compute_cloud_masked_diff(
    rgb1: np.ndarray,
    rgb2: np.ndarray,
) -> tuple[float, float, bool]:
    """Compute pixel difference and SSIM solely on mutually cloud-free pixels.

    Returns:
        (clear_pixel_diff_pct, usable_clear_area_pct, is_reliable)
    """
    rgb1 = load_rgb(rgb1)
    rgb2 = load_rgb(rgb2)

    h = min(rgb1.shape[0], rgb2.shape[0])
    w = min(rgb1.shape[1], rgb2.shape[1])
    rgb1 = rgb1[:h, :w]
    rgb2 = rgb2[:h, :w]

    mask1 = detect_cloud_mask(rgb1)
    mask2 = detect_cloud_mask(rgb2)
    clear_mask = ~(mask1 | mask2)

    total_clear = np.sum(clear_mask)
    usable_pct = float(total_clear / clear_mask.size * 100.0)

    if usable_pct < 20.0:
        # Insufficient clear area to perform reliable comparison
        return (0.0, usable_pct, False)

    # Compute pixel difference on clear pixels only
    diff = np.abs(rgb1.astype(np.float32) - rgb2.astype(np.float32))
    changed_pixels = np.any(diff > 30, axis=2) & clear_mask
    clear_diff_pct = float(np.sum(changed_pixels) / total_clear * 100.0)

    return (round(clear_diff_pct, 2), round(usable_pct, 2), True)
