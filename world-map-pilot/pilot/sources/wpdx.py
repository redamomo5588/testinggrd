"""Water Point Data Exchange (WPdx+) — optional, from a local CSV export."""
import logging
from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely.geometry import box

log = logging.getLogger(__name__)


def fetch(csv_path, bbox):
    if not csv_path or not Path(csv_path).exists():
        log.warning("WPdx skipped (no CSV configured/found)")
        return gpd.GeoDataFrame({"source": [], "class": []}, geometry=[], crs=4326)
    df = pd.read_csv(csv_path, low_memory=False)
    lon, lat = ("lon_deg", "lat_deg") if "lon_deg" in df else ("#lon_deg", "#lat_deg")
    gdf = gpd.GeoDataFrame(df, geometry=gpd.points_from_xy(df[lon], df[lat]), crs=4326)
    gdf = gdf[gdf.within(box(*bbox))]
    status = gdf.get("status_id", gdf.get("#status_id"))
    out = gpd.GeoDataFrame({
        "source": "wpdx",
        "class": gdf.get("water_source_clean", gdf.get("#water_source_clean", "water_point")).fillna("water_point"),
        "functional": status.map({"Yes": True, "No": False}) if status is not None else None,
    }, geometry=gdf.geometry.values, crs=4326)
    log.info("wpdx: %d points", len(out))
    return out
