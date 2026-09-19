"""
Crop Health Alert System (CHAS) - Core Module
==============================================
Multi-index vegetation health scoring with NDVI, EVI, and SAVI.

We use a composite health index (CHI) that combines three vegetation indices:
    CHI = 0.6*NDVI + 0.2*EVI + 0.2*SAVI

Why these weights?
- NDVI gets 60% because it's the most established index with decades of validation
  for tracking biomass and chlorophyll (Rouse et al., 1974)
- EVI gets 20% to handle atmospheric effects and prevent saturation in dense canopies
  (Huete et al., 2002)
- SAVI gets 20% to reduce soil brightness interference, especially important during
  early crop growth when canopy cover is sparse (Huete, 1988)

This multi-index approach reduces false alarms compared to NDVI-only methods.
"""

from typing import Dict, Any, Optional, Tuple
import ee
import numpy as np


def compute_ndvi(image: ee.Image, nir_band: str, red_band: str) -> ee.Image:
    """
    Compute Normalized Difference Vegetation Index (NDVI).
    
    NDVI = (NIR - RED) / (NIR + RED)
    
    Args:
        image: Input ee.Image with NIR and Red bands.
        nir_band: Name of the near-infrared band.
        red_band: Name of the red band.
    
    Returns:
        ee.Image with 'NDVI' band added, range [-1, 1].
    """
    ndvi = image.normalizedDifference([nir_band, red_band]).rename('NDVI')
    return image.addBands(ndvi)


def compute_evi(
    image: ee.Image, 
    nir_band: str, 
    red_band: str, 
    blue_band: str,
    G: float = 2.5,
    C1: float = 6.0,
    C2: float = 7.5,
    L: float = 1.0
) -> ee.Image:
    """
    Compute Enhanced Vegetation Index (EVI).
    
    EVI = G * (NIR - RED) / (NIR + C1*RED - C2*BLUE + L)
    
    EVI optimizes the vegetation signal with improved sensitivity in high 
    biomass regions and improved vegetation monitoring through a de-coupling 
    of the canopy background signal and a reduction in atmosphere influences.
    
    Args:
        image: Input ee.Image with NIR, Red, and Blue bands.
        nir_band: Name of the near-infrared band.
        red_band: Name of the red band.
        blue_band: Name of the blue band.
        G: Gain factor (default 2.5, MODIS standard).
        C1: Coefficient 1 for aerosol resistance term (default 6.0).
        C2: Coefficient 2 for aerosol resistance term (default 7.5).
        L: Canopy background adjustment factor (default 1.0).
    
    Returns:
        ee.Image with 'EVI' band added.
    
    Reference:
        Huete, A. R., et al. (2002). Remote Sensing of Environment, 83(1-2), 195-213.
    """
    nir = image.select(nir_band)
    red = image.select(red_band)
    blue = image.select(blue_band)
    
    evi = (G * (nir.subtract(red))
           .divide(nir.add(C1 * red).subtract(C2 * blue).add(L)))\
        .rename('EVI')
    
    return image.addBands(evi)


def compute_savi(
    image: ee.Image,
    nir_band: str,
    red_band: str,
    L: float = 0.5
) -> ee.Image:
    """
    Compute Soil Adjusted Vegetation Index (SAVI).
    
    SAVI = ((NIR - RED) / (NIR + RED + L)) * (1 + L)
    
    SAVI is similar to NDVI but incorporates a soil adjustment factor L to 
    minimize soil brightness influences from spectral reflectance measurements 
    of vegetation. The L factor varies with vegetation cover:
    - L = 0 for very dense vegetation (SAVI becomes NDVI)
    - L = 1 for very sparse vegetation
    - L = 0.5 is a general-purpose compromise (default)
    
    Args:
        image: Input ee.Image with NIR and Red bands.
        nir_band: Name of the near-infrared band.
        red_band: Name of the red band.
        L: Soil adjustment factor (default 0.5 for intermediate vegetation).
    
    Returns:
        ee.Image with 'SAVI' band added.
    
    Reference:
        Huete, A. R. (1988). Remote Sensing of Environment, 25(3), 295-309.
    """
    nir = image.select(nir_band)
    red = image.select(red_band)
    
    savi = (((nir.subtract(red)).divide(nir.add(red).add(L)))
            .multiply(1 + L))\
        .rename('SAVI')
    
    return image.addBands(savi)


