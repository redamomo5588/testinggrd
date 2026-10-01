"""Buildings: Overture conflated footprints + height and terrain attributes."""
import numpy as np
from rasterio.transform import rowcol


def _primary_source(src):
    if src is None or len(src) == 0:
        return "unknown"
    for s in src:
        if not s.get("property"):
            return s.get("dataset") or "unknown"
    return src[0].get("dataset") or "unknown"


def sample(grid, arr, gdf_utm):
    """Value of a grid array at each feature's representative point (NaN outside)."""
    p = gdf_utm.geometry.representative_point()
    r, c = rowcol(grid.transform, p.x.values, p.y.values)
    r, c = np.asarray(r), np.asarray(c)
    ok = (r >= 0) & (r < grid.height) & (c >= 0) & (c < grid.width)
    out = np.full(len(p), np.nan, dtype="float32")
    out[ok] = arr[r[ok], c[ok]]
    return out


def enrich(b, grid, dem, canopy, floor_h=3.0):
    b = b.copy()
    b["source"] = b["sources"].map(_primary_source)
    b = b.drop(columns=["sources"])
    b["height_m"] = b["height"].astype("float64")
    b["height_source"] = np.where(b["height_m"].notna(), "overture_height", None)
    est = b["height_m"].isna() & b["num_floors"].notna()
    b.loc[est, "height_m"] = b.loc[est, "num_floors"] * floor_h
    b.loc[est, "height_source"] = "num_floors_x_%gm" % floor_h
    utm = b.to_crs(grid.crs)
    b["area_m2"] = utm.area.round(1)
    b["ground_elev_m"] = sample(grid, dem, utm)       # Copernicus DSM at 30 m: approximate
    b["canopy_at_site_m"] = sample(grid, canopy, utm)  # trees over/around the footprint
    return b.drop(columns=["height"])


def source_mix(b):
    return {k: int(v) for k, v in b["source"].value_counts().items()}


def height_coverage(b):
    return {k: int(v) for k, v in b["height_source"].fillna("none").value_counts().items()}


__all__ = ["enrich", "sample", "source_mix", "height_coverage"]
