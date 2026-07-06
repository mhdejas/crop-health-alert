#!/usr/bin/env python3
"""
generate_demo_screenshots.py
============================
Generates demonstration screenshots for the GitHub README without
requiring an active GEE connection.

Produces:
  screenshots/ndvi_map_example.png       – simulated NDVI anomaly map
  screenshots/qgis_alert_zones.png       – simulated QGIS-style alert view
  screenshots/pdf_report_preview.png     – simulated PDF report preview
  screenshots/console_output.png         – terminal-style console output
  screenshots/alert_email_preview.png    – HTML email preview

Run: python generate_demo_screenshots.py
Requires: pip install Pillow
"""

from pathlib import Path
import math
import random

try:
    from PIL import Image, ImageDraw, ImageFont, ImageFilter
except ImportError:
    raise SystemExit("Install Pillow first:  pip install Pillow")

random.seed(42)
OUT = Path("screenshots")
OUT.mkdir(exist_ok=True)


# ── Colour palette ──────────────────────────────────────────────────────────
C_BG       = (15,  20,  25)
C_PANEL    = (22,  32,  42)
C_BORDER   = (40,  60,  80)
C_GREEN    = (46, 160,  67)
C_YELLOW   = (230,190,  50)
C_RED      = (210,  50,  50)
C_ORANGE   = (220, 120,  40)
C_BLUE     = (30, 130, 200)
C_TEXT     = (220,230,240)
C_MUTED    = (120,140,160)
C_WHITE    = (255,255,255)
C_DARKGREY = (35,  45,  55)


def try_font(size: int) -> ImageFont.ImageFont:
    """Load a system monospace font or fall back to default."""
    candidates = [
        "DejaVuSansMono.ttf", "Consolas.ttf", "CourierNew.ttf",
        "LiberationMono-Regular.ttf", "FreeMono.ttf",
    ]
    for name in candidates:
        try:
            return ImageFont.truetype(name, size)
        except Exception:
            pass
    return ImageFont.load_default()


def try_font_bold(size: int) -> ImageFont.ImageFont:
    candidates = [
        "DejaVuSansMono-Bold.ttf", "ConsolasBold.ttf",
        "LiberationMono-Bold.ttf",
    ]
    for name in candidates:
        try:
            return ImageFont.truetype(name, size)
        except Exception:
            pass
    return try_font(size)


# ── Helper ───────────────────────────────────────────────────────────────────
def rounded_rect(draw, xy, radius=8, fill=None, outline=None, width=1):
    x0, y0, x1, y1 = xy
    draw.rounded_rectangle([x0, y0, x1, y1], radius=radius, fill=fill,
                            outline=outline, width=width)


