---
name: ps1-npc
description: Create PS1-style pedestrians (NPC) for the GTA PS1 project from Fabien's base model Art/NPC/hero.fbx - outfit / face / skin-tone variants of the texture atlas (AI region edits), the female body, Humanoid rig + CC0 mocap clips, the instanced crowd (VAT + GPU instancing, hundreds of pedestrians, WebGL) and the ragdolls when the car hits them. Use for any request about characters, pedestrians, NPC bodies / outfits / faces, their animation, crowd density / performance, running people over, or their Unity integration.
---

# PS1 pedestrians (NPC)

## Quality bar (Fabien, non negotiable)

- **No procedural humans, no procedural animation.** Two attempts (segmented boxes, Skin-modifier blobs with a
  scripted walk) were rejected as "dégueulasses". The base is **his** model `Art/NPC/hero.fbx` (952 tris, A-pose,
  rigged, faces −Y, scale 0.01) with its atlas `Art/NPC/man_t256.png` (256 px). Every NPC is this mesh (or a
  reshaped copy of it) with a different atlas. Animations are **real mocap** retargeted through Unity Humanoid.
- Textures stay 256 px, point sampled, no mipmaps (ImportRules). Variants must keep the UV layout exactly.

## Files

| Path | What |
|---|---|
| `Art/NPC/hero.fbx`, `man_t256.png` | Base model + atlas (never edited; copied/derived from) · `Art/NPC/UAL/` license + Unity setup sheet |
| `Assets/GTA/NPC/hero.fbx`, `hero_f.fbx` | Man (copy of the base) and woman (reshaped by `npc.py`), imported Humanoid |
| `Assets/GTA/NPC/Anims/UAL_Standard.fbx` | Quaternius Universal Animation Library (CC0): 46 Humanoid clips, `*_Loop` = loops |
| `Assets/GTA/NPC/Skins/M_*.mat` | One PS1Lit material per atlas (ragdolls), built by the menu |
| `Assets/GTA/NPC/Crowd/` | Built: `<name>.asset` (CrowdCharacter), `_VatPos`/`_VatNrm` (vertex animation textures), `_Body` mesh, `_Skins` (Texture2DArray), `M_<name>_Crowd.mat`, `<Scene>_walk.bytes` (sidewalk bitmap) |
| `Assets/GTA/Textures/T_hero.png`, `T_hero_<V>.png`, `T_hero_f.png`, `T_hero_f_<V>.png` | Atlases: base man, man variants, base woman, woman variants |
| `Tools/texture/npc_variants.py` | crop / compose / recolor / tint: makes the variant atlases |
| `Tools/citygen/npc.py` | Blender: `load()`, `female()`, `export()`, `inspect()` — bodies |
| `Assets/GTA/Editor/ImportRules.cs` (`IsNpc`) | Humanoid, avatar from model, bakeAxisConversion, clip renaming `Rig|Walk_Loop` → `Walk_Loop`, loop flags |
| `Assets/GTA/Editor/NpcPrefabs.cs` | Menus **GTA > Build NPC Crowd** and **GTA > Setup Crowd In Open Scene** |
| `Assets/GTA/Scripts/CrowdSystem.cs`, `CrowdCharacter.cs` | The crowd: simulation, instanced drawing, impacts, ragdoll pool |
| `Assets/GTA/Shaders/PS1Crowd.shader` | PS1Lit lighting + VAT vertex fetch + outfit array, instanced (Forward, ShadowCaster, DepthOnly) |
| `Assets/GTA/Prefabs/NPC/<name>_Ragdoll.prefab` | Skinned model + Animator (posing only) + 11 rigidbodies / CharacterJoints, layer Ignore Raycast |

Naming contract: skins of `<name>.fbx` are every `Assets/GTA/Textures/T_<name>.png` / `T_<name>_<Variant>.png`,
minus those of a character whose name extends it (`hero` ignores `T_hero_f*`). So woman variants are `f_<Variant>`.

## A. New outfit / face / skin tone (texture variant) — the common request

The atlas is split into UV islands (`REGIONS` in `npc_variants.py`, pixel rects, y down):

