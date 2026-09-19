"""
Crop Health Alert System (CHAS) - Anomaly Detection Module
===========================================================
Adaptive thresholding that adjusts based on local landscape variability.

The problem: A fixed z-score threshold (like -1.5σ) creates too many false 
alarms in naturally variable areas (wetlands) and misses subtle stress in 
stable monocultures.

Our solution: Calculate the Coefficient of Variation (CV) for each pixel from
historical data, then adjust thresholds accordingly:
- High CV areas (wetlands, riparian zones) → More tolerant thresholds
- Low CV areas (irrigated fields) → More sensitive thresholds

Formula: adaptive_threshold = base_threshold × (1 + 0.5 × CV_local)

This means a pixel in a stable wheat field might trigger at -1.3σ while a 
pixel in a seasonal wetland needs -2.0σ to flag an alert.
"""

from typing import Dict, Any, Optional, Tuple, List
import ee
import numpy as np


def compute_coefficient_of_variation(
    image_collection: ee.ImageCollection,
    band_name: str = 'CHI',
    scale: int = 100
) -> ee.Image:
    """
    Compute pixel-wise Coefficient of Variation (CV) across an image collection.
    
    CV = standard_deviation / mean
    
    CV interpretation:
    - CV < 0.1: Very stable (e.g., irrigated monoculture)
    - CV 0.1-0.3: Moderate variability (typical rainfed agriculture)
    - CV > 0.3: High variability (wetlands, stressed ecosystems)
    
    Args:
        image_collection: ee.ImageCollection with consistent bands.
        band_name: Name of the band to analyze.
        scale: Spatial resolution in meters.
    
    Returns:
        ee.Image with 'CV' band representing coefficient of variation.
    """
    # Compute mean and standard deviation
    stats = image_collection.reduce(ee.Reducer.mean().combine(
        reducer2=ee.Reducer.stdDev(),
        sharedInputs=True
    ))
    
    mean_band = f'{band_name}_mean'
    std_band = f'{band_name}_stdDev'
    
    mean = stats.select(mean_band)
    std = stats.select(std_band)
    
    # CV = std / mean (add small epsilon to avoid division by zero)
    cv = std.divide(mean.add(0.001)).rename('CV')
    
    return cv.addBands([mean, std])


def compute_adaptive_threshold(
    baseline_stats: ee.Image,
    base_threshold: float = -1.5,
    alpha: float = 0.5,
    cv_band: str = 'CV',
    min_threshold: float = -3.0,
    max_threshold: float = -0.5
) -> ee.Image:
    """
    Compute pixel-wise adaptive anomaly threshold based on local CV.
    
    Formula: threshold_pixel = base_threshold * (1 + α * CV_local)
    
    Rationale:
    - High CV areas (naturally variable) → less negative threshold (more tolerant)
    - Low CV areas (stable) → more negative threshold (more sensitive)
    
    Args:
        baseline_stats: Image with mean, stddev, and CV bands from baseline.
        base_threshold: Base z-score threshold (default -1.5).
        alpha: Sensitivity parameter for CV adjustment (default 0.5).
        cv_band: Name of the CV band.
        min_threshold: Minimum allowed threshold (most sensitive).
        max_threshold: Maximum allowed threshold (least sensitive).
    
    Returns:
        ee.Image with 'adaptive_threshold' band.
    """
    cv = baseline_stats.select(cv_band)
    
    # Adaptive formula: adjust threshold based on local variability
    # Note: base_threshold is negative, so multiplying by (1 + alpha*CV) makes it
    # less negative (more tolerant) for high CV areas
    adaptive = base_threshold.multiply(
        ee.Number(1).add(alpha.multiply(cv))
    )
    
    # Clamp to reasonable bounds
    adaptive_clamped = adaptive.max(min_threshold).min(max_threshold)
    
    return baseline_stats.addBands(adaptive_clamped.rename('adaptive_threshold'))


