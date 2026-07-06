"""
Tests for Agricultural Health Alert System
==========================================
Run with: python -m pytest tests/ -v
Or:       python tests/test_crop_health_alert.py
"""

import json
import os
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch, mock_open

# Ensure the parent directory is on the path
sys.path.insert(0, str(Path(__file__).parent.parent))

# ---------------------------------------------------------------------------
# Mock earthengine-api so tests run without GEE credentials
# ---------------------------------------------------------------------------
ee_mock = MagicMock()
ee_mock.EEException = Exception
sys.modules["ee"] = ee_mock

import crop_health_alert as cha


class TestConfigValidation(unittest.TestCase):
    """Tests for validate_config()."""

    def _base_cfg(self) -> dict:
        """Minimal valid configuration."""
        return {
            "AOI":             "test.geojson",
            "START_DATE":      "2024-06-01",
            "END_DATE":        "2024-06-30",
            "BASELINE_YEARS":  3,
            "SATELLITE":       "Sentinel-2",
            "NDVI_THRESHOLD":  1.0,
            "MIN_CLOUD_COVER": 20,
            "ALERT_METHOD":    "console",
            "OUTPUT_DIR":      "./alerts",
            "LOG_FILE":        None,
            "GENERATE_REPORT": False,
            "SMTP_SERVER":     None,
            "SMTP_PORT":       587,
            "SENDER_EMAIL":    None,
            "RECIPIENT_EMAILS": [],
            "SMTP_PASSWORD":   None,
            "GEE_CREDENTIALS_FILE": None,
            "GEE_PROJECT":     None,
        }

    def test_valid_config_passes(self):
        """A fully valid config should not raise."""
        cha.validate_config(self._base_cfg())

    def test_missing_aoi_raises(self):
        cfg = self._base_cfg()
        cfg["AOI"] = None
        with self.assertRaises(cha.ConfigError):
            cha.validate_config(cfg)

    def test_missing_start_date_raises(self):
        cfg = self._base_cfg()
        cfg["START_DATE"] = None
        with self.assertRaises(cha.ConfigError):
            cha.validate_config(cfg)

    def test_invalid_date_format_raises(self):
        cfg = self._base_cfg()
        cfg["START_DATE"] = "01-06-2024"   # wrong format
        with self.assertRaises(cha.ConfigError):
            cha.validate_config(cfg)

    def test_end_before_start_raises(self):
        cfg = self._base_cfg()
        cfg["START_DATE"] = "2024-07-01"
        cfg["END_DATE"]   = "2024-06-01"
        with self.assertRaises(cha.ConfigError):
            cha.validate_config(cfg)

    def test_negative_threshold_raises(self):
        cfg = self._base_cfg()
        cfg["NDVI_THRESHOLD"] = -0.5
        with self.assertRaises(cha.ConfigError):
            cha.validate_config(cfg)

    def test_zero_threshold_raises(self):
        cfg = self._base_cfg()
        cfg["NDVI_THRESHOLD"] = 0.0
        with self.assertRaises(cha.ConfigError):
            cha.validate_config(cfg)

    def test_invalid_satellite_raises(self):
        cfg = self._base_cfg()
        cfg["SATELLITE"] = "MODIS"
        with self.assertRaises(cha.ConfigError):
            cha.validate_config(cfg)

    def test_cloud_cover_out_of_range_raises(self):
        cfg = self._base_cfg()
        cfg["MIN_CLOUD_COVER"] = 150
        with self.assertRaises(cha.ConfigError):
            cha.validate_config(cfg)

    def test_email_method_without_smtp_raises(self):
        cfg = self._base_cfg()
        cfg["ALERT_METHOD"] = "email"
        cfg["SMTP_SERVER"]  = None
        with self.assertRaises(cha.ConfigError):
            cha.validate_config(cfg)

    def test_email_method_with_all_creds_passes(self):
        cfg = self._base_cfg()
        cfg["ALERT_METHOD"]     = "email"
        cfg["SMTP_SERVER"]      = "smtp.gmail.com"
        cfg["SENDER_EMAIL"]     = "me@gmail.com"
        cfg["SMTP_PASSWORD"]    = "secret"
        cfg["RECIPIENT_EMAILS"] = ["farmer@example.com"]
        cha.validate_config(cfg)   # should not raise

    def test_baseline_years_too_large_raises(self):
        cfg = self._base_cfg()
        cfg["BASELINE_YEARS"] = 15
        with self.assertRaises(cha.ConfigError):
            cha.validate_config(cfg)