# ════════════════════════════════════════════════════════════════════════════
# 1. NDVI Anomaly Map
# ════════════════════════════════════════════════════════════════════════════
def make_ndvi_map():
    W, H = 900, 640
    img  = Image.new("RGB", (W, H), C_BG)
    draw = ImageDraw.Draw(img)

    fn   = try_font(13)
    fn_b = try_font_bold(15)
    fn_t = try_font_bold(20)

    # Title bar
    draw.rectangle([0, 0, W, 44], fill=(18, 28, 38))
    draw.text((16, 12), "🌾  NDVI Anomaly Map — Monitoring Period: 2024-06-01 → 2024-06-30", font=fn_b, fill=C_TEXT)

    # Map area
    MAP = (16, 54, W - 200, H - 16)
    rounded_rect(draw, MAP, radius=6, fill=(24, 40, 32), outline=C_BORDER, width=1)
    mx, my = MAP[0], MAP[1]
    mw, mh = MAP[2] - MAP[0], MAP[3] - MAP[1]

    # Paint NDVI background gradient (green = healthy)
    for y in range(mh):
        for x in range(0, mw, 2):
            base = 0.4 + 0.4 * math.sin(x / 60) * math.cos(y / 50)
            base += random.gauss(0, 0.04)
            base = max(0, min(1, base))
            r = int(30  + (1 - base) * 130)
            g = int(80  + base * 120)
            b = int(30  + base * 20)
            try:
                img.putpixel((mx + x, my + y), (r, g, b))
                img.putpixel((mx + x + 1, my + y), (r, g, b))
            except IndexError:
                pass

    # Blur slightly for realism
    region = img.crop(MAP)
    region = region.filter(ImageFilter.GaussianBlur(1.2))
    img.paste(region, (MAP[0], MAP[1]))
    draw = ImageDraw.Draw(img)

    # Alert zones (red polygons)
    zones = [
        [(130, 120), (200, 110), (220, 160), (190, 180), (130, 170)],
        [(310, 220), (380, 210), (400, 270), (340, 285), (305, 255)],
        [(490, 140), (550, 130), (570, 190), (510, 200)],
        [(200, 300), (260, 290), (270, 340), (210, 350)],
    ]
    for zone in zones:
        pts = [(mx + x, my + y) for x, y in zone]
        draw.polygon(pts, fill=(180, 40, 40, 160), outline=(255, 80, 80))
        cx = sum(p[0] for p in pts) // len(pts)
        cy = sum(p[1] for p in pts) // len(pts)
        draw.text((cx - 6, cy - 6), "⚠", font=fn, fill=(255, 220, 60))

    # Grid lines
    for x in range(0, mw, 80):
        draw.line([(mx + x, my), (mx + x, MAP[3])], fill=(40, 60, 50), width=1)
    for y in range(0, mh, 60):
        draw.line([(mx, my + y), (MAP[2], my + y)], fill=(40, 60, 50), width=1)

    # Legend panel
    lx = MAP[2] + 12
    rounded_rect(draw, [lx, 54, W - 8, H - 16], radius=6, fill=C_PANEL, outline=C_BORDER)
    draw.text((lx + 10, 66), "NDVI Legend", font=fn_b, fill=C_TEXT)

    legend = [
        (C_RED,    "Alert zone (−1.5σ+)"),
        ((40,160,60), "Healthy crop"),
        ((180,180,40), "Moderate stress"),
        ((200,100,40), "Severe stress"),
        ((60,100,160), "Water / bare"),
    ]
    for i, (col, label) in enumerate(legend):
        y = 95 + i * 36
        draw.rectangle([lx + 10, y, lx + 30, y + 18], fill=col, outline=C_BORDER)
        draw.text((lx + 38, y + 2), label, font=fn, fill=C_TEXT)

    # Stats box
    sy = 300
    draw.text((lx + 10, sy), "Statistics", font=fn_b, fill=C_TEXT)
    stats = [
        ("Zones detected", "4"),
        ("Total area",     "~38 ha"),
        ("Mean NDVI",      "0.241"),
        ("Baseline mean",  "0.612"),
        ("Anomaly (σ)",    "−1.87"),
        ("Satellite",      "Sentinel-2"),
        ("Cloud cover",    "< 20%"),
    ]
    for i, (k, v) in enumerate(stats):
        y = sy + 28 + i * 26
        draw.text((lx + 12, y), k + ":", font=fn, fill=C_MUTED)
        draw.text((lx + 12, y + 12), v, font=fn_b, fill=C_YELLOW)

    img.save(OUT / "ndvi_map_example.png")
    print("✓  ndvi_map_example.png")


