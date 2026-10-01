import geopandas as gpd
from shapely.geometry import Point, box

from pilot.config import make_grid
from pilot.derive import roads, water_points
from pilot.sources import rasters


def test_tile_names():
    bb = (29.98, -2.02, 30.18, -1.89)
    dem = list(rasters.copernicus_dem(bb))
    assert any("S03_00_E029" in u for u in dem) and any("S02_00_E030" in u for u in dem) and len(dem) == 4
    assert any("S03E027" in u for u in rasters.worldcover(bb))
    assert sorted(u.rsplit("/", 1)[-1] for u in rasters.gsw_occurrence(bb)) == [
        "occurrence_20E_0Nv1_4_2021.tif", "occurrence_30E_0Nv1_4_2021.tif"]
    assert all(u.endswith(".tif") and len(u.rsplit("/", 1)[-1]) == 13 for u in rasters.meta_canopy(bb))


def test_grid_utm_and_alignment():
    g = make_grid((29.98, -2.02, 30.18, -1.89), 10)
    assert g.crs.to_epsg() == 32736 and g.transform.c % 10 == 0 and g.transform.f % 10 == 0


def test_crossroads_degree():
    # T-junction at c2 (A ends, B passes through), plain bend at c1 (two ends), footway-only star at c3
    segs = gpd.GeoDataFrame({
        "class": ["residential", "primary", "footway", "footway", "footway"],
        "connectors": [
            [{"connector_id": "c1", "at": 0.0}, {"connector_id": "c2", "at": 1.0}],
            [{"connector_id": "c0", "at": 0.0}, {"connector_id": "c2", "at": 0.5}, {"connector_id": "c9", "at": 1.0}],
            [{"connector_id": "c3", "at": 0.0}], [{"connector_id": "c3", "at": 1.0}], [{"connector_id": "c3", "at": 0.0}],
        ]}, geometry=[None] * 5)
    conns = gpd.GeoDataFrame({"id": ["c1", "c2", "c3"]}, geometry=[Point(0, 0), Point(1, 1), Point(2, 2)], crs=4326)
    out = roads.crossroads(segs, conns, box(-1, -1, 3, 3)).set_index("id")
    assert list(out.index) == ["c2", "c3"]
    assert out.loc["c2", "kind"] == "vehicle" and out.loc["c3", "kind"] == "pedestrian_only"


def test_water_point_dedupe_priority():
    pts = gpd.GeoDataFrame({"source": ["overture_water", "wpdx", "overture_infrastructure"],
                            "class": ["spring", "borehole", "drinking_water"]},
                           geometry=[Point(30.0, -1.95), Point(30.0001, -1.95), Point(30.01, -1.95)], crs=4326)
    out = water_points.dedupe(pts, "EPSG:32736", 30)
    assert len(out) == 2
    assert out.loc[out["source"] == "wpdx", "merged_from"].item() == "wpdx,overture_water"
