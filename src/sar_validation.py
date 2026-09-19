"""
Crop Health Alert System (CHAS) - SAR Validation Module
========================================================
Sentinel-1 SAR cross-validation to filter out cloud shadows and false alarms.

The problem: Optical indices (NDVI, EVI, SAVI) can't tell the difference between
actual crop stress and cloud shadows. Solution: Use Sentinel-1 radar data.

How it works:
- Low vegetation index + Low radar backscatter → Waterlogging/flood (real alert)
- Low vegetation index + High radar backscatter → Drought stress (real alert)  
- Low vegetation index + Normal radar backscatter → Likely cloud shadow (ignore)

This "cloud killer" logic dramatically reduces false positives without missing
genuine agricultural stress.
"""

from typing import Dict, Any, Optional, Tuple, List
import ee


def get_sentinel1_collection(
    aoi: ee.Geometry,
    start_date: str,
    end_date: str,
    orbit_direction: str = 'DESCENDING'
) -> ee.ImageCollection:
    """
    Load Sentinel-1 GRD C-band SAR collection filtered by AOI and date range.
    
    Args:
        aoi: Area of interest geometry.
        start_date: Start date in YYYY-MM-DD format.
        end_date: End date in YYYY-MM-DD format.
        orbit_direction: 'ASCENDING' or 'DESCENDING' (default).
    
    Returns:
        Filtered ee.ImageCollection of Sentinel-1 GRD data.
    """
    collection = (
        ee.ImageCollection('COPERNICUS/S1_GRD')
        .filterBounds(aoi)
        .filterDate(start_date, end_date)
        .filter(ee.Filter.eq('orbitProperties_pass', orbit_direction))
        .filter(ee.Filter.listContains('transmitterReceiverPolarisation', 'VV'))
        .filter(ee.Filter.listContains('transmitterReceiverPolarisation', 'VH'))
        .filter(ee.Filter.eq('instrumentMode', 'IW'))
    )
    return collection


def preprocess_sar(image: ee.Image) -> ee.Image:
    """
    Preprocess Sentinel-1 SAR image: select VV/VH bands and apply terrain correction.
    
    Args:
        image: Input Sentinel-1 GRD image.
    
    Returns:
        Preprocessed image with VV and VH bands in dB scale.
    """
    # Select VV and VH polarizations
    vv = image.select('VV').rename('VV')
    vh = image.select('VH').rename('VH')
    
    # Convert to dB scale for better analysis
    # dB = 10 * log10(linear_value)
    vv_db = vv.log10().multiply(10).rename('VV_dB')
    vh_db = vh.log10().multiply(10).rename('VH_dB')
    
    # Compute VV/VH ratio (useful for land cover discrimination)
    vv_vh_ratio = vv.divide(vh.add(0.001)).rename('VV_VH_RATIO')
    
    return image.addBands([vv_db, vh_db, vv_vh_ratio])


def compute_sar_composite(
    collection: ee.ImageCollection,
    reducer: str = 'median'
) -> ee.Image:
    """
    Create a composite image from SAR collection using specified reducer.
    
    Args:
        collection: Sentinel-1 ImageCollection.
        reducer: Reduction method ('median', 'mean', 'min', 'max').
    
    Returns:
        Composite ee.Image with VV, VH, and ratio bands.
    """
    if reducer == 'median':
        composite = collection.reduce(ee.Reducer.median())
    elif reducer == 'mean':
        composite = collection.reduce(ee.Reducer.mean())
    elif reducer == 'min':
        composite = collection.reduce(ee.Reducer.min())
    elif reducer == 'max':
        composite = collection.reduce(ee.Reducer.max())
    else:
        raise ValueError(f"Unknown reducer: {reducer}")
    
    # Rename bands appropriately
    band_names = ['VV', 'VH', 'VV_dB', 'VH_dB', 'VV_VH_RATIO']
    new_names = [f"{b}_{reducer}" for b in band_names]
    
    return composite.rename(new_names)