# ════════════════════════════════════════════════════════════════════════════
# 2. QGIS-Style Alert Zone View
# ════════════════════════════════════════════════════════════════════════════
def make_qgis_view():
    W, H = 1000, 700
    img  = Image.new("RGB", (W, H), (240, 238, 232))
    draw = ImageDraw.Draw(img)
    fn   = try_font(12)
    fn_b = try_font_bold(14)
    fn_t = try_font_bold(18)

    # QGIS-like top bar
    draw.rectangle([0, 0, W, 34], fill=(55, 60, 70))
    for i, lbl in enumerate(["Project", "Edit", "View", "Layer", "Settings", "Plugins", "Vector", "Raster", "Mesh", "Processing", "Help"]):
        draw.text((12 + i * 72, 10), lbl, font=fn, fill=(210, 215, 220))
    draw.rectangle([0, 34, W, 68], fill=(70, 75, 85))
    for i, sym in enumerate(["⊞", "✎", "💾", "🔍", "✋", "➡", "🔎", "📏", "⬡", "🖊"]):
        draw.text((14 + i * 36, 48), sym, font=fn, fill=C_TEXT)

    # Left panel
    draw.rectangle([0, 68, 200, H], fill=(248, 246, 242))
    draw.rectangle([0, 68, 200, 100], fill=(230, 228, 222))
    draw.text((8, 78), "Layers", font=fn_b, fill=(50, 50, 60))
    layers = [
        ("▶ alert_zones_20240701.geojson", C_RED),
        ("▶ current_ndvi_june2024",        C_GREEN),
        ("▶ baseline_mean_ndvi",           (80, 120, 80)),
        ("▶ farm_boundary.geojson",        C_BLUE),
        ("▶ ESA_WorldCover_Cropland",      (120, 160, 80)),
        ("▶ OpenStreetMap",                C_MUTED),
    ]
    for i, (lbl, col) in enumerate(layers):
        y = 108 + i * 30
        draw.rectangle([4, y + 2, 196, y + 24], fill=(238, 236, 230) if i % 2 == 0 else (248, 246, 242))
        draw.rectangle([4, y + 6, 20, y + 20], fill=col)
        draw.text((26, y + 5), lbl[:28], font=fn, fill=(40, 40, 50))

    # Map canvas
    MAP = (200, 68, W - 200, H - 30)
    draw.rectangle(MAP, fill=(210, 230, 200))
    mx, my = MAP[0], MAP[1]
    mw, mh = MAP[2] - MAP[0], MAP[3] - MAP[1]

    # Field polygons (green)
    fields = [
        [(50, 80), (200, 75), (205, 180), (55, 190)],
        [(210, 70), (340, 65), (345, 160), (215, 170)],
        [(50, 200), (180, 195), (185, 310), (52, 315)],
        [(190, 185), (360, 178), (365, 290), (195, 298)],
        [(370, 60), (480, 55), (485, 200), (372, 208)],
        [(60, 330), (250, 325), (255, 430), (62, 438)],
        [(260, 315), (400, 308), (405, 420), (263, 428)],
    ]
    for fld in fields:
        pts = [(mx + x, my + y) for x, y in fld]
        g   = random.randint(130, 190)
        draw.polygon(pts, fill=(60, g, 50), outline=(40, 100, 40))

    # Alert zone overlays (red hatched fill)
    alert_zones_q = [
        [(70, 85), (170, 80), (175, 150), (72, 158)],
        [(220, 75), (310, 70), (312, 130), (222, 138)],
        [(270, 200), (360, 192), (362, 260), (272, 268)],
    ]
    for zone in alert_zones_q:
        pts = [(mx + x, my + y) for x, y in zone]
        draw.polygon(pts, fill=(200, 40, 40, 120), outline=(255, 60, 60), width=2)
        cx = sum(p[0] for p in pts) // len(pts)
        cy = sum(p[1] for p in pts) // len(pts)
        draw.ellipse([cx - 8, cy - 8, cx + 8, cy + 8], fill=(255, 80, 80))
        draw.text((cx - 5, cy - 6), "!", font=fn_b, fill=C_WHITE)

    # Scale bar
    draw.rectangle([mx + 20, MAP[3] - 26, mx + 120, MAP[3] - 14], fill=C_WHITE, outline=(80, 80, 80))
    draw.rectangle([mx + 20, MAP[3] - 26, mx + 70, MAP[3] - 14], fill=(40, 40, 40))
    draw.text((mx + 18, MAP[3] - 38), "0        500 m", font=fn, fill=(40, 40, 40))

    # Compass
    draw.text((MAP[2] - 60, my + 10), "N\n↑", font=fn_b, fill=(40, 40, 40))

    # Right panel
    rx = MAP[2] + 4
    draw.rectangle([rx, 68, W, H], fill=(248, 246, 242))
    draw.text((rx + 8, 80), "Feature Info", font=fn_b, fill=(50, 50, 60))
    draw.line([(rx + 4, 100), (W - 4, 100)], fill=(200, 198, 192), width=1)
    info = [
        ("Layer",       "alert_zones"),
        ("FID",         "1"),
        ("Mean NDVI",   "0.237"),
        ("Anomaly σ",   "−2.14"),
        ("Area (ha)",   "12.4"),
        ("Centroid lon","78.968°"),
        ("Centroid lat","20.601°"),
    ]
    for i, (k, v) in enumerate(info):
        y = 110 + i * 32
        draw.rectangle([rx + 4, y, W - 4, y + 28], fill=(240, 238, 232) if i%2==0 else (248,246,242))
        draw.text((rx + 8, y + 6),    k, font=fn, fill=(80, 80, 90))
        draw.text((rx + 8, y + 18), v, font=fn_b, fill=(30, 30, 40))

    # Status bar
    draw.rectangle([0, H - 30, W, H], fill=(55, 60, 70))
    draw.text((8, H - 20), "Coordinate: 78.968°E 20.601°N   |   Scale 1:15 000   |   EPSG:4326   |   3 alert zones selected", font=fn, fill=(180,185,190))

    img.save(OUT / "qgis_alert_zones.png")
    print("✓  qgis_alert_zones.png")


