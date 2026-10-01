"""Pilot pipeline: python -m pilot.run config/kigali.toml"""
import argparse
import json
import logging
import os
import time

import numpy as np
from rasterio.enums import Resampling
from shapely.geometry import box

from . import config as cfgmod
from .derive import buildings as bld, roads as rd, surfaces as sf, water_points as wp
from .io import write_cog, write_vector
from .sources import overture, rasters, wpdx

log = logging.getLogger("pilot")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("config")
    ap.add_argument("--out", default="out")
    ap.add_argument("--pg", default=os.environ.get("PG_DSN"),
                    help="PostGIS DSN, e.g. postgresql://user:pw@host/db (default: $PG_DSN)")
    ap.add_argument("--schema", default="worldmap")
    ap.add_argument("--preview", action="store_true", help="also render out/<city>/preview.png")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s", datefmt="%H:%M:%S")

    cfg = cfgmod.load(a.config, a.out)
    g, bbox, rules, out = cfg.grid, cfg.bbox, cfg.rules, cfg.out_dir
    aoi = box(*bbox)
    buf = (bbox[0] - .01, bbox[1] - .01, bbox[2] + .01, bbox[3] + .01)  # complete topology at edges
    timings, t = {}, time.time()

    def lap(k):
        nonlocal t
        timings[k] = round(time.time() - t, 1)
        t = time.time()

    log.info("grid %s %dx%d @ %gm", g.crs.to_string(), g.width, g.height, cfg.resolution_m)

    # 1. ingest -------------------------------------------------------------
    rel = cfg.overture_release
    V = {k: overture.fetch(rel, k, bbox) for k in ("buildings", "infrastructure", "water", "places")}
    segs = overture.fetch(rel, "segments", buf)
    conns = overture.fetch(rel, "connectors", buf)
    wp_src = wpdx.fetch(cfg.wpdx_csv, bbox)
    lap("ingest_vectors")

    L = {
        "dem": rasters.read_to_grid(rasters.copernicus_dem(bbox), g, Resampling.bilinear),
        "canopy": rasters.read_to_grid(rasters.meta_canopy(bbox), g, Resampling.bilinear, reduce="max"),
        "landcover": rasters.read_to_grid(rasters.worldcover(bbox), g, Resampling.nearest, "uint8", 0),
        "gsw_occurrence": rasters.read_to_grid(rasters.gsw_occurrence(bbox), g, Resampling.bilinear),
    }
    lap("ingest_rasters")

    # 2. conflate / derive ----------------------------------------------------
    road = rd.roads(segs)
    V["crossroads"] = rd.crossroads(road, conns, aoi)
    V["roads"] = road[road.intersects(aoi)].reset_index(drop=True)
    V["buildings"] = bld.enrich(V["buildings"], g, L["dem"], L["canopy"], rules.get("floor_height_m", 3.0))
    pts = wp.collect(V["infrastructure"], V["water"], wp_src)
    V["water_points"] = wp.dedupe(pts, g.crs, rules.get("water_point_dedupe_m", 30.0))

    utm = {k: v.to_crs(g.crs) for k, v in V.items()}
    L["building"] = sf.burn(utm["buildings"], g)
    L["road"] = sf.burn(utm["roads"], g, all_touched=True)
    ov_water = sf.burn(utm["water"][utm["water"].geom_type.isin(["Polygon", "MultiPolygon"])], g)
    L["forest"], forest_stats = sf.forest(L["landcover"], L["canopy"], rules.get("forest_min_canopy_m", 5.0))
    L["water"], water_stats = sf.water(L["landcover"], L["gsw_occurrence"], ov_water,
                                       rules.get("water_min_occurrence_pct", 50))
    L["landcover_fused"] = sf.fused_landcover(L["landcover"], L["water"], L["building"])
    lap("conflate_derive")

    # 3. publish --------------------------------------------------------------
    for k, arr in L.items():
        write_cog(out / "raster" / f"{k}.tif", arr, g, np.nan if arr.dtype.kind == "f" else None)
    for k in ("buildings", "roads", "crossroads", "water_points", "water", "infrastructure", "places"):
        write_vector(out / "vector" / f"{k}.parquet", V[k])
    lap("publish")

    # 4. QA report ------------------------------------------------------------
    cov = {k: round(100 * float(np.isfinite(v).mean() if v.dtype.kind == "f" else (v > 0).mean()), 1)
           for k, v in L.items() if k in ("dem", "canopy", "landcover", "gsw_occurrence")}
    b = V["buildings"]
    report = {
        "aoi": {"name": cfg.name, "bbox": bbox, "grid_crs": g.crs.to_string(), "grid": [g.width, g.height],
                "resolution_m": cfg.resolution_m, "overture_release": rel},
        "counts": {k: int(len(V[k])) for k in ("buildings", "roads", "crossroads", "water_points", "places")},
        "crossroads_by_kind": {k: int(v) for k, v in V["crossroads"]["kind"].value_counts().items()},
        "road_km": round(float(utm["roads"].length.sum()) / 1000, 1),
        "buildings_by_source": bld.source_mix(b),
        "building_height_coverage": bld.height_coverage(b),
        "building_area_km2": round(float(b["area_m2"].sum()) / 1e6, 2),
        "water_points_by_source": {k: int(v) for k, v in V["water_points"]["source"].value_counts().items()},
        "raster_coverage_pct": cov,
        "forest_agreement": forest_stats,
        "forest_pct_of_aoi": round(100 * float(L["forest"].mean()), 2),
        "water_agreement": water_stats,
        "timings_s": timings,
    }
    (out / "report.json").write_text(json.dumps(report, indent=2))
    log.info("report:\n%s", json.dumps(report, indent=2))
    if a.pg:
        from .postgis import load
        load(a.pg, a.schema, cfg, V, L, report)
        lap("postgis_load")
        report["timings_s"] = timings
        log.info("postgis load done in %ss", timings["postgis_load"])
    if a.preview:
        from .preview import render
        render(out / "preview.png", g, L, {k: utm[k] for k in ("buildings", "roads", "crossroads", "water_points")})
        log.info("preview -> %s", out / "preview.png")


if __name__ == "__main__":
    main()
