#!/usr/bin/env python3
"""Optical Cloud & Shadow Detection, Masking, and Ground Filter for ReefWatch.

Provides pixel-level cloud masking, cloud shadow detection, reef/land segmentation,
and cloud-free ground change isolation for Sentinel-2, Planet, and MODIS optical imagery.

Key capabilities:
1. Detects high-reflectance, low-saturation cloud bodies.
2. Detects cloud shadow projections on sea surface and reefs.
3. Segments coral reef / land regions of interest from deep ocean.
4. Isolates true ground construction from passing cloud artifacts.

Usage:
    from cloud_filter import detect_cloud_mask, detect_cloud_shadow_mask, segment_reef_land_mask, assess_cloud_interference
"""

from __future__ import annotations

from pathlib import Path
import numpy as np
from PIL import Image

# Standard thresholds
DEFAULT_CLOUD_MAX_PCT = 30.0
CLOUD_MIN_INTENSITY = 170
CLOUD_MEAN_INTENSITY = 180
CLOUD_MAX_COLOR_DELTA = 40  # Low chroma/saturation = white/gray cloud


def load_rgb(image_input: str | Path | np.ndarray | Image.Image) -> np.ndarray:
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


def detect_cloud_mask(rgb: np.ndarray) -> np.ndarray:
    """Generate a boolean mask where True indicates a cloud pixel.

    Detects bright, neutral-toned cloud bodies while avoiding false positives
    on coral sand and shallow turquoise lagoons.
    """
    rgb = load_rgb(rgb)
    r = rgb[:, :, 0].astype(np.int16)
    g = rgb[:, :, 1].astype(np.int16)
    b = rgb[:, :, 2].astype(np.int16)

    mean_val = (r + g + b) / 3.0
    max_val = np.maximum(np.maximum(r, g), b)
    min_val = np.minimum(np.minimum(r, g), b)
    color_spread = max_val - min_val

    # Cloud signature: bright in all bands + neutral/low chroma + high average intensity
    is_cloud = (
        (r >= CLOUD_MIN_INTENSITY)
        & (g >= CLOUD_MIN_INTENSITY)
        & (b >= CLOUD_MIN_INTENSITY)
        & (color_spread <= CLOUD_MAX_COLOR_DELTA)
        & (mean_val >= CLOUD_MEAN_INTENSITY)
    )
    return is_cloud


def detect_cloud_shadow_mask(rgb: np.ndarray) -> np.ndarray:
    """Generate a boolean mask where True indicates a cloud shadow on the sea/reef."""
    rgb = load_rgb(rgb)
    r = rgb[:, :, 0].astype(np.int16)
    g = rgb[:, :, 1].astype(np.int16)
    b = rgb[:, :, 2].astype(np.int16)

    mean_val = (r + g + b) / 3.0
    # Shadows are extremely dark compared to ambient tropical waters
    is_shadow = (r < 35) & (g < 40) & (b < 60) & (mean_val < 42)
    return is_shadow


def segment_reef_land_mask(rgb: np.ndarray) -> np.ndarray:
    """Segment coral reef, shallow lagoons, sand cays, and artificial islands from deep ocean.

    Deep ocean is characterized by dominant blue band (B > R + 25) with low overall luminance.
    Reefs, shoals, and built-up land have higher green/red reflectance or elevated brightness.
    """
    rgb = load_rgb(rgb)
    r = rgb[:, :, 0].astype(np.int16)
    g = rgb[:, :, 1].astype(np.int16)
    b = rgb[:, :, 2].astype(np.int16)
    mean_val = (r + g + b) / 3.0

    # Deep ocean signature
    is_deep_ocean = (b > (r + 20)) & (g < 85) & (r < 65) & (mean_val < 75)
    # Reef / Land is everything that is NOT deep ocean
    return ~is_deep_ocean


def calculate_cloud_cover(rgb: np.ndarray) -> float:
    """Calculate the cloud cover percentage of an optical image (0.0 to 100.0%)."""
    mask = detect_cloud_mask(rgb)
    if mask.size == 0:
        return 0.0
    cloud_pct = float(np.sum(mask) / mask.size * 100.0)
    return round(cloud_pct, 2)


def assess_cloud_interference(
    img1: str | Path | np.ndarray | Image.Image,
    img2: str | Path | np.ndarray | Image.Image,
    max_allowed_cloud_pct: float = DEFAULT_CLOUD_MAX_PCT,
) -> dict[str, any]:
    """Assess whether a bitemporal comparison is compromised by cloud cover."""
    rgb1 = load_rgb(img1)
    rgb2 = load_rgb(img2)

    h = min(rgb1.shape[0], rgb2.shape[0])
    w = min(rgb1.shape[1], rgb2.shape[1])
    rgb1 = rgb1[:h, :w]
    rgb2 = rgb2[:h, :w]

    mask1 = detect_cloud_mask(rgb1)
    mask2 = detect_cloud_mask(rgb2)

    cloud_pct1 = round(float(np.sum(mask1) / mask1.size * 100.0), 2)
    cloud_pct2 = round(float(np.sum(mask2) / mask2.size * 100.0), 2)

    is_obscured = (cloud_pct1 > max_allowed_cloud_pct) or (cloud_pct2 > max_allowed_cloud_pct)

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