class TestGetCollectionInfo(unittest.TestCase):
    """Tests for get_collection_info()."""

    def test_sentinel2_bands(self):
        info = cha.get_collection_info("Sentinel-2")
        self.assertEqual(info["nir_band"], "B8")
        self.assertEqual(info["red_band"], "B4")

    def test_landsat8_bands(self):
        info = cha.get_collection_info("Landsat-8")
        self.assertEqual(info["nir_band"], "SR_B5")
        self.assertEqual(info["red_band"], "SR_B4")

    def test_landsat9_bands(self):
        info = cha.get_collection_info("Landsat-9")
        self.assertEqual(info["nir_band"], "SR_B5")
        self.assertEqual(info["red_band"], "SR_B4")


class TestLoadConfig(unittest.TestCase):
    """Tests for load_config() with mock argparse namespace."""

    def _mock_args(self, **kwargs):
        args = MagicMock()
        # Set all attributes to None by default
        for attr in ["config", "aoi", "start", "end", "baseline_years",
                     "satellite", "ndvi_threshold", "cloud", "alert_method",
                     "output_dir", "log_file", "smtp_server", "smtp_port",
                     "sender", "recipient", "generate_report", "dry_run",
                     "mask_ag", "gee_project", "gee_creds"]:
            setattr(args, attr, None)
        for k, v in kwargs.items():
            setattr(args, k, v)
        return args

    def test_defaults_applied(self):
        args = self._mock_args()
        cfg = cha.load_config(args)
        self.assertEqual(cfg["BASELINE_YEARS"], 3)
        self.assertEqual(cfg["SATELLITE"], "Sentinel-2")

    def test_cli_overrides_defaults(self):
        args = self._mock_args(satellite="Landsat-8", ndvi_threshold=2.0)
        cfg = cha.load_config(args)
        self.assertEqual(cfg["SATELLITE"], "Landsat-8")
        self.assertEqual(cfg["NDVI_THRESHOLD"], 2.0)

    def test_config_file_loaded(self):
        file_cfg = {
            "AOI": "my_farm.geojson",
            "START_DATE": "2024-05-01",
            "END_DATE": "2024-05-31",
            "BASELINE_YEARS": 5,
        }
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json",
                                         delete=False, encoding="utf-8") as fh:
            json.dump(file_cfg, fh)
            tmp_path = fh.name

        try:
            args = self._mock_args(config=tmp_path)
            cfg = cha.load_config(args)
            self.assertEqual(cfg["BASELINE_YEARS"], 5)
            self.assertEqual(cfg["AOI"], "my_farm.geojson")
        finally:
            os.unlink(tmp_path)

    def test_env_var_password(self):
        args = self._mock_args()
        with patch.dict(os.environ, {"CROP_SMTP_PASSWORD": "env_secret"}):
            cfg = cha.load_config(args)
        self.assertEqual(cfg["SMTP_PASSWORD"], "env_secret")

    def test_recipient_string_split_to_list(self):
        args = self._mock_args(recipient="a@b.com, c@d.com")
        cfg = cha.load_config(args)
        self.assertIsInstance(cfg["RECIPIENT_EMAILS"], list)
        self.assertEqual(len(cfg["RECIPIENT_EMAILS"]), 2)