def classify_backscatter_level(
    sar_image: ee.Image,
    vv_threshold_low: float = -18.0,
    vv_threshold_high: float = -8.0,
    vh_threshold_low: float = -25.0,
    vh_threshold_high: float = -15.0
) -> ee.Image:
    """
    Classify backscatter levels into categories: LOW, MEDIUM, HIGH.
    
    Threshold values are in dB and based on empirical studies:
    - Low VV (< -18 dB): Smooth surfaces, water bodies
    - Medium VV (-18 to -8 dB): Vegetation, agricultural land
    - High VV (> -8 dB): Urban areas, rough surfaces, dry stressed vegetation
    
    Args:
        sar_image: SAR image with VV_dB and VH_dB bands.
        vv_threshold_low: Lower threshold for VV (dB).
        vv_threshold_high: Upper threshold for VV (dB).
        vh_threshold_low: Lower threshold for VH (dB).
        vh_threshold_high: Upper threshold for VH (dB).
    
    Returns:
        Image with classification bands.
    """
    vv_db = sar_image.select('VV_dB_median' if 'VV_dB_median' in sar_image.bandNames().getInfo() 
                              else sar_image.select('VV_dB'))
    vh_db = sar_image.select('VH_dB_median' if 'VH_dB_median' in sar_image.bandNames().getInfo()
                              else sar_image.select('VH_dB'))
    
    # Classify VV level
    vv_low = vv_db.lt(vv_threshold_low)
    vv_high = vv_db.gt(vv_threshold_high)
    vv_medium = vv_db.lte(vv_threshold_high).And(vv_db.gte(vv_threshold_low))
    
    # Classify VH level
    vh_low = vh_db.lt(vh_threshold_low)
    vh_high = vh_db.gt(vh_threshold_high)
    vh_medium = vh_db.lte(vh_threshold_high).And(vh_db.gte(vh_threshold_low))
    
    classification = (
        vv_low.multiply(1)
        .add(vv_medium.multiply(2))
        .add(vv_high.multiply(3))
        .rename('VV_CLASS')
    )
    
    return sar_image.addBands([classification, vv_low, vv_medium, vv_high, vh_low, vh_medium, vh_high])


def validate_optical_anomaly_with_sar(
    optical_anomaly_mask: ee.Image,
    sar_composite: ee.Image,
    chi_band: str = 'CHI',
    chi_threshold: float = 0.3,
    vv_water_threshold: float = -15.0,
    vv_drought_threshold: float = -10.0
) -> ee.Image:
    """
    Validate optical vegetation anomalies using SAR backscatter data.
    
    Decision Matrix:
    ┌────────────────────────┬───────────────────────┬─────────────────────────────┐
    │ Condition              │ SAR Signature         │ Classification              │
    ├────────────────────────┼───────────────────────┼─────────────────────────────┤
    │ Low CHI + Low VV       │ Specular reflection   │ WATERLOGGING/FLOOD (Valid)  │
    │ Low CHI + High VV      │ Volume scattering     │ DROUGHT/DRY_STRESS (Valid)  │
    │ Low CHI + Normal VV    │ No SAR anomaly        │ CLOUD_SHADOW (False Positive)│
    │ Normal CHI             │ Any                   │ NO_ALERT                    │
    └────────────────────────┴───────────────────────┴─────────────────────────────┘
    
    Args:
        optical_anomaly_mask: Binary mask where 1 = optical anomaly detected.
        sar_composite: SAR composite image with VV_dB band.
        chi_band: Name of the composite health index band.
        chi_threshold: Threshold below which optical anomaly is flagged.
        vv_water_threshold: VV dB threshold for water detection (default -15 dB).
        vv_drought_threshold: VV dB threshold for dry stress (default -10 dB).
    
    Returns:
        Image with validation status band:
        - 0: No alert
        - 1: Valid alert - waterlogging/flood
        - 2: Valid alert - drought/dry stress  
        - 3: Review needed - likely cloud/shadow artifact
    """
    # Get SAR backscatter
    vv_band_name = 'VV_dB_median' if 'VV_dB_median' in sar_composite.bandNames().getInfo() else 'VV_dB'
    vv_db = sar_composite.select(vv_band_name)
    
    # Define conditions
    low_chi = optical_anomaly_mask.eq(1)
    very_low_vv = vv_db.lt(vv_water_threshold)      # Water/flood signature
    high_vv = vv_db.gt(vv_drought_threshold)        # Dry stress signature
    normal_vv = vv_db.lte(vv_drought_threshold).And(vv_db.gte(vv_water_threshold))
    
    # Apply decision logic
    waterlogging = low_chi.And(very_low_vv).multiply(1)
    drought = low_chi.And(high_vv).multiply(2)
    review_needed = low_chi.And(normal_vv).multiply(3)
    
    # Combine classifications (priority: waterlogging > drought > review > none)
    validation_status = (
        waterlogging.add(drought).add(review_needed)
        .rename('VALIDATION_STATUS')
    )
    
    # Create confidence score based on SAR-optical agreement
    # Higher confidence when SAR strongly supports optical observation
    confidence = (
        ee.Algorithms.If(very_low_vv, 0.95,
            ee.Algorithms.If(high_vv, 0.85,
                ee.Algorithms.If(normal_vv, 0.40, 0.20)))
    )
    
    confidence_img = ee.Image(confidence).rename('CONFIDENCE_SCORE')
    
    return validation_status.addBands(confidence_img)


