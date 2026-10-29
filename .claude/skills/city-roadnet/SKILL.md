---
name: city-roadnet
description: Build or edit the PS1-style city road network (streets, avenues, junctions, traffic lights, roundabouts, elevated highway, ramps/exits) with the Blender generator in Tools/citygen and export it to Unity. Use for any request about roads, intersections, highway/periph, interchanges, city blocks or buildings layout.
---

# City road network (Blender → Unity)

Generator: `Tools/citygen/roadnet.py` (library) + `Tools/citygen/city_demo.py` (the map).
Asset kit (buildings, street props, vegetation): `Tools/citygen/kit.py`; art-direction test scene:
`Tools/citygen/da_scene.py` → `Assets/GTA/DA/DAScene.fbx` (see ps1-art-direction).
Everything is procedural Python run in Blender through the Blender MCP. Never hand-model roads.

## Run / rebuild / export

```python
# mcp__blender__execute_blender_code
import sys, importlib
p = r'F:\Develop\Unity_Project\GTA PS1\Tools\citygen'
if p not in sys.path: sys.path.insert(0, p)
import roadnet, city_demo
importlib.reload(roadnet); importlib.reload(city_demo)
result = city_demo.build(export=r'F:\Develop\Unity_Project\GTA PS1\Assets\GTA\City\CityDemo.fbx')
```
Exporting also writes `CityDemo_placements.json` + the prefab FBX files; then in Unity run GTA > Place Props In
Open Scene (or `PropPlacer.Run()` from MCP) on the scene. `result['warnings']` must be empty (a warning = an edge eaten by its junction setbacks → move nodes apart).
It also writes `CityDemo_peds.json`, the pedestrian graph (`Net.ped_graph()`: sidewalk middle lines, junction
corners, crosswalks; Unity coordinates) walked by the crowd; `city_demo.export_peds(path)` rewrites only that file
(works with `blender -b --python`). After a road or block change, run GTA > Setup Crowd In Open Scene in Unity.
Build takes ~3 s. Unity reimports the FBX on focus; `Assets/GTA/Editor/CityModelImport.cs` sets 32-bit
indices and adds a MeshCollider to every object except `Markings`. Scene: `Assets/Scenes/CityDemo.unity`.

## Data model

- `net.node(x, y, z=0, kind='auto', control=None, curb_r=8, ring=None)`
  - `kind`: `auto` (≥3 edges → junction, 2 non-collinear → bend, else plain), `plain` (edges just butt:
    highway nodes, splits, curve joints), roundabout when `ring=(r_island, r_outer, r_fillet)`.
  - `control`: `'signal'` (mast arms, crosswalks, stop lines), `'stop'` (stop signs), `'yield'`, `None`.
- `net.edge(a, b, profile, prof_b=None, pts=[...], flat=(fa, fb), no_barrier={'L': (fromA, fromB)})`
  - `pts`: intermediate centerline points (curves = dense points, use `rn.arc`).
  - `prof_b`: taper to another profile with the SAME strip list (widths are lerped).
  - z eases (smoothstep) from `a.z` to `b.z`, keeping `flat` meters level at each end.
- `Profile(left, right, marks, oneway)`: strips from the centerline outward:
  `lane`, `shoulder` (also parking lane), `mbarrier` (half median Jersey), `sidewalk`, `barrier` (deck edge).
  Marks: `(lateral, 'solid'|'dashed'|'double'|'none', 'W'|'Y')`, lateral > 0 = right of edge direction.
- Drive on the right. A one-way edge's direction is the travel direction.

## Standards (keep the city coherent)

| Item | Value |
|---|---|
| Lane | 3.3–3.7 m (highway 3.7, ramp 4.0) |
| Parking lane | 2.4 m (`shoulder`) |
| Sidewalk | 3 m street, 4 m avenue; curb 0.15 m |
| Curb radius | 8 m (12 m for bends); roundabout fillet 10 m, keep fillet > sidewalk width |
| Highway | 3+3 lanes, deck z = 7.5 m (≥ 6 m clearance), median barrier, shoulders 1.2/3.0 |
| Ramp slope | ≤ 6–7 % → ≥ ~180 m to climb 7.5 m with smoothstep (max slope = 1.5·Δz/L) |
| Block | 130 × 100 m grid (US downtown); junction spacing must exceed both setbacks + 10 m |
| Markings | 0.15 m solid, 0.12 m dashes 3 m on / 9 m off, double yellow center on two-way |

## Recipes

- **Grid street / avenue**: nodes at grid points, `control='signal'` where an avenue is involved, `'stop'` otherwise.
- **Roundabout**: one node with `ring=(16, 26, 10)`; approaches must arrive radially and straight.
- **Highway exit/entrance (parallel taper)**: on the highway, `node(-TAPER) → node(-SPLIT)` with
  `prof_b=highway(aux)` (adds a ramp-wide strip), then a `plain` node at the gore. The ramp starts at its own
  `plain` node placed laterally at `HW_EDGE + RAMP_W/2`, tangent to the highway, curves away (S-curve via
  `smooth`), descends with `flat` at the street end, and joins a normal signalised junction.
  At the gore the facing barriers stand on the shoulders (highway `gore=True` shoulder 2.5, ramp left shoulder 1.0),
  so they meet **back to back** at the seam – never let one barrier stand on the other road (they cross into an X).
  `net.gore(hw_edge, ramp_edge)` caps the gap between them into one solid median until they are 1.5 m apart,
  then they split. They rise from the nose (`no_barrier` = `GAP` = 1 m) over 10 m. See `build_net()` sides loop.
