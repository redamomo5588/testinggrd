"""Overture Maps (vector backbone: OSM + Microsoft + Google + Meta, already conflated, stable GERS ids)."""
import logging
import os

import geopandas as gpd
import pyarrow.dataset as ds
import pyarrow.fs as pafs
from shapely.geometry import box

log = logging.getLogger(__name__)
BUCKET = "overturemaps-us-west-2/release"

THEMES = {
    "buildings": ("buildings", "building", ["id", "sources", "height", "num_floors", "subtype", "class", "geometry"]),
    "segments": ("transportation", "segment", ["id", "subtype", "class", "connectors", "names", "geometry"]),
    "connectors": ("transportation", "connector", ["id", "geometry"]),
    "infrastructure": ("base", "infrastructure", ["id", "subtype", "class", "names", "sources", "geometry"]),
    "water": ("base", "water", ["id", "subtype", "class", "names", "is_intermittent", "sources", "geometry"]),
    "land_cover": ("base", "land_cover", ["id", "subtype", "geometry"]),
    "places": ("places", "place", ["id", "names", "basic_category", "confidence", "geometry"]),
}


def _fs():
    proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
    kw = {"proxy_options": proxy} if proxy else {}
    return pafs.S3FileSystem(anonymous=True, region="us-west-2", **kw)


def fetch(release, layer, bbox):
    """Return a GeoDataFrame (EPSG:4326) of one Overture layer clipped to bbox."""
    theme, typ, cols = THEMES[layer]
    dset = ds.dataset(f"{BUCKET}/{release}/theme={theme}/type={typ}/", filesystem=_fs(), format="parquet")
    x0, y0, x1, y1 = bbox
    flt = (ds.field("bbox", "xmin") < x1) & (ds.field("bbox", "xmax") > x0) & \
          (ds.field("bbox", "ymin") < y1) & (ds.field("bbox", "ymax") > y0)
    tbl = dset.to_table(filter=flt, columns=[c for c in cols if c in dset.schema.names])
    df = tbl.to_pandas()
    gdf = gpd.GeoDataFrame(df.drop(columns="geometry"), geometry=gpd.GeoSeries.from_wkb(df["geometry"]), crs=4326)
    gdf = gdf[gdf.intersects(box(*bbox))].reset_index(drop=True)
    log.info("overture %s: %d features", layer, len(gdf))
    return gdf
