import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from affine import Affine
from pyproj import Transformer
from shapely.geometry import box

from pilot.config import make_grid
from pilot.derive.buildings import enrich
from pilot.sources import gba

TO3857 = Transformer.from_crs(4326, 3857, always_xy=True)
X0, Y0 = TO3857.transform(30.06, -1.95)
BBOX = (30.05, -1.96, 30.07, -1.94)


def _buildings():
    # a: 20x20 m, b: 20x20 m, c: 2x2 m (smaller than a 3 m pixel); coordinates built in 3857
    geoms_3857 = [box(X0, Y0, X0 + 20, Y0 + 20), box(X0 + 100, Y0, X0 + 120, Y0 + 20),
                  box(X0 + 203, Y0 + 1.7, X0 + 205, Y0 + 3.7)]  # contains no 3 m pixel centre
    g = gpd.GeoDataFrame({"id": ["a", "b", "c"]}, geometry=geoms_3857, crs=3857).to_crs(4326)
    return g


def test_match_lod1_forces_3857_and_picks_best_iou(tmp_path):
    lod1 = gpd.GeoDataFrame(
        {"height": [12.5, 30.0, 7.0], "var": [1.0, 4.0, 2.0]},
        geometry=[box(X0 + 1, Y0 + 1, X0 + 21, Y0 + 21),     # matches a (IoU ~0.82)
                  box(X0 + 115, Y0, X0 + 135, Y0 + 20),       # overlaps b weakly (IoU 0.14) -> rejected
                  box(X0 + 500, Y0, X0 + 520, Y0 + 20)],      # matches nothing
        crs=3857)
    lod1.set_crs(4326, allow_override=True).to_file(tmp_path / "tile.geojson")  # mislabelled, as in GBA
    out = gba.match_lod1(_buildings(), tmp_path, BBOX)
    assert out["height_gba_m"].tolist()[0] == 12.5 and out["height_gba_var"].tolist()[0] == 1.0
    assert out["height_gba_m"].isna().tolist()[1:] == [True, True]


def test_zonal_max_with_subpixel_fallback(tmp_path):
    res = 3.0
    w, h = 100, 20
    tr = Affine(res, 0, X0 - 3, 0, -res, Y0 + 30)
    arr = np.zeros((h, w), dtype="float32")
    arr[:, :] = 5.0
    r0, c0 = rasterio.transform.rowcol(tr, X0 + 10, Y0 + 10)
    arr[r0, c0] = 21.0                       # peak inside building a
    arr[:, 33:45] = -9999                    # building b area = nodata
    with rasterio.open(tmp_path / "h.tif", "w", driver="GTiff", width=w, height=h, count=1, dtype="float32",
                       crs="EPSG:3857", transform=tr, nodata=-9999) as dst:
        dst.write(arr, 1)
    out = gba.zonal_max(_buildings(), tmp_path, BBOX)
    assert out.iloc[0] == 21.0 and np.isnan(out.iloc[1])
    assert out.iloc[2] == 5.0  # sub-pixel footprint resolved by the all_touched pass


def test_height_priority_and_license():
    b = _buildings()
    b["sources"] = [[{"property": "", "dataset": "OpenStreetMap"}]] * 3
    b["height"] = [9.0, np.nan, np.nan]
    b["num_floors"] = [np.nan, 4.0, 2.0]
    b["subtype"] = b["class"] = None
    lod1 = pd.DataFrame({"height_gba_m": [15.0, 18.0, np.nan], "height_gba_var": [1.0, 2.0, np.nan]}, index=b.index)
    g = make_grid(BBOX, 10)
    z = np.zeros(g.shape, dtype="float32")
    out = enrich(b, g, z, z, 3.0, lod1, None)
    assert out["height_source"].tolist() == ["overture_height", "gba_lod1", "num_floors_x_3m"]
    assert out["height_m"].tolist() == [9.0, 18.0, 6.0]
    assert out["height_license"].notna().tolist() == [False, True, False]
    assert out["height_gba_m"].tolist()[:2] == [15.0, 18.0]
