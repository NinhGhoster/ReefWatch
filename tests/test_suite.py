#!/usr/bin/env python3
"""Comprehensive test suite for ReefWatch.

Tests all core components:
- Module imports and environment
- Data schemas and feature databases
- Secret safety and credential masking
- Change detection algorithms (SSIM, pixel diff, classification)
- MVP export and contract validation
- S2 correlation and OSINT cross-referencing
- Daily report and alert generation
- Analyst Review Queue & Dashboard generation
- Monitoring utilities (haversine, bounding boxes, feature mapping)
"""

import contextlib
import importlib
import io
import json
import math
import os
import subprocess
import sys
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

BASE_DIR = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = BASE_DIR / "scripts"
DATA_DIR = BASE_DIR / "data"
DERIVED_DIR = BASE_DIR / "derived"
DERIVED_DIR.mkdir(parents=True, exist_ok=True)

if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))


class TestModuleImports(unittest.TestCase):
    """Test that all scripts in scripts/ can be imported without errors."""

    def test_all_scripts_importable(self):
        script_files = sorted(SCRIPTS_DIR.glob("*.py"))
        self.assertGreater(len(script_files), 20, "Should find at least 20 python scripts")
        for script_path in script_files:
            mod_name = script_path.stem
            with self.subTest(module=mod_name):
                try:
                    with contextlib.redirect_stdout(io.StringIO()):
                        mod = importlib.import_module(mod_name)
                    self.assertIsNotNone(mod)
                except Exception as e:
                    self.fail(f"Failed to import {mod_name}: {e}")


class TestDataIntegrity(unittest.TestCase):
    """Test data schemas and consistency across target and scs feature databases."""

    def test_target_features_json(self):
        tf_path = DATA_DIR / "target_features.json"
        self.assertTrue(tf_path.exists(), "target_features.json must exist")
        with open(tf_path) as f:
            features = json.load(f)
        self.assertIsInstance(features, list)
        self.assertEqual(len(features), 77, "target_features.json should contain 77 features")

        required_keys = {"key", "name", "group", "country", "lat", "lon"}
        for feat in features:
            self.assertTrue(required_keys.issubset(feat.keys()), f"Missing keys in {feat}")
            self.assertIsInstance(feat["lat"], (int, float))
            self.assertIsInstance(feat["lon"], (int, float))
            self.assertGreaterEqual(feat["lat"], 5.0)
            self.assertLessEqual(feat["lat"], 25.0)
            self.assertGreaterEqual(feat["lon"], 105.0)
            self.assertLessEqual(feat["lon"], 125.0)

    def test_scs_features_json(self):
        scs_path = DATA_DIR / "scs_features.json"
        self.assertTrue(scs_path.exists(), "scs_features.json must exist")
        with open(scs_path) as f:
            db = json.load(f)
        self.assertIn("island_groups", db)
        groups = db["island_groups"]
        self.assertIn("spratly_islands", groups)
        self.assertIn("paracel_islands", groups)

    def test_nisar_config_json(self):
        cfg_path = DATA_DIR / "nisar_config.json"
        self.assertTrue(cfg_path.exists(), "nisar_config.json must exist")
        with open(cfg_path) as f:
            cfg = json.load(f)
        self.assertIn("products", cfg)
        self.assertIn("feature_orbits", cfg)
        self.assertEqual(len(cfg["feature_orbits"]), 77, "Should configure orbits for 77 features")

    def test_ship_urls_json(self):
        urls_path = DATA_DIR / "ship_urls.json"
        if urls_path.exists():
            with open(urls_path) as f:
                urls = json.load(f)
            self.assertIsInstance(urls, (dict, list))


class TestSecretSafety(unittest.TestCase):
    """Test secret utilities and secret-safety contracts."""

    def test_has_configured_secret_rejects_placeholders(self):
        import secret_utils

        # Placeholders should be recognized
        self.assertTrue(secret_utils.is_placeholder_secret(None))
        self.assertTrue(secret_utils.is_placeholder_secret(""))
        self.assertTrue(secret_utils.is_placeholder_secret("your_api_key_here"))
        self.assertTrue(secret_utils.is_placeholder_secret("CHANGEME"))
        self.assertTrue(secret_utils.is_placeholder_secret("example_token"))

        # Real token should pass placeholder check
        self.assertFalse(secret_utils.is_placeholder_secret("PLNT_1234567890abcdef"))

    def test_secret_scan_in_derived(self):
        """Ensure no derived file contains raw secret keys or tokens."""
        import validate_mvp_snapshot

        for json_file in ["overview.json", "review_queue.json", "source_health.json"]:
            path = DERIVED_DIR / json_file
            if path.exists():
                with open(path) as f:
                    data = json.load(f)
                # assert_no_secret_strings raises ValidationError if leaks exist
                validate_mvp_snapshot.assert_no_secret_strings(data, json_file)


