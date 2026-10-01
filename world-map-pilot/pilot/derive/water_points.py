"""Water points: merge OSM-derived (via Overture) and WPdx points, de-duplicated by distance."""
import geopandas as gpd
import pandas as pd

# Access/supply points only: excludes decorative fountains, swimming pools, weirs, etc.
WATER_POINT_CLASSES = {"drinking_water", "water_point", "water_tap", "water_well", "well", "spring", "hot_spring",
                       "watering_place", "water_tower", "reservoir_covered", "borehole", "standpipe"}
PRIORITY = {"wpdx": 0, "overture_infrastructure": 1, "overture_water": 2}


def collect(infra, water, wpdx):
    parts = []
    i = infra[infra["class"].isin(WATER_POINT_CLASSES) & (infra.geom_type == "Point")]
    parts.append(gpd.GeoDataFrame({"source": "overture_infrastructure", "class": i["class"].values},
                                  geometry=i.geometry.values, crs=4326))
    w = water[water["class"].isin(WATER_POINT_CLASSES) & (water.geom_type == "Point")]
    parts.append(gpd.GeoDataFrame({"source": "overture_water", "class": w["class"].values},
                                  geometry=w.geometry.values, crs=4326))
    if len(wpdx):
        parts.append(wpdx[["source", "class", "geometry"]])
    return gpd.GeoDataFrame(pd.concat(parts, ignore_index=True), crs=4326)


def dedupe(points, crs_m, dist_m):
    """Greedy: keep highest-priority point, drop lower-priority ones within dist_m (grid hash)."""
    if points.empty:
        return points.assign(merged_from=[])
    p = points.to_crs(crs_m)
    p["_prio"] = p["source"].map(PRIORITY).fillna(9)
    p = p.sort_values("_prio", kind="stable")
    cells, keep, merged = {}, [], {}
    for idx, x, y in zip(p.index, p.geometry.x, p.geometry.y):
        cx, cy = int(x // dist_m), int(y // dist_m)
        hit = None
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for k, kx, ky in cells.get((cx + dx, cy + dy), []):
                    if (kx - x) ** 2 + (ky - y) ** 2 <= dist_m ** 2:
                        hit = k
                        break
        if hit is None:
            keep.append(idx)
            cells.setdefault((cx, cy), []).append((idx, x, y))
            merged[idx] = [points.at[idx, "source"]]
        else:
            merged[hit].append(points.at[idx, "source"])
    out = points.loc[keep].copy()
    out["merged_from"] = [",".join(merged[i]) for i in keep]
    return out.reset_index(drop=True)