# ════════════════════════════════════════════════════════════════════════════
# 3. PDF Report Preview
# ════════════════════════════════════════════════════════════════════════════
def make_pdf_preview():
    W, H = 800, 1000
    img  = Image.new("RGB", (W, H), (240, 238, 234))
    draw = ImageDraw.Draw(img)
    fn   = try_font(13)
    fn_b = try_font_bold(15)
    fn_t = try_font_bold(24)
    fn_s = try_font(11)

    # Page shadow
    draw.rectangle([14, 14, W - 10, H - 10], fill=(180, 178, 174))
    draw.rectangle([10, 10, W - 14, H - 14], fill=C_WHITE)

    # Header stripe
    draw.rectangle([10, 10, W - 14, 90], fill=(30, 90, 50))
    draw.text((30, 20), "Agricultural Health Alert System", font=fn_b, fill=C_WHITE)
    draw.text((30, 44), "NDVI Anomaly Detection Report", font=fn_t, fill=(180, 240, 180))
    draw.text((30, 74), "Generated: 2024-07-01 08:32 UTC", font=fn_s, fill=(160, 220, 160))

    # Summary table
    ty = 110
    draw.text((30, ty), "Analysis Summary", font=fn_b, fill=(30, 90, 50))
    headers = ["Parameter", "Value"]
    rows = [
        ["Satellite",          "Sentinel-2 (10 m)"],
        ["Monitoring period",  "2024-06-01 → 2024-06-30"],
        ["Baseline years",     "3 (2021, 2022, 2023)"],
        ["NDVI threshold",     "1.5 σ below baseline mean"],
        ["Cloud cover filter", "≤ 20%"],
        ["Alert zones found",  "4 zones (~38 ha total)"],
        ["Mean NDVI (zones)",  "0.241 (baseline: 0.612)"],
        ["Land mask",          "ESA WorldCover cropland"],
    ]
    col_w = [280, 280]
    tx = 30
    # header row
    draw.rectangle([tx, ty + 24, tx + sum(col_w), ty + 46], fill=(30, 90, 50))
    draw.text((tx + 6, ty + 28), "Parameter", font=fn_s, fill=C_WHITE)
    draw.text((tx + col_w[0] + 6, ty + 28), "Value", font=fn_s, fill=C_WHITE)
    for ri, row in enumerate(rows):
        ry = ty + 46 + ri * 26
        bg = (240, 248, 240) if ri % 2 == 0 else C_WHITE
        draw.rectangle([tx, ry, tx + sum(col_w), ry + 26], fill=bg)
        draw.text((tx + 6,          ry + 6), row[0], font=fn_s, fill=(50, 50, 60))
        draw.text((tx + col_w[0]+6, ry + 6), row[1], font=fn_b, fill=(30, 90, 50))
    draw.rectangle([tx, ty + 24, tx + sum(col_w), ty + 46 + len(rows)*26],
                   outline=(180, 200, 180), width=1)

    # Simulated mini map thumbnail
    map_y = ty + 46 + len(rows) * 26 + 30
    draw.text((30, map_y), "NDVI Anomaly Map Thumbnail", font=fn_b, fill=(30, 90, 50))
    map_box = (30, map_y + 24, W - 30 - 14, map_y + 240)
    draw.rectangle(map_box, fill=(40, 90, 55))
    # Fake map content
    for x in range(0, map_box[2] - map_box[0], 4):
        for y in range(0, map_box[3] - map_box[1], 4):
            v = 0.35 + 0.55 * abs(math.sin(x/40) * math.cos(y/35))
            r = int(30 + (1-v)*130)
            g = int(70 + v*120)
            try:
                img.putpixel((map_box[0]+x, map_box[1]+y), (r, g, 40))
            except IndexError:
                pass
    draw = ImageDraw.Draw(img)
    # Red alert blobs
    for cx, cy, r_ in [(120, 80, 28), (300, 100, 22), (200, 150, 18)]:
        bx, by = map_box[0]+cx, map_box[1]+cy
        draw.ellipse([bx-r_, by-r_, bx+r_, by+r_], fill=(200, 40, 40, 180), outline=(255,80,80))

    # Recommendations
    rec_y = map_box[3] + 24
    draw.text((30, rec_y), "Recommendations", font=fn_b, fill=(30, 90, 50))
    recs = [
        "1.  Conduct ground-truth inspection of flagged zones within 48–72 hours.",
        "2.  Cross-reference with recent rainfall and temperature anomaly records.",
        "3.  Apply targeted pest/disease scouting protocol to alert areas.",
        "4.  Consider UAV survey for high-priority zones (anomaly > 2σ).",
        "5.  Re-run analysis after next cloud-free overpass to confirm persistence.",
    ]
    for i, rec in enumerate(recs):
        draw.text((30, rec_y + 28 + i * 24), rec, font=fn_s, fill=(40, 50, 60))

    # Footer
    draw.line([(30, H - 45), (W - 30, H - 45)], fill=(180, 200, 180), width=1)
    draw.text((30, H - 36), "Agricultural Health Alert System  ·  MIT License  ·  github.com/your-username/crop-health-alert", font=fn_s, fill=C_MUTED)

    img.save(OUT / "pdf_report_preview.png")
    print("✓  pdf_report_preview.png")


