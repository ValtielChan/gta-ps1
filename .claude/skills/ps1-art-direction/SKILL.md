---
name: ps1-art-direction
description: PS1 art direction rules for the GTA PS1 project - texel density, texture sizes, UV scale, palette, vegetation (clumps + cutout cards + billboard LODs), shader, post effects, render resolution. Use whenever creating or importing textures, materials, meshes, buildings, props, trees or cars, or tuning the look.
---

# PS1 art direction (project rules)

**PS1 for the material (textures, shapes, resolution), modern for the light.** One coherent pixel size
across the whole world: a texture is judged by its pixels per meter, not by its resolution.
Reference scene: `Assets/Scenes/DAScene.unity` (built by `Tools/citygen/da_scene.py`).

## Texel density (the rule that matters)

- **World surfaces: 16 px per meter** (1 pixel ≈ 6 cm – Fabien asked for pixels 2× bigger than 32 px/m). UVs are
  world-scale: **1 UV unit = 4 m** (`roadnet.UV_M`) → a tiling texture is **64 × 64 px for 4 × 4 m**
  (`ps1ify.py` default). Bigger motif = 128 px for 8 m, never stretch.
- Facades: one texture = one **4 m wide × 4 m high bay (one floor)**; building widths are multiples of 4 m and
  floors are 4 m, so windows land exactly on the grid (`kit.building`, `kit.FLOOR`).
- Exceptions (≤ 2× off) for small props with fitted UVs: stop sign / signal head / lamp lens 32 px, bench 64 px,
  grass tuft 32 px, chain-link 32 px per 2 m. Billboard impostors 128 px for the whole tree.

## Textures (`Assets/GTA/Textures/T_<Name>.png`)

- **Source images are REALISTIC photo textures**; the PS1 look comes only from degrading them (`ps1ify.py`:
  box downscale + palette), like 90s artists did. Never generate stylized / pixel-art sources (cartoon look).
  To change the look of an existing texture, re-run `ps1ify` on its saved raw – never regenerate it.

- Power of two, 64–256. Point filter, no compression, mipmaps on (alpha coverage preserved) – `ImportRules.cs`.
- ≤ 32 colors (`ps1ify.py --colors 32`), slightly desaturated, flat lighting baked, dirt/wear painted in.
- **Tintable greys**: `MetalPaint`, `Stucco`, `StuccoBay` are neutral; material `Foo__Tint` multiplies them
  by `COLORS['Foo__Tint']` (hydrant yellow, mailbox blue, pink stucco…). One texture, many props.
- Alpha cutout only (no blending): any texture with alpha → cutout + double-sided automatically. Exception: glass
  materials named `<Foo>__Glass` blend at 45 % opacity with T_Foo (car windows), no shadow.

## Objects: no placeholders, coherent, prefabs

- **Every object ships with its own textures** in the same pass (no flat color, no generic texture standing in for
  the real thing): photo of the object's face(s) on fitted faces (`Mesh.box(..., faces={'ny': 'Foo'})`,
  `Mesh.extrude(profile, depth, front, side)` for rounded fronts, `cyl(wrap=True)` for unrolled sides,
  `loft(..., bottom='Foo')` to project an underside photo on the model itself) + a matching material texture on
  the other faces (same paint / metal as the photo: e.g. the whole signal housing in `SignalMetal__Aged`).
