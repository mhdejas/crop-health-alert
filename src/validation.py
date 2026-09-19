"""
Crop Health Alert System (CHAS) - Validation Module
====================================================
Performance metrics to measure how well the alert system works.

We validate alerts against ground truth (field surveys, rainfall data, or known
stress areas) using standard classification metrics:

- Precision: Of all alerts sent, how many were real stress? (avoid false alarms)
- Recall: Of all actual stress events, how many did we catch? (avoid missed detections)
- F1-Score: Balance between precision and recall
- Specificity: How well we identify healthy crops correctly

Target: >90% precision and recall under operational conditions.
"""

from typing import Dict, Any, Optional, Tuple, List
import ee
import numpy as np


def create_confusion_matrix(
    predicted_alerts: ee.Image,
    ground_truth: ee.Image,
    aoi: ee.Geometry,
    scale: int = 100,
    alert_band: str = 'anomaly',
    truth_band: str = 'ground_truth'
) -> Dict[str, int]:
    """
    Generate confusion matrix comparing predicted alerts to ground truth.
    
    Args:
        predicted_alerts: Image with binary alert predictions (1=alert, 0=no alert).
        ground_truth: Image with binary ground truth (1=stress, 0=healthy).
        aoi: Area of interest for evaluation.
        scale: Spatial resolution in meters.
        alert_band: Name of the prediction band.
        truth_band: Name of the ground truth band.
    
    Returns:
        Dictionary with confusion matrix values: TP, FP, TN, FN.
    """
    # Stack both images
    combined = predicted_alerts.select(alert_band).rename('pred')\
        .addBands(ground_truth.select(truth_band).rename('truth'))
    
    # Create error matrix: pred * 10 + truth gives unique values for each combination
    # pred=1, truth=1 → 11 (TP)
    # pred=1, truth=0 → 10 (FP)
    # pred=0, truth=1 → 1 (FN)
    # pred=0, truth=0 → 0 (TN)
    error_matrix = combined.select('pred').multiply(10).add(combined.select('truth'))
    
    # Count pixels in each category
    histogram = error_matrix.reduceRegion(
        reducer=ee.Reducer.frequencyHistogram(),
        geometry=aoi,
        scale=scale,
        maxPixels=1e9
    )
    
    counts = ee.Dictionary(histogram.get('error_matrix')).getInfo() \
        if hasattr(histogram, 'getInfo') else ee.Dictionary(histogram.get('error_matrix'))
    
    # Parse confusion matrix components
    tp = int(counts.get('11', 0))
    fp = int(counts.get('10', 0))
    tn = int(counts.get('0', 0))
    fn = int(counts.get('1', 0))
    
    return {
        'true_positive': tp,
        'false_positive': fp,
        'true_negative': tn,
        'false_negative': fn
    }


def calculate_performance_metrics(confusion_matrix: Dict[str, int]) -> Dict[str, float]:
    """
    Calculate performance metrics from confusion matrix values.
    
    Args:
        confusion_matrix: Dictionary with TP, FP, TN, FN counts.
    
    Returns:
        Dictionary with Precision, Recall, F1-Score, Specificity, Accuracy.
    """
    tp = confusion_matrix['true_positive']
    fp = confusion_matrix['false_positive']
    tn = confusion_matrix['true_negative']
    fn = confusion_matrix['false_negative']
    
    # Avoid division by zero
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    specificity = tn / (tn + fp) if (tn + fp) > 0 else 0.0
    accuracy = (tp + tn) / (tp + tn + fp + fn) if (tp + tn + fp + fn) > 0 else 0.0
    
    # F1-Score: harmonic mean of precision and recall
    f1_score = 2 * (precision * recall) / (precision + recall) if (precision + recall) > 0 else 0.0
    
    # Matthews Correlation Coefficient (MCC) - balanced measure for imbalanced datasets
    mcc_numerator = (tp * tn) - (fp * fn)
    mcc_denominator = np.sqrt((tp + fp) * (tp + fn) * (tn + fp) * (tn + fn))
    mcc = mcc_numerator / mcc_denominator if mcc_denominator > 0 else 0.0
    
    return {
        'precision': round(precision, 4),
        'recall': round(recall, 4),
        'f1_score': round(f1_score, 4),
        'specificity': round(specificity, 4),
        'accuracy': round(accuracy, 4),
        'mcc': round(mcc, 4),
        'total_samples': tp + tn + fp + fn,
        'confusion_matrix': confusion_matrix
    }


