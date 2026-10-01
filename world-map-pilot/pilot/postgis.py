"""Load pilot outputs into PostGIS (vectors: geometry 4326, rasters: postgis_raster tiles in grid UTM)."""
import json
import logging
import struct

import numpy as np
import psycopg
from shapely import to_wkb

log = logging.getLogger(__name__)

SCHEMA_SQL = """
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS postgis_raster;
CREATE SCHEMA IF NOT EXISTS {s};
CREATE TABLE IF NOT EXISTS {s}.aoi (
  name text PRIMARY KEY, bbox geometry(Polygon,4326), grid_srid int, resolution_m real,
  overture_release text, report jsonb, loaded_at timestamptz DEFAULT now());
CREATE TABLE IF NOT EXISTS {s}.buildings (
  id text, aoi text, source text, subtype text, class text, num_floors real, height_m real, height_source text,
  area_m2 real, ground_elev_m real, canopy_at_site_m real, geom geometry(Geometry,4326), PRIMARY KEY (aoi, id));
ALTER TABLE {s}.buildings ADD COLUMN IF NOT EXISTS height_osm_m real, ADD COLUMN IF NOT EXISTS height_floors_m real,
  ADD COLUMN IF NOT EXISTS height_gba_m real, ADD COLUMN IF NOT EXISTS height_gba_var real,
  ADD COLUMN IF NOT EXISTS height_license text;
CREATE TABLE IF NOT EXISTS {s}.roads (
  id text, aoi text, subtype text, class text, name text, connectors jsonb,
  geom geometry(Geometry,4326), PRIMARY KEY (aoi, id));
CREATE TABLE IF NOT EXISTS {s}.crossroads (
  id text, aoi text, degree int, degree_vehicle int, kind text, geom geometry(Point,4326), PRIMARY KEY (aoi, id));
CREATE TABLE IF NOT EXISTS {s}.water_points (
  gid serial PRIMARY KEY, aoi text, source text, class text, merged_from text, geom geometry(Point,4326));
CREATE TABLE IF NOT EXISTS {s}.water_features (
  id text, aoi text, subtype text, class text, name text, is_intermittent boolean,
  geom geometry(Geometry,4326), PRIMARY KEY (aoi, id));
CREATE TABLE IF NOT EXISTS {s}.infrastructure (
  id text, aoi text, subtype text, class text, name text, geom geometry(Geometry,4326), PRIMARY KEY (aoi, id));
CREATE TABLE IF NOT EXISTS {s}.places (
  id text, aoi text, name text, basic_category text, confidence real,
  geom geometry(Point,4326), PRIMARY KEY (aoi, id));
CREATE TABLE IF NOT EXISTS {s}.raster_tiles (
  rid serial PRIMARY KEY, aoi text, layer text, rast raster);
"""

INDEX_SQL = """
CREATE INDEX IF NOT EXISTS buildings_geom_idx ON {s}.buildings USING gist (geom);
CREATE INDEX IF NOT EXISTS roads_geom_idx ON {s}.roads USING gist (geom);
CREATE INDEX IF NOT EXISTS crossroads_geom_idx ON {s}.crossroads USING gist (geom);
CREATE INDEX IF NOT EXISTS water_points_geom_idx ON {s}.water_points USING gist (geom);
CREATE INDEX IF NOT EXISTS water_features_geom_idx ON {s}.water_features USING gist (geom);
CREATE INDEX IF NOT EXISTS infrastructure_geom_idx ON {s}.infrastructure USING gist (geom);
CREATE INDEX IF NOT EXISTS places_geom_idx ON {s}.places USING gist (geom);
CREATE INDEX IF NOT EXISTS raster_tiles_hull_idx ON {s}.raster_tiles USING gist (ST_ConvexHull(rast));
CREATE INDEX IF NOT EXISTS raster_tiles_layer_idx ON {s}.raster_tiles (aoi, layer);
"""

TABLES = ("buildings", "roads", "crossroads", "water_points", "water_features", "infrastructure", "places", "raster_tiles")


def _primary_name(n):
    return n.get("primary") if isinstance(n, dict) else None


def _jsonable(v):
    if isinstance(v, np.ndarray):
        v = v.tolist()
    if isinstance(v, (list, tuple)):
        return [_jsonable(x) for x in v]
    if isinstance(v, dict):
        return {k: _jsonable(x) for k, x in v.items()}
    if isinstance(v, (np.floating, np.integer)):
        return v.item()
    return v


def _val(v):
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return None
    if isinstance(v, (np.floating, np.integer, np.bool_)):
        return v.item()
    return v


def _copy(cur, table, cols, rows):
    with cur.copy(f"COPY {table} ({', '.join(cols)}) FROM STDIN") as cp:
        for r in rows:
            cp.write_row(r)


def _rows(gdf, aoi, spec):
    """spec: list of (db_column, callable(row_dict) -> value); geometry appended as EWKB."""
    wkb = to_wkb(gdf.geometry.values, hex=True, include_srid=True) if len(gdf) else []
    recs = gdf.drop(columns="geometry").to_dict("records")
    for rec, g in zip(recs, wkb):
        yield [aoi] + [_val(f(rec)) for _, f in spec] + [g]