- **Barriers** (`barrier` strips) are full height everywhere, at grade too. Fades (3 m into a junction, 10 m after a
  `no_barrier` point) lower the height down to a flat strip at road level – the width never changes (no needles).
- **Corner sidewalks** keep a constant width around the curb fillet (back edge concentric, so block lots have
  rounded corners). Facing an arm without sidewalk (ramp), the sidewalk keeps its width and is capped there.
- **Bridges / overpasses**: an edge with z > 3 m becomes a deck with pillars (auto-skipped near at-grade roads
  and junctions). Crossing edges need no node; keep ≥ 6 m vertical clearance.
- **Blocks**: `node.block_corners` gives each corner's sidewalk outline → `city_demo.blocks()` builds lots
  exactly matching the sidewalks, then parcels/buildings inside (`style_for`: towers downtown, brick / stucco
  mid-rise, apartments / spanish / strip malls outside). Parks get a hedge with entrances, bushes in groups and
  benches; parking lots a chain-link fence with shrubs (`kit.fence` / `kit.hedge` stamped into one mesh each);
  apartment fronts get corner shrubs. Street-name signs on every grid junction, power poles + wires on the rural loop.

## Verify before handing over

Always render the exact spot you changed in Unity (camera clone → RenderTexture → PNG, several street-level angles
plus one from above), judge it critically and keep fixing until it looks right. Never hand over a visible defect.

1. Top-down ortho renders (Workbench, `view_transform='Standard'`) of the whole map and close-ups of: a 4-way,
   a T, the roundabout, a gore/split, a ramp landing. Look for green slivers (holes), overlaps, marks on the
   wrong side (stop line must be on the right of approaching traffic).
2. Street-level perspective render (camera z≈2 m).
3. In Unity Play mode drive it (`R` reset). If MCP must inject input: set
   `InputSystem.settings.backgroundBehavior = IgnoreFocus` and `PlayerSettings.runInBackground = true`.

## Props from the road generator

Lamps, signal heads, stop / yield signs are **prefab placements** (`net.place(prefab, p, z, yaw)` ->
`net.placements`), not baked geometry: prefabs face -Y (signs, heads) or +X (lamp arms); yaw is Blender radians.
Signal poles + mast arms and the highway exit gantry stay baked (their size varies).

## Materials

Material names are the Blender↔Unity contract (`roadnet.material`, `ImportRules.cs`): `Foo` → `T_Foo.png`,
`Foo__Tint` → `T_Foo.png` × `COLORS` tint. Road parts: Asphalt, Sidewalk, `Concrete__Curb`, Concrete,
MarkWhite/MarkYellow (flat paint), `MetalPaint__Pole`, `MetalPaint__Signal`, StopSign (fitted cap UVs).

## Known limits / next steps

- Scene meshes are tiled: `Mesh.tiles(size)` splits a category by 128 m cells (`Roads_<i>_<j>`, `RoadsV_`
  vertical parts, `RoadsDeck_`, `Markings_`, `Lots_`, `Drives_`, `Fences_`, `Hedges_`, `Wires_`, `Ground_` 512 m).
  The flat layers (`ImportRules.Planar`) get a top-down lightmap chart in Unity, so keep road / lot / marking tops
  in those layers and anything vertical in `RoadsV` (`city_demo.road_layer`).
- Residential districts (`city_demo.DISTRICTS`, one per rural-loop side): streets leave the loop every 120-200 m
  (`residential()` profile: 3.2 lane + 2.2 parking + 2 m sidewalk, no centre line, 4-way stops), cross streets at
  `rows`; `net.blocks` -> `houses()` cuts each block into lots along its two cross-street sides, back to back
  (blocks along the rural loop, which has no sidewalk: one row facing the inner street, backing onto the loop behind
  a fence and a row of trees). Per lot: house prefab centred on its lot (footprint incl. garage wing / side driveway
  in `HOUSE_PLANS`, keep in sync with `kit.PREFABS`), concrete driveway and walkway, foundation shrubs, front and
  back trees. Every yard is closed (`boundary()`, kinds picket / hedge / tallhedge / wood / chain per district
  `front` / `back`): along the sidewalk with gaps at the driveway and the walkway, low between front yards, fences
  or tall hedges between back yards and along the lot backs. Boundaries sit 1 m inside the sidewalk and are clipped
  to the block outline (`clip`, rounded corners); block edges are measured where the middle lines cross the outline
  (the corner sidewalks stick out past the straight edges along the loop).
- Terrain: `height(x, y)` is flat inside `FLAT` and rises into noise hills beyond (smooth-shaded `Ground` tiles with
  exact normals); `turbines()` puts wind turbines on crests 1.05-1.7 km out. Keep roads inside `FLAT`.
- Traffic lights are static meshes (no light cycle yet). No dead-end caps / cul-de-sacs, no diagonal streets yet
  (the junction math supports any angle; very acute angles produce long setbacks).
