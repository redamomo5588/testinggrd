import math
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from affine import Affine
from pyproj import CRS, Transformer


@dataclass
class Grid:
    """Master raster grid every raster layer is aligned to."""
    crs: CRS
    transform: Affine
    width: int
    height: int

    @property
    def shape(self):
        return (self.height, self.width)

    @property
    def bounds(self):
        x0, y1 = self.transform.c, self.transform.f
        res = self.transform.a
        return (x0, y1 - self.height * res, x0 + self.width * res, y1)


@dataclass
class Config:
    name: str
    bbox: tuple
    resolution_m: float
    overture_release: str
    rules: dict
    wpdx_csv: str
    gba: dict
    out_dir: Path
    grid: Grid = field(init=False)

    def __post_init__(self):
        self.grid = make_grid(self.bbox, self.resolution_m)


def utm_crs(lon, lat):
    zone = int((lon + 180) // 6) + 1
    return CRS.from_epsg((32600 if lat >= 0 else 32700) + zone)


def make_grid(bbox, res):
    lon0, lat0, lon1, lat1 = bbox
    crs = utm_crs((lon0 + lon1) / 2, (lat0 + lat1) / 2)
    tr = Transformer.from_crs(4326, crs, always_xy=True)
    xs, ys = tr.transform([lon0, lon1, lon0, lon1], [lat0, lat0, lat1, lat1])
    x0 = math.floor(min(xs) / res) * res
    y0 = math.floor(min(ys) / res) * res
    x1 = math.ceil(max(xs) / res) * res
    y1 = math.ceil(max(ys) / res) * res
    return Grid(crs, Affine(res, 0, x0, 0, -res, y1), int((x1 - x0) / res), int((y1 - y0) / res))


def load(path, out_root="out"):
    c = tomllib.loads(Path(path).read_text())
    return Config(
        name=c["name"],
        bbox=tuple(c["bbox"]),
        resolution_m=float(c.get("resolution_m", 10)),
        overture_release=c["overture"]["release"],
        rules=c.get("rules", {}),
        wpdx_csv=c.get("wpdx", {}).get("csv", ""),
        gba=c.get("gba", {}),
        out_dir=Path(out_root) / c["name"],
    )