- Model **each object alone and check it**: `kit.inspect(names, out_dir)` renders 3/4 close-ups. Parts must touch
  (bench in one piece), geometry follows the real silhouette with few polygons, no detached decal quads floating
  under a mesh, pixels stay square (match the mesh proportions to the photo's aspect; `--trim` keeps it).
- **Houses** (`kit.house`): walls of 4 m bays from a texture family (`kit.HOUSES`: wall tile, window, door, garage, roof),
  hip or gable roof with eaves / fascia / soffit, porch or garage wing; prefabs `HouseA/B_<Tint>`, `RanchA/B`, `MansionA/B`.
- **Repeated objects are prefabs** (`kit.PREFABS`): exported one by one to `Assets/GTA/Props/<Name>.fbx`, placed
  from `<Scene>_placements.json` by `PropPlacer` (Unity menu GTA > Place Props In Open Scene). Unique things
  (buildings with their random shops, fences, hedges, roads) stay in the scene FBX.
- **Buildings = one material family** (`kit.STYLES`): upper bay, blind wall, ground floor, entrance, service door and
  garage all share the same wall (red brick + stone plinth, buff brick, white stucco tinted per building, granite +
  terracotta deco...). Never mix a bay of another material on a facade. Each family is color-matched to its reference
  bay by `Tools/texture/facades.py` (`ps1ify --match`); add any new bay of a family there and re-run it.
- Ground floors follow a program per side (`kit.ground_program`): street front = shops (strip / buff brick, with
  sometimes a whole 8 m store), mixed (shops around the residents' entrance), residential (entrance every ~20 m,
  windows, rare corner store) or office (lobby + glazing, corner cafe); back = service door / garage of the family.
- Storefronts: `kit.next_shop` never reuses one of the last 3. Fabric awnings on ~25 % of shops only, hung under the
  sign band, fabric picked among `kit.AWNINGS`.

## Geometry & vegetation

- Flat shading, low poly: props 30–300 tris, trees ~250, buildings = boxes + parapet + rooftop units/water tank.
- **PS1 props = a few flat cutout quads + one photo texture** when the object is thin (bench = backrest, seat and
  two leg cards from one front photo, `--trim`). Keep real silhouettes with few polygons where volume reads
  (signal head = box + textured front + 3 visors, cobra-head lamp = small elliptic loft + underside photo).
- **Road markings** are decals with cutout textures from `Tools/texture/marks.py` (ragged pixel edges, paint
  nuance, wear) at road density: `Mesh.mark()` picks MarkThin / MarkWide / MarkBar by paint width; yellow =
  `__Yellow` tint. Never flat-colored geometry.
- Overlapping cards must never be coplanar (stagger them by a few cm) and never sit on a solid face: z-fighting.
- **Vertex colors carry grime / fake AO** (`Mesh(shade=kit.grime(...))`): darker at the foot of walls and props,
  darker inside canopies. PS1-authentic and breaks texture repetition. Every mesh has them (white default).
- **Trees** (`kit.broadleaf`): 6-sided trunk + branches, 3–4 lumpy low-poly clumps (`blob`, opaque `Leaves`)
  + cutout `LeafCard` cards sticking out for a crunchy silhouette.
  **Palms** (`kit.palm`): curved 6-sided trunk, dark skirt, 14 fan fronds = 3-segment bent cards (`PalmFrond`).
  **Bushes / hedges**: same clump + cards recipe, tinted `__Bush`. **Grass**: ground texture + crossed tuft cards.
- **LOD**: every tree/bush is `Name_NN` (empty) → `_LOD0` (mesh) + `_LOD1` (two crossed cards with an impostor
  `T_Imp_<Name>.png` rendered from the LOD0 mesh by `kit.render_impostor`). `ImportRules` builds one LODGroup per
  parent (billboard below 12 % screen height). Re-render impostors whenever a tree mesh or leaf texture changes.
- Long surfaces subdivided (road segments ≤ 6 m) for vertex lighting / future affine warping.

## Rendering (Unity)

- Shader `GTA/PS1Lit` for everything: albedo × tint × vertex color, sun (**no real-time shadows**: the static world is lightmapped by GTA > Bake Lighting at 1 texel/m, bilinear, blob shadows under cars and pedestrians), Forward+ point lights,
  SH ambient, fog. Assigned automatically at FBX import by material name.
- Draw distances (`PS1Resolution` sets `Camera.layerCullDistances`): layer `SmallProps` 160 m (street furniture,
  bushes), `Details` 250 m (markings, fences, hedges, wires, driveways, lamps, poles; city tiles by name in
  `ImportRules`), `Houses` 380 m (`PropPlacer.Layer`); buildings, trees (billboard LODs) and terrain stay. Fog
  60 -> 450 m hides the pop-in. Cut-out textures must reach their edges where the mesh touches the ground.
- Internal resolution **360 px high** (one field: `PS1Resolution.targetHeight`) (`PS1Resolution` on the camera drives URP render scale; URP upscales with
  **point** filter, MSAA off).
- Post: `GTA/PS1Post` full-screen pass (after post-processing, at low res): 4×4 Bayer dither + 32 levels/channel.
  Volume `Assets/GTA/Settings/DA_PostFX.asset`: light bloom, neutral tonemapping, +saturation/contrast, vignette.
  SSAO disabled (vertex colors do it).
- Lighting (DA scene): warm sun (1, 0.93, 0.8) ×1.6 at 42°, trilight ambient, LA haze fog 60 → 420 m.
- **Postponed on purpose**: vertex snapping / affine texture warping (decide later with Fabien).

## Review a look change

Capture at the internal resolution (render `Camera.main` into a 640×360 RT with render scale 1), upscale ×2
nearest, and compare street level, sidewalk props, park and a wide view (see CLAUDE.md "Working with Unity").