# ════════════════════════════════════════════════════════════════════════════
# 4. Console / Terminal Output
# ════════════════════════════════════════════════════════════════════════════
def make_console_output():
    W, H = 900, 580
    img  = Image.new("RGB", (W, H), (18, 18, 18))
    draw = ImageDraw.Draw(img)
    fn   = try_font(14)
    fn_b = try_font_bold(14)

    # Title bar
    draw.rectangle([0, 0, W, 34], fill=(40, 40, 44))
    for i, col in enumerate([(235, 90, 80), (250, 190, 60), (100, 200, 80)]):
        draw.ellipse([12 + i*22, 10, 24 + i*22, 22], fill=col)
    draw.text((W//2 - 120, 8), "Terminal — crop_health_alert.py", font=fn, fill=(180, 180, 180))

    lines = [
        ("$", "python crop_health_alert.py --config config.json",          (100, 200, 100), fn_b),
        ("", "",                                                            C_TEXT, fn),
        ("", "2024-07-01 08:31:42 [INFO] ══════════════════════════════════", C_MUTED, fn),
        ("", "2024-07-01 08:31:42 [INFO]  Agricultural Health Alert System – Starting", (120, 220, 120), fn_b),
        ("", "2024-07-01 08:31:42 [INFO] ══════════════════════════════════", C_MUTED, fn),
        ("", "2024-07-01 08:31:42 [INFO] Config: satellite=Sentinel-2 | period=2024-06-01→2024-06-30 | threshold=1.5σ", C_TEXT, fn),
        ("", "2024-07-01 08:31:43 [INFO] Earth Engine initialised successfully.", (100, 200, 100), fn),
        ("", "2024-07-01 08:31:44 [INFO] AOI loaded from GeoJSON: farm_boundary.geojson", C_TEXT, fn),
        ("", "2024-07-01 08:31:44 [INFO] Step 1/4 – Computing historical NDVI baseline …", (255, 200, 60), fn_b),
        ("", "  Baseline year: 100%|████████████████| 3/3 [00:18<00:00,  6.1s/year]", (80, 160, 255), fn),
        ("", "2024-07-01 08:31:44 [INFO]   Computing baseline for year 2021 → 2021",   C_MUTED, fn),
        ("", "2024-07-01 08:31:50 [INFO]   Computing baseline for year 2022 → 2022",   C_MUTED, fn),
        ("", "2024-07-01 08:31:56 [INFO]   Computing baseline for year 2023 → 2023",   C_MUTED, fn),
        ("", "2024-07-01 08:32:02 [INFO] Baseline computed from 3 year(s).",            (100, 200, 100), fn),
        ("", "2024-07-01 08:32:02 [INFO] Step 2/4 – Computing current NDVI composite …",(255,200,60), fn_b),
        ("", "2024-07-01 08:32:02 [INFO] Found 7 image(s) for monitoring period.",      C_TEXT, fn),
        ("", "2024-07-01 08:32:09 [INFO] Current NDVI composite completed.",            (100,200,100), fn),
        ("", "2024-07-01 08:32:09 [INFO] Step 3/4 – Detecting NDVI anomalies …",        (255,200,60), fn_b),
        ("", "2024-07-01 08:32:09 [INFO] Converting anomaly raster to vector alert zones …", C_TEXT, fn),
        ("", "2024-07-01 08:32:24 [INFO] Anomaly detection completed.",                 (100,200,100), fn),
        ("", "2024-07-01 08:32:24 [INFO] Step 4/4 – Generating alerts …",               (255,200,60), fn_b),
        ("", "2024-07-01 08:32:24 [INFO] Exporting 4 alert zone(s) → ./alerts/alert_zones_20240701_083224.geojson", C_TEXT, fn),
        ("", "",  C_TEXT, fn),
        ("", "════════════════════════════════════════════════════════════", (80, 120, 80), fn),
        ("", "  🌾  CROP HEALTH ALERT SYSTEM — RESULTS",                   (180, 240, 180), fn_b),
        ("", "════════════════════════════════════════════════════════════", (80, 120, 80), fn),
        ("", "  Monitoring period : 2024-06-01 → 2024-06-30",              C_TEXT, fn),
        ("", "  Satellite         : Sentinel-2",                            C_TEXT, fn),
        ("", "  NDVI threshold    : 1.5 σ",                                C_TEXT, fn),
        ("", "  Alert zones found : 4  ⚠️",                                 (255, 120, 80), fn_b),
        ("", "  Mean NDVI (zones) : 0.241",                                 C_TEXT, fn),
        ("", "  GeoJSON saved to  : ./alerts/alert_zones_20240701_083224.geojson", (120, 200, 255), fn),
        ("", "  CSV saved to      : ./alerts/alert_summary_20240701_083224.csv",   (120, 200, 255), fn),
        ("", "  Map thumbnail     : ./alerts/ndvi_map_20240701_083224.png",        (120, 200, 255), fn),
        ("", "════════════════════════════════════════════════════════════", (80, 120, 80), fn),
    ]

    y = 50
    for prefix, text, color, font in lines:
        if prefix:
            draw.text((14, y), prefix, font=fn, fill=(100, 200, 100))
            draw.text((28, y), text, font=font, fill=color)
        else:
            draw.text((14, y), text, font=font, fill=color)
        y += 20
        if y > H - 20:
            break

    # Cursor blink
    draw.rectangle([14, y + 2, 22, y + 16], fill=(200, 200, 200))

    img.save(OUT / "console_output.png")
    print("✓  console_output.png")


# ════════════════════════════════════════════════════════════════════════════
# 5. Email Alert Preview
# ════════════════════════════════════════════════════════════════════════════
def make_email_preview():
    W, H = 800, 640
    img  = Image.new("RGB", (W, H), (245, 245, 248))
    draw = ImageDraw.Draw(img)
    fn   = try_font(13)
    fn_b = try_font_bold(14)
    fn_t = try_font_bold(20)
    fn_s = try_font(11)

    # Email client chrome
    draw.rectangle([0, 0, W, 40], fill=(55, 60, 68))
    draw.text((16, 12), "✉  Gmail", font=fn_b, fill=(180, 185, 195))
    draw.rectangle([0, 40, W, H], fill=(240, 242, 245))

    # Email card
    E = (20, 50, W - 20, H - 20)
    rounded_rect(draw, E, radius=6, fill=C_WHITE, outline=(200, 200, 205))

    ex = E[0] + 24

    # Subject
    draw.text((ex, 66), "⚠️  Crop Health Alert – 4 anomaly zone(s) detected [2024-06-01 → 2024-06-30]", font=fn_b, fill=(180, 40, 40))
    draw.line([(ex, 98), (E[2] - 24, 98)], fill=(220, 220, 225), width=1)

    # From / To
    draw.text((ex, 106), "From:", font=fn_s, fill=C_MUTED)
    draw.text((ex + 52, 106), "alerts@cropmonitor.io", font=fn_s, fill=C_BLUE)
    draw.text((ex, 124), "To:", font=fn_s, fill=C_MUTED)
    draw.text((ex + 52, 124), "farmer@example.com", font=fn_s, fill=C_BLUE)
    draw.text((E[2] - 160, 106), "01 Jul 2024, 08:32", font=fn_s, fill=C_MUTED)
    draw.line([(ex, 144), (E[2] - 24, 144)], fill=(220, 220, 225), width=1)

    # Body
    draw.rectangle([ex, 152, E[2]-24, 196], fill=(255, 245, 245))
    draw.text((ex + 10, 160), "⚠️  Agricultural Health Alert", font=fn_t, fill=(180, 40, 40))
    draw.text((ex + 10, 186), "4 anomalous NDVI zone(s) detected during 2024-06-01 → 2024-06-30", font=fn, fill=(60, 60, 70))

    # Stats table
    table_y = 210
    draw.text((ex, table_y), "Analysis Summary", font=fn_b, fill=(40, 40, 50))
    trows = [
        ("Satellite",        "Sentinel-2"),
        ("Alert zones",      "4"),
        ("NDVI threshold",   "1.5 σ"),
        ("Baseline years",   "3"),
        ("Mean NDVI (zones)","0.241"),
    ]
    for i, (k, v) in enumerate(trows):
        ry = table_y + 28 + i * 28
        bg = (245, 250, 245) if i % 2 == 0 else C_WHITE
        draw.rectangle([ex, ry, E[2]-24, ry+26], fill=bg, outline=(215, 220, 215))
        draw.text((ex + 8,   ry + 6), k, font=fn_s, fill=(80, 80, 90))
        draw.text((ex + 200, ry + 6), v, font=fn_b, fill=(30, 90, 50))

    # Recommended actions
    ra_y = table_y + 28 + len(trows)*28 + 16
    draw.text((ex, ra_y), "Recommended Actions", font=fn_b, fill=(40, 40, 50))
    for i, rec in enumerate([
        "• Inspect flagged fields for signs of disease or pest damage.",
        "• Cross-reference with recent rainfall and temperature data.",
        "• Consider commissioning a ground-truth survey.",
    ]):
        draw.text((ex, ra_y + 26 + i*22), rec, font=fn_s, fill=(60, 60, 70))

    # Attachment
    att_y = ra_y + 26 + 3*22 + 16
    draw.rectangle([ex, att_y, ex + 280, att_y + 38], fill=(240, 248, 255), outline=(180, 200, 230))
    draw.text((ex + 10, att_y + 4),  "📎  alert_zones_20240701_083224.geojson", font=fn_s, fill=C_BLUE)
    draw.text((ex + 10, att_y + 20), "GeoJSON vector file  ·  18.4 KB", font=fn_s, fill=C_MUTED)

    # Footer
    foot_y = H - 60
    draw.line([(ex, foot_y), (E[2]-24, foot_y)], fill=(220, 220, 225), width=1)
    draw.text((ex, foot_y + 8), "Generated by Agricultural Health Alert System  ·  2024-07-01 08:32 UTC", font=fn_s, fill=C_MUTED)

    img.save(OUT / "alert_email_preview.png")
    print("✓  alert_email_preview.png")


# ════════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    print("Generating demo screenshots …\n")
    make_ndvi_map()
    make_qgis_view()
    make_pdf_preview()
    make_console_output()
    make_email_preview()
    print(f"\n✅  All screenshots saved to ./{OUT}/")
