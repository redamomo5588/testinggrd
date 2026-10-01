"""GlobalBuildingAtlas (Zhu et al. 2025, ESSD 17:6647) building heights.

Two optional inputs, both read from local folders (download from HuggingFace zhu-xlab/GBA.LoD1 / mediaTUM 1782307):
  * lod1_dir   : LoD1 polygons (GeoJSON/GeoParquet/GPKG output of produce_lod1.py), props `height`, `var`.
                 GBA polygons are EPSG:3857 even when a file claims 4326 (see GBA README), so the CRS is forced.
  * height_dir : GBA.Height GeoTIFF height maps (3 m). Height per footprint = max pixel inside it,
                 the same rule GBA uses to build its LoD1 models.
License: GBA.LoD1 / GBA.Height are CC BY-NC 4.0 (non-commercial). Rows using them are flagged.
"""
import logging
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
import shapely
from rasterio.features import rasterize
from rasterio.warp import transform_bounds
from rasterio.windows import from_bounds

log = logging.getLogger(__name__)
LICENSE = "CC BY-NC 4.0 (GlobalBuildingAtlas)"
VECTOR_EXT = (".geojson", ".json", ".parquet", ".gpkg", ".fgb")


def _files(d, exts):
    if not d or not Path(d).is_dir():
        return []
    return sorted(p for p in Path(d).rglob("*") if p.suffix.lower() in exts)


def match_lod1(buildings, lod1_dir, bbox, crs="EPSG:3857", min_iou=0.3):
    """Transfer GBA LoD1 height/var to buildings by best footprint overlap (IoU >= min_iou)."""
    out = pd.DataFrame({"height_gba_m": np.nan, "height_gba_var": np.nan}, index=buildings.index)
    files = _files(lod1_dir, VECTOR_EXT)
    if not files:
        log.warning("GBA LoD1 skipped (no files in %r)", lod1_dir)
        return out
    bb = transform_bounds("EPSG:4326", crs, *bbox)
    parts = []
    for f in files:
        g = gpd.read_parquet(f, bbox=bb) if f.suffix == ".parquet" else gpd.read_file(f, bbox=bb)
        if len(g):
            parts.append(g.set_crs(crs, allow_override=True)[["height", "var", "geometry"]])
    if not parts:
        return out
    gba = gpd.GeoDataFrame(pd.concat(parts, ignore_index=True), crs=crs)
    gba = gba[gba["height"].notna() & (gba["height"] > 0)].reset_index(drop=True)
    b = buildings[["geometry"]].to_crs(crs)
    bi, gi = gba.sindex.query(b.geometry.values, predicate="intersects")
    if not len(bi):
        return out
    ga, gb = b.geometry.values[bi], gba.geometry.values[gi]
    inter = shapely.area(shapely.intersection(ga, gb))
    iou = inter / (shapely.area(ga) + shapely.area(gb) - inter)
    pairs = pd.DataFrame({"b": bi, "g": gi, "iou": iou})
    best = pairs[pairs["iou"] >= min_iou].sort_values("iou").drop_duplicates("b", keep="last")
    idx = buildings.index[best["b"].values]
    out.loc[idx, "height_gba_m"] = gba["height"].values[best["g"].values]
    out.loc[idx, "height_gba_var"] = gba["var"].values[best["g"].values]
    log.info("GBA LoD1: %d polygons in AOI, %d buildings matched (IoU>=%.1f)", len(gba), len(best), min_iou)
    return out


def zonal_max(buildings, height_dir, bbox):
    """Max GBA.Height pixel inside each footprint (all_touched fallback for footprints smaller than a pixel)."""
    out = pd.Series(np.nan, index=buildings.index, name="height_gba_m")
    files = _files(height_dir, (".tif", ".tiff"))
    if not files:
        log.warning("GBA height rasters skipped (no files in %r)", height_dir)
        return out
    vals = np.full(len(buildings), np.nan)
    for f in files:
        with rasterio.open(f) as src:
            l, b_, r, t = transform_bounds("EPSG:4326", src.crs, *bbox)
            sl, sb, sr, st = src.bounds
            l, b_, r, t = max(l, sl), max(b_, sb), min(r, sr), min(t, st)
            if l >= r or b_ >= t:
                continue
            win = from_bounds(l, b_, r, t, src.transform).round_offsets().round_lengths()
            arr = src.read(1, window=win, masked=True).astype("float32").filled(np.nan)
            arr[arr <= 0] = np.nan
            tr = src.window_transform(win)
            geoms = buildings.geometry.to_crs(src.crs).values
        tile = np.full(len(buildings), np.nan)
        for all_touched in (False, True):  # 2nd pass only for footprints that hit no pixel centre
            todo = np.flatnonzero(np.isnan(tile))
            if not len(todo):
                break
            ids = rasterize(((geoms[i], i + 1) for i in todo), out_shape=arr.shape, transform=tr,
                            fill=0, all_touched=all_touched, dtype="int32")
            m = (ids > 0) & np.isfinite(arr)
            acc = np.full(len(buildings) + 1, np.nan)
            np.fmax.at(acc, ids[m], arr[m])
            tile = np.fmax(tile, acc[1:])
        vals = np.fmax(vals, tile)  # footprints split across tiles keep the overall max
        log.info("GBA height raster %s read", f.name)
    out[:] = vals
    log.info("GBA height rasters: %d buildings with height", int(np.isfinite(vals).sum()))
    return out
