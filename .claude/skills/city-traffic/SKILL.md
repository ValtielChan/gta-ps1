---
name: city-traffic
description: Road traffic for the GTA PS1 project - the lane graph and parking spots exported by the road generator (lanes, junction connectors, roundabout, highway exits / merges, curbside and parking-lot spots), the Unity TrafficSystem (hundreds of instanced cars living around the player, signals / stop signs / yields, passing still obstacles, gridlock dissolving), the pooled rigidbody proxies the player can crash into, parked cars that become physical near the player, paint variants of the car atlas. Use for any request about traffic, AI cars, parked cars, traffic lights / phases, jams, car density / performance, crashing into cars, adding a car model to the traffic.
---

# City traffic (lane graph -> instanced cars -> physical proxies)

Same philosophy as the crowd (skill `ps1-npc`): cars are plain structs simulated and drawn with GPU instancing
(`Graphics.DrawMeshInstanced`, WebGL friendly); only the cars near the player exist physically.

## Files

| Path | What |
|---|---|
| `Tools/citygen/roadnet.py` `Net.traffic_graph()` | Lane graph from the road network (after `build()`) |
| `Tools/citygen/city_demo.py` | `parking_spots()` (curbside + lot stalls), `write_traffic()`, `export_traffic()` |
| `Assets/GTA/City/<Scene>_traffic.json` | Lanes (polylines in travel order, Unity coords, speed, junction, turn, arm, next), junctions (control), `parked` (x, y, z, fwd x, fwd z) |
| `Assets/GTA/Scripts/TrafficSystem.cs` | Simulation, drawing, proxies, wrecks, parked cars, dev checks (`Stats`, `Heads`, `Chain`, `Stuck`) |
| `Assets/GTA/Scripts/CarDamage.cs` | Damage of the proxies (added at runtime by `MakeProxy`): dents the body mesh at each impact (> 2 m/s along the normal, vertices pushed toward the centre, crumple, darker vertex colors), smoke from the hood past `damage` 1 (black at 2.5), one shared particle system, `M_Smoke` / `T_Smoke` (`Tools/texture/smoke.py`); `Repair()` on attach. The player's car has none |
| `Assets/GTA/Scripts/TrafficCar.cs`, `TrafficProxy.cs` | Baked car model asset (combined body, wheels, paints, proxy prefab); collision forwarder |
| `Assets/GTA/Editor/TrafficBuild.cs` | Menus **GTA > Build Traffic Cars** and **GTA > Setup Traffic In Open Scene** |
| `Assets/GTA/Traffic/` | Built: `<Car>.asset`, `<Car>_Body/_Wheel0..3.asset`, `M_<Car>_<Paint>(.mat / _Glass.mat)`, `M_<Car>_<Interior>` |
| `Assets/GTA/Prefabs/Traffic/<Car>_Traffic.prefab` | Proxy: rigidbody (car mass) + box + combined body + 4 wheels |
| `Tools/texture/car_paint.py` | `T_<Atlas>.png` -> `T_<Atlas>_<Paint>.png` (body paint found in the atlas: hue window or white body minus the small bright islands such as rims; lights, chrome, glass, tires kept) |
| `Tools/citygen/cars.py` `export_car(name, traffic=True)` | `Art/Cars/<Name>.blend` -> `Assets/GTA/Cars/Traffic/<Name>.fbx` + `T_<material>.png` |
| `Assets/GTA/Cars/Traffic/` | Traffic models (W123 without interior, W110, S5, R5Turbo, Chevelle69, TS35 bus); the player's W123i (with interior) stays out of the traffic |

## Lane graph (Python, `traffic_graph`)

- One polyline per lane in travel order. Drive on the right: right-side `lane` strips run A->B, left-side B->A,
  one-way edges (ramps) A->B with the two half lanes merged into one centre lane.
- Tapered lanes (`highway(aux)`): a lane exists where its width >= 2 m; it starts / ends on its neighbour lane
  (smoothstep blend <= 40 m), which is cut there. `turn` 5 = exit, 6 = merge (yields).
- Junction connectors: straight i->i (lanes counted from the centre), right = rightmost -> rightmost, left =
  innermost -> innermost, no U-turn; cubic Hermite, ~2 m samples; `arm` = signal group (0 = E-W, 1 = N-S).
- Roundabout: one lane on the outer ring (counter-clockwise), cut at every arm's exit / entry; ring segments
  `turn` 3, Hermite entries (0) / exits (1).