class TestLoadAOI(unittest.TestCase):
    """Tests for load_aoi()."""

    def test_geojson_feature_collection(self):
        gj = {
            "type": "FeatureCollection",
            "features": [{
                "type": "Feature",
                "properties": {},
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[0,0],[1,0],[1,1],[0,1],[0,0]]]
                }
            }]
        }
        with tempfile.NamedTemporaryFile(mode="w", suffix=".geojson",
                                         delete=False, encoding="utf-8") as fh:
            json.dump(gj, fh)
            tmp_path = fh.name

        try:
            geom = cha.load_aoi(tmp_path)
            # ee is mocked, just verify it was called
            self.assertIsNotNone(geom)
        finally:
            os.unlink(tmp_path)

    def test_invalid_path_raises_config_error(self):
        with self.assertRaises(cha.ConfigError):
            cha.load_aoi("/nonexistent/path/to/file.geojson")

    def test_inline_geojson_string(self):
        gj_str = '{"type":"Polygon","coordinates":[[[0,0],[1,0],[1,1],[0,1],[0,0]]]}'
        # Should not raise
        cha.load_aoi(gj_str)


class TestExportCSV(unittest.TestCase):
    """Tests for export_csv_summary()."""

    def test_csv_created_with_correct_columns(self):
        mock_fc_info = {
            "features": [{
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[78.0, 20.0], [79.0, 20.0],
                                     [79.0, 21.0], [78.0, 21.0], [78.0, 20.0]]]
                },
                "properties": {"mean": 0.45, "count": 120}
            }]
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = os.path.join(tmpdir, "test_summary.csv")

            # Mock the FeatureCollection
            mock_fc = MagicMock()
            mock_fc.getInfo.return_value = mock_fc_info

            cha.export_csv_summary(mock_fc, csv_path)

            self.assertTrue(Path(csv_path).exists())
            content = Path(csv_path).read_text(encoding="utf-8")
            self.assertIn("centroid_lon", content)
            self.assertIn("centroid_lat", content)
            self.assertIn("mean_ndvi", content)


class TestLogging(unittest.TestCase):
    """Tests for setup_logging()."""

    def test_returns_logger(self):
        logger = cha.setup_logging()
        self.assertIsInstance(logger, __import__("logging").Logger)

    def test_file_handler_created(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = os.path.join(tmpdir, "test.log")
            logger = cha.setup_logging(log_path)
            logger.info("test message")
            self.assertTrue(Path(log_path).exists())


class TestEmailSend(unittest.TestCase):
    """Tests for send_email_alert() – mocked SMTP."""

    def _email_cfg(self):
        return {
            "SMTP_SERVER":      "smtp.example.com",
            "SMTP_PORT":        587,
            "SENDER_EMAIL":     "sender@example.com",
            "RECIPIENT_EMAILS": ["farmer@example.com"],
            "SMTP_PASSWORD":    "secret",
            "SATELLITE":        "Sentinel-2",
            "START_DATE":       "2024-06-01",
            "END_DATE":         "2024-06-30",
            "NDVI_THRESHOLD":   1.5,
            "BASELINE_YEARS":   3,
        }

    @patch("smtplib.SMTP")
    def test_email_sent_on_success(self, mock_smtp_cls):
        mock_smtp = MagicMock()
        mock_smtp_cls.return_value.__enter__ = MagicMock(return_value=mock_smtp)
        mock_smtp_cls.return_value.__exit__ = MagicMock(return_value=False)

        cha.send_email_alert(self._email_cfg(), n_zones=3,
                              geojson_path=None, stats={"mean_ndvi": 0.35})

        mock_smtp_cls.assert_called_once()

    @patch("smtplib.SMTP", side_effect=Exception("Connection refused"))
    def test_email_failure_logs_warning_not_crash(self, mock_smtp_cls):
        """Email send failure should log warning, not raise."""
        # Should not raise
        cha.send_email_alert(self._email_cfg(), n_zones=3,
                              geojson_path=None, stats={})


# ---------------------------------------------------------------------------
# Run tests
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    unittest.main(verbosity=2)