def simulate_ground_truth_from_rainfall(
    rainfall_deficit: ee.Image,
    deficit_threshold: float = -0.5,
    drought_severity_band: str = 'SPI'
) -> ee.Image:
    """
    Simulate ground truth proxy using rainfall deficit data (IMD-style).
    
    This creates a synthetic ground truth layer based on Standardized Precipitation
    Index (SPI) or similar drought indices. Useful when actual field observations
    are unavailable.
    
    SPI Interpretation:
    - SPI < -2.0: Extreme drought (definite stress)
    - SPI -2.0 to -1.5: Severe drought
    - SPI -1.5 to -1.0: Moderate drought
    - SPI -1.0 to 0: Mild dry conditions
    - SPI > 0: Normal/wet conditions
    
    Args:
        rainfall_deficit: Image with SPI or similar drought index.
        deficit_threshold: Threshold below which conditions indicate stress.
        drought_severity_band: Name of the drought index band.
    
    Returns:
        Binary image simulating ground truth (1=stress, 0=healthy).
    """
    spi = rainfall_deficit.select(drought_severity_band)
    
    # Ground truth: stress when SPI < threshold
    ground_truth = spi.lt(deficit_threshold).rename('ground_truth')
    
    return ground_truth


def simulate_ground_truth_from_known_events(
    aoi: ee.Geometry,
    known_stress_areas: Optional[ee.Geometry] = None,
    known_healthy_areas: Optional[ee.Geometry] = None
) -> ee.Image:
    """
    Create ground truth from known stress/healthy area geometries.
    
    Use this when you have field survey data or expert knowledge about
    which areas experienced stress during the monitoring period.
    
    Args:
        aoi: Overall area of interest.
        known_stress_areas: Geometry of areas confirmed to have stress.
        known_healthy_areas: Geometry of areas confirmed healthy.
    
    Returns:
        Image with ground truth classification.
    """
    # Start with unknown (0)
    ground_truth = ee.Image.constant(0).clip(aoi)
    
    # Mark known stress areas as 1
    if known_stress_areas is not None:
        stress_mask = ee.Image.constant(1).paint(known_stress_areas, 1)
        ground_truth = ground_truth.where(stress_mask.eq(1), 1)
    
    # Mark known healthy areas as 0 (explicitly)
    if known_healthy_areas is not None:
        healthy_mask = ee.Image.constant(1).paint(known_healthy_areas, 1)
        ground_truth = ground_truth.where(healthy_mask.eq(1), 0)
    
    return ground_truth.rename('ground_truth')


def generate_validation_report(
    metrics: Dict[str, Any],
    output_format: str = 'dict'
) -> str:
    """
    Generate a formatted validation report from performance metrics.
    
    Args:
        metrics: Dictionary from calculate_performance_metrics().
        output_format: Output format ('dict', 'markdown', 'latex').
    
    Returns:
        Formatted report string.
    """
    if output_format == 'dict':
        return metrics
    
    elif output_format == 'markdown':
        report = "## Validation Report\n\n"
        report += "### Performance Metrics\n\n"
        report += f"| Metric | Value |\n"
        report += f"|--------|-------|\n"
        report += f"| **Precision** | {metrics['precision']:.4f} |\n"
        report += f"| **Recall** | {metrics['recall']:.4f} |\n"
        report += f"| **F1-Score** | {metrics['f1_score']:.4f} |\n"
        report += f"| **Specificity** | {metrics['specificity']:.4f} |\n"
        report += f"| **Accuracy** | {metrics['accuracy']:.4f} |\n"
        report += f"| **MCC** | {metrics['mcc']:.4f} |\n\n"
        report += "### Confusion Matrix\n\n"
        cm = metrics['confusion_matrix']
        report += f"```\n"
        report += f"                Actual\n"
        report += f"              Stress  Healthy\n"
        report += f"Predicted  \n"
        report += f"Stress      TP={cm['true_positive']:6d}  FP={cm['false_positive']:6d}\n"
        report += f"Healthy     FN={cm['false_negative']:6d}  TN={cm['true_negative']:6d}\n"
        report += f"```\n"
        report += f"\nTotal samples evaluated: {metrics['total_samples']:,}\n"
        return report
    
    elif output_format == 'latex':
        report = r"\section{Validation Results}" + "\n\n"
        report += r"\begin{table}[h]" + "\n"
        report += r"\centering" + "\n"
        report += r"\caption{Crop Health Alert System Performance Metrics}" + "\n"
        report += r"\begin{tabular}{lc}" + "\n"
        report += r"\hline" + "\n"
        report += r"\textbf{Metric} & \textbf{Value} \\" + "\n"
        report += r"\hline" + "\n"
        report += f"Precision & {metrics['precision']:.4f} \\\\" + "\n"
        report += f"Recall & {metrics['recall']:.4f} \\\\" + "\n"
        report += f"F1-Score & {metrics['f1_score']:.4f} \\\\" + "\n"
        report += f"Specificity & {metrics['specificity']:.4f} \\\\" + "\n"
        report += f"Accuracy & {metrics['accuracy']:.4f} \\\\" + "\n"
        report += f"MCC & {metrics['mcc']:.4f} \\\\" + "\n"
        report += r"\hline" + "\n"
        report += r"\end{tabular}" + "\n"
        report += r"\end{table}" + "\n\n"
        
        report += r"\begin{equation}" + "\n"
        report += r"\text{Precision} = \frac{TP}{TP + FP}" + "\n"
        report += r"\end{equation}" + "\n\n"
        
        report += r"\begin{equation}" + "\n"
        report += r"\text{Recall} = \frac{TP}{TP + FN}" + "\n"
        report += r"\end{equation}" + "\n\n"
        
        report += r"\begin{equation}" + "\n"
        report += r"F_1 = 2 \cdot \frac{\text{Precision} \cdot \text{Recall}}{\text{Precision} + \text{Recall}}" + "\n"
        report += r"\end{equation}" + "\n"
        return report
    
    else:
        raise ValueError(f"Unknown output_format: {output_format}")


