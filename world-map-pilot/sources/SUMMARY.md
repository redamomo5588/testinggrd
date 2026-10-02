# Source assessment: 821 sources, 8 data types

Files: `catalog/*.psv` (raw list) → `assess.py` → `catalog.csv` (scored + probed) and `data_endpoints_probe.csv` (download hosts).

| Type | Sources | Global + open + commercial-OK | Tier A (≥80) |
|---|---|---|---|
| Roads (crossroads derived from road topology) | 106 | 16 | 20 |
| Building footprints / built-up | 104 | 20 | 23 |
| Building heights | 101 | 14 | 22 |
| Terrain | 102 | 15 | 20 |
| Forest / canopy | 102 | 37 | 46 |
| Land cover | 101 | 26 | 31 |
| Water bodies | 101 | 49 | 52 |
| Water points | 104 | 7 | 12 |

Crossroads: no independent intersection datasets exist anywhere. They are computed from a routable road graph
(`topology=Y` in catalog.csv). Water points: only about 7 sources are both global and open, and none is complete.

## Scoring (catalog.csv `score`, 0-100)
coverage (global 30 / continental 18 / national 10 / city 4) + license (commercial-OK 20 / restricted 10 / NC 6 / paid 4)
+ recency (≥2024 20 / ≥2022 15 / ≥2018 9 / older 3) + access (download 20 / API 17 / registration 12 / paid 6 / on request 3)
+ reachability (ok 10 / restricted 7 / blocked-here 5). Flags: NON-COMMERCIAL, PAID, SHARE-ALIKE, STALE<2018, NOT-GLOBAL, URL-BROKEN.
The score is metadata only. Accuracy is judged by hand in the decision table below.

## Accessibility check (from this container, 2026-10-02)
- Landing pages: 9 OK, 26 reachable but restricted (login/403), 785 **blocked by this environment's egress policy**, 0 broken links.
- Data endpoints of the 46 shortlisted sources: **10 verified downloadable** (OSM AWS mirror, Overture S3 ×3, Google Open Buildings GCS,
  Copernicus DEM S3, AWS Terrain Tiles, Hansen GCS, Meta canopy S3, ESA WorldCover S3, JRC GSW GCS). Earth Engine answers but needs
  login (Dynamic World, Google 2.5D). The other 34 are **unverified**: their hosts are blocked here (Zenodo, HuggingFace, Azure blobs,
  JRC FTP, HydroSHEDS, WPdx, GeoNames, NASA Earthdata, ...).
- To finish verification: set the environment's network access to Full, then run `python sources/assess.py` (~5 min).

## Decision (per data type)
Legend: ✅ verified downloadable here · ⚠ exists but host blocked here (unverified) · 🔒 login · NC = non-commercial only

| Type | Primary | Gap fill | Validation / QA | Rejected (why) |
|---|---|---|---|---|
| Roads + crossroads | Overture transportation ✅ (OSM-based, topology → crossroads) | Microsoft Road Detections ⚠ (rural gaps, no topology) | Boeing street networks ⚠, national road nets (TIGER, OS Open Roads, NWB...) | GRIP/gROADS (stale, coarse), commercial HERE/TomTom (cost) |
| Building footprints | Overture buildings ✅ (OSM + Google + Microsoft, de-duplicated) | Google Open Buildings v3 ✅ (confidence score), GHS-BUILT-S ⚠ | national cadastres (BAG, BD TOPO, Catastro, LINZ...) | EUBUCCO alone (Europe only), ML training sets (not coverage) |
| Building heights | **Commercial:** 3D-GloBFP ⚠ (CC-BY) + Google 2.5D 🔒 (CC-BY, Global South). **Non-commercial:** GlobalBuildingAtlas ⚠ (NC, best coverage) | OSM height/levels ✅ via Overture, GHS-BUILT-H ⚠ (100 m) | national LiDAR/LoD2 (3DBAG, PLATEAU, swissBUILDINGS3D, 3DEP) | DSM-minus-DEM from 30 m Copernicus (too coarse for single buildings) |
| Terrain | Copernicus GLO-30 ✅ (DSM) | DeltaDTM ⚠ (coastal bare earth, CC-BY) | national LiDAR DTMs, ICESat-2 ATL08 | FABDEM/FathomDEM if commercial (NC); SRTM/ASTER (older, noisier) |
| Forest / canopy | Meta canopy 1 m ✅ + Hansen GFC ✅ (loss/gain) | JRC GFC2020 ⚠ (EUDR forest definition), ETH 10 m ⚠ | GEDI L2A ⚠, national forest inventories | Simard 2005 / MODIS VCF (coarse, old) |
| Land cover | ESA WorldCover ✅ (10 m) | Dynamic World 🔒 (NRT), Esri/IO annual ⚠ | LUCAS, Geo-Wiki, national maps (NLCD, CLC+) | GlobCover/GLC2000 (stale), MODIS (500 m) |
| Water bodies | JRC GSW ✅ + Overture/OSM water ✅ | HydroRIVERS/HydroLAKES ⚠, GLWD v2 ⚠ (wetlands), SWORD ⚠ | SWOT ⚠, national hydro networks (NHDPlus, EU-Hydro) | SWBD/MOD44W (old, coarse), MERIT Hydro if commercial (NC) |
| Water points | WPdx+ ⚠ (best for Africa/LatAm, has functionality status) + OSM/Overture ✅ | SIASAR ⚠, national well DBs (NWIS, SIAGAS, BGS, BRGM...), Jasechko wells ⚠ | HDX/REACH surveys | GeoNames/Wikidata (sparse names only), NGO maps (restricted, overlap WPdx) |

## Bottom line
- 6 of 8 types have a reliable, open, global primary source, and 5 of those primaries are verified downloadable here.
- **Building heights** depend on the commercial/non-commercial decision: GBA is the best source but non-commercial only.
- **Water points** cannot be made globally reliable from open data. Coverage will be good in Africa and Latin America
  (WPdx, SIASAR), the US and Europe (well registries), and patchy elsewhere.
- The current pilot already uses the verified primaries. The changes this assessment implies:
  add WPdx, HydroSHEDS, GLWD v2, JRC GFC2020 and a CC-BY height source (3D-GloBFP), all of which need network access.
