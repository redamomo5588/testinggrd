"""Hootenanny conflation helpers: export GeoDataFrames to OSM XML and run `hoot` in Docker.

The `hoot:local` image is built by docker/hootenanny/Dockerfile (Hootenanny 0.2.87, CentOS 7).
"""
import logging
import subprocess
from pathlib import Path
from xml.sax.saxutils import quoteattr

from shapely.geometry import LineString, MultiLineString, MultiPolygon, Polygon

log = logging.getLogger(__name__)
IMAGE = "hoot:local"

# Overture road class -> OSM tags
ROAD_TAGS = {"sidewalk": {"highway": "footway", "footway": "sidewalk"},
             "crosswalk": {"highway": "footway", "footway": "crossing"},
             "unknown": {"highway": "road"}}


def _lines(geom):
    if isinstance(geom, LineString):
        return [geom]
    if isinstance(geom, MultiLineString):
        return list(geom.geoms)
    return []


def _rings(geom):
    if isinstance(geom, Polygon):
        return [geom.exterior]
    if isinstance(geom, MultiPolygon):
        return [p.exterior for p in geom.geoms]
    return []


def to_osm_xml(gdf, path, tags_fn, kind="line"):
    """Write features as OSM ways; identical coordinates share one node so topology survives."""
    nodes, ways = {}, []
    nid = wid = 0
    for rec, geom in zip(gdf.drop(columns="geometry").to_dict("records"), gdf.geometry):
        parts = _lines(geom) if kind == "line" else _rings(geom)
        for part in parts:
            refs = []
            for x, y in part.coords:
                k = (round(x, 7), round(y, 7))
                if k not in nodes:
                    nid -= 1
                    nodes[k] = nid
                if not refs or refs[-1] != nodes[k]:
                    refs.append(nodes[k])
            if len(refs) >= 2:
                wid -= 1
                ways.append((wid, refs, tags_fn(rec)))
    with open(path, "w") as f:
        f.write("<?xml version='1.0' encoding='UTF-8'?>\n<osm version='0.6' generator='world-map-pilot'>\n")
        for (x, y), i in nodes.items():
            f.write(f"<node id='{i}' version='1' lat='{y}' lon='{x}'/>\n")
        for i, refs, tags in ways:
            f.write(f"<way id='{i}' version='1'>")
            f.write("".join(f"<nd ref='{r}'/>" for r in refs))
            f.write("".join(f"<tag k={quoteattr(k)} v={quoteattr(str(v))}/>" for k, v in tags.items() if v is not None))
            f.write("</way>\n")
        f.write("</osm>\n")
    log.info("wrote %s: %d nodes, %d ways", path, len(nodes), len(ways))
    return len(ways)


def road_tags(rec):
    t = dict(ROAD_TAGS.get(rec["class"], {"highway": rec["class"]}))
    t["name"] = rec.get("name")
    t["overture:id"] = rec["id"]
    return t


def run(args, workdir, timeout=7200):
    """Run `hoot <args>` with workdir mounted at /data."""
    cmd = ["docker", "run", "--rm", "-v", f"{Path(workdir).resolve()}:/data", "-w", "/data", IMAGE, "hoot", *args]
    log.info("hoot %s", " ".join(args))
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if p.returncode:
        raise RuntimeError(f"hoot failed ({p.returncode}):\n{p.stderr[-3000:]}")
    return p.stdout


def read_osm_ways(path):
    """Parse an OSM XML file (e.g. Hootenanny output) into a GeoDataFrame of ways with their tags."""
    import xml.etree.ElementTree as ET

    import geopandas as gpd

    nodes, rows = {}, []
    for _, el in ET.iterparse(path, events=("end",)):
        if el.tag == "node":
            nodes[el.get("id")] = (float(el.get("lon")), float(el.get("lat")))
            el.clear()
        elif el.tag == "way":
            coords = [nodes[n.get("ref")] for n in el.iter("nd") if n.get("ref") in nodes]
            if len(coords) >= 2:
                tags = {t.get("k"): t.get("v") for t in el.iter("tag")}
                rows.append({"osm_id": el.get("id"), **tags, "geometry": LineString(coords)})
            el.clear()
    return gpd.GeoDataFrame(rows, geometry="geometry", crs=4326) if rows else gpd.GeoDataFrame(
        {"osm_id": []}, geometry=[], crs=4326)


def load_changes(dsn, schema, aoi, added, removed, ref_release, new_release):
    """Store Hootenanny differential results in <schema>.road_changes."""
    import psycopg
    from shapely import to_wkb

    with psycopg.connect(dsn) as con, con.cursor() as cur:
        cur.execute(f"""CREATE TABLE IF NOT EXISTS {schema}.road_changes (
            gid serial PRIMARY KEY, aoi text, change text, ref_release text, new_release text,
            overture_id text, highway text, name text, geom geometry(LineString,4326))""")
        cur.execute(f"DELETE FROM {schema}.road_changes WHERE aoi = %s AND ref_release = %s AND new_release = %s",
                    (aoi, ref_release, new_release))
        with cur.copy(f"COPY {schema}.road_changes (aoi, change, ref_release, new_release, overture_id, highway,"
                      f" name, geom) FROM STDIN") as cp:
            for change, g in (("added", added), ("removed", removed)):
                for rec, wkb in zip(g.drop(columns="geometry").to_dict("records"),
                                    to_wkb(g.geometry.values, hex=True, include_srid=True) if len(g) else []):
                    cp.write_row([aoi, change, ref_release, new_release, rec.get("overture:id"), rec.get("highway"),
                                  rec.get("name"), wkb])
        cur.execute(f"CREATE INDEX IF NOT EXISTS road_changes_geom_idx ON {schema}.road_changes USING gist (geom)")
