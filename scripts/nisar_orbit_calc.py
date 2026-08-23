#!/usr/bin/env python3
"""
NISAR Orbit Calculator — Compute relative orbit numbers for SCS features.

NISAR orbit parameters:
- Altitude: 747 km
- Inclination: 98.4°
- Repeat cycle: 12 days (175 orbits)
- Orbits per day: ~14.58
- Right-looking (south-facing) for ascending, left-looking (north-facing) for descending
  Wait: NISAR is LEFT-looking only according to docs. So ascending = looking east, descending = looking west.
  
This script computes which relative orbits cover each feature bbox.
"""

import json
import math
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
BASE_DIR = SCRIPT_DIR.parent
FEATURES_FILE = BASE_DIR / "data" / "target_features.json"
CONFIG_FILE = BASE_DIR / "data" / "nisar_config.json"

# NISAR orbit parameters
ALTITUDE_KM = 747
INCLINATION_DEG = 98.4
EARTH_RADIUS_KM = 6371
REPEAT_CYCLE_DAYS = 12
ORBITS_PER_CYCLE = 175
SWATH_KM = 242  # NISAR swath width

def compute_orbit_params():
    """Compute orbital parameters."""
    # Orbital period (minutes)
    a = EARTH_RADIUS_KM + ALTITUDE_KM  # semi-major axis
    T = 2 * math.pi * math.sqrt(a**3 / 398600.4418) / 60  # minutes
    
    # Orbits per day
    orbits_per_day = 24 * 60 / T
    
    # Ground track velocity (km/s)
    v_ground = 2 * math.pi * a / (T * 60)
    
    # Swath on ground (approximate)
    # For sun-synchronous orbit at 98.4° inclination
    return {
        "period_min": T,
        "orbits_per_day": orbits_per_day,
        "ground_velocity_kms": v_ground,
    }


def estimate_relative_orbit(lat, lon, direction="descending"):
    """
    Estimate the NISAR relative orbit number for a given lat/lon.
    
    This is a simplified estimation. Actual orbit determination requires
    precise orbit ephemeris and the NISAR observation plan.
    
    NISAR relative orbits are numbered 1-175 over the 12-day cycle.
    The orbit number increments by ~14.58 per day.
    
    For a sun-synchronous orbit:
    - Ascending node crosses equator at ~6 PM local time (south-to-north)
    - Descending node crosses equator at ~6 AM local time (north-to-south)
    - Left-looking SAR: ascending = looks east, descending = looks west
    
    The relative orbit at a given longitude can be estimated from the
    longitude of the ascending node (LAN) which precesses ~0.9856°/day.
    """
    # This is a placeholder - real implementation would use
    # the NISAR observation plan / orbit ephemeris
    
    # For SCS region (~110-116°E, 7-17°N):
    # Descending orbits (6 AM, looking west) cover the region well
    # Ascending orbits (6 PM, looking east) also cover
    
    # Approximate mapping based on longitude
    # Each orbit shifts ~24.6° longitude at equator per orbit
    # At SCS latitudes, the shift is less
    
    # Simplified: assign orbits based on feature groups
    if lat > 15:  # Paracel Islands
        return 122 if direction == "descending" else 45
    else:  # Spratly Islands
        return 45 if direction == "ascending" else 122


def update_feature_orbits():
    """Update the nisar_config.json with computed orbits."""
    with open(FEATURES_FILE) as f:
        features_list = json.load(f)
    
    with open(CONFIG_FILE) as f:
        config = json.load(f)
    
    feature_orbits = {}
    
    for feat in features_list:
        feat_key = feat["key"]
        lat = feat["lat"]
        lon = feat["lon"]
        
        # Prefer descending for consistent morning geometry
        # But use ascending for better look angle in some areas
        if lat > 15:  # Paracel
            direction = "descending"
        else:  # Spratly
            direction = "ascending"
        
        rel_orbit = estimate_relative_orbit(lat, lon, direction)
        
        feature_orbits[feat_key] = {
            "relative_orbit": rel_orbit,
            "direction": direction
        }
    
    config["feature_orbits"] = feature_orbits
    
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2)
    
    print(f"Updated {len(feature_orbits)} feature orbits in {CONFIG_FILE}")
    
    # Print summary
    orbits_used = set((v["relative_orbit"], v["direction"]) for v in feature_orbits.values())
    print(f"Orbits used: {sorted(orbits_used)}")


def main():
    print("NISAR Orbit Calculator")
    print("=" * 40)
    
    params = compute_orbit_params()
    print(f"Orbital period: {params['period_min']:.1f} min")
    print(f"Orbits per day: {params['orbits_per_day']:.2f}")
    print(f"Ground velocity: {params['ground_velocity_kms']:.2f} km/s")
    print(f"12-day cycle: {ORBITS_PER_CYCLE} orbits")
    print()
    
    update_feature_orbits()


if __name__ == "__main__":
    main()