- Links: a lane whose last point lies within 0.6 m of another lane's first point continues into it (`next`).
  `export_traffic` reports `dead_ends` (must be 0), `km` and `parked`.
- Speeds (`lane_speed`): highway 28, rural 20, avenue 14, street 11, ramp 12.5 m/s.
- Parking spots (`parking_spots`): every >= 2 m shoulder against a sidewalk (street parking lanes), 6.5 m slots
  facing the traffic of that side, 12 m clear of the junction setbacks, 5 m from hydrants, not under decks; plus
  the stalls of the parking lots (`blocks(stalls=...)`, nose in, a quarter backed in). No extra draw from the city
  `rnd`: the city stays identical. 940 spots in CityDemo.

```python
# Blender MCP or blender -b --python (builds the city in memory, exports nothing else, ~10 s)
import sys; sys.path.insert(0, r'F:\Develop\Unity_Project\GTA PS1\Tools\citygen')
import roadnet, city_demo   # (importlib.reload both in a live Blender)
city_demo.export_traffic(r'F:\Develop\Unity_Project\GTA PS1\Assets\GTA\City\CityDemo_traffic.json')
```

Check it with a top-down PIL plot of the lanes (arrows, colored by `turn`) and the parked boxes before Unity.

## Unity: TrafficSystem

- **Population around the player (GTA style)**: up to `count` (700) cars placed within `liveRadius` (450 m), at
  most one per `laneSpacing` (45 m) of lane (so ~440 in downtown); an unseen car beyond `recycleDistance` (520 m)
  is re-placed around the player (6 per frame).
- **Quieter suburbs**: outside downtown (`CrowdSystem.downtownHalf`, inside the ring highway) a road lane holds
  `suburbTraffic` (0.35) of the downtown density (per-lane `cap`, rounded at random so short streets get one car or
  none), parked spots are taken at `parkedOccupancy` x `suburbParked` (0.4); an unseen car on a suburban lane over its
  cap (cars turning in from the busy roads) is re-placed elsewhere. A failed re-placement waits `jamTime` again. A car stuck more than `jamTime` (30 s) unseen and > 80 m away is
  re-placed too (gridlocks the player cannot see dissolve).
- Each car keeps its lane and picks its `next` on entering a lane (weights: straight 2, right 1.5, left 1, ring
  1.5, exit 0.5). Car ahead = next car on the lane, then along the `next` lanes (60 m). `Follow` = min(sqrt(v^2 +
  2 b free), free / headway). `accel` 3, `brake` 4, `hardBrake` 8, `headway` 1 s, `minGap` 1.8 m.
