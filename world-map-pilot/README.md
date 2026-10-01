# World map pilot (one city)

Pilot of a global "everything" map: an Overture vector backbone fused with global rasters on one aligned grid.
Default area of interest (AOI): **Kigali** (`config/kigali.toml`). Any city works: copy the config and change `name` and `bbox`.

```bash
pip install -r requirements.txt
python -m pilot.run config/kigali.toml      # ~2–3 min, ~80 MB output in out/kigali/
python -m pytest -q tests                   # offline unit tests
```

## Pipeline
```
ingest     Overture (S3 GeoParquet, bbox row-group pushdown) + COG windowed reads (no full tile downloads)
normalize  every raster warped to one master grid: auto UTM zone, 10 m, snapped to 10 m
conflate   buildings: Overture (OSM > Google > Microsoft, already merged) + heights + terrain
           water points: OSM-derived + WPdx, greedy distance de-dupe with source priority
           water mask: WorldCover ∪ JRC GSW ∪ OSM polygons (with per-source agreement stats)
           forest: WorldCover tree ∧ canopy ≥ 5 m (with agreement stats)
derive     crossroads from connector topology (≥3 arms; vehicle / mixed / pedestrian_only)
           fused land cover (WorldCover + observed water + mapped buildings)
publish    out/<city>/raster/*.tif (COG), out/<city>/vector/*.parquet (GeoParquet), report.json, preview.png
```

## Sources
| Layer | Source | Res. | License |
|---|---|---|---|
| Buildings, roads, connectors, water, infrastructure, places | Overture Maps `2026-09-23.1` | vector | ODbL / CDLA |
| Terrain (DSM) | Copernicus GLO-30 | 30 m | Copernicus DEM license (commercial OK) |
| Canopy height | Meta/WRI CHM v1 (1 m → 10 m block max) | 1 m | CC-BY 4.0 |
| Land cover | ESA WorldCover 2021 v200 | 10 m | CC-BY 4.0 |
| Surface water | JRC GSW occurrence 1984–2021 | 30 m | Copernicus/JRC free |
| Water points (optional) | WPdx+ CSV (`[wpdx] csv`) | points | CC-BY 4.0 |

## Outputs
Rasters: `dem`, `canopy`, `landcover`, `gsw_occurrence`, `building`, `road`, `forest`, `water`, `landcover_fused`.
Vectors: `buildings` (source, height_m, height_source, area_m2, ground_elev_m, canopy_at_site_m), `roads`,
`crossroads` (degree, degree_vehicle, kind), `water_points` (source, class, merged_from), `water`, `infrastructure`, `places`.

## Kigali results (`docs/kigali_report.json`, `docs/kigali_preview.png`)
- 431,849 buildings: OSM 50%, Google 44%, Microsoft 6%
- 3,246 km of roads, 13,303 vehicle crossroads
- 100% raster coverage
- **Building height is the main gap**: 97% have no height (only 11k from floor counts, 24 measured)
- **Forest definitions disagree**: 9.7% of cells are tree in both sources, 14.0% WorldCover-only, 8.4% canopy-only
- **Water agrees poorly**: only 1.4% of water cells are confirmed by all three sources, 49% by just one
  (wetlands vs. open water, and JRC misses narrow rivers)
- Only 5 water points: OSM is sparse here, and WPdx is needed

## Known gaps / next steps
1. Building heights: join GlobalBuildingAtlas (LoD1) or Google Open Buildings 2.5D; a DSM−DTM estimate needs a bare-earth DTM.
2. WPdx and OSM Overpass were not reachable from the build environment. Pass a WPdx CSV via config.
3. Microsoft Road Detections to fill road gaps where Overture has none (buffer test).
4. Scale out: replace the in-memory steps with tiles on the same grid (e.g. 10 km UTM tiles) and run on Dask/Spark.
5. The Overture vector layers are ODbL share-alike, so a database combining them must stay ODbL.
