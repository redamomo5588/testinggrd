"""Buildings: Overture conflated footprints + height and terrain attributes."""
import numpy as np
import pandas as pd
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


DEFAULT_PRIORITY = ("overture_height", "gba_lod1", "gba_raster", "num_floors")


def enrich(b, grid, dem, canopy, floor_h=3.0, gba_lod1=None, gba_raster=None, priority=DEFAULT_PRIORITY):
    """Attach height candidates and pick height_m by `priority`; every candidate is kept in its own column."""
    from ..sources.gba import LICENSE as GBA_LICENSE
    b = b.copy()
    b["source"] = b["sources"].map(_primary_source)
    b = b.drop(columns=["sources"])
    cand = {
        "overture_height": b["height"].astype("float64"),
        "num_floors": b["num_floors"].astype("float64") * floor_h,
        "gba_lod1": gba_lod1["height_gba_m"] if gba_lod1 is not None else pd.Series(np.nan, index=b.index),
        "gba_raster": gba_raster if gba_raster is not None else pd.Series(np.nan, index=b.index),
    }
    b["height_osm_m"] = cand["overture_height"]
    b["height_floors_m"] = cand["num_floors"]
    b["height_gba_m"] = cand["gba_lod1"].fillna(cand["gba_raster"])
    b["height_gba_var"] = gba_lod1["height_gba_var"] if gba_lod1 is not None else np.nan
    b["height_m"] = np.nan
    b["height_source"] = None
    for k in priority:
        m = b["height_m"].isna() & cand[k].notna()
        b.loc[m, "height_m"] = cand[k][m]
        b.loc[m, "height_source"] = k if k != "num_floors" else "num_floors_x_%gm" % floor_h
    b["height_license"] = np.where(b["height_source"].isin(["gba_lod1", "gba_raster"]), GBA_LICENSE, None)
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