| region | rect | content |
|---|---|---|
| torso | 0,0 → 144,124 | shirt front \| shirt back, trouser waistband at the bottom |
| legs | 0,117 → 96,256 | two trouser strips |
| arms | 95,114 → 177,256 | sleeve (top) + bare arm skin (bottom) |
| head | 144,0 → 256,112 | face, hair, neck |
| hands | 174,150 → 228,218 | (too small for the API: use `tint`) |
| feet | 170,187 → 254,256 | shoes |

Editing **one region**, upscaled ×8, with a "same geometry, new garment" prompt keeps the layout. Editing the whole
atlas does not (tested: it redraws the layout). Steps:

```bash
V="python -I Tools/texture/npc_variants.py"; RAW=<scratchpad>/raw
$V crop torso $RAW                       # -> crop_torso_x8.png + the API size (e.g. 1152x992)
$V crop torso $RAW/f --base Assets/GTA/Textures/T_hero_f.png     # woman: crop the woman atlas
# host the crop (the API needs a public URL; 1 h is enough):
curl -s -F reqtype=fileupload -F time=1h -F "fileToUpload=@$RAW/crop_torso_x8.png" https://litterbox.catbox.moe/resources/internals/api.php
```

Then `mcp__muware__gpt_image_edit` (load with ToolSearch) with `images=[url]`, `size` = the printed size,
`return_base64=true`, default model/quality (≈ 0.01–0.02 $ per region). Prompt template that works:

> This image is one region of a flat UV texture atlas of a low-poly PlayStation-1 style game character (pixel art
> upscaled): <what the region shows>. Keep EXACTLY the same layout: every shape stays at the same position and size,
> same seams, same edges. Only repaint the surface. Flat hand-painted colors with soft baked shading, no outlines,
> no text, no logos. Output the same image dimensions. <the change: "Repaint the T-shirt as a heather grey hoodie…;
> keep the trouser waistband at the bottom unchanged">.

Long sleeves: ask the arms edit to turn the bare-arm part into sleeve fabric (+ cuff). Skin tone: edit **head** and
**arms** ("keep the sleeve; repaint the bare arm skin as dark brown skin"), then `tint` the hands (and the arms
when you want to keep an existing sleeve exactly):

```bash
$V tint hands $RAW/edit_black_arms.png $RAW/edit_black_hands.png        # scales skin pixels by the arms' skin ratio
$V tint arms  $RAW/edit_black_arms.png $RAW/tint_black_arms.png
```

The tool result is > 1 MB so Claude Code dumps it to `…/tool-results/mcp-muware-gpt_image_edit-<id>.txt`: decode
`json['images'][0]['b64_json']` with python into `$RAW/edit_<what>.png`. Then compose (BOX downscale ×8 → paste):

```bash
$V compose Hoodie --torso $RAW/edit_hoodie_torso.png --arms $RAW/edit_hoodie_arms.png      # -> T_hero_Hoodie.png
$V recolor Suit --pants 0 0.3 0.35 --shoes 0 0.2 0.4                                       # cheap palette swap first
$V compose Suit --base Assets/GTA/Textures/T_hero_Suit.png --torso … --arms …              # then the edits on top
$V compose f_Blonde --base Assets/GTA/Textures/T_hero_f.png --head $RAW/edit_f_blonde_head.png
```

`recolor` = H shift (degrees) + S, V multipliers on `shirt` / `pants` / `shoes` rects, skin tones spared. Edits are
**combinatorial**: keep every `edit_*.png` in the scratchpad and mix heads × torsos × legs (`Black_Hoodie` = hoodie
atlas + black head + tinted hands). Previews `T_hero_<V>_x3.png` go to `%TEMP%/npc_variants` (never into Assets or
Art). Existing edits (session 2026-10-26, scratchpad `raw/`): hoodie, suit, hawaiian, flannel (torso+arms+legs+head
50s grey), black man head/arms, latino head; woman: blonde head, black head/arms, blazer torso+arms, breton stripes.

Gotchas: litterbox answers 504 sometimes → retry the upload; an API 400 means the URL served HTML or the size is too
small (hands); the base man's T-shirt is teal, say so in prompts that "keep the sleeve"; the tool can't read local
paths (server side).

## B. New body (the woman was made this way)