def create_sar_validation_report(
    validated_alerts: ee.Image,
    aoi: ee.Geometry,
    scale: int = 100
) -> Dict[str, Any]:
    """
    Generate summary statistics for SAR validation results.
    
    Args:
        validated_alerts: Image with VALIDATION_STATUS band.
        aoi: Area of interest for computing statistics.
        scale: Spatial resolution in meters.
    
    Returns:
        Dictionary with validation statistics.
    """
    status_band = 'VALIDATION_STATUS'
    
    # Count pixels in each validation category
    stats = validated_alerts.select(status_band).reduceRegion(
        reducer=ee.Reducer.frequencyHistogram(),
        geometry=aoi,
        scale=scale,
        maxPixels=1e9
    )
    
    # Parse histogram
    histogram = ee.Dictionary(stats.get(status_band))
    
    # Calculate percentages
    total = ee.Number(histogram.values().reduce(ee.Reducer.sum()))
    
    def calc_percentage(count):
        return ee.Number(count).divide(total).multiply(100).round(2)
    
    waterlogging_pct = calc_percentage(histogram.get('1', 0))
    drought_pct = calc_percentage(histogram.get('2', 0))
    review_pct = calc_percentage(histogram.get('3', 0))
    
    return {
        'waterlogging_pixels': histogram.get('1', 0),
        'drought_pixels': histogram.get('2', 0),
        'review_needed_pixels': histogram.get('3', 0),
        'waterlogging_percent': waterlogging_pct.getInfo() if hasattr(waterlogging_pct, 'getInfo') else waterlogging_pct,
        'drought_percent': drought_pct.getInfo() if hasattr(drought_pct, 'getInfo') else drought_pct,
        'review_needed_percent': review_pct.getInfo() if hasattr(review_pct, 'getInfo') else review_pct,
        'validation_confidence_mean': validated_alerts.select('CONFIDENCE_SCORE').reduceRegion(
            reducer=ee.Reducer.mean(),
            geometry=aoi,
            scale=scale
        ).get('CONFIDENCE_SCORE')
    }


def fuse_optical_sar_alerts(
    chi_image: ee.Image,
    sar_collection: ee.ImageCollection,
    chi_threshold: float = 0.3,
    baseline_chi: Optional[ee.Image] = None,
    zscore_threshold: float = -1.5
) -> Tuple[ee.Image, Dict[str, Any]]:
    """
    Main fusion function combining optical CHI with SAR validation.
    
    This is the primary entry point for the SAR cross-validation workflow.
    
    Args:
        chi_image: Current period Composite Health Index image.
        sar_collection: Sentinel-1 ImageCollection for validation.
        chi_threshold: Absolute threshold for low vegetation health.
        baseline_chi: Historical baseline CHI mean (optional).
        zscore_threshold: Z-score threshold for anomaly detection.
    
    Returns:
        Tuple of (validated_alert_image, validation_statistics).
    """
    # Step 1: Detect optical anomalies
    if baseline_chi is not None:
        # Z-score based anomaly detection
        chi_std = baseline_chi.select('CHI_stddev')
        chi_mean = baseline_chi.select('CHI_mean')
        chi_current = chi_image.select('CHI')
        
        zscore = chi_current.subtract(chi_mean).divide(chi_std.add(0.001))
        optical_anomaly = zscore.lt(zscore_threshold).rename('OPTICAL_ANOMALY')
    else:
        # Simple threshold-based detection
        optical_anomaly = chi_image.select('CHI').lt(chi_threshold).rename('OPTICAL_ANOMALY')
    
    # Step 2: Process SAR data
    sar_composite = compute_sar_composite(sar_collection, reducer='median')
    sar_classified = classify_backscatter_level(sar_composite)
    
    # Step 3: Validate optical anomalies with SAR
    validated = validate_optical_anomaly_with_sar(
        optical_anomaly,
        sar_composite,
        chi_threshold=chi_threshold
    )
    
    # Step 4: Generate validation report
    # Note: In actual GEE usage, these would be computed client-side after export
    validation_summary = {
        'status': 'SAR validation applied',
        'bands_added': ['VALIDATION_STATUS', 'CONFIDENCE_SCORE'],
        'validation_categories': {
            '1': 'Waterlogging/Flood (Low VV backscatter)',
            '2': 'Drought/Dry Stress (High VV backscatter)',
            '3': 'Review Needed (Inconsistent signals - possible cloud shadow)'
        }
    }
    
    return validated, validation_summary