- **Junction entry** (`MustStop`, within 30 m of `stopAt`):
  - don't block the box: enter only if the lane after the connector has room (`RoomAfter`: cars on it + in the
    connectors feeding it, 7.1 m each);
  - signal: `Phase` per junction, random offset, cycle 2 x (green 9 + yellow 2.5 + all-red 1) s; red stops, yellow
    stops if it can, a left turner waiting at the line clears on yellow; green goes unless a conflicting connector
    is occupied before the crossing point (left turns also wait for oncoming cars within 3 s);
  - all-way stop: full stop at the line (remembered in `stopDone` until the lane changes: creeping on resets
    `stopped`, which used to loop forever and gridlock every stop-sign district), then first stopped, first gone
    (cars still arriving don't count);
  - yield / uncontrolled / merges: wait for cars on or coming to a conflicting connector; connectors and merge
    lanes yield to the other feeders of the lane they join by rank (main, ring, straight, right, left, merge).
  - waiting > 6 s at a non-signal junction: go anyway (patience).
- **Obstacles** (50 m grid): player car, wrecks, parked cars off their spot, cars moving aside, and
  `CrowdSystem.Crossing` pedestrians -> brake for anything in the corridor ahead (45 m).
- **Passing a still obstacle** (wreck, pushed parked car, player stopped mid-block): after 1.5 s behind it, more
  than 16 m before the lane end, shift aside (left or right, the smaller move, <= `maxShift` 3.8 m) when the side
  corridor (-12..+60 m) is free of cars (`SideClear`, car grid), slow while moving across, back once it is behind.
  A car aside is an obstacle for the others (oncoming ones brake). Never enters a junction aside.
- Pedestrians: at the curb they wait for a gap (`TrafficSystem.CanCross`: no car moving toward the crosswalk within
  ~3 s, none on it, none waiting > 4 s); cars brake for the ones already crossing.
- **Proxies** (`proxies` 14, `physicsDistance` 45 m): dynamic rigidbodies (car mass, no gravity, never sleep,
  discrete collisions) driven every FixedUpdate by the car's velocity + a clamped correction. Live proxies ignore
  each other. A real hit (other rigidbody, > `crashSpeed` 2.5 m/s and impulse > 0.3 x mass) or a shove > 1.5 m
  right after a contact makes a **wreck** (gravity, box down to the ground, speculative CCD, kept `wreckLifetime`
  60 s until far and unseen); the traffic car respawns out of sight. A divergence without contact (long frame:
  physics catching up) just snaps the proxy back. The static world and ragdoll limbs never wreck a car.
- **Parked cars**: `parkedOccupancy` (0.7) of the spots, random model / paint, drawn instanced (static
  matrices). Within `parkRadius` (35 m) they take a proxy from `parkPool` (`parkedProxies` 30 per model): free
  body at rest (asleep) that can be pushed, rammed, thrown; released at 1.3x the radius once asleep, keeping the
  pose it was left in (`moved` -> obstacle for traffic).
- Drawing: body (one submesh per material: paint, glass if any) per paint + 4 wheels (spin, steering from the
  lane curvature), frustum / distance (300 m) culled, no shadows: a PS1 blob quad (`BlobShadow`, `M_Blob`) under every car within `blobDistance` (120 m), proxies included. Proxied cars render themselves.

Measured (editor, 2026-10-26): ~440 moving + ~660 parked cars, 1.0-1.5 ms per frame; after 3 min with the
player parked downtown: 71 % moving, mean 35 km/h, no queue head stopped > 20 s.

## Workflow

1. New / changed traffic model (Fabien drops an FBX: take its `.blend` from his sandbox folder, the FBX path says
   where): copy it to `Art/Cars/<Name>.blend` (objects `<Name>_Body`, `<Name>_Wheel_FL/FR/RL/RR` at the wheel
   centres, one atlas material; front +X else pass `front_axis`), `cars.export_car('<Name>', traffic=True)` (Blender
   CLI: `blender -b --factory-startup --python` a script that puts `Tools/citygen` on `sys.path`), then
   `python -I Tools/texture/car_paint.py Assets/GTA/Textures/T_<Atlas>.png --preview <scratch dir>` (check the
   contact sheet: only the body paint changes) and **GTA > Build Traffic Cars** (every FBX of `Cars/Traffic`; every
   `T_<Atlas>_*.png` = a paint, the base atlas = `Base`; box from the body bounds above the wheel centres, mass
   175 kg/m2 of footprint). Add the new `<Name>.asset` to `Traffic.cars` in the scene (or re-run Setup Traffic).
   Sizes come from the box: cars keep their own length in the queues, models longer than 7 m (buses) spawn at
   0.15 weight, models longer than 6 m never park (6.5 m slots).
2. Road or block change: re-export the lane graph (above), then **GTA > Setup Traffic In Open Scene** (replaces the
   `Traffic` object with the script defaults, saves the scene). Serialized fields keep old values in the scene:
   re-run Setup after changing a default.
3. Verify in Play (from `Unity_RunCommand`), after a 3 minute soak with the player parked off the road:
   `Stats()` (moving, stuck > 60 s by reason, overlaps, proxies, wrecks, jam respawns, parked, ms), mean speed via
   `Position(i, out fwd, out speed)`, `Heads(20)` + `Chain(i)` (follows car ahead / full exit lane to the root
   cause or a cycle), the `traffic:` console lines (each wreck and its cause). Render `Camera.main` into a
   RenderTexture (move it in one command, render in the next). Crash test: place the player 14 m behind a car,
   `linearVelocity` = its speed + 14, `Time.timeScale` 0.25.

## Known limits / next

- No lane changes (except passing still obstacles), no overtaking; highway inner lanes never exit.
- Signal heads are static meshes (all lamps lit): drive the `SignalHead` lamps from `TrafficSystem.Phase`.
- One ring lane; permissive left turns; no right on red; no green waves (random offsets).
- Parked cars lose their dents once they go static again (beyond 1.3 x `parkRadius`).
- Traffic cars do not hit pedestrians (only the player's car does).
- Stop-controlled T junctions are all-way stops (the generator puts a sign on every arm).