```python
import sys, importlib; sys.path.append(r'F:\Develop\Unity_Project\GTA PS1\Tools\citygen')
import npc; importlib.reload(npc)
npc.load()                                  # hero.fbx -> collection NPC: mesh 'male_player' + armature 'rig'
ob = npc.female('female_player', height=0.95)   # reshape in world space from vertex-group weights, same rig/UV/weights
npc.inspect('female_player', out_dir)       # Workbench front / 3/4 / back renders -> look at them
npc.export('female_player', 'hero_f')       # -> Assets/GTA/NPC/hero_f.fbx (mesh + 'rig', no animation)
```

`female()` is the template for other builds (heavy, slim, short): per-vertex scaling driven by bone weights and
height bands, `ob.scale = src.scale * height`. Blender 5: actions have no `.fcurves`; the FBX mesh comes in at scale
0.01, rotated 90°, facing −Y — work in world space (`matrix_world`). Export with `bake_space_transform=False`
(the rig must stay as is), ImportRules does the rest (Humanoid, avatar from this model, auto-mapped; no Chest bone
is fine). Check in Unity: `avatar.isHuman`, material `<name>` → `T_<name>.png`, bounds ≈ 0.7 × 1.9 × 1.1.

## C. Animations

- UAL clips are in place (apparentSpeed ≈ 0) → `CrowdSystem.walkSpeed` = 1.35 m/s tuned by eye; each pedestrian
  walks 0.85–1.15× that and plays the walk clip at the same ratio (no foot sliding).
- Baked clips = `NpcPrefabs.Clips` = `CrowdSystem.Clip` (Idle_Loop, Walk_Loop, Sitting_Idle_Loop,
  Sitting_Talking_Loop, Idle_Talking_Loop), 20 fps, no interpolation (PS1 look). Adding one (Sprint_Loop for panic,
  Death01…): append it to both, rebuild. The UAL sitting clips put the pelvis 0.51 m high and 0.13 m behind the
  root, feet on the ground: they fit the kit benches (seat 0.46 m) as is.
  Other UAL clips: Jog/Sprint/Sitting/Pickup… (clip list of `UAL_Standard.fbx`).
- Adding Mixamo (Fabien logs in; Playwright): download FBX for Unity, *Without skin*, 30 fps, drop it into
  `Assets/GTA/NPC/Anims/`; ImportRules makes it Humanoid and keeps the part after `|` as clip name; name files so
  the loop rule applies (`*_Loop`) or set loopTime by hand; add it to `NpcPrefabs.Clips`.
- Humanoid muscle limits clamp hand-authored poses (hanging arms stop at ~60°); mocap is unaffected.

## D. Unity: the crowd (hundreds of pedestrians, WebGL)

Why this design: the game ships on WebGL (single thread, no compute shaders, CPU skinning). One SkinnedMeshRenderer +
Animator per pedestrian costs too much past a few dozens. So pedestrians are **not GameObjects**:

- **Population of the whole city** (`CrowdSystem`, plain structs: position, heading, timers, outfit, clip, graph
  link). Fabien wants people everywhere, orderly (no "chaos"), crossing at crosswalks:
  - `walkers` (2000) spread evenly along the **pedestrian graph** `Assets/GTA/City/<City>_peds.json` exported by
    the road generator (sidewalk middle lines ~21 km, corners, 184 crosswalks). Each one walks the graph keeping
    `lane` (0.25–0.9 m) to its right, so the two directions pass each other; at a graph point it carries on, turns
    the corner or crosses (`crossChance` 0.3), never goes back except at a dead end; 15 % chance every 8–20 s to
    stop 2–6 s (never on a crossing); waits while the car blocks its next step.
  - `spots` (from GTA > Setup: 2 seats per Bench, 3 seats + 2 standing spots per BusStop) occupied with
    `seatOccupancy` / `standOccupancy`: Sitting_Idle or Sitting_Talking, Idle at the bus stops.
  - `talkingGroups` (160) of 2–3 people facing each other (Idle_Talking) where the sidewalk bitmap is paved all
    around within 1.6 m (in practice the paved lots between buildings).
  - LOD: beyond `fullSimDistance` (120 m) a quarter of the walkers is stepped per frame (dt × 4). A killed
    pedestrian comes back as a walker somewhere out of sight (> 60 m and out of view, or beyond drawDistance).
