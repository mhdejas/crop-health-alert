"""
CHAS Package - Crop Health Alert System
========================================
Multi-modal crop monitoring using satellite data fusion.

What this does:
1. Combines NDVI, EVI, and SAVI into a single health score
2. Uses radar (Sentinel-1) to filter out cloud shadows
3. Adjusts sensitivity based on local landscape variability
4. Validates performance with standard metrics

Quick start:
    from src import core, sar_validation, anomaly, validation
    
    import ee
    ee.Initialize()
    
    # Calculate composite health index
    chi_image = core.compute_composite_health_index(image, nir_band, red_band, blue_band)
    
    # Validate with SAR to remove false positives
    validated, stats = sar_validation.fuse_optical_sar_alerts(chi_image, sar_collection)
"""

from .core import (
    compute_ndvi,
    compute_evi,
    compute_savi,
    compute_composite_health_index,
    get_sentinel2_bands,
    get_landsat_bands
)

from .sar_validation import (
    get_sentinel1_collection,
    preprocess_sar,
    compute_sar_composite,
    classify_backscatter_level,
    validate_optical_anomaly_with_sar,
    fuse_optical_sar_alerts
)

from .anomaly import (
    compute_coefficient_of_variation,
    compute_adaptive_threshold,
    detect_anomalies_adaptive,
    detect_anomalies_static,
    create_landcover_mask,
    apply_context_aware_filtering
)

from .validation import (
    create_confusion_matrix,
    calculate_performance_metrics,
    simulate_ground_truth_from_rainfall,
    generate_validation_report,
    run_comprehensive_validation
)

__version__ = '2.0.0'
__author__ = 'CHAS Development Team'
__all__ = [
    # Core module
    'compute_ndvi',
    'compute_evi',
    'compute_savi',
    'compute_composite_health_index',
    'get_sentinel2_bands',
    'get_landsat_bands',
    
    # SAR validation module
    'get_sentinel1_collection',
    'preprocess_sar',
    'compute_sar_composite',
    'classify_backscatter_level',
    'validate_optical_anomaly_with_sar',
    'fuse_optical_sar_alerts',
    
    # Anomaly detection module
    'compute_coefficient_of_variation',
    'compute_adaptive_threshold',
    'detect_anomalies_adaptive',
    'detect_anomalies_static',
    'create_landcover_mask',
    'apply_context_aware_filtering',
    
    # Validation module
    'create_confusion_matrix',
    'calculate_performance_metrics',
    'simulate_ground_truth_from_rainfall',
    'generate_validation_report',
    'run_comprehensive_validation'
]
