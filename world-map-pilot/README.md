# World map pilot (one city)

Pilot of a global "everything" map: an Overture vector backbone fused with global rasters on one aligned grid.
Default area of interest (AOI): **Kigali** (`config/kigali.toml`). Any city works: copy the config and change `name` and `bbox`.

```bash
pip install -r requirements.txt
docker compose up -d                                   # PostGIS 16 / 3.4 (or use any PostGIS ≥3 server)
python -m pilot.run config/kigali.toml --pg postgresql://worldmap:worldmap@localhost/worldmap
python -m pytest -q tests                              # offline unit tests
```
`--pg` (or `$PG_DSN`) loads everything into schema `worldmap` (`--schema` to change). Re-running a city replaces only that
city's rows, so many cities can share one database. Without `--pg`, only files are written. `--preview` renders a PNG.

Restore the prebuilt Kigali database (`worldmap_kigali.dump`, 75 MB):
```bash
createdb worldmap && psql -d worldmap -c "CREATE EXTENSION postgis; CREATE EXTENSION postgis_raster;"
pg_restore -d worldmap --no-owner worldmap_kigali.dump
```

## PostGIS schema (`worldmap`)
| Table | Rows (Kigali) | Key columns |
|---|---|---|
| `aoi` | 1 | name, bbox, grid_srid, resolution_m, overture_release, report (jsonb QA) |
| `buildings` | 431,849 | id (GERS), source, height_m, height_source, height_osm_m, height_floors_m, height_gba_m, height_gba_var, height_license, area_m2, ground_elev_m, canopy_at_site_m, geom |
| `roads` | 23,301 | id, class, name, connectors (jsonb topology), geom |
| `crossroads` | 16,779 | id, degree, degree_vehicle, kind, geom |
| `water_points` | 5 | source, class, merged_from, geom |
| `water_features` | 513 | id, subtype, class, name, is_intermittent, geom |
| `infrastructure` | 3,087 | id, subtype, class, name, geom |
| `places` | 2,883 | id, name, basic_category, confidence, geom |
| `raster_tiles` | 486 | aoi, layer, rast (256×256 tiles, grid UTM SRID) |

Vectors: EPSG:4326 + GiST. Raster layers: `dem`, `canopy`, `landcover`, `landcover_fused`, `gsw_occurrence`, `forest`,
`water`, `building`, `road`.

```sql
-- value of any raster layer under each building
SELECT b.id, ST_Value(r.rast, ST_Transform(ST_PointOnSurface(b.geom), a.grid_srid)) AS canopy_m
FROM worldmap.buildings b JOIN worldmap.aoi a ON a.name = b.aoi
JOIN worldmap.raster_tiles r ON r.aoi = b.aoi AND r.layer = 'canopy'
 AND ST_Intersects(r.rast, ST_Transform(ST_PointOnSurface(b.geom), a.grid_srid)) LIMIT 10;

-- forest area (km²) per AOI
SELECT aoi, sum((ST_SummaryStats(rast)).sum) * 100 / 1e6 AS forest_km2
FROM worldmap.raster_tiles WHERE layer = 'forest' GROUP BY aoi;

-- 4-way+ vehicle crossroads with no water point within 500 m
SELECT c.id FROM worldmap.crossroads c WHERE c.degree_vehicle >= 4 AND NOT EXISTS (
  SELECT 1 FROM worldmap.water_points w WHERE ST_DWithin(c.geom::geography, w.geom::geography, 500));
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
publish    PostGIS schema `worldmap` + out/<city>/raster/*.tif (COG), out/<city>/vector/*.parquet, report.json
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
| Building heights (optional) | GlobalBuildingAtlas LoD1 polygons / GBA.Height 3 m rasters (`[gba]`) | 3 m | **CC BY-NC 4.0** |

## Building heights (GlobalBuildingAtlas)
1. Download the tiles covering the area of interest (GBA README, "How to Use the Data"):
   - LoD1: HuggingFace `zhu-xlab/GBA.ODbLPolygon` + `zhu-xlab/GBA.LoD1`, find tiles with `representative/lod1.geojson`,
     then run `produce_lod1.py`. Point `[gba] lod1_dir` at the output folder.
   - and/or height maps: `GBA.Height` from mediaTUM (https://mediatum.ub.tum.de/1782307), tiles listed in
     `height_tif.geojson`. Point `[gba] height_dir` at the GeoTIFF folder.
2. Re-run the pipeline. The loader matches GBA polygons to Overture buildings by best footprint overlap
   (IoU ≥ `min_iou`, CRS forced to EPSG:3857) and/or takes the max height-map pixel inside each footprint
   (GBA's own LoD1 rule, with an all_touched pass for footprints smaller than a pixel).
3. `height_m` takes the first available value in `[rules] height_priority`
   (default: OSM measured height → GBA LoD1 → GBA raster → floors × 3 m). Every candidate stays in its own column.
   Rows whose height comes from GBA get `height_license = 'CC BY-NC 4.0 (GlobalBuildingAtlas)'`, which means
   **no commercial use** of those values.

## Outputs
Rasters: `dem`, `canopy`, `landcover`, `gsw_occurrence`, `building`, `road`, `forest`, `water`, `landcover_fused`.
Vectors: `buildings` (source, height_m, height_source, area_m2, ground_elev_m, canopy_at_site_m), `roads`,
`crossroads` (degree, degree_vehicle, kind), `water_points` (source, class, merged_from), `water`, `infrastructure`, `places`.

## Kigali results (`docs/kigali_report.json`)
- 431,849 buildings: OSM 50%, Google 44%, Microsoft 6%
- 3,246 km of roads, 13,303 vehicle crossroads
- 100% raster coverage
- **Building height is the main gap**: 97% have no height (only 11k from floor counts, 24 measured)
- **Forest definitions disagree**: 9.7% of cells are tree in both sources, 14.0% WorldCover-only, 8.4% canopy-only
- **Water agrees poorly**: only 1.4% of water cells are confirmed by all three sources, 49% by just one
  (wetlands vs. open water, and JRC misses narrow rivers)
- Only 5 water points: OSM is sparse here, and WPdx is needed

## Known gaps / next steps
1. Building heights: the GBA loader is implemented and unit-tested, but GBA hosts (huggingface.co, mediatum.ub.tum.de)
   were blocked from the build environment, so the shipped Kigali dump has no GBA heights yet.
2. WPdx and OSM Overpass were not reachable from the build environment. Pass a WPdx CSV via config.
3. Microsoft Road Detections to fill road gaps where Overture has none (buffer test).
4. Scale out: replace the in-memory steps with tiles on the same grid (e.g. 10 km UTM tiles) and run on Dask/Spark.
5. The Overture vector layers are ODbL share-alike, so a database combining them must stay ODbL.