- **Drawing**: `Graphics.DrawMeshInstanced` per body and per shadow class (≤ 4 draws): distance (`drawDistance`
  250 m, fog ends at 520) and CPU frustum culling, the ones within `shadowDistance` (30 m) cast shadows. Per instance `_Crowd` = (outfit slice, VAT row). The shader
  texel-fetches the vertex position / normal (vertex index in uv1.x) and samples the outfit array.
- **Physics on demand**: a pedestrian inside the car's BoxCollider footprint (grown by the distance covered this
  frame) above `minHitSpeed` (3 m/s) is swapped for a pooled ragdoll (`ragdollsPerCharacter` = 8, oldest reused,
  hidden after `bodyLifetime` 45 s): placed on the pedestrian, outfit material set, posed by evaluating the same
  clip at the same frame (PlayableGraph, Animator disabled after), then thrown with 1.3 × car velocity + sideways
  (bumper side) + up; legs 1.1×, torso 0.9× so the body tumbles. Car slowed by 3 %. A flying body (hips > 3 m/s,
  < 4 s old) knocks the pedestrians it passes. A slow car pushes pedestrians aside; they also steer around it.
  Ragdolls are on layer Ignore Raycast so the car's suspension rays roll through them (no jitter).

Measured in the editor (2026-10-27): the whole-city population (2446: 2000 walkers, ~70 seated / waiting, ~380 in
groups) costs ~1.1–1.5 ms per frame (9.3 ms off, 10.4–10.8 ms on, same view).
The shader compiles for GLES3/WebGL (check: `ShaderUtil.GetShaderData(shader).GetSubshader(0).GetPass(i)
.CompileVariant(type, keywords, ShaderCompilerPlatform.GLES3x, BuildTarget.WebGL)`).

Steps:
1. `GTA > Build NPC Crowd` after adding a character FBX, an atlas `T_<name>*.png` or a clip.
2. After the city changes: export the pedestrian graph (skill city-roadnet: `city_demo.build(export=…)` or
   `city_demo.export_peds(…)`), then `GTA > Setup Crowd In Open Scene` (rebakes the sidewalk bitmap ~8 s, reads the
   seats from the placed props, links `<Scene>_peds.json`): it replaces the `Crowd` object and saves the scene.
3. Verify in Play (ManageEditor Play/Stop): `CrowdSystem.Count` / `Feet(i, out yaw)` give positions; render a clone
   of `Camera.main` into a RenderTexture and look at it. The draws are culled with Camera.main's frustum during
   Update: move Camera.main in one command, render in the next one (same command = empty shots). Impact test: put
   the car ~6 m behind a pedestrian facing it, `linearVelocity` 16 m/s, `Time.timeScale` 0.025, capture several
   frames. Simulated keyboard input does not drive the car while the editor is in the background.
4. From RunCommand: `NpcPrefabs` is not visible (other assembly), use `EditorApplication.ExecuteMenuItem("GTA/…")`.
   Reflection on private fields makes RunCommand fail with a bare NullReferenceException: use public members.
   After editing C# from outside, `AssetDatabase.ImportAsset(<script>, ForceUpdate)` triggers the compile; compile
   errors only show in the editor log (`-logFile`), not always in ReadConsole. Never leave an
   `Application.logMessageReceived` handler capturing `result`: every later command then fails.

## Known limits / next

- Pedestrians ignore each other (same lane, different speeds: they pass through) and the traffic lights (they
  cross whenever they choose to). Nobody walks inside the parks or across the paved lots (graph = street sidewalks).
- No panic: the crowd keeps walking past bodies (next: Sprint_Loop clip + flee from the car / a hit).
- Sidewalks are assumed flat (one ground height in the map header): store heights when slopes appear.
- One draw per batch caps a batch at 1023 instances (split if `count` grows past that).
- Hair is texture only (no hair geometry); bust/hips are vertex reshapes of the male mesh.
- Skins are picked uniformly at random per instance: a crowd of 12 may repeat; shuffle if it bothers.