class TestChangeDetectionAlgorithms(unittest.TestCase):
    """Test image change detection calculations and classifications."""

    def test_ssim_identical_images(self):
        from change_detector import calculate_brightness_change, calculate_pixel_diff, calculate_ssim

        img = np.full((100, 100, 3), 128, dtype=np.uint8)
        score = calculate_ssim(img, img)
        self.assertAlmostEqual(score, 1.0, places=3)

        diff_pct = calculate_pixel_diff(img, img)
        self.assertAlmostEqual(diff_pct, 0.0, places=3)

        bright_pct = calculate_brightness_change(img, img)
        self.assertAlmostEqual(bright_pct, 0.0, places=3)

    def test_ssim_different_images(self):
        from change_detector import calculate_pixel_diff, calculate_ssim, classify_change

        img1 = np.full((100, 100, 3), 40, dtype=np.uint8)
        img2 = np.zeros((100, 100, 3), dtype=np.uint8)
        img2[:, :, 0] = 160  # Red
        img2[:, :, 1] = 120  # Green
        img2[:, :, 2] = 70   # Blue (non-cloud terrestrial color)

        score = calculate_ssim(img1, img2)
        self.assertLess(score, 0.85)

        diff_pct = calculate_pixel_diff(img1, img2)
        self.assertGreater(diff_pct, 50.0)

        types = classify_change(img1, img2, score, diff_pct, 10.0)
        self.assertIn("major_change", types)

        # Cloud interference test
        cloud_img = np.full((100, 100, 3), 240, dtype=np.uint8)
        cloud_types = classify_change(img1, cloud_img, score, diff_pct, 100.0)
        self.assertIn("cloud_interference", cloud_types)


class TestMVPSnapshotContract(unittest.TestCase):
    """Test MVP snapshot export and validation scripts."""

    def test_export_and_validate_mvp_snapshot(self):
        import export_mvp_snapshot
        import validate_mvp_snapshot

        with contextlib.redirect_stdout(io.StringIO()):
            export_mvp_snapshot.main()
            ret_validate = validate_mvp_snapshot.main()
        self.assertEqual(ret_validate, 0)


class TestHaversineAndSpatialCalculations(unittest.TestCase):
    """Test coordinate and distance calculations."""

    def test_haversine_distance(self):
        from quick_check import haversine_km

        # Distance between Woody Island (16.83N, 112.34E) and Rocky Island (16.80N, 112.30E) is ~5-6 km
        dist = haversine_km(16.83, 112.34, 16.80, 112.30)
        self.assertGreater(dist, 4.0)
        self.assertLess(dist, 7.0)

        # Same point should be 0 distance
        self.assertAlmostEqual(haversine_km(10.0, 110.0, 10.0, 110.0), 0.0, places=4)


class TestS2CorrelationAndOSINT(unittest.TestCase):
    """Test S2 optical correlation and OSINT cross-reference modules."""

    def test_s2_correlation_report_generation(self):
        import s2_correlation

        # Run correlation
        changes = s2_correlation.load_changes()
        self.assertIsInstance(changes, list)

    def test_osint_crossref_report_generation(self):
        import osint_crossref

        # Test report generation
        with contextlib.redirect_stdout(io.StringIO()):
            osint_crossref.generate_osint_report([])
        report_path = DERIVED_DIR / "osint_crossref_report.json"
        self.assertTrue(report_path.exists())


class TestAlertAndDailyReport(unittest.TestCase):
    """Test daily report and alert engines."""

    def test_alert_engine_no_crash(self):
        import alert_engine

        with contextlib.redirect_stdout(io.StringIO()):
            alerts = alert_engine.generate_all_alerts(hours=48)
        self.assertIsInstance(alerts, list)

    def test_daily_report_generation(self):
        import run_daily_report

        with contextlib.redirect_stdout(io.StringIO()):
            report = run_daily_report.generate_report(hours=24)
        self.assertIsInstance(report, str)
        self.assertIn("SCS Daily Report", report)


class TestAnalystWorkflows(unittest.TestCase):
    """Test Review Queue CLI and HTML Dashboard generator."""

    def test_review_queue_load(self):
        import review_queue

        queue = review_queue.load_review_queue()
        self.assertIsInstance(queue, list)

    def test_dashboard_generation(self):
        import generate_dashboard

        out_path = generate_dashboard.build_dashboard_html()
        self.assertTrue(Path(out_path).exists())
        self.assertTrue(Path(out_path).stat().st_size > 5000)


class TestCloudFilter(unittest.TestCase):
    """Test optical cloud detection, masking, and interference assessment."""

    def test_detect_cloud_mask_on_white_cloud(self):
        from cloud_filter import calculate_cloud_cover, detect_cloud_mask

        # High brightness white cloud image
        cloud_img = np.full((100, 100, 3), 240, dtype=np.uint8)
        mask = detect_cloud_mask(cloud_img)
        self.assertTrue(np.all(mask))
        self.assertEqual(calculate_cloud_cover(cloud_img), 100.0)

    def test_detect_cloud_mask_on_clear_ocean(self):
        from cloud_filter import calculate_cloud_cover, detect_cloud_mask

        # Dark blue clear ocean
        ocean_img = np.zeros((100, 100, 3), dtype=np.uint8)
        ocean_img[:, :, 2] = 80  # Blue
        ocean_img[:, :, 1] = 40  # Green
        ocean_img[:, :, 0] = 10  # Red
        mask = detect_cloud_mask(ocean_img)
        self.assertFalse(np.any(mask))
        self.assertEqual(calculate_cloud_cover(ocean_img), 0.0)

    def test_assess_cloud_interference(self):
        from cloud_filter import assess_cloud_interference

        clear_img = np.full((100, 100, 3), 40, dtype=np.uint8)
        cloud_img = np.full((100, 100, 3), 245, dtype=np.uint8)

        # Clear vs Clear
        res_clear = assess_cloud_interference(clear_img, clear_img)
        self.assertFalse(res_clear["is_cloud_obscured"])
        self.assertEqual(res_clear["recommendation"], "clear")

        # Clear vs Cloud
        res_cloudy = assess_cloud_interference(clear_img, cloud_img)
        self.assertTrue(res_cloudy["is_cloud_obscured"])
        self.assertEqual(res_cloudy["cloud_pct_image2"], 100.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
