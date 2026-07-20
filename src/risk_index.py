"""
risk_index.py
--------------
Core functions for computing a bushfire risk index from Sentinel-2
vegetation/moisture indices and SRTM-derived terrain variables.

Designed to run against Google Earth Engine (GEE) ee.Image objects.
All functions are pure and unit-testable independent of GEE auth,
except where noted.

Author: Qifeng Wang
"""

import ee


# ---------------------------------------------------------------------
# 1. Spectral indices
# ---------------------------------------------------------------------

def add_ndvi(image: ee.Image) -> ee.Image:
    """Add NDVI band (vegetation greenness / fuel load proxy).

    NDVI = (NIR - Red) / (NIR + Red)
    Sentinel-2 SR: B8 = NIR, B4 = Red
    """
    ndvi = image.normalizedDifference(["B8", "B4"]).rename("NDVI")
    return image.addBands(ndvi)


def add_ndmi(image: ee.Image) -> ee.Image:
    """Add NDMI band (vegetation moisture content proxy).

    NDMI = (NIR - SWIR1) / (NIR + SWIR1)
    Sentinel-2 SR: B8 = NIR, B11 = SWIR1

    Low NDMI -> drier canopy -> higher fire susceptibility.
    """
    ndmi = image.normalizedDifference(["B8", "B11"]).rename("NDMI")
    return image.addBands(ndmi)


def mask_s2_clouds(image: ee.Image) -> ee.Image:
    """Cloud-mask a Sentinel-2 SR HARMONIZED image using the QA60 band."""
    qa = image.select("QA60")
    cloud_bit = 1 << 10
    cirrus_bit = 1 << 11
    mask = (
        qa.bitwiseAnd(cloud_bit).eq(0)
        .And(qa.bitwiseAnd(cirrus_bit).eq(0))
    )
    return image.updateMask(mask).divide(10000).copyProperties(
        image, ["system:time_start"]
    )


# ---------------------------------------------------------------------
# 2. Terrain variables
# ---------------------------------------------------------------------

def get_terrain_layers(dem: ee.Image) -> ee.Image:
    """Derive slope and a southern-hemisphere solar-exposure index
    from an SRTM (or similar) DEM.

    Aspect is folded into a 0-1 'north-facing-ness' score because in
    the Southern Hemisphere north-facing slopes receive more direct
    sun and therefore dry out faster -> higher fire risk.
    """
    terrain = ee.Algorithms.Terrain(dem)
    slope = terrain.select("slope").rename("slope")
    aspect = terrain.select("aspect").rename("aspect")

    # North-facing-ness: cos(aspect) peaks (=1) at aspect=0 (due north)
    # and troughs (=0 after rescale) at aspect=180 (due south).
    aspect_rad = aspect.multiply(3.14159265).divide(180)
    north_facing = aspect_rad.cos().add(1).divide(2).rename("north_facing")

    return dem.addBands([slope, north_facing])


# ---------------------------------------------------------------------
# 3. Normalisation helper
# ---------------------------------------------------------------------

def normalize(image: ee.Image, band: str, region: ee.Geometry,
              scale: int = 20) -> ee.Image:
    """Min-max normalise a single band to 0-1 over the given region."""
    stats = image.select(band).reduceRegion(
        reducer=ee.Reducer.minMax(),
        geometry=region,
        scale=scale,
        maxPixels=1e9,
        bestEffort=True,
    )
    band_min = ee.Number(stats.get(f"{band}_min"))
    band_max = ee.Number(stats.get(f"{band}_max"))
    return image.select(band).subtract(band_min).divide(
        band_max.subtract(band_min)
    ).rename(f"{band}_norm")


# ---------------------------------------------------------------------
# 4. Composite risk index
# ---------------------------------------------------------------------

# Default weights - tune these against known fire-history pixels
# (see notebooks/02_validation.ipynb for a suggested calibration approach)
DEFAULT_WEIGHTS = {
    "fuel_load": 0.35,       # from NDVI (more biomass = more fuel)
    "dryness": 0.35,         # from inverse NDMI (drier canopy = higher risk)
    "slope": 0.15,           # steeper slope = faster fire spread
    "north_facing": 0.15,    # more solar exposure = drier fuel (Sth Hemisphere)
}


def compute_risk_index(
    s2_image: ee.Image,
    dem: ee.Image,
    region: ee.Geometry,
    weights: dict = None,
) -> ee.Image:
    """Combine spectral + terrain layers into a single 0-100 risk index.

    Returns an ee.Image with bands:
      - NDVI, NDMI, slope, north_facing (raw)
      - risk_index (0-100, continuous)
      - risk_class (1=Low, 2=Moderate, 3=High, 4=Extreme)
    """
    weights = weights or DEFAULT_WEIGHTS

    s2 = add_ndmi(add_ndvi(s2_image))
    terrain = get_terrain_layers(dem)

    ndvi_n = normalize(s2, "NDVI", region)
    # Dryness = inverse of moisture -> higher when NDMI is low
    ndmi_n = normalize(s2, "NDMI", region)
    dryness_n = ee.Image(1).subtract(ndmi_n).rename("NDMI_norm")
    slope_n = normalize(terrain, "slope", region)
    north_n = terrain.select("north_facing")  # already 0-1

    risk = (
        ndvi_n.multiply(weights["fuel_load"])
        .add(dryness_n.multiply(weights["dryness"]))
        .add(slope_n.multiply(weights["slope"]))
        .add(north_n.multiply(weights["north_facing"]))
        .multiply(100)
        .rename("risk_index")
    )

    risk_class = (
        risk.where(risk.lt(25), 1)
        .where(risk.gte(25).And(risk.lt(50)), 2)
        .where(risk.gte(50).And(risk.lt(75)), 3)
        .where(risk.gte(75), 4)
        .rename("risk_class")
    )

    return (
        s2.select(["NDVI", "NDMI"])
        .addBands(terrain.select(["slope", "north_facing"]))
        .addBands(risk)
        .addBands(risk_class)
    )