def detect_anomalies_adaptive(
    current_chi: ee.Image,
    baseline_mean: ee.Image,
    baseline_std: ee.Image,
    cv_image: ee.Image,
    base_threshold: float = -1.5,
    alpha: float = 0.5
) -> ee.Image:
    """
    Detect vegetation health anomalies using adaptive thresholds.
    
    This function implements the full adaptive anomaly detection workflow:
    1. Calculate z-scores: (current - baseline_mean) / baseline_std
    2. Compute adaptive threshold per pixel based on CV
    3. Flag pixels where z-score < adaptive_threshold
    
    Args:
        current_chi: Current period CHI image.
        baseline_mean: Historical baseline mean CHI.
        baseline_std: Historical baseline standard deviation.
        cv_image: Coefficient of variation image.
        base_threshold: Base z-score threshold.
        alpha: CV sensitivity parameter.
    
    Returns:
        ee.Image with anomaly detection results:
        - 'zscore': Normalized anomaly score
        - 'adaptive_threshold': Pixel-specific threshold
        - 'anomaly': Binary mask (1 = anomaly detected)
        - 'anomaly_severity': Categorized severity (1=moderate, 2=severe, 3=critical)
    """
    # Step 1: Compute z-scores
    zscore = current_chi.subtract(baseline_mean).divide(baseline_std.add(0.001))
    
    # Step 2: Compute adaptive threshold
    adaptive_thresh = compute_adaptive_threshold(
        cv_image, 
        base_threshold=base_threshold, 
        alpha=alpha
    ).select('adaptive_threshold')
    
    # Step 3: Detect anomalies (z-score below adaptive threshold)
    anomaly_mask = zscore.lt(adaptive_thresh).rename('anomaly')
    
    # Step 4: Classify severity
    # Moderate: between threshold and threshold - 1
    # Severe: between threshold - 1 and threshold - 2
    # Critical: below threshold - 2
    moderate = anomaly_mask.And(zscore.gt(adaptive_thresh.subtract(1))).multiply(1)
    severe = anomaly_mask.And(
        zscore.lte(adaptive_thresh.subtract(1)).And(zscore.gt(adaptive_thresh.subtract(2)))
    ).multiply(2)
    critical = anomaly_mask.And(zscore.lte(adaptive_thresh.subtract(2))).multiply(3)
    
    severity = moderate.add(severe).add(critical).rename('anomaly_severity')
    
    result = ee.Image.cat([
        zscore.rename('zscore'),
        adaptive_thresh,
        anomaly_mask,
        severity
    ])
    
    return result


def detect_anomalies_static(
    current_chi: ee.Image,
    baseline_mean: ee.Image,
    baseline_std: ee.Image,
    threshold: float = -1.5
) -> ee.Image:
    """
    Detect anomalies using traditional static threshold (for comparison).
    
    This is the legacy method retained for baseline comparison and validation.
    
    Args:
        current_chi: Current period CHI image.
        baseline_mean: Historical baseline mean.
        baseline_std: Historical baseline standard deviation.
        threshold: Fixed z-score threshold.
    
    Returns:
        ee.Image with static anomaly detection results.
    """
    zscore = current_chi.subtract(baseline_mean).divide(baseline_std.add(0.001))
    anomaly = zscore.lt(threshold).rename('anomaly_static')
    
    return zscore.rename('zscore_static').addBands(anomaly)


def create_landcover_mask(
    aoi: ee.Geometry,
    landcover_classes: Optional[List[int]] = None
) -> ee.Image:
    """
    Create a mask based on ESA WorldCover land cover classes.
    
    Useful for applying different thresholds to different land types:
    - Cropland (class 40): Standard agricultural thresholds
    - Wetlands (class 95): Higher tolerance (naturally variable)
    - Forest (classes 10, 20, 30): Different baseline expectations
    
    Args:
        aoi: Area of interest geometry.
        landcover_classes: List of ESA WorldCover class codes to include.
                          If None, returns the full landcover image.
    
    Returns:
        ee.Image with landcover classification.
    
    Reference:
        ESA WorldCover 10m v200: https://developers.google.com/earth-engine/datasets/catalog/ESA_WorldCover_v200
    """
    worldcover = ee.ImageCollection('ESA/WorldCover/v200').first().clip(aoi)
    
    if landcover_classes is not None:
        mask = worldcover.remap(landcover_classes, [1] * len(landcover_classes), 0)
        return worldcover.updateMask(mask)
    
    return worldcover.rename('landcover')


