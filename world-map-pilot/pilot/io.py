import numpy as np
import rasterio


def write_cog(path, arr, grid, nodata=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    prof = dict(driver="COG", width=grid.width, height=grid.height, count=1, dtype=arr.dtype.name,
                crs=grid.crs, transform=grid.transform, compress="DEFLATE", nodata=nodata)
    if np.issubdtype(arr.dtype, np.floating):
        prof["predictor"] = 3
    with rasterio.open(path, "w", **prof) as dst:
        dst.write(arr, 1)


def write_vector(path, gdf):
    path.parent.mkdir(parents=True, exist_ok=True)
    for c in gdf.columns:  # nested Arrow structs (lists of dicts) -> keep GeoParquet simple
        if c != "geometry" and gdf[c].dtype == object and gdf[c].map(lambda v: isinstance(v, (list, dict, np.ndarray))).any():
            gdf = gdf.drop(columns=c)
    gdf.to_parquet(path, compression="zstd", write_covering_bbox=True)