SPECS = {
    "buildings": [("id", lambda r: r["id"]), ("source", lambda r: r["source"]), ("subtype", lambda r: r.get("subtype")),
                  ("class", lambda r: r.get("class")), ("num_floors", lambda r: r.get("num_floors")),
                  ("height_m", lambda r: r["height_m"]), ("height_source", lambda r: r["height_source"]),
                  ("height_osm_m", lambda r: r["height_osm_m"]), ("height_floors_m", lambda r: r["height_floors_m"]),
                  ("height_gba_m", lambda r: r["height_gba_m"]), ("height_gba_var", lambda r: r["height_gba_var"]),
                  ("height_license", lambda r: r["height_license"]),
                  ("area_m2", lambda r: r["area_m2"]), ("ground_elev_m", lambda r: r["ground_elev_m"]),
                  ("canopy_at_site_m", lambda r: r["canopy_at_site_m"])],
    "roads": [("id", lambda r: r["id"]), ("subtype", lambda r: r["subtype"]), ("class", lambda r: r["class"]),
              ("name", lambda r: r.get("name")),
              ("connectors", lambda r: json.dumps(_jsonable(r["connectors"])) if r["connectors"] is not None else None)],
    "crossroads": [("id", lambda r: r["id"]), ("degree", lambda r: r["degree"]),
                   ("degree_vehicle", lambda r: r["degree_vehicle"]), ("kind", lambda r: r["kind"])],
    "water_points": [("source", lambda r: r["source"]), ("class", lambda r: r["class"]),
                     ("merged_from", lambda r: r["merged_from"])],
    "water_features": [("id", lambda r: r["id"]), ("subtype", lambda r: r["subtype"]), ("class", lambda r: r["class"]),
                       ("name", lambda r: _primary_name(r.get("names"))),
                       ("is_intermittent", lambda r: r.get("is_intermittent"))],
    "infrastructure": [("id", lambda r: r["id"]), ("subtype", lambda r: r["subtype"]), ("class", lambda r: r["class"]),
                       ("name", lambda r: _primary_name(r.get("names")))],
    "places": [("id", lambda r: r["id"]), ("name", lambda r: _primary_name(r.get("names"))),
               ("basic_category", lambda r: r.get("basic_category")), ("confidence", lambda r: r.get("confidence"))],
}
SOURCE_LAYER = {"water_features": "water"}

# PostGIS raster WKB pixel types
_PIXTYPE = {"uint8": (4, "B"), "float32": (10, "f")}


def raster_wkb(arr, x0, y0, res, srid, nodata):
    """Single-band PostGIS raster WKB (little endian)."""
    pt, fmt = _PIXTYPE[arr.dtype.name]
    h, w = arr.shape
    head = struct.pack("<BHHddddddiHH", 1, 0, 1, res, -res, x0, y0, 0.0, 0.0, srid, w, h)
    flags = pt | (64 if nodata is not None else 0)
    band = struct.pack("<B" + fmt, flags, nodata if nodata is not None else 0)
    return head + band + np.ascontiguousarray(arr).astype("<" + fmt).tobytes()


def load(dsn, schema, cfg, V, L, report, tile=256):
    s = schema
    g = cfg.grid
    srid = g.crs.to_epsg()
    with psycopg.connect(dsn) as con, con.cursor() as cur:
        cur.execute(SCHEMA_SQL.format(s=s))
        for t in TABLES:
            cur.execute(f"DELETE FROM {s}.{t} WHERE aoi = %s", (cfg.name,))
        for t, spec in SPECS.items():
            gdf = V[SOURCE_LAYER.get(t, t)]
            if t == "water_features":
                gdf = gdf.drop_duplicates("id")
            _copy(cur, f"{s}.{t}", ["aoi"] + [c for c, _ in spec] + ["geom"], _rows(gdf, cfg.name, spec))
            log.info("postgis %s.%s: %d rows", s, t, len(gdf))
        n = 0
        res = g.transform.a
        x0, y0 = g.transform.c, g.transform.f
        with cur.copy(f"COPY {s}.raster_tiles (aoi, layer, rast) FROM STDIN") as cp:
            for layer, arr in L.items():
                nod = float("nan") if arr.dtype.kind == "f" else None
                for r in range(0, g.height, tile):
                    for c in range(0, g.width, tile):
                        sub = arr[r:r + tile, c:c + tile]
                        wkb = raster_wkb(sub, x0 + c * res, y0 - r * res, res, srid, nod)
                        cp.write_row([cfg.name, layer, wkb.hex()])
                        n += 1
        log.info("postgis %s.raster_tiles: %d tiles (%d layers, %dx%d px, EPSG:%d)", s, n, len(L), tile, tile, srid)
        cur.execute(f"""INSERT INTO {s}.aoi (name, bbox, grid_srid, resolution_m, overture_release, report)
                        VALUES (%s, ST_MakeEnvelope(%s,%s,%s,%s,4326), %s, %s, %s, %s)
                        ON CONFLICT (name) DO UPDATE SET bbox=EXCLUDED.bbox, grid_srid=EXCLUDED.grid_srid,
                        resolution_m=EXCLUDED.resolution_m, overture_release=EXCLUDED.overture_release,
                        report=EXCLUDED.report, loaded_at=now()""",
                    (cfg.name, *cfg.bbox, srid, cfg.resolution_m, cfg.overture_release, json.dumps(report)))
        cur.execute(INDEX_SQL.format(s=s))
    with psycopg.connect(dsn, autocommit=True) as con:
        for t in TABLES + ("aoi",):
            con.execute(f"ANALYZE {s}.{t}")
