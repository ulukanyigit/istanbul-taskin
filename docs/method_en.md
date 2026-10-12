# Istanbul Flood Simulator — method note

**Question.** If the stormwater network fails, where in Istanbul does water pond first, after how many millimetres of
rain, and who is exposed? **Level:** city-wide screening, not an engineering design or an official hazard map.

## Data and grid
TUREF/TM30 (EPSG:5254), 10 m grid (19,050 × 10,027) covering the province and all HydroSHEDS level-12 basins draining
into it. FABDEM v1.2 (Copernicus GLO-30 with buildings and forests removed), ESA WorldCover 2021 and HiHydroSoil v2
hydrologic soil groups → TR-55 curve numbers (mean CN 80.4). OpenStreetMap (892k buildings, 253k road segments,
streams, 2,318 culverts, 1,374 underpasses, 4,759 critical facilities). JRC GHS-POP 2020 scaled to the TÜİK 2020 total
(15.46 M) and distributed to buildings by footprint; GHSL built-up 1990/2020; NASA GPM IMERG V07; NASA GEDI L2A.
All raster inputs are produced in Google Earth Engine on one fixed grid.

## DEM conditioning
Depressions are **not** filled — they are the result. Only artificial obstructions are removed and urban flow paths
opened: bridges masked and interpolated, buildings +5 m, roads −0.30 m, open streams carved along a monotonic profile
(running median + cumulative minimum), culverts breached (each kept as a blockable feature), underpasses cut with a
sloping floor 5 m below grade, sea as outlet.

## Depressions and fill–spill tree
A numba Priority-Flood (Barnes et al. 2014) yields 58,874 depressions (≥10 cm deep, ≥300 m², ≥20 m³) out of 228,605
raw ones; a second pass gives each pixel's first-entered depression (local catchment), each depression's spill point and
receiver — a fill–spill–merge tree (bluespot approach, Balstrøm & Crawford 2018). Sorted pixel elevations per
depression give an exact volume→level relation. **Fill threshold:** SCS-CN runoff (Ia = 0.2S) from each local
catchment for 0–300 mm, routed upstream→downstream; the smallest rainfall at which a depression is full.

## Bucket engine and scenarios
Every 5 minutes: local SCS-CN runoff from cumulative rain → drainage capacity (mm/h per catchment area) → overflow to
the receiver → water level from the hypsometry. Travel time is neglected. The Python reference and the browser engine
(JavaScript, Web Worker) agree to ≤0.8 cm in all 58,874 depressions. Scenarios: design storms (total, duration,
triangular hyetograph) or historical IMERG events, drainage capacity, underpass pumps (0.5 m³/s each), culvert
blockage (pond behind the restored embankment, fed by the culvert's upstream area and by depressions whose spill path
crosses the culvert), pipe burst at a clicked point, and 1990 vs present land cover.

## Exposure and risk
Water at a building's wall (building pixels + 1-pixel ring): ≥10 cm "touching", ≥30 cm "basement/ground-floor risk".
Drivable OSM network (1.3 M nodes); edges with ≥30 cm at the midpoint closed; multi-source Dijkstra to hospitals.
Neighbourhood risk index = mean of province-wide percentile ranks of hazard, exposure and access loss; Getis-Ord Gi*
(2 km) hot spots.

## Key results (no drainage, uniform rain, within the province)
50 mm: 65.8 km² under water, 100,067 buildings with ≥10 cm at the wall (2.57 M residents), 149 hospitals, 767
schools and 205 metro entrances touched, 383 km of road impassable. Hot-spot belt: Bağcılar–Esenler–Bayrampaşa–
Güngören–Zeytinburnu–Fatih. **Urbanisation:** with 1990 imperviousness, urban depressions full at 25 mm would be
9,680 instead of 12,162 today (+26 %); at 10 mm 1,673 vs 3,038 (+82 %).

## Validation
22 sourced news reports (2021–2026) geocoded as 11 streets and 11 points, compared with 2,000 random built-up points
and 500 random named streets. Streets: AUC 0.83 [0.74–0.91] for the fill threshold; points: AUC ≈ 0.66, CI includes
0.5. Misses are coastal/under-bridge locations, most likely sewer backflow, which the model does not represent.

## Sensitivity and uncertainty
Each conditioning parameter was rescaled within its own mask (z = FABDEM + delta × k) and the depression analysis
re-run. Building height (+3/+8 m), stream carving (×0.5/×1.5) and underpass depth (3/7 m) barely change anything (93–100
of the top-100 urban depressions retained, ρ ≥ 0.99). Road lowering is the sensitive parameter: −0.15 m instead of
−0.30 m keeps 19 of the top 100 (ρ 0.19; a third of urban depressions fall below the 10 cm filter), −0.50 m keeps 36
(ρ 0.84). A spatially correlated DEM error of σ = 0.25 m (4 Monte Carlo runs) keeps 17–26 (ρ 0.41). Aggregated to
neighbourhoods (urban volume filling at 25 mm), the picture is robust: Spearman ρ 0.94–0.95 for road variants and ~0.89
for DEM error, 32–41 of the top-50 neighbourhoods shared, district ρ 0.78–0.95 (0.96–0.98 at 50 mm). Street-level
rankings are therefore indicative; the neighbourhood scorecard is the robust product. The GEDI export returned no samples,
so σ is an assumption (relative, not absolute, error is what matters for 10–30 cm depressions).

## Limitations
30 m source DEM; unknown sewer network (single capacity parameter); no travel time, backflow or storm surge; no
basement/floor levels; incomplete OSM underpass/culvert tags; drainage, pump and culvert settings are scenario
assumptions, not utility data.