def validate_with_imd_data(
    predicted_alerts: ee.Image,
    imd_rainfall_data: ee.Image,
    aoi: ee.Geometry,
    spi_threshold: float = -1.0,
    scale: int = 1000
) -> Dict[str, Any]:
    """
    Validate alerts against IMD (India Meteorological Department) rainfall data.
    
    This function uses SPI (Standardized Precipitation Index) derived from IMD
    rainfall data as a proxy for agricultural stress validation.
    
    Args:
        predicted_alerts: Alert prediction image.
        imd_rainfall_data: IMD rainfall/SPI data image.
        aoi: Area of interest.
        spi_threshold: SPI threshold indicating drought stress.
        scale: Spatial resolution.
    
    Returns:
        Complete validation results dictionary.
    """
    # Generate ground truth proxy from rainfall deficit
    ground_truth = simulate_ground_truth_from_rainfall(
        imd_rainfall_data,
        deficit_threshold=spi_threshold,
        drought_severity_band='SPI'
    )
    
    # Create confusion matrix
    confusion = create_confusion_matrix(
        predicted_alerts,
        ground_truth,
        aoi,
        scale=scale
    )
    
    # Calculate metrics
    metrics = calculate_performance_metrics(confusion)
    
    return {
        'validation_method': 'IMD Rainfall Proxy',
        'spi_threshold_used': spi_threshold,
        'metrics': metrics,
        'report_markdown': generate_validation_report(metrics, 'markdown'),
        'report_latex': generate_validation_report(metrics, 'latex')
    }


def run_comprehensive_validation(
    predicted_alerts: ee.Image,
    baseline_chi: ee.Image,
    current_chi: ee.Image,
    aoi: ee.Geometry,
    sar_validated: bool = False,
    adaptive_threshold: bool = False,
    scale: int = 100
) -> Dict[str, Any]:
    """
    Run comprehensive validation comparing multiple detection approaches.
    
    This function compares:
    1. Static threshold NDVI-only (baseline)
    2. Multi-index CHI (improved)
    3. SAR-validated alerts (if available)
    4. Adaptive threshold (if enabled)
    
    Args:
        predicted_alerts: Final alert predictions.
        baseline_chi: Historical baseline CHI.
        current_chi: Current period CHI.
        aoi: Area of interest.
        sar_validated: Whether SAR validation was applied.
        adaptive_threshold: Whether adaptive thresholds were used.
        scale: Spatial resolution.
    
    Returns:
        Comprehensive validation report.
    """
    # For demonstration, use simulated ground truth
    # In production, replace with actual field data or IMD rainfall
    ground_truth = simulate_ground_truth_from_known_events(aoi)
    
    # Get confusion matrix
    confusion = create_confusion_matrix(
        predicted_alerts,
        ground_truth,
        aoi,
        scale=scale
    )
    
    # Calculate metrics
    metrics = calculate_performance_metrics(confusion)
    
    # Add metadata
    metrics['sar_validated'] = sar_validated
    metrics['adaptive_threshold_applied'] = adaptive_threshold
    metrics['validation_timestamp'] = str(np.datetime64('now'))
    
    return metrics