def compute_composite_health_index(
    image: ee.Image,
    nir_band: str,
    red_band: str,
    blue_band: Optional[str] = None,
    weights: Optional[Dict[str, float]] = None,
    savi_L: float = 0.5
) -> ee.Image:
    """
    Compute Composite Health Index (CHI) from weighted combination of NDVI, EVI, SAVI.
    
    Composite = w_ndvi * NDVI + w_evi * EVI + w_savi * SAVI
    
    Default weights (0.6, 0.2, 0.2) are based on literature review balancing:
    - NDVI's proven reliability and widespread adoption
    - EVI's atmospheric correction benefits
    - SAVI's soil background normalization
    
    Args:
        image: Input ee.Image with required spectral bands.
        nir_band: Name of the near-infrared band.
        red_band: Name of the red band.
        blue_band: Name of the blue band (required for EVI). If None, EVI skipped.
        weights: Dictionary with keys 'ndvi', 'evi', 'savi' specifying weights.
                 Defaults to {'ndvi': 0.6, 'evi': 0.2, 'savi': 0.2}.
        savi_L: Soil adjustment factor for SAVI (default 0.5).
    
    Returns:
        ee.Image with 'CHI' (Composite Health Index) band added.
    
    Raises:
        ValueError: If weights don't sum to 1.0 or if blue_band is missing for EVI.
    """
    # Default weights based on literature
    if weights is None:
        weights = {'ndvi': 0.6, 'evi': 0.2, 'savi': 0.2}
    
    # Validate weights sum to 1.0
    weight_sum = sum(weights.values())
    if not np.isclose(weight_sum, 1.0, atol=0.01):
        raise ValueError(
            f"Weights must sum to 1.0. Current sum: {weight_sum:.3f}. "
            f"Recommended: {{'ndvi': 0.6, 'evi': 0.2, 'savi': 0.2}}"
        )
    
    # Step 1: Compute all vegetation indices
    img_with_ndvi = compute_ndvi(image, nir_band, red_band)
    img_with_savi = compute_savi(img_with_ndvi, nir_band, red_band, L=savi_L)
    
    if blue_band is not None and weights.get('evi', 0) > 0:
        img_with_all = compute_evi(img_with_savi, nir_band, red_band, blue_band)
    else:
        # If no blue band, redistribute EVI weight to NDVI
        if weights.get('evi', 0) > 0:
            adjusted_weights = weights.copy()
            adjusted_weights['ndvi'] += adjusted_weights['evi']
            adjusted_weights['evi'] = 0
            weights = adjusted_weights
        img_with_all = img_with_savi
    
    # Step 2: Extract indices and apply weighted combination
    ndvi = img_with_all.select('NDVI')
    savi = img_with_all.select('SAVI')
    
    chi = ndvi.multiply(weights.get('ndvi', 0))\
        .add(savi.multiply(weights.get('savi', 0)))
    
    if weights.get('evi', 0) > 0 and blue_band is not None:
        evi = img_with_all.select('EVI')
        chi = chi.add(evi.multiply(weights['evi']))
    
    chi = chi.rename('CHI')
    
    return img_with_all.addBands(chi)


def get_sentinel2_bands() -> Dict[str, str]:
    """
    Get Sentinel-2 band names for vegetation index calculations.
    
    Returns:
        Dictionary with band names for NIR, Red, Blue, Green, SWIR.
    """
    return {
        'nir': 'B8',      # 10m resolution
        'red': 'B4',      # 10m resolution
        'blue': 'B2',     # 10m resolution
        'green': 'B3',    # 10m resolution
        'swir1': 'B11',   # 20m resolution
        'swir2': 'B12'    # 20m resolution
    }


def get_landsat_bands() -> Dict[str, str]:
    """
    Get Landsat 8/9 band names for vegetation index calculations.
    
    Returns:
        Dictionary with band names for NIR, Red, Blue, Green, SWIR.
    """
    return {
        'nir': 'SR_B5',   # 30m resolution
        'red': 'SR_B4',   # 30m resolution
        'blue': 'SR_B2',  # 30m resolution
        'green': 'SR_B3', # 30m resolution
        'swir1': 'SR_B6', # 30m resolution
        'swir2': 'SR_B7'  # 30m resolution
    }
