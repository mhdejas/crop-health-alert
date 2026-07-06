#!/usr/bin/env python3
"""
Agricultural Health Alert System
=================================
Monitors crop health using satellite NDVI data from Google Earth Engine.
Detects anomalous NDVI drops indicative of disease, pest outbreaks, or
water stress, and generates structured alerts via email, file, or console.

Author : Agricultural Remote Sensing Toolkit
Version: 1.0.0
License: MIT
Python : 3.9+
GEE API : >= 0.1.324

Usage:
    python crop_health_alert.py --config config.json
    python crop_health_alert.py --aoi farm.geojson --start 2024-06-01 --end 2024-06-30

See README.md for full documentation.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import smtplib
import sys
import tempfile
import traceback
from datetime import datetime, timedelta
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Third-party imports – give clear messages if missing
# ---------------------------------------------------------------------------
try:
    import ee
except ImportError:
    sys.exit(
        "ERROR: earthengine-api not installed.\n"
        "Run: pip install earthengine-api"
    )

try:
    from tqdm import tqdm
    TQDM_AVAILABLE = True
except ImportError:
    TQDM_AVAILABLE = False

try:
    import geemap
    GEEMAP_AVAILABLE = True
except ImportError:
    GEEMAP_AVAILABLE = False

try:
    from reportlab.lib.pagesizes import letter
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image as RLImage
    )
    REPORTLAB_AVAILABLE = True
except ImportError:
    REPORTLAB_AVAILABLE = False

# ---------------------------------------------------------------------------
# Default configuration
# ---------------------------------------------------------------------------
DEFAULT_CONFIG: Dict[str, Any] = {
    "AOI": None,                      # Path to GeoJSON/Shapefile or None
    "START_DATE": None,               # "YYYY-MM-DD"
    "END_DATE": None,                 # "YYYY-MM-DD"
    "BASELINE_YEARS": 3,
    "SATELLITE": "Sentinel-2",        # "Sentinel-2" | "Landsat-8" | "Landsat-9"
    "NDVI_THRESHOLD": 1.0,            # Std-devs below baseline mean
    "MIN_CLOUD_COVER": 20,            # Max cloud cover % per scene
    "ALERT_METHOD": "console",        # "email" | "file" | "console" | "all"
    "OUTPUT_DIR": "./alerts",
    "LOG_FILE": None,
    "GENERATE_REPORT": False,
    "DRY_RUN": False,
    "MASK_NON_AGRICULTURAL": True,    # Use ESA WorldCover to mask
    "SMTP_SERVER": None,
    "SMTP_PORT": 587,
    "SENDER_EMAIL": None,
    "RECIPIENT_EMAILS": [],           # List of email strings
    "SMTP_PASSWORD": None,
    "GEE_CREDENTIALS_FILE": None,     # Service account JSON, or None for default
    "GEE_PROJECT": None,              # GEE cloud project ID (required for newer API)
}

# ---------------------------------------------------------------------------
# Custom exceptions
# ---------------------------------------------------------------------------
class ConfigError(ValueError):
    """Raised when configuration is invalid."""

class EEInitError(RuntimeError):
    """Raised when Earth Engine initialisation fails."""

class NoImagesError(RuntimeError):
    """Raised when no valid images are found for a period."""

# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------
def setup_logging(log_file: Optional[str] = None) -> logging.Logger:
    """
    Configure root logger with console handler and optional file handler.

    Args:
        log_file: Path to write log file. If None, console-only.

    Returns:
        Configured logger instance.
    """
    fmt = "%(asctime)s [%(levelname)s] %(message)s"
    datefmt = "%Y-%m-%d %H:%M:%S"

    handlers: List[logging.Handler] = [logging.StreamHandler(sys.stdout)]
    if log_file:
        Path(log_file).parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(log_file, encoding="utf-8"))

    logging.basicConfig(level=logging.INFO, format=fmt, datefmt=datefmt, handlers=handlers)
    logger = logging.getLogger("CropHealthAlert")
    return logger


logger = setup_logging()  # replaced later after config is loaded

# ---------------------------------------------------------------------------
# Parameter validation
# ---------------------------------------------------------------------------
def validate_config(cfg: Dict[str, Any]) -> None:
    """
    Validate all configuration parameters and raise ConfigError on failure.

    Args:
        cfg: Configuration dictionary to validate.

    Raises:
        ConfigError: If any parameter is invalid or missing.
    """
    # Required fields
    if not cfg.get("AOI"):
        raise ConfigError("AOI must be specified (GeoJSON path, shapefile, or WKT).")
    if not cfg.get("START_DATE"):
        raise ConfigError("START_DATE is required (YYYY-MM-DD).")
    if not cfg.get("END_DATE"):
        raise ConfigError("END_DATE is required (YYYY-MM-DD).")

    # Date format validation
    date_re = re.compile(r"^\d{4}-\d{2}-\d{2}$")
    for key in ("START_DATE", "END_DATE"):
        if not date_re.match(str(cfg[key])):
            raise ConfigError(f"{key} must be YYYY-MM-DD, got: {cfg[key]}")

    start = datetime.strptime(cfg["START_DATE"], "%Y-%m-%d")
    end   = datetime.strptime(cfg["END_DATE"],   "%Y-%m-%d")
    if end <= start:
        raise ConfigError("END_DATE must be after START_DATE.")

    # Numeric ranges
    if not (0 < cfg["BASELINE_YEARS"] <= 10):
        raise ConfigError("BASELINE_YEARS must be between 1 and 10.")
    if cfg["NDVI_THRESHOLD"] <= 0:
        raise ConfigError("NDVI_THRESHOLD must be a positive number.")
    if not (0 <= cfg["MIN_CLOUD_COVER"] <= 100):
        raise ConfigError("MIN_CLOUD_COVER must be 0–100.")

    # Satellite
    valid_sats = {"Sentinel-2", "Landsat-8", "Landsat-9"}
    if cfg["SATELLITE"] not in valid_sats:
        raise ConfigError(f"SATELLITE must be one of {valid_sats}.")

    # Alert method
    valid_methods = {"email", "file", "console", "all"}
    methods = {cfg["ALERT_METHOD"]} if isinstance(cfg["ALERT_METHOD"], str) else set(cfg["ALERT_METHOD"])
    if not methods.issubset(valid_methods):
        raise ConfigError(f"ALERT_METHOD must be from {valid_methods}.")

    # Email credentials
    needs_email = cfg["ALERT_METHOD"] in ("email", "all")
    if needs_email:
        missing = [k for k in ("SMTP_SERVER", "SENDER_EMAIL", "SMTP_PASSWORD") if not cfg.get(k)]
        if missing:
            raise ConfigError(
                f"Email alert requires: {missing}. "
                "Set them in config or environment variables."
            )
        if not cfg.get("RECIPIENT_EMAILS"):
            raise ConfigError("RECIPIENT_EMAILS must list at least one address.")

    # Report
    if cfg.get("GENERATE_REPORT") and not REPORTLAB_AVAILABLE:
        logger.warning("GENERATE_REPORT=True but reportlab is not installed. Report will be skipped.")

# ---------------------------------------------------------------------------
# Earth Engine initialisation
# ---------------------------------------------------------------------------
def initialize_ee(cfg: Dict[str, Any]) -> None:
    """
    Initialise Google Earth Engine with service-account credentials or
    fall back to the default authenticated user.

    Args:
        cfg: Configuration dict; checks GEE_CREDENTIALS_FILE and GEE_PROJECT.

    Raises:
        EEInitError: If initialisation fails.
    """
    cred_file = cfg.get("GEE_CREDENTIALS_FILE")
    project   = cfg.get("GEE_PROJECT")

    try:
        if cred_file:
            credentials = ee.ServiceAccountCredentials(
                email=None,   # read from the JSON file
                key_file=cred_file
            )
            ee.Initialize(credentials, project=project)
        else:
            ee.Initialize(project=project)
        logger.info("Earth Engine initialised successfully.")
    except ee.EEException as exc:
        if "not authenticated" in str(exc).lower() or "credentials" in str(exc).lower():
            raise EEInitError(
                "Earth Engine is not authenticated.\n"
                "Run: earthengine authenticate\n"
                "Or provide GEE_CREDENTIALS_FILE in your config."
            ) from exc
        raise EEInitError(f"Earth Engine initialisation failed: {exc}") from exc

# ---------------------------------------------------------------------------
# AOI loading
# ---------------------------------------------------------------------------
def load_aoi(aoi_path: str) -> ee.Geometry:
    """
    Load an Area of Interest from a GeoJSON file, shapefile, or WKT string.

    Args:
        aoi_path: Path to .geojson / .shp file, or an inline GeoJSON string.

    Returns:
        ee.Geometry representing the AOI.

    Raises:
        ConfigError: If the file cannot be read or parsed.
    """
    path = Path(aoi_path)

    # --- GeoJSON file ---------------------------------------------------------
    if path.suffix.lower() in (".geojson", ".json"):
        try:
            with open(path, encoding="utf-8") as fh:
                gj = json.load(fh)
        except (OSError, json.JSONDecodeError) as exc:
            raise ConfigError(f"Cannot read GeoJSON file '{path}': {exc}") from exc

        # Support FeatureCollection or Feature or Geometry
        if gj.get("type") == "FeatureCollection":
            fc = ee.FeatureCollection(gj)
            geometry = fc.geometry()
        elif gj.get("type") == "Feature":
            geometry = ee.Feature(gj).geometry()
        else:
            geometry = ee.Geometry(gj)
        logger.info("AOI loaded from GeoJSON: %s", path.name)
        return geometry

    # --- Shapefile ------------------------------------------------------------
    if path.suffix.lower() == ".shp":
        if GEEMAP_AVAILABLE:
            fc = geemap.shp_to_ee(str(path))
            logger.info("AOI loaded from shapefile via geemap: %s", path.name)
            return fc.geometry()
        else:
            raise ConfigError(
                "geemap is required to load shapefiles. "
                "Install it with: pip install geemap\n"
                "Or convert your shapefile to GeoJSON first."
            )

    # --- Inline GeoJSON string ------------------------------------------------
    try:
        gj = json.loads(aoi_path)
        geometry = ee.Geometry(gj)
        logger.info("AOI loaded from inline GeoJSON string.")
        return geometry
    except (json.JSONDecodeError, Exception):
        pass

    raise ConfigError(
        f"Cannot interpret AOI: '{aoi_path}'. "
        "Provide a .geojson file path, .shp file path, or inline GeoJSON string."
    )

# ---------------------------------------------------------------------------
# Band & collection helpers
# ---------------------------------------------------------------------------
def get_collection_info(satellite: str) -> Dict[str, str]:
    """
    Return GEE collection ID and band names for the chosen satellite.

    Args:
        satellite: "Sentinel-2" | "Landsat-8" | "Landsat-9"

    Returns:
        Dict with keys: collection_id, nir_band, red_band, cloud_band, cloud_threshold
    """
    mapping = {
        "Sentinel-2": {
            "collection_id": "COPERNICUS/S2_SR_HARMONIZED",
            "nir_band":       "B8",
            "red_band":       "B4",
            "cloud_band":     "CLOUDY_PIXEL_PERCENTAGE",
            "cloud_threshold": None,  # filter at image level
        },
        "Landsat-8": {
            "collection_id": "LANDSAT/LC08/C02/T1_L2",
            "nir_band":       "SR_B5",
            "red_band":       "SR_B4",
            "cloud_band":     "CLOUD_COVER",
            "cloud_threshold": None,
        },
        "Landsat-9": {
            "collection_id": "LANDSAT/LC09/C02/T1_L2",
            "nir_band":       "SR_B5",
            "red_band":       "SR_B4",
            "cloud_band":     "CLOUD_COVER",
            "cloud_threshold": None,
        },
    }
    return mapping[satellite]

# ---------------------------------------------------------------------------
# Core GEE functions
# ---------------------------------------------------------------------------
def compute_ndvi(image: ee.Image, nir_band: str, red_band: str) -> ee.Image:
    """
    Compute NDVI for a single image.

    NDVI = (NIR - RED) / (NIR + RED)

    Args:
        image:    Input ee.Image.
        nir_band: Name of the near-infrared band.
        red_band: Name of the red band.

    Returns:
        ee.Image with a single band 'NDVI' in [-1, 1].
    """
    ndvi = image.normalizedDifference([nir_band, red_band]).rename("NDVI")
    return image.addBands(ndvi)


def get_cloud_filtered_collection(
    collection_id: str,
    aoi: ee.Geometry,
    start_date: str,
    end_date: str,
    max_cloud: int,
    cloud_band: str,
) -> ee.ImageCollection:
    """
    Load an image collection filtered by AOI, date range, and cloud cover.

    Args:
        collection_id: GEE collection asset ID.
        aoi:           Area of interest geometry.
        start_date:    ISO date string YYYY-MM-DD.
        end_date:      ISO date string YYYY-MM-DD.
        max_cloud:     Maximum allowed cloud cover percentage.
        cloud_band:    Property name for cloud cover in image metadata.

    Returns:
        Filtered ee.ImageCollection.
    """
    return (
        ee.ImageCollection(collection_id)
        .filterBounds(aoi)
        .filterDate(start_date, end_date)
        .filter(ee.Filter.lte(cloud_band, max_cloud))
    )


def mask_agricultural_land(image: ee.Image, aoi: ee.Geometry) -> ee.Image:
    """
    Mask out non-agricultural pixels using ESA WorldCover 10 m (2021).

    Agricultural class codes in WorldCover:
        40 = Cropland

    Args:
        image: Input ee.Image (must already have an NDVI band).
        aoi:   Area of interest.

    Returns:
        Image with non-cropland pixels masked.
    """
    worldcover = ee.ImageCollection("ESA/WorldCover/v200").first().clip(aoi)
    cropland_mask = worldcover.eq(40)  # class 40 = Cropland
    return image.updateMask(cropland_mask)


def compute_baseline(
    aoi: ee.Geometry,
    start_date: str,
    end_date: str,
    baseline_years: int,
    satellite: str,
    max_cloud: int,
    mask_ag: bool,
) -> Tuple[ee.Image, ee.Image]:
    """
    Compute historical NDVI baseline mean and std-dev over N previous years,
    using the same month window as the monitoring period.

    Args:
        aoi:            Area of interest.
        start_date:     Monitoring period start (YYYY-MM-DD).
        end_date:       Monitoring period end (YYYY-MM-DD).
        baseline_years: Number of prior years to include.
        satellite:      Satellite name.
        max_cloud:      Max cloud cover %.
        mask_ag:        Whether to apply agricultural land mask.

    Returns:
        Tuple of (baseline_mean, baseline_stddev) as ee.Image objects.

    Raises:
        NoImagesError: If no valid images found in any baseline year.
    """
    info = get_collection_info(satellite)
    nir, red = info["nir_band"], info["red_band"]

    s_dt = datetime.strptime(start_date, "%Y-%m-%d")
    e_dt = datetime.strptime(end_date,   "%Y-%m-%d")

    annual_composites: List[ee.Image] = []

    steps = list(range(1, baseline_years + 1))
    iterator = tqdm(steps, desc="Building baseline", unit="year") if TQDM_AVAILABLE else steps

    for offset in iterator:
        yr_start = (s_dt.replace(year=s_dt.year - offset)).strftime("%Y-%m-%d")
        yr_end   = (e_dt.replace(year=e_dt.year - offset)).strftime("%Y-%m-%d")

        logger.info("  Computing baseline for year %s → %s", yr_start[:4], yr_end[:4])

        col = get_cloud_filtered_collection(
            info["collection_id"], aoi, yr_start, yr_end,
            max_cloud, info["cloud_band"]
        )

        # Check if any images exist (using getInfo – unavoidable for validation)
        count = col.size().getInfo()
        if count == 0:
            logger.warning("  No images for baseline year %s, skipping.", yr_start[:4])
            continue

        # Map NDVI computation
        with_ndvi = col.map(lambda img: compute_ndvi(img, nir, red))
        composite = with_ndvi.select("NDVI").median()

        if mask_ag:
            composite = mask_agricultural_land(composite, aoi)

        annual_composites.append(composite)

    if not annual_composites:
        raise NoImagesError(
            "No valid images found in any baseline year. "
            "Try reducing MIN_CLOUD_COVER or extending the date range."
        )

    baseline_stack = ee.ImageCollection(annual_composites)
    baseline_mean  = baseline_stack.mean().rename("baseline_mean")
    baseline_std   = baseline_stack.reduce(ee.Reducer.stdDev()).rename("baseline_stddev")

    logger.info("Baseline computed from %d year(s).", len(annual_composites))
    return baseline_mean, baseline_std


def compute_current_ndvi(
    aoi: ee.Geometry,
    start_date: str,
    end_date: str,
    satellite: str,
    max_cloud: int,
    mask_ag: bool,
) -> ee.Image:
    """
    Compute a median NDVI composite for the current monitoring period.

    Args:
        aoi:        Area of interest.
        start_date: Monitoring period start (YYYY-MM-DD).
        end_date:   Monitoring period end (YYYY-MM-DD).
        satellite:  Satellite name.
        max_cloud:  Max cloud cover %.
        mask_ag:    Whether to apply agricultural land mask.

    Returns:
        ee.Image with band 'NDVI'.

    Raises:
        NoImagesError: If no valid images are found.
    """
    info = get_collection_info(satellite)
    nir, red = info["nir_band"], info["red_band"]

    col = get_cloud_filtered_collection(
        info["collection_id"], aoi, start_date, end_date,
        max_cloud, info["cloud_band"]
    )

    count = col.size().getInfo()
    if count == 0:
        raise NoImagesError(
            f"No valid images found for monitoring period {start_date} → {end_date}. "
            "Try reducing MIN_CLOUD_COVER."
        )

    logger.info("Found %d image(s) for monitoring period.", count)
    with_ndvi = col.map(lambda img: compute_ndvi(img, nir, red))
    composite = with_ndvi.select("NDVI").median()

    if mask_ag:
        composite = mask_agricultural_land(composite, aoi)

    logger.info("Current NDVI composite completed.")
    return composite.rename("NDVI")


def detect_anomaly(
    current_ndvi: ee.Image,
    baseline_mean: ee.Image,
    baseline_std: ee.Image,
    threshold: float,
    aoi: ee.Geometry,
) -> Tuple[ee.Image, ee.FeatureCollection]:
    """
    Detect NDVI anomalies where current NDVI drops significantly below baseline.

    Anomaly score = (current - baseline_mean) / baseline_stddev
    Alert mask    = anomaly < -threshold

    Args:
        current_ndvi:  Current period NDVI image.
        baseline_mean: Historical mean NDVI.
        baseline_std:  Historical std-dev NDVI.
        threshold:     Negative z-score threshold for alerting.
        aoi:           Area of interest.

    Returns:
        Tuple of (anomaly_score image, alert_zones FeatureCollection).
    """
    # Compute normalised anomaly (z-score style)
    anomaly = (
        current_ndvi.subtract(baseline_mean)
        .divide(baseline_std.add(1e-6))   # avoid division by zero
        .rename("anomaly_score")
    )

    # Apply spatial smoothing (3×3 focal mean) to reduce noise
    anomaly_smoothed = anomaly.focal_mean(radius=1, kernelType="square", units="pixels")

    # Binary alert mask: 1 where NDVI dropped more than threshold std-devs
    alert_mask = anomaly_smoothed.lt(-threshold).selfMask()

    # Convert to vectors (polygons) – NOTE: reduceToVectors can be slow for large AOIs
    logger.info("Converting anomaly raster to vector alert zones …")
    alert_vectors = alert_mask.reduceToVectors(
        geometry=aoi,
        scale=20,                         # 20 m for Sentinel-2; adjust for Landsat
        geometryType="polygon",
        eightConnected=False,
        maxPixels=1e9,
        reducer=ee.Reducer.countEvery(),
    )

    # Attach mean NDVI anomaly statistic to each zone
    alert_vectors = current_ndvi.reduceRegions(
        collection=alert_vectors,
        reducer=ee.Reducer.mean(),
        scale=20,
    )

    logger.info("Anomaly detection completed.")
    return anomaly_smoothed, alert_vectors


# ---------------------------------------------------------------------------
# Export helpers
# ---------------------------------------------------------------------------
def export_geojson(features: ee.FeatureCollection, output_path: str) -> int:
    """
    Export a FeatureCollection to a local GeoJSON file via getInfo().

    This is appropriate for small/medium alert zones. For very large exports,
    prefer ee.batch.Export.table.toDrive().

    Args:
        features:    ee.FeatureCollection to export.
        output_path: Destination file path.

    Returns:
        Number of features written.
    """
    logger.info("Fetching alert vectors from Earth Engine …")
    fc_info = features.getInfo()
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as fh:
        json.dump(fc_info, fh, indent=2)
    n_feats = len(fc_info.get("features", []))
    logger.info("Exported %d alert zone(s) → %s", n_feats, output_path)
    return n_feats


def export_csv_summary(features: ee.FeatureCollection, output_path: str) -> None:
    """
    Export a CSV summary of alert zones with centroid, area, and mean NDVI.

    Args:
        features:    ee.FeatureCollection (should have 'mean' property).
        output_path: Destination CSV file path.
    """
    import csv

    fc_info = features.getInfo()
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    rows = []
    for feat in fc_info.get("features", []):
        geom  = feat.get("geometry", {})
        props = feat.get("properties", {})

        # Compute approximate centroid
        coords = geom.get("coordinates", [[]])
        cx, cy = None, None
        if coords and isinstance(coords[0], list) and len(coords[0]) > 0:
            ring = coords[0]
            # Normalise to a flat list of [lon, lat] pairs
            if ring and isinstance(ring[0], (int, float)):
                flat = [ring]
            elif ring and isinstance(ring[0], (list, tuple)) and isinstance(ring[0][0], (int, float)):
                flat = ring
            elif ring and isinstance(ring[0], (list, tuple)):
                flat = ring[0]
            else:
                flat = []
            valid = [p for p in flat if isinstance(p, (list, tuple)) and len(p) >= 2]
            if valid:
                cx = sum(p[0] for p in valid) / len(valid)
                cy = sum(p[1] for p in valid) / len(valid)

        rows.append({
            "centroid_lon": round(cx, 6) if cx else "",
            "centroid_lat": round(cy, 6) if cy else "",
            "mean_ndvi":    round(props.get("mean", 0), 4),
            "pixel_count":  props.get("count", ""),
            "geometry_type": geom.get("type", ""),
        })

    with open(output_path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=["centroid_lon", "centroid_lat",
                                                 "mean_ndvi", "pixel_count", "geometry_type"])
        writer.writeheader()
        writer.writerows(rows)

    logger.info("CSV summary exported → %s", output_path)


# ---------------------------------------------------------------------------
# Email
# ---------------------------------------------------------------------------
def send_email_alert(
    cfg: Dict[str, Any],
    n_zones: int,
    geojson_path: Optional[str],
    stats: Dict[str, Any],
) -> None:
    """
    Send an HTML alert email with optional GeoJSON attachment.

    SMTP credentials are read from cfg (which itself reads from env vars
    if not provided directly – see load_config).

    Args:
        cfg:          Configuration dict with SMTP settings.
        n_zones:      Number of detected alert zones.
        geojson_path: Path to GeoJSON file to attach (may be None).
        stats:        Dict of summary statistics to include in email body.
    """
    smtp_server  = cfg["SMTP_SERVER"]
    smtp_port    = int(cfg["SMTP_PORT"])
    sender       = cfg["SENDER_EMAIL"]
    recipients   = cfg["RECIPIENT_EMAILS"]
    password     = cfg["SMTP_PASSWORD"]

    if isinstance(recipients, str):
        recipients = [r.strip() for r in recipients.split(",")]

    subject = (
        f"🌾 Crop Health Alert – {n_zones} anomaly zone(s) detected "
        f"[{cfg['START_DATE']} → {cfg['END_DATE']}]"
    )

    html_body = f"""
    <html><body>
    <h2 style="color:#c0392b;">⚠️ Agricultural Health Alert</h2>
    <p>The Crop Health Alert System has detected <strong>{n_zones}</strong>
    anomalous NDVI zone(s) in your area of interest during the monitoring period
    <strong>{cfg['START_DATE']}</strong> to <strong>{cfg['END_DATE']}</strong>.</p>

    <h3>Summary Statistics</h3>
    <table border="1" cellpadding="6" style="border-collapse:collapse;">
      <tr><th>Metric</th><th>Value</th></tr>
      <tr><td>Satellite</td><td>{cfg['SATELLITE']}</td></tr>
      <tr><td>Alert zones detected</td><td>{n_zones}</td></tr>
      <tr><td>NDVI threshold (σ)</td><td>{cfg['NDVI_THRESHOLD']}</td></tr>
      <tr><td>Baseline years</td><td>{cfg['BASELINE_YEARS']}</td></tr>
      <tr><td>Mean NDVI (alert zones)</td><td>{stats.get('mean_ndvi', 'N/A')}</td></tr>
    </table>

    <h3>Recommended Actions</h3>
    <ul>
      <li>Inspect highlighted fields for signs of disease, pest damage, or water stress.</li>
      <li>Cross-reference with recent rainfall and temperature records.</li>
      <li>Consider commissioning a ground-truth survey for affected zones.</li>
    </ul>

    <p>The attached GeoJSON file contains the exact geometries of affected zones
    and can be opened in QGIS, ArcGIS, or any GIS tool.</p>

    <p style="color:#7f8c8d; font-size:0.9em;">
    Generated by Agricultural Health Alert System – {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}
    </p>
    </body></html>
    """

    msg = MIMEMultipart("mixed")
    msg["Subject"] = subject
    msg["From"]    = sender
    msg["To"]      = ", ".join(recipients)
    msg.attach(MIMEText(html_body, "html"))

    if geojson_path and Path(geojson_path).exists():
        with open(geojson_path, "rb") as fh:
            part = MIMEBase("application", "octet-stream")
            part.set_payload(fh.read())
        encoders.encode_base64(part)
        part.add_header("Content-Disposition", "attachment",
                        filename=Path(geojson_path).name)
        msg.attach(part)

    try:
        with smtplib.SMTP(smtp_server, smtp_port, timeout=30) as server:
            server.ehlo()
            server.starttls()
            server.login(sender, password)
            server.sendmail(sender, recipients, msg.as_string())
        logger.info("Alert email sent to: %s", recipients)
    except (smtplib.SMTPException, OSError, Exception) as exc:
        logger.warning("Failed to send email alert: %s", exc)


# ---------------------------------------------------------------------------
# PDF report
# ---------------------------------------------------------------------------
def generate_pdf_report(
    cfg: Dict[str, Any],
    n_zones: int,
    stats: Dict[str, Any],
    output_path: str,
    map_image_path: Optional[str] = None,
) -> None:
    """
    Generate a PDF report summarising the analysis results.

    Requires reportlab. If not available, logs a warning and returns.

    Args:
        cfg:            Configuration dict.
        n_zones:        Number of alert zones detected.
        stats:          Summary statistics dictionary.
        output_path:    Destination PDF path.
        map_image_path: Optional path to a PNG map image to embed.
    """
    if not REPORTLAB_AVAILABLE:
        logger.warning("reportlab not installed – PDF report skipped.")
        return

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(output_path, pagesize=letter)
    styles = getSampleStyleSheet()
    story = []

    # Title
    story.append(Paragraph("Agricultural Health Alert Report", styles["Title"]))
    story.append(Spacer(1, 12))
    story.append(Paragraph(
        f"Generated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}",
        styles["Normal"]
    ))
    story.append(Spacer(1, 20))

    # Summary table
    data = [
        ["Parameter",       "Value"],
        ["Satellite",        cfg["SATELLITE"]],
        ["Monitoring period", f"{cfg['START_DATE']} → {cfg['END_DATE']}"],
        ["Baseline years",   str(cfg["BASELINE_YEARS"])],
        ["NDVI threshold",   str(cfg["NDVI_THRESHOLD"]) + " σ"],
        ["Alert zones",      str(n_zones)],
        ["Mean NDVI (zones)", str(stats.get("mean_ndvi", "N/A"))],
    ]
    tbl = Table(data, colWidths=[200, 300])
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.darkgreen),
        ("TEXTCOLOR",  (0, 0), (-1, 0), colors.white),
        ("FONTNAME",   (0, 0), (-1, 0), "Helvetica-Bold"),
        ("GRID",       (0, 0), (-1, -1), 0.5, colors.grey),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.whitesmoke, colors.white]),
    ]))
    story.append(tbl)
    story.append(Spacer(1, 20))

    # Map image (if available)
    if map_image_path and Path(map_image_path).exists():
        story.append(Paragraph("NDVI Anomaly Map", styles["Heading2"]))
        story.append(RLImage(map_image_path, width=450, height=300))
        story.append(Spacer(1, 12))

    # Interpretation
    story.append(Paragraph("Interpretation", styles["Heading2"]))
    interp = (
        "Areas flagged in this report show a statistically significant decline in NDVI "
        "relative to the historical baseline. This may indicate crop stress caused by "
        "pest infestation, fungal/bacterial disease, drought, or nutrient deficiency. "
        "Ground-truth verification is recommended before taking remedial action."
    )
    story.append(Paragraph(interp, styles["Normal"]))

    doc.build(story)
    logger.info("PDF report generated → %s", output_path)


# ---------------------------------------------------------------------------
# Static map export (optional via geemap)
# ---------------------------------------------------------------------------
def export_map_thumbnail(
    current_ndvi: ee.Image,
    anomaly: ee.Image,
    aoi: ee.Geometry,
    output_path: str,
) -> Optional[str]:
    """
    Export a static PNG thumbnail of the NDVI and anomaly layers.

    Uses Earth Engine's getThumbURL (no geemap required).

    Args:
        current_ndvi: Current NDVI image.
        anomaly:      Anomaly score image.
        aoi:          Area of interest geometry.
        output_path:  Destination PNG path.

    Returns:
        Path to saved image, or None on failure.
    """
    import urllib.request

    try:
        vis_ndvi = {"min": -0.1, "max": 0.9, "palette": ["red", "yellow", "green"]}
        thumb_url = current_ndvi.getThumbURL({
            **vis_ndvi,
            "region": aoi,
            "dimensions": 512,
            "format": "PNG",
        })
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        urllib.request.urlretrieve(thumb_url, output_path)
        logger.info("Map thumbnail saved → %s", output_path)
        return output_path
    except Exception as exc:
        logger.warning("Could not export map thumbnail: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Alert orchestration
# ---------------------------------------------------------------------------
def generate_alerts(
    cfg: Dict[str, Any],
    alert_zones: ee.FeatureCollection,
    current_ndvi: ee.Image,
    anomaly: ee.Image,
    aoi: ee.Geometry,
) -> Dict[str, Any]:
    """
    Orchestrate all alert outputs (file, email, console, report).

    Args:
        cfg:         Configuration dictionary.
        alert_zones: FeatureCollection of anomaly polygons.
        current_ndvi: Current NDVI composite.
        anomaly:      Anomaly score image.
        aoi:          Area of interest.

    Returns:
        Stats dictionary summarising what was generated.
    """
    out_dir = Path(cfg["OUTPUT_DIR"])
    out_dir.mkdir(parents=True, exist_ok=True)

    ts          = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    geojson_path = str(out_dir / f"alert_zones_{ts}.geojson")
    csv_path     = str(out_dir / f"alert_summary_{ts}.csv")
    map_path     = str(out_dir / f"ndvi_map_{ts}.png")
    pdf_path     = str(out_dir / f"alert_report_{ts}.pdf")

    method = cfg["ALERT_METHOD"]
    write_file   = method in ("file", "all")
    send_mail    = method in ("email", "all")
    to_console   = method in ("console", "all")

    # Always get the zone count (cheap metadata call)
    n_zones = alert_zones.size().getInfo()
    stats: Dict[str, Any] = {"n_zones": n_zones}

    if n_zones == 0:
        logger.info("No anomaly zones detected – no alert generated.")
        if to_console:
            print("\n✅  No significant NDVI anomalies detected in the monitoring period.\n")
        return stats

    logger.info("Alert zones detected: %d", n_zones)

    # --- File export ----------------------------------------------------------
    if write_file or send_mail:
        export_geojson(alert_zones, geojson_path)
        export_csv_summary(alert_zones, csv_path)
    if not write_file and send_mail:
        # Still need the file to attach – generated above, cleanup after
        pass

    # Compute mean NDVI over alert zones for stats
    try:
        mean_ndvi_info = (
            current_ndvi
            .reduceRegion(ee.Reducer.mean(), alert_zones.geometry(), scale=20, maxPixels=1e9)
            .getInfo()
        )
        stats["mean_ndvi"] = round(mean_ndvi_info.get("NDVI", 0), 4)
    except Exception as exc:
        logger.warning("Could not compute mean NDVI statistic: %s", exc)
        stats["mean_ndvi"] = "N/A"

    # --- Map thumbnail --------------------------------------------------------
    map_file = None
    if not cfg.get("DRY_RUN"):
        map_file = export_map_thumbnail(current_ndvi, anomaly, aoi, map_path)

    # --- PDF report -----------------------------------------------------------
    if cfg.get("GENERATE_REPORT") and not cfg.get("DRY_RUN"):
        generate_pdf_report(cfg, n_zones, stats, pdf_path, map_file)

    # --- Email ----------------------------------------------------------------
    if send_mail and not cfg.get("DRY_RUN"):
        send_email_alert(cfg, n_zones, geojson_path if write_file or send_mail else None, stats)

    # --- Console summary ------------------------------------------------------
    if to_console or cfg.get("DRY_RUN"):
        print("\n" + "=" * 60)
        print("  🌾  CROP HEALTH ALERT SYSTEM — RESULTS")
        print("=" * 60)
        print(f"  Monitoring period : {cfg['START_DATE']} → {cfg['END_DATE']}")
        print(f"  Satellite         : {cfg['SATELLITE']}")
        print(f"  NDVI threshold    : {cfg['NDVI_THRESHOLD']} σ")
        print(f"  Alert zones found : {n_zones}")
        print(f"  Mean NDVI (zones) : {stats.get('mean_ndvi', 'N/A')}")
        if write_file:
            print(f"  GeoJSON saved to  : {geojson_path}")
            print(f"  CSV saved to      : {csv_path}")
        if map_file:
            print(f"  Map thumbnail     : {map_file}")
        if cfg.get("GENERATE_REPORT") and Path(pdf_path).exists():
            print(f"  PDF report        : {pdf_path}")
        print("=" * 60 + "\n")

    return stats


# ---------------------------------------------------------------------------
# Configuration loading
# ---------------------------------------------------------------------------
def load_config(args: argparse.Namespace) -> Dict[str, Any]:
    """
    Merge configuration from (in priority order):
      1. JSON config file (--config)
      2. Command-line arguments
      3. Environment variables (EMAIL_* and SMTP_*)
      4. DEFAULT_CONFIG

    Args:
        args: Parsed argparse namespace.

    Returns:
        Final merged configuration dictionary.
    """
    cfg = dict(DEFAULT_CONFIG)

    # 1. JSON config file
    if args.config:
        config_path = Path(args.config)
        if not config_path.exists():
            raise ConfigError(f"Config file not found: {config_path}")
        with open(config_path, encoding="utf-8") as fh:
            file_cfg = json.load(fh)
        cfg.update(file_cfg)

    # 2. CLI arguments (only override if explicitly provided)
    cli_map = {
        "aoi":            "AOI",
        "start":          "START_DATE",
        "end":            "END_DATE",
        "baseline_years": "BASELINE_YEARS",
        "satellite":      "SATELLITE",
        "ndvi_threshold": "NDVI_THRESHOLD",
        "cloud":          "MIN_CLOUD_COVER",
        "alert_method":   "ALERT_METHOD",
        "output_dir":     "OUTPUT_DIR",
        "log_file":       "LOG_FILE",
        "smtp_server":    "SMTP_SERVER",
        "smtp_port":      "SMTP_PORT",
        "sender":         "SENDER_EMAIL",
        "recipient":      "RECIPIENT_EMAILS",
        "generate_report":"GENERATE_REPORT",
        "dry_run":        "DRY_RUN",
        "mask_ag":        "MASK_NON_AGRICULTURAL",
        "gee_project":    "GEE_PROJECT",
        "gee_creds":      "GEE_CREDENTIALS_FILE",
    }
    for cli_key, cfg_key in cli_map.items():
        val = getattr(args, cli_key, None)
        if val is not None:
            cfg[cfg_key] = val

    # Handle recipient as list
    if isinstance(cfg.get("RECIPIENT_EMAILS"), str):
        cfg["RECIPIENT_EMAILS"] = [r.strip() for r in cfg["RECIPIENT_EMAILS"].split(",")]

    # 3. Environment variables for sensitive values
    env_map = {
        "SMTP_SERVER":   "CROP_SMTP_SERVER",
        "SMTP_PORT":     "CROP_SMTP_PORT",
        "SENDER_EMAIL":  "CROP_SENDER_EMAIL",
        "SMTP_PASSWORD": "CROP_SMTP_PASSWORD",
        "GEE_PROJECT":   "GEE_PROJECT",
    }
    for cfg_key, env_key in env_map.items():
        if not cfg.get(cfg_key) and os.environ.get(env_key):
            cfg[cfg_key] = os.environ[env_key]

    # Also check generic env var for password
    if not cfg.get("SMTP_PASSWORD"):
        cfg["SMTP_PASSWORD"] = os.environ.get("SMTP_PASSWORD")

    return cfg


# ---------------------------------------------------------------------------
# CLI argument parser
# ---------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    """Build and return the command-line argument parser."""
    parser = argparse.ArgumentParser(
        description="Agricultural Health Alert System – NDVI anomaly detection via GEE",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    parser.add_argument("--config",          help="Path to JSON config file")
    parser.add_argument("--aoi",             help="GeoJSON/shapefile path or inline GeoJSON")
    parser.add_argument("--start",           help="Monitoring start date YYYY-MM-DD")
    parser.add_argument("--end",             help="Monitoring end date YYYY-MM-DD")
    parser.add_argument("--baseline_years",  type=int,   help="Number of baseline years")
    parser.add_argument("--satellite",       choices=["Sentinel-2", "Landsat-8", "Landsat-9"])
    parser.add_argument("--ndvi_threshold",  type=float, help="NDVI anomaly threshold (std-devs)")
    parser.add_argument("--cloud",           type=int,   help="Max cloud cover %%")
    parser.add_argument("--alert_method",    choices=["email", "file", "console", "all"])
    parser.add_argument("--output_dir",      help="Output directory for files")
    parser.add_argument("--log_file",        help="Log file path")
    parser.add_argument("--smtp_server",     help="SMTP server hostname")
    parser.add_argument("--smtp_port",       type=int)
    parser.add_argument("--sender",          help="Sender email address")
    parser.add_argument("--recipient",       help="Recipient email(s), comma-separated")
    parser.add_argument("--generate_report", action="store_true", default=None)
    parser.add_argument("--dry_run",         action="store_true", default=None,
                        help="Compute anomaly map only; skip file/email exports")
    parser.add_argument("--mask_ag",         action="store_true", default=None,
                        help="Mask non-agricultural land via ESA WorldCover")
    parser.add_argument("--gee_project",     help="GEE cloud project ID")
    parser.add_argument("--gee_creds",       help="Path to GEE service account JSON")

    return parser


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------
def main() -> int:
    """
    Main execution flow.

    Returns:
        Exit code (0 = success, 1 = error).
    """
    parser = build_parser()
    args   = parser.parse_args()

    # -------------------------------------------------------------------
    # Load & validate configuration
    # -------------------------------------------------------------------
    try:
        cfg = load_config(args)
    except ConfigError as exc:
        print(f"[CONFIG ERROR] {exc}", file=sys.stderr)
        return 1

    # Re-setup logging now that we know the log file
    global logger
    logger = setup_logging(cfg.get("LOG_FILE"))

    logger.info("=" * 55)
    logger.info(" Agricultural Health Alert System – Starting")
    logger.info("=" * 55)
    logger.info("Config: satellite=%s | period=%s→%s | threshold=%.1fσ",
                cfg["SATELLITE"], cfg.get("START_DATE"), cfg.get("END_DATE"),
                cfg.get("NDVI_THRESHOLD", 1.0))

    try:
        validate_config(cfg)
    except ConfigError as exc:
        logger.error("Configuration error: %s", exc)
        return 1

    # -------------------------------------------------------------------
    # Initialise Earth Engine
    # -------------------------------------------------------------------
    try:
        initialize_ee(cfg)
    except EEInitError as exc:
        logger.error("%s", exc)
        return 1

    # -------------------------------------------------------------------
    # Load AOI
    # -------------------------------------------------------------------
    try:
        aoi = load_aoi(cfg["AOI"])
    except ConfigError as exc:
        logger.error("AOI error: %s", exc)
        return 1

    # -------------------------------------------------------------------
    # Step 1 – Historical baseline
    # -------------------------------------------------------------------
    logger.info("Step 1/4 – Computing historical NDVI baseline …")
    try:
        baseline_mean, baseline_std = compute_baseline(
            aoi=aoi,
            start_date=cfg["START_DATE"],
            end_date=cfg["END_DATE"],
            baseline_years=cfg["BASELINE_YEARS"],
            satellite=cfg["SATELLITE"],
            max_cloud=cfg["MIN_CLOUD_COVER"],
            mask_ag=cfg["MASK_NON_AGRICULTURAL"],
        )
    except NoImagesError as exc:
        logger.error("Baseline computation failed: %s", exc)
        return 1
    except ee.EEException as exc:
        logger.error("Earth Engine error during baseline: %s", exc)
        return 1

    # -------------------------------------------------------------------
    # Step 2 – Current NDVI
    # -------------------------------------------------------------------
    logger.info("Step 2/4 – Computing current NDVI composite …")
    try:
        current_ndvi = compute_current_ndvi(
            aoi=aoi,
            start_date=cfg["START_DATE"],
            end_date=cfg["END_DATE"],
            satellite=cfg["SATELLITE"],
            max_cloud=cfg["MIN_CLOUD_COVER"],
            mask_ag=cfg["MASK_NON_AGRICULTURAL"],
        )
    except NoImagesError as exc:
        logger.error("Current NDVI failed: %s", exc)
        return 1
    except ee.EEException as exc:
        logger.error("Earth Engine error during current NDVI: %s", exc)
        return 1

    # -------------------------------------------------------------------
    # Step 3 – Anomaly detection
    # -------------------------------------------------------------------
    logger.info("Step 3/4 – Detecting NDVI anomalies …")
    try:
        anomaly, alert_zones = detect_anomaly(
            current_ndvi=current_ndvi,
            baseline_mean=baseline_mean,
            baseline_std=baseline_std,
            threshold=cfg["NDVI_THRESHOLD"],
            aoi=aoi,
        )
    except ee.EEException as exc:
        logger.error("Anomaly detection failed: %s", exc)
        return 1

    # -------------------------------------------------------------------
    # Step 4 – Generate alerts
    # -------------------------------------------------------------------
    logger.info("Step 4/4 – Generating alerts …")
    try:
        stats = generate_alerts(
            cfg=cfg,
            alert_zones=alert_zones,
            current_ndvi=current_ndvi,
            anomaly=anomaly,
            aoi=aoi,
        )
    except ee.EEException as exc:
        logger.error("Alert generation failed: %s", exc)
        return 1

    logger.info("Run completed successfully. Alert zones: %d", stats.get("n_zones", 0))
    return 0


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    sys.exit(main())
