"""Road change detection between two Overture releases with Hootenanny differential conflation, tiled.

python -m pilot.change_detect config/madrid.toml --ref 2026-08-19.0 --new 2026-09-23.1 --pg postgresql://...

Each tile is conflated with a buffer; a result way is kept only by the tile that owns its midpoint,
so tiles stitch without duplicates.
"""
import argparse
import json
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import geopandas as gpd
import pandas as pd
from shapely.geometry import box

from . import config as cfgmod
from . import hoot
from .derive import roads as rd
from .sources import overture

log = logging.getLogger("change_detect")


def tiles(bbox, n):
    x0, y0, x1, y1 = bbox
    dx, dy = (x1 - x0) / n, (y1 - y0) / n
    return [(i, j, (x0 + i * dx, y0 + j * dy, x0 + (i + 1) * dx, y0 + (j + 1) * dy)) for i in range(n) for j in range(n)]


def vehicle_roads(release, bbox):
    r = rd.roads(overture.fetch(release, "segments", bbox))
    return r[~r["class"].isin(rd.NON_VEHICLE) & r.intersects(box(*bbox))]


def run_tile(work, name, ref, new, timeout, reuse=False):
    out = {}
    for change, a, b in (("added", "ref", "new"), ("removed", "new", "ref")):
        res = f"{name}_{change}.osm"
        if reuse and (work / res).exists():
            out[change] = (work / res, 0.0)
            continue
        t = time.time()
        hoot.run(["conflate", "-C", "DifferentialConflation.conf", "-C", "NetworkAlgorithm.conf",
                  f"{name}_{a}.osm", f"{name}_{b}.osm", res], work, timeout)
        out[change] = (work / res, round(time.time() - t, 1))
    return name, out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("config")
    ap.add_argument("--ref", required=True, help="reference (older) Overture release")
    ap.add_argument("--new", required=True, help="newer Overture release")
    ap.add_argument("--grid", type=int, default=4, help="n x n tiles")
    ap.add_argument("--buffer-deg", type=float, default=0.002, help="tile overlap (~200 m)")
    ap.add_argument("--jobs", type=int, default=os.cpu_count())
    ap.add_argument("--tile-timeout", type=int, default=1800)
    ap.add_argument("--reuse", action="store_true", help="skip tiles whose Hootenanny outputs already exist")
    ap.add_argument("--out", default="out")
    ap.add_argument("--pg", default=os.environ.get("PG_DSN"))
    ap.add_argument("--schema", default="worldmap")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s", datefmt="%H:%M:%S")
    cfg = cfgmod.load(a.config, a.out)
    work = cfg.out_dir / "hoot_tiles"
    work.mkdir(parents=True, exist_ok=True)
    t0 = time.time()

    buf = a.buffer_deg
    full = (cfg.bbox[0] - buf, cfg.bbox[1] - buf, cfg.bbox[2] + buf, cfg.bbox[3] + buf)
    data = {"ref": vehicle_roads(a.ref, full), "new": vehicle_roads(a.new, full)}
    log.info("vehicle roads: ref %d, new %d", len(data["ref"]), len(data["new"]))

    grid = tiles(cfg.bbox, a.grid)
    for i, j, tb in grid if not a.reuse else []:
        tbuf = box(tb[0] - buf, tb[1] - buf, tb[2] + buf, tb[3] + buf)
        for k, g in data.items():
            sub = g[g.intersects(tbuf)].copy()
            sub["geometry"] = sub.geometry.intersection(tbuf)
            hoot.to_osm_xml(sub[~sub.geometry.is_empty], work / f"t{i}{j}_{k}.osm", hoot.road_tags)

    results, timings = {}, {}
    with ThreadPoolExecutor(a.jobs) as ex:
        futs = [ex.submit(run_tile, work, f"t{i}{j}", a.ref, a.new, a.tile_timeout, a.reuse) for i, j, _ in grid]
        for f in as_completed(futs):
            name, out = f.result()
            results[name] = out
            timings[name] = {c: s for c, (_, s) in out.items()}
            log.info("tile %s done: %s", name, timings[name])

    parts = {"added": [], "removed": []}
    for i, j, tb in grid:
        core = box(*tb)
        for change in parts:
            g = hoot.read_osm_ways(results[f"t{i}{j}"][change][0])
            if len(g):
                mid = g.geometry.interpolate(0.5, normalized=True)
                parts[change].append(g[mid.within(core)])
    added, removed = (gpd.GeoDataFrame(pd.concat(parts[c], ignore_index=True), crs=4326) if parts[c]
                      else gpd.GeoDataFrame(geometry=[], crs=4326) for c in ("added", "removed"))

    def km(g):
        return round(float(g.to_crs(cfg.grid.crs).length.sum()) / 1000, 2) if len(g) else 0.0

    summary = {"aoi": cfg.name, "ref_release": a.ref, "new_release": a.new, "tiles": len(grid),
               "ref_vehicle_roads": len(data["ref"]), "new_vehicle_roads": len(data["new"]),
               "added_ways": len(added), "added_km": km(added), "removed_ways": len(removed), "removed_km": km(removed),
               "added_by_highway": added["highway"].value_counts().to_dict() if len(added) else {},
               "removed_by_highway": removed["highway"].value_counts().to_dict() if len(removed) else {},
               "wall_time_s": round(time.time() - t0, 1), "tile_timings_s": timings}
    (cfg.out_dir / "road_changes.json").write_text(json.dumps(summary, indent=2))
    for name, g in (("added", added), ("removed", removed)):
        if len(g):
            g.to_file(cfg.out_dir / f"roads_{name}.geojson", driver="GeoJSON")
    if a.pg:
        hoot.load_changes(a.pg, a.schema, cfg.name, added, removed, a.ref, a.new)
    log.info("summary:\n%s", json.dumps({k: v for k, v in summary.items() if k != "tile_timings_s"}, indent=2))


if __name__ == "__main__":
    main()
