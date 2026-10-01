"""Road network + crossroads derived from Overture connector topology."""
from collections import Counter

import geopandas as gpd

NON_VEHICLE = {"footway", "path", "steps", "cycleway", "pedestrian", "bridleway", "sidewalk", "crosswalk", "track"}


def roads(segments):
    r = segments[segments["subtype"] == "road"].copy()
    r["name"] = r["names"].map(lambda n: n.get("primary") if isinstance(n, dict) else None)
    return r.drop(columns=["names"])


def crossroads(road_segments, connectors, bbox_poly):
    """A connector is a crossroad when >=3 road arms meet there.

    Arms: a segment ending at the connector adds 1, a segment passing through it adds 2.
    `road_segments` must be fetched with a buffer around the AOI so edge degrees are complete.
    """
    deg_all, deg_veh = Counter(), Counter()
    for conns, cls in zip(road_segments["connectors"], road_segments["class"]):
        if conns is None:
            continue
        for c in conns:
            arms = 1 if c["at"] in (0.0, 1.0) else 2
            deg_all[c["connector_id"]] += arms
            if cls not in NON_VEHICLE:
                deg_veh[c["connector_id"]] += arms
    pts = connectors[connectors.within(bbox_poly)].copy()
    pts["degree"] = pts["id"].map(deg_all).fillna(0).astype(int)
    pts["degree_vehicle"] = pts["id"].map(deg_veh).fillna(0).astype(int)
    pts = pts[pts["degree"] >= 3]
    pts["kind"] = "pedestrian_only"
    pts.loc[pts["degree_vehicle"] >= 3, "kind"] = "vehicle"
    pts.loc[(pts["degree_vehicle"] < 3) & (pts["degree_vehicle"] >= 1), "kind"] = "mixed"
    return gpd.GeoDataFrame(pts.reset_index(drop=True), crs=connectors.crs)
