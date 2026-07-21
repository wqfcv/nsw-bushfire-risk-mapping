"""
clip_fire_severity_raster.py
------------------------------
Clip the statewide FESM 2019/20 fire-severity RASTER (ESRI Arc/Info Binary
Grid format - the folder full of .adf files you get from SEED) down to the
Blue Mountains AOI, and save a small, GitHub-friendly GeoTIFF.

Why raster, not shapefile: the "Data Download Package" from SEED for FESM
is an ESRI Grid raster (folder containing hdr.adf, w001001.adf, etc.),
not a shapefile. This is actually convenient for us - our risk index is
also a raster, so we can compare pixel-to-pixel instead of doing zonal
statistics over polygons.

Run this LOCALLY (not in Colab) right after unzipping the FESM package.

Usage
-----
    pip install rasterio

    python src/clip_fire_severity_raster.py \
        --input "D:/download/FireSeverityFESM/fesm_201920" \
        --output data/fesm_2019_20_blue_mountains.tif

Note: --input should point at the FOLDER that directly contains hdr.adf
(e.g. ".../FireSeverityFESM/fesm_201920"), not an individual .adf file -
that's how GDAL's Arc/Info Binary Grid (AIG) driver expects to open it.
"""

import argparse
import os

import numpy as np
import rasterio
from rasterio.mask import mask
from rasterio.warp import calculate_default_transform, reproject, Resampling
from shapely.geometry import box, mapping

# Must match the AOI defined in notebooks/01_bushfire_risk_mapping.ipynb
# (lon_min, lat_min, lon_max, lat_max) in WGS84 / EPSG:4326
BLUE_MOUNTAINS_BBOX = (150.10, -33.85, 150.45, -33.55)
DST_CRS = "EPSG:4326"


def clip_raster_to_aoi(input_path: str, output_path: str,
                        bbox=BLUE_MOUNTAINS_BBOX, dst_crs=DST_CRS):
    print(f"Opening {input_path} ...")
    with rasterio.open(input_path) as src:
        print(f"  source CRS: {src.crs}")
        print(f"  source size: {src.width} x {src.height}, {src.count} band(s)")
        print(f"  source nodata: {src.nodata}")

        # --- Step 1: reproject the whole-state raster's metadata to WGS84 ---
        # (we reproject on the fly during the windowed clip below, so we
        # don't need to materialise the full statewide raster in memory)
        transform, width, height = calculate_default_transform(
            src.crs, dst_crs, src.width, src.height, *src.bounds
        )
        reprojected_meta = src.meta.copy()
        reprojected_meta.update(
            {
                "driver": "GTiff",
                "crs": dst_crs,
                "transform": transform,
                "width": width,
                "height": height,
            }
        )

        # Reproject into an in-memory dataset first (statewide extent, but
        # this step is fast because raster data is 1-byte-per-pixel class codes)
        with rasterio.io.MemoryFile() as memfile:
            with memfile.open(**reprojected_meta) as reprojected:
                reproject(
                    source=rasterio.band(src, 1),
                    destination=rasterio.band(reprojected, 1),
                    src_transform=src.transform,
                    src_crs=src.crs,
                    dst_transform=transform,
                    dst_crs=dst_crs,
                    resampling=Resampling.nearest,  # nearest = don't blend class codes
                )

                # --- Step 2: clip to the Blue Mountains bbox ---
                aoi_geom = [mapping(box(*bbox))]
                clipped_data, clipped_transform = mask(
                    reprojected, aoi_geom, crop=True
                )

        clipped_meta = reprojected_meta.copy()
        clipped_meta.update(
            {
                "height": clipped_data.shape[1],
                "width": clipped_data.shape[2],
                "transform": clipped_transform,
                "compress": "lzw",
            }
        )

    unique_vals, counts = np.unique(clipped_data, return_counts=True)
    print("\nUnique pixel values in the clipped raster (class codes):")
    for v, c in zip(unique_vals, counts):
        print(f"  value={v}  count={c}")
    print(
        "\nCheck the FESMv3 metadata PDF (downloaded alongside the grid) to "
        "map these codes to severity labels (typically something like "
        "0=unburnt/no data, 1=low, 2=moderate, 3=high, 4=extreme - but "
        "confirm against the PDF rather than assuming)."
    )

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with rasterio.open(output_path, "w", **clipped_meta) as dst:
        dst.write(clipped_data)

    size_kb = os.path.getsize(output_path) / 1024
    print(f"\nSaved clipped raster to {output_path} ({size_kb:.0f} KB)")
    return output_path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input", required=True,
        help="Path to the FESM grid FOLDER (containing hdr.adf), e.g. "
             "'D:/download/FireSeverityFESM/fesm_201920'",
    )
    parser.add_argument(
        "--output",
        default="data/fesm_2019_20_blue_mountains.tif",
        help="Where to save the clipped GeoTIFF",
    )
    args = parser.parse_args()
    clip_raster_to_aoi(args.input, args.output)
