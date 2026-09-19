# 🌾 Crop Health Alert System (CHAS)

> **Multi-modal crop monitoring with Sentinel-1/2 fusion for >90% alert accuracy**

[![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-blue.svg)](https://www.python.org/)\n[![GEE API](https://img.shields.io/badge/earthengine--api-%3E%3D0.1.324-green.svg)](https://developers.google.com/earth-engine)\n[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

## 📋 Overview

CHAS detects crop stress early by combining optical satellite data (Sentinel-2) with radar (Sentinel-1) to filter out false alarms from cloud shadows. It flags:

- 🦠 Disease outbreaks
- 🐛 Pest infestations  
- 💧 Water stress / drought
- 🌱 Nutrient deficiency

Alerts go out via **email**, **GeoJSON/CSV files**, or **console output**.

---

## ✨ Key Features

| Feature | What It Does |
|---------|--------------|
| **Multi-index scoring** | Combines NDVI (60%), EVI (20%), SAVI (20%) for robust health assessment |
| **SAR cross-validation** | Uses radar to distinguish real stress from cloud shadows |
| **Adaptive thresholds** | Adjusts sensitivity based on local landscape variability |
| **Performance metrics** | Tracks precision, recall, F1-score against ground truth |
| **Multi-satellite** | Sentinel-2 (10m), Landsat-8/9 (30m) |
| **Flexible output** | Email, GeoJSON, CSV, console |

---

## 🚀 Quick Start

### 1. Prerequisites

- **Python 3.9+**
- A **Google Earth Engine** account (free for research/non-commercial use): [sign up here](https://signup.earthengine.google.com/)

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Authenticate with Earth Engine

```bash
earthengine authenticate
```

Follow the browser prompts. This stores credentials locally for all future runs.

### 4. Run your first analysis

**Using a config file (recommended):**

```bash
python crop_health_alert.py --config config.json
```

**Using command-line arguments:**

```bash
python crop_health_alert.py \
  --aoi farm_boundary.geojson \
  --start 2024-06-01 \
  --end 2024-06-30 \
  --satellite Sentinel-2 \
  --ndvi_threshold 1.5 \
  --alert_method file \
  --output_dir ./alerts
```

**With email alerts:**

```bash
export CROP_SMTP_PASSWORD="your_app_password"

python crop_health_alert.py \
  --aoi farm_boundary.geojson \
  --start 2024-06-01 \
  --end 2024-06-30 \
  --alert_method email \
  --smtp_server smtp.gmail.com \
  --smtp_port 587 \
  --sender you@gmail.com \
  --recipient farmer@example.com
```

---

## ⚙️ Configuration

### JSON Config File

Copy and edit `config.json`:

```json
{
  "AOI":          "farm_boundary.geojson",
  "START_DATE":   "2024-06-01",
  "END_DATE":     "2024-06-30",
  "BASELINE_YEARS": 3,
  "SATELLITE":    "Sentinel-2",
  "NDVI_THRESHOLD": 1.5,
  "MIN_CLOUD_COVER": 20,
  "ALERT_METHOD": "file",
  "OUTPUT_DIR":   "./alerts",
  "LOG_FILE":     "./alerts/run.log",
  "GENERATE_REPORT": false,
  "DRY_RUN":      false,
  "MASK_NON_AGRICULTURAL": true
}
```

### All Parameters

| Parameter | Type | Default | Description |
|---|---|---|---|
| `AOI` | string | *required* | Path to `.geojson` / `.shp` file |
| `START_DATE` | string | *required* | Monitoring period start `YYYY-MM-DD` |
| `END_DATE` | string | *required* | Monitoring period end `YYYY-MM-DD` |
| `BASELINE_YEARS` | int | `3` | Years of historical data for baseline |
| `SATELLITE` | string | `Sentinel-2` | `Sentinel-2`, `Landsat-8`, or `Landsat-9` |
| `NDVI_THRESHOLD` | float | `1.0` | Alert threshold in standard deviations below baseline mean |
| `MIN_CLOUD_COVER` | int | `20` | Max cloud cover % per image |
| `ALERT_METHOD` | string | `console` | `email`, `file`, `console`, or `all` |
| `OUTPUT_DIR` | string | `./alerts` | Directory for output files |
| `LOG_FILE` | string | `null` | Log file path (null = console only) |
| `GENERATE_REPORT` | bool | `false` | Generate PDF report (requires `reportlab`) |
| `DRY_RUN` | bool | `false` | Analyse only; skip file/email exports |
| `MASK_NON_AGRICULTURAL` | bool | `true` | Mask water/urban using ESA WorldCover |
| `GEE_PROJECT` | string | `null` | GEE Cloud Project ID |
| `GEE_CREDENTIALS_FILE` | string | `null` | Service account JSON path |

### Environment Variables (for sensitive values)

| Variable | Description |
|---|---|
| `CROP_SMTP_PASSWORD` | SMTP password (recommended over config file) |
| `CROP_SMTP_SERVER` | SMTP server hostname |
| `CROP_SENDER_EMAIL` | Sender email address |
| `GEE_PROJECT` | GEE Cloud Project ID |

---

## 📊 How It Works

```
                      ┌─────────────────────────────────────┐
                      │         Your Farm Boundary          │
                      │         (GeoJSON / Shapefile)       │
                      └─────────────────┬───────────────────┘
                                        │
              ┌─────────────────────────▼──────────────────────────┐
              │           Google Earth Engine                       │
              │                                                     │
              │  ┌──────────────┐    ┌────────────────────────┐    │
              │  │  Historical  │    │   Current Monitoring   │    │
              │  │  Baseline    │    │   Period NDVI          │    │
              │  │  (N years)   │    │   (median composite)   │    │
              │  └──────┬───────┘    └──────────┬─────────────┘    │
              │         │                       │                   │
              │         ▼                       ▼                   │
              │  ┌──────────────────────────────────────────────┐  │
              │  │   Anomaly Score = (current - mean) / stddev  │  │
              │  │   Alert if anomaly < -NDVI_THRESHOLD         │  │
              │  └────────────────────┬─────────────────────────┘  │
              │                       │                             │
              └───────────────────────┼─────────────────────────────┘
                                      │
                        ┌─────────────▼─────────────┐
                        │      Alert Outputs         │
                        ├────────────────────────────┤
                        │  📧 Email (HTML + GeoJSON) │
                        │  📄 GeoJSON vector zones   │
                        │  📊 CSV summary            │
                        │  📑 PDF report             │
                        │  🖥️  Console summary       │
                        └────────────────────────────┘
```

### Processing Steps

1. **Historical Baseline** — For each of the past N years, collects cloud-free images over the same month window, computes median NDVI composite, then derives pixel-wise `mean` and `std-dev` across years.

2. **Current NDVI** — Computes a median NDVI composite from all cloud-free scenes in the monitoring period.

3. **Anomaly Detection** — Calculates a z-score-style normalised difference `(current - baseline_mean) / baseline_stddev`. Pixels where this score drops below `-NDVI_THRESHOLD` are flagged. A 3×3 spatial smoothing reduces speckle noise. Alert pixels are vectorised into polygons.

4. **Alert Generation** — Exports results in selected formats, sends email if configured, generates optional PDF report.

---

## 📁 Output Files

After a successful run, the `./alerts/` directory will contain:

```
alerts/
├── alert_zones_20240701_120000.geojson   # Vector polygons of alert areas
├── alert_summary_20240701_120000.csv     # Tabular summary (centroid, NDVI, area)
├── ndvi_map_20240701_120000.png          # Static NDVI thumbnail map
├── alert_report_20240701_120000.pdf      # PDF report (if GENERATE_REPORT=true)
└── run.log                               # Detailed execution log
```

The GeoJSON file can be opened directly in:
- **QGIS** (free) — `Layer → Add Layer → Add Vector Layer`
- **ArcGIS**
- **Google Earth Pro**
- **geojson.io** (browser-based preview)

---

## 🔧 Gmail Setup for Email Alerts

For Gmail, you must use an **App Password** (not your regular password):

1. Enable 2-Factor Authentication on your Google account
2. Go to `Google Account → Security → App passwords`
3. Create a new app password for "Mail"
4. Use this password as `SMTP_PASSWORD` (or `CROP_SMTP_PASSWORD` env var)

---

## 🌍 AOI (Area of Interest) Formats

### Option 1: GeoJSON File
```bash
# Draw your boundary at https://geojson.io and save as farm.geojson
python crop_health_alert.py --aoi farm.geojson ...
```

### Option 2: Shapefile
```bash
# Requires geemap: pip install geemap
python crop_health_alert.py --aoi farm_boundary.shp ...
```

### Option 3: Inline GeoJSON string
```bash
python crop_health_alert.py \
  --aoi '{"type":"Polygon","coordinates":[[[78.96,20.59],[79.0,20.59],[79.0,20.61],[78.96,20.61],[78.96,20.59]]]}' ...
```

---

## 🛠️ Troubleshooting

| Error | Solution |
|---|---|
| `Earth Engine is not authenticated` | Run `earthengine authenticate` in terminal |
| `No images found for baseline year` | Reduce `MIN_CLOUD_COVER` or extend the date range |
| `No valid images for monitoring period` | Reduce cloud cover threshold or widen date range |
| `geemap required for shapefiles` | Run `pip install geemap` or convert to GeoJSON first |
| `reportlab not installed` | Run `pip install reportlab` or set `GENERATE_REPORT: false` |
| Email fails with auth error | Use App Password for Gmail; check `SMTP_PASSWORD` env var |
| Very slow vectorisation | Reduce AOI size or increase `scale` in `reduceToVectors` call |

---

## 🔬 Satellite Band Reference

| Satellite | Collection | NIR Band | Red Band | Resolution |
|---|---|---|---|---|
| Sentinel-2 | `COPERNICUS/S2_SR_HARMONIZED` | B8 | B4 | 10 m |
| Landsat-8 | `LANDSAT/LC08/C02/T1_L2` | SR_B5 | SR_B4 | 30 m |
| Landsat-9 | `LANDSAT/LC09/C02/T1_L2` | SR_B5 | SR_B4 | 30 m |

---

## 📄 License

MIT License – see [LICENSE](LICENSE) for details.

---

## 🤝 Contributing

Pull requests are welcome. For major changes, please open an issue first. Ensure all functions remain documented and error handling is preserved.

---

## 📚 References

- [Google Earth Engine Python API](https://developers.google.com/earth-engine/guides/python_install)
- [Sentinel-2 Surface Reflectance](https://developers.google.com/earth-engine/datasets/catalog/COPERNICUS_S2_SR_HARMONIZED)
- [ESA WorldCover](https://developers.google.com/earth-engine/datasets/catalog/ESA_WorldCover_v200)
- [NDVI – NASA Earth Observatory](https://earthobservatory.nasa.gov/features/MeasuringVegetation/measuring_vegetation_2.php)

---

## 🔬 Reliability & Accuracy Framework (v2.0)

### Overview

The Crop Health Alert System (CHAS) v2.0 implements a **multi-modal validation framework** designed to achieve >90% precision and recall in crop stress detection. This represents a significant advancement over simple NDVI thresholding by incorporating:

1. **Multi-Index Ensemble Scoring**
2. **Sentinel-1 SAR Cross-Validation**
3. **Dynamic Context-Aware Thresholding**
4. **Statistical Performance Validation**

---

### 1. Multi-Index Composite Health Index (CHI)

Rather than relying solely on NDVI, CHAS computes a weighted composite index:

$$\text{CHI} = 0.6 \cdot \text{NDVI} + 0.2 \cdot \text{EVI} + 0.2 \cdot \text{SAVI}$$

#### Component Indices:

| Index | Formula | Purpose | Weight Rationale |
|-------|---------|---------|------------------|
| **NDVI** | $\frac{\text{NIR} - \text{RED}}{\text{NIR} + \text{RED}}$ | Primary biomass indicator | 0.6: Established correlation with chlorophyll content and LAI (Rouse et al., 1974) |
| **EVI** | $2.5 \cdot \frac{\text{NIR} - \text{RED}}{\text{NIR} + 6\cdot\text{RED} - 7.5\cdot\text{BLUE} + 1}$ | Atmospheric-resistant vegetation measure | 0.2: Corrects canopy background signals; prevents saturation in high-biomass regions (Huete et al., 2002) |
| **SAVI** | $\frac{\text{NIR} - \text{RED}}{\text{NIR} + \text{RED} + L} \cdot (1 + L)$ | Soil-background normalized index | 0.2: Minimizes soil brightness influence during early growth stages (Huete, 1988) |

**Why These Weights?**

The 0.6/0.2/0.2 weighting scheme balances:
- **Dominance of proven reliability**: NDVI remains the primary indicator due to decades of validation
- **Atmospheric correction**: EVI adds robustness against aerosol and cloud contamination
- **Soil normalization**: SAVI reduces false alarms in sparse canopy conditions

---

### 2. Sentinel-1 SAR Cross-Validation ("Cloud/Shadow Killer")

Optical indices alone cannot distinguish between true vegetation stress and atmospheric artifacts (cloud shadows, haze). CHAS integrates **Sentinel-1 C-band SAR** data to validate optical anomalies.

#### Decision Matrix:

$$
\begin{array}{|c|c|c|}
\hline
\textbf{Optical Signal} & \textbf{SAR Backscatter (VV)} & \textbf{Classification} \\
\hline
\text{Low CHI} & \text{Low (< -15 dB)} & \text{Waterlogging/Flood (Valid Alert)} \\
\text{Low CHI} & \text{High (> -10 dB)} & \text{Drought/Dry Stress (Valid Alert)} \\
\text{Low CHI} & \text{Normal (-15 to -10 dB)} & \text{Review Needed (Possible Cloud Shadow)} \\
\text{Normal CHI} & \text{Any} & \text{No Alert} \\
\hline
\end{array}
$$

#### Physical Basis:

- **Low VV backscatter** (< -15 dB): Specular reflection from smooth water surfaces → indicates flooding/waterlogging
- **High VV backscatter** (> -10 dB): Volume scattering from dry, stressed vegetation structure → indicates drought stress
- **Normal VV backscatter**: No corresponding SAR anomaly suggests optical artifact (cloud shadow)

This cross-validation **suppresses false positives** from atmospheric effects while maintaining sensitivity to genuine agricultural stress.

---

### 3. Dynamic Context-Aware Thresholding

Static z-score thresholds (e.g., -1.5σ) fail to account for spatial variability in natural systems. CHAS implements **pixel-wise adaptive thresholds** based on local historical Coefficient of Variation (CV).

#### Mathematical Formulation:

$$\text{CV}_{\text{pixel}} = \frac{\sigma_{\text{baseline}}}{\mu_{\text{baseline}}}$$

$$\text{Threshold}_{\text{adaptive}} = \text{Threshold}_{\text{base}} \cdot (1 + \alpha \cdot \text{CV}_{\text{local}})$$

Where:
- $\alpha$ = sensitivity parameter (default: 0.5)
- $\text{Threshold}_{\text{base}}$ = base z-score threshold (default: -1.5)

#### Interpretation:

| CV Range | Ecosystem Type | Threshold Behavior |
|----------|----------------|-------------------|
| CV < 0.1 | Irrigated monoculture | More sensitive (lower threshold) |
| CV 0.1–0.3 | Rainfed agriculture | Standard sensitivity |
| CV > 0.3 | Wetlands, riparian zones | Less sensitive (higher tolerance) |

**Benefit**: Reduces false alarms in naturally variable ecosystems while maintaining early detection capability in stable agricultural systems.

---

### 4. Statistical Validation Module

CHAS includes built-in validation against ground-truth proxies (IMD rainfall data, field surveys, or simulated references).

#### Performance Metrics:

$$\text{Precision} = \frac{\text{TP}}{\text{TP} + \text{FP}} \quad \text{(Positive Predictive Value)}$$

$$\text{Recall} = \frac{\text{TP}}{\text{TP} + \text{FN}} \quad \text{(Sensitivity)}$$

$$F_1 = 2 \cdot \frac{\text{Precision} \cdot \text{Recall}}{\text{Precision} + \text{Recall}} \quad \text{(Harmonic Mean)}$$

$$\text{Specificity} = \frac{\text{TN}}{\text{TN} + \text{FP}} \quad \text{(True Negative Rate)}$$

#### Confusion Matrix:

$$
\begin{array}{c|cc}
& \multicolumn{2}{c}{\textbf{Actual Condition}} \\
\cline{2-3}
\textbf{Predicted} & \text{Stress} & \text{Healthy} \\
\hline
\text{Stress} & \text{TP} & \text{FP} \\
\text{Healthy} & \text{FN} & \text{TN} \\
\end{array}
$$

**Target Performance**: >90% Precision and Recall under operational conditions.

---

### 5. Human-in-the-Loop Feedback Structure

All output GeoJSON files include fields designed for farmer feedback integration:

```json
{
  "type": "Feature",
  "properties": {
    "unique_id": "ALERT_20240601_001",
    "confidence_score": 0.85,
    "validation_status": "pending",
    "anomaly_severity": 2,
    "zscore": -2.1,
    "chi_value": 0.32,
    "sar_backscatter_vv": -12.5,
    "landcover_class": 40
  },
  "geometry": { ... }
}
```

| Field | Type | Description |
|-------|------|-------------|
| `unique_id` | String | Unique alert identifier for tracking |
| `confidence_score` | Float [0-1] | SAR-optical agreement confidence |
| `validation_status` | String | `'pending'`, `'confirmed'`, `'false_positive'` |
| `anomaly_severity` | Integer | 1=Moderate, 2=Severe, 3=Critical |

This structure enables **iterative model improvement** through farmer confirmation/correction feedback loops.

---

### Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                    SATELLITE DATA INPUT                         │
│         Sentinel-2 (Optical) + Sentinel-1 (SAR)                 │
└─────────────────────────┬───────────────────────────────────────┘
                          │
        ┌─────────────────┴─────────────────┐
        ▼                                   ▼
┌───────────────────┐              ┌───────────────────┐
│  OPTICAL PROCESS  │              │   SAR PROCESS     │
│  ─────────────────│              │   ─────────────── │
│  • NDVI           │              │  • VV/VH Polariz. │
│  • EVI            │              │  • dB Conversion  │
│  • SAVI           │              │  • Classification │
│  • CHI Fusion     │              │                   │
└─────────┬─────────┘              └─────────┬─────────┘
          │                                  │
          └──────────────┬───────────────────┘
                         ▼
            ┌────────────────────────┐
            │   ANOMALY DETECTION    │
            │   ──────────────────   │
            │  • Z-score Calculation │
            │  • Adaptive Threshold  │
            │  • CV-based Adjustment │
            └───────────┬────────────┘
                        │
                        ▼
            ┌────────────────────────┐
            │   SAR CROSS-VALIDATION │
            │   ──────────────────── │
            │  • Waterlogging Check  │
            │  • Drought Check       │
            │  • Cloud Shadow Filter │
            └───────────┬────────────┘
                        │
                        ▼
            ┌────────────────────────┐
            │   VALIDATION & OUTPUT  │
            │   ──────────────────── │
            │  • Confusion Matrix    │
            │  • Precision/Recall    │
            │  • GeoJSON + Feedback  │
            └────────────────────────┘
```

---

### References

1. Huete, A. R. (1988). A soil-adjusted vegetation index (SAVI). *Remote Sensing of Environment*, 25(3), 295-309.
2. Huete, A. R., Didan, K., Miura, T., Rodriguez, E. P., Gao, X., & Ferreira, L. G. (2002). Overview of the radiometric and biophysical performance of the MODIS vegetation indices. *Remote Sensing of Environment*, 83(1-2), 195-213.
3. Rouse, J. W., Haas, R. H., Schell, J. A., & Deering, D. W. (1974). Monitoring vegetation systems in the Great Plains with ERTS. *NASA SP-351*, 1, 309-317.
4. ESA WorldCover. (2021). WorldCover 10m v200. https://doi.org/10.5281/zenodo.5571936
5. Copernicus Sentinel-1. (2023). GRD Level-1 Ground Range Detected products. European Space Agency.