def apply_context_aware_filtering(
    anomaly_image: ee.Image,
    landcover: ee.Image,
    wetland_multiplier: float = 1.5,
    forest_multiplier: float = 1.2
) -> ee.Image:
    """
    Apply additional context-aware filtering based on land cover type.
    
    This provides a second layer of adaptive thresholding:
    - Wetlands: Increase threshold tolerance (naturally high NDVI variability)
    - Forests: Moderate increase (seasonal but generally stable)
    - Cropland: Standard thresholds (managed, expected stability)
    
    ESA WorldCover Classes:
    - 10: Tree Cover (Forest)
    - 20: Shrubland
    - 30: Grassland
    - 40: Cropland
    - 50: Built-up
    - 60: Barren
    - 70: Snow/Ice
    - 80: Open Water
    - 90: Herbaceous Wetland
    - 95: Mangroves
    - 100: Moss/Lichen
    
    Args:
        anomaly_image: Image with anomaly detection results.
        landcover: ESA WorldCover landcover image.
        wetland_multiplier: Factor to relax threshold for wetlands.
        forest_multiplier: Factor to relax threshold for forests.
    
    Returns:
        ee.Image with refined anomaly masks.
    """
    lc = landcover.select('MapZone') if 'MapZone' in landcover.bandNames().getInfo() else landcover
    
    # Define landcover-based adjustments
    wetland_classes = ee.Image.constant(0).where(
        lc.eq(90).Or(lc.eq(95)), 1
    ).rename('is_wetland')
    
    forest_classes = ee.Image.constant(0).where(
        lc.eq(10).Or(lc.eq(20)), 1
    ).rename('is_forest')
    
    cropland = lc.eq(40).rename('is_cropland')
    
    # Adjust anomaly threshold based on landcover
    # Wetlands: require stronger signal to trigger alert
    # Forests: moderate adjustment
    # Cropland: standard thresholds
    
    anomaly = anomaly_image.select('anomaly')
    zscore = anomaly_image.select('zscore')
    
    # For wetlands, require zscore < threshold * wetland_multiplier
    wetland_adjusted = anomaly.And(
        zscore.lt(ee.Number(-1.5).multiply(wetland_multiplier))
    ).where(wetland_classes.eq(0), anomaly)
    
    # Combine all adjustments
    refined_anomaly = wetland_adjusted.rename('anomaly_refined')
    
    return anomaly_image.addBands([refined_anomaly, wetland_classes, forest_classes, cropland])


def generate_anomaly_summary(
    result_image: ee.Image,
    aoi: ee.Geometry,
    scale: int = 100
) -> Dict[str, Any]:
    """
    Generate summary statistics for anomaly detection results.
    
    Args:
        result_image: Image with anomaly detection bands.
        aoi: Area of interest.
        scale: Spatial resolution.
    
    Returns:
        Dictionary with summary statistics.
    """
    # Count pixels by severity
    severity_hist = result_image.select('anomaly_severity').reduceRegion(
        reducer=ee.Reducer.frequencyHistogram(),
        geometry=aoi,
        scale=scale,
        maxPixels=1e9
    )
    
    # Get z-score statistics
    zscore_stats = result_image.select('zscore').reduceRegion(
        reducer=ee.Reducer.min().combine(
            ee.Reducer.max().combine(
                ee.Reducer.mean(),
                sharedInputs=True
            ),
            sharedInputs=True
        ),
        geometry=aoi,
        scale=scale
    )
    
    return {
        'severity_histogram': severity_hist.getInfo() if hasattr(severity_hist, 'getInfo') else severity_hist,
        'zscore_min': zscore_stats.getInfo() if hasattr(zscore_stats, 'getInfo') else zscore_stats,
        'total_area_km2': aoi.area(scale).getInfo() if hasattr(aoi, 'area') else aoi.area()
    }
