"""Raster fusion rules: forest, water, fused land cover, rasterized vectors."""
import numpy as np
from rasterio.features import rasterize

# ESA WorldCover codes
TREE, SHRUB, GRASS, CROP, BUILT, BARE, SNOW, WATER, WETLAND, MANGROVE, MOSS = 10, 20, 30, 40, 50, 60, 70, 80, 90, 95, 100


def burn(gdf_utm, grid, all_touched=False):
    geoms = [g for g in gdf_utm.geometry if g is not None and not g.is_empty]
    if not geoms:
        return np.zeros(grid.shape, dtype="uint8")
    return rasterize(((g, 1) for g in geoms), out_shape=grid.shape, transform=grid.transform,
                     fill=0, all_touched=all_touched, dtype="uint8")


def forest(landcover, canopy, min_h):
    """Forest = WorldCover tree cover AND canopy >= min_h (FAO-like). Returns mask + agreement stats."""
    wc_tree = landcover == TREE
    tall = np.nan_to_num(canopy, nan=0) >= min_h
    valid = landcover > 0
    n = int(valid.sum()) or 1
    stats = {
        "both_tree_pct": round(100 * float((wc_tree & tall).sum()) / n, 2),
        "worldcover_only_pct": round(100 * float((wc_tree & ~tall).sum()) / n, 2),
        "canopy_only_pct": round(100 * float((~wc_tree & tall & valid).sum()) / n, 2),
    }
    return (wc_tree & tall).astype("uint8"), stats


def water(landcover, gsw, ov_water, min_occ):
    """Water = any of WorldCover water, JRC occurrence >= min_occ, Overture (OSM) water polygons."""
    a = landcover == WATER
    b = np.nan_to_num(gsw, nan=0) >= min_occ
    c = ov_water.astype(bool)
    union = a | b | c
    n = int(union.sum()) or 1
    stats = {
        "water_cells": int(union.sum()),
        "cells_by_source": {"worldcover": int(a.sum()), "jrc_gsw": int(b.sum()), "overture_osm": int(c.sum())},
        "all_three_agree_pct": round(100 * float((a & b & c).sum()) / n, 2),
        "single_source_pct": round(100 * float(((a.astype(int) + b + c) == 1).sum()) / n, 2),
    }
    return union.astype("uint8"), stats


def fused_landcover(landcover, water_mask, building_mask):
    """WorldCover base; observed water and mapped building footprints take precedence."""
    out = landcover.copy()
    out[water_mask == 1] = WATER
    out[building_mask == 1] = BUILT
    return out
