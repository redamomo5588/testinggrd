"""Global raster sources, read as windowed COG requests and warped onto the master grid."""
import logging
import math

import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.errors import RasterioIOError
from rasterio.warp import reproject, transform_bounds
from rasterio.windows import from_bounds

log = logging.getLogger(__name__)

GDAL_ENV = dict(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR", CPL_VSIL_CURL_ALLOWED_EXTENSIONS=".tif",
                GDAL_HTTP_MAX_RETRY="3", GDAL_HTTP_RETRY_DELAY="2")


def _span(lo, hi, step):
    return range(math.floor(lo / step) * step, math.floor(hi / step) * step + 1, step) if step > 0 else []


def copernicus_dem(bbox):
    """Copernicus GLO-30 DSM, 1x1 deg tiles named by SW corner. Surface model (includes trees/buildings)."""
    for lat in _span(bbox[1], bbox[3], 1):
        for lon in _span(bbox[0], bbox[2], 1):
            n = f"Copernicus_DSM_COG_10_{'N' if lat >= 0 else 'S'}{abs(lat):02d}_00_{'E' if lon >= 0 else 'W'}{abs(lon):03d}_00_DEM"
            yield f"https://copernicus-dem-30m.s3.amazonaws.com/{n}/{n}.tif"


def worldcover(bbox):
    """ESA WorldCover 2021 v200, 10 m, 3x3 deg tiles named by SW corner."""
    for lat in _span(bbox[1], bbox[3], 3):
        for lon in _span(bbox[0], bbox[2], 3):
            t = f"{'N' if lat >= 0 else 'S'}{abs(lat):02d}{'E' if lon >= 0 else 'W'}{abs(lon):03d}"
            yield f"https://esa-worldcover.s3.eu-central-1.amazonaws.com/v200/2021/map/ESA_WorldCover_10m_2021_v200_{t}_Map.tif"


def gsw_occurrence(bbox):
    """JRC Global Surface Water occurrence 1984-2021 (%), 10x10 deg tiles named by NW corner."""
    for lat in range(math.ceil(bbox[1] / 10) * 10, math.ceil(bbox[3] / 10) * 10 + 1, 10):
        for lon in _span(bbox[0], bbox[2], 10):
            t = f"{abs(lon)}{'E' if lon >= 0 else 'W'}_{abs(lat)}{'N' if lat >= 0 else 'S'}"
            yield f"https://storage.googleapis.com/global-surface-water/downloads2021/occurrence/occurrence_{t}v1_4_2021.tif"


def _quadkey(x, y, z):
    return "".join(str(((x >> i) & 1) | (((y >> i) & 1) << 1)) for i in range(z - 1, -1, -1))


def _tile_xy(lon, lat, z):
    n = 2 ** z
    lat = max(min(lat, 85.0511), -85.0511)
    x = int((lon + 180) / 360 * n)
    y = int((1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n)
    return min(x, n - 1), min(y, n - 1)


def meta_canopy(bbox, z=9):
    """Meta/WRI global canopy height v1 (1 m, metres), zoom-9 quadkey tiles."""
    xa, ya = _tile_xy(bbox[0], bbox[3], z)
    xb, yb = _tile_xy(bbox[2], bbox[1], z)
    for x in range(xa, xb + 1):
        for y in range(ya, yb + 1):
            yield f"https://dataforgood-fb-data.s3.amazonaws.com/forests/v1/alsgedi_global_v6_float/chm/{_quadkey(x, y, z)}.tif"


def read_to_grid(urls, grid, resampling=Resampling.bilinear, dtype="float32", nodata=np.nan, reduce=None):
    """Mosaic the given COG tiles onto the grid, reading only the needed window (and overview level).

    reduce="max": read full resolution and take the block maximum to ~grid resolution first
    (keeps tree tops instead of averaging them with gaps).
    """
    dst = np.full(grid.shape, nodata, dtype=dtype)
    res = grid.transform.a
    with rasterio.Env(**GDAL_ENV):
        for url in urls:
            try:
                src = rasterio.open(url)
            except RasterioIOError:
                log.warning("missing tile %s", url)
                continue
            with src:
                l, b, r, t = transform_bounds(grid.crs, src.crs, *grid.bounds, densify_pts=21)
                sl, sb, sr, st = src.bounds
                l, b, r, t = max(l, sl), max(b, sb), min(r, sr), min(t, st)
                if l >= r or b >= t:
                    continue
                win = from_bounds(l, b, r, t, src.transform).round_offsets().round_lengths()
                # pad 2 source pixels so neighbouring tiles overlap (no seams), clamp to the tile
                c0, r0 = max(0, int(win.col_off) - 2), max(0, int(win.row_off) - 2)
                c1 = min(src.width, int(win.col_off + win.width) + 2)
                r1 = min(src.height, int(win.row_off + win.height) + 2)
                win = rasterio.windows.Window(c0, r0, c1 - c0, r1 - r0)
                # true ground resolution of the source
                _, la0, _, la1 = transform_bounds(grid.crs, "EPSG:4326", *grid.bounds)
                lat = (la0 + la1) / 2
                if src.crs.is_geographic:
                    src_res_m = abs(src.transform.a) * 111_320
                elif src.crs.to_epsg() == 3857:
                    src_res_m = abs(src.transform.a) * math.cos(math.radians(lat))
                else:
                    src_res_m = abs(src.transform.a)
                if reduce == "max" and res / src_res_m >= 2:
                    k = int(res / src_res_m)
                    full = src.read(1, window=win)
                    h, w = full.shape[0] // k * k, full.shape[1] // k * k
                    arr = full[:h, :w].reshape(h // k, k, w // k, k).max(axis=(1, 3))
                    shape = arr.shape
                    wtr = src.window_transform(win) * rasterio.Affine.scale(k, k)
                else:
                    # downsample on read when the source is much finer than the grid (uses COG overviews)
                    f = max(1.0, (res / 2) / src_res_m)
                    shape = (max(1, int(win.height / f)), max(1, int(win.width / f)))
                    categorical = resampling in (Resampling.nearest, Resampling.mode)
                    on_read = Resampling.nearest if f == 1 else (Resampling.mode if categorical else Resampling.average)
                    arr = src.read(1, window=win, out_shape=shape, resampling=on_read)
                    wtr = src.window_transform(win) * rasterio.Affine.scale(win.width / shape[1], win.height / shape[0])
                tmp = np.full(grid.shape, nodata, dtype=dtype)
                reproject(arr, tmp, src_transform=wtr, src_crs=src.crs, src_nodata=src.nodata,
                          dst_transform=grid.transform, dst_crs=grid.crs, dst_nodata=nodata, resampling=resampling)
                empty = np.isnan(dst) if np.issubdtype(dst.dtype, np.floating) else dst == nodata
                dst[empty] = tmp[empty]
            log.info("read %s", url.rsplit("/", 1)[-1])
    return dst
