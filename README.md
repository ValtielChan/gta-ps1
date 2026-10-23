# GTA PS1

Free-roam driving in a Los Angeles–style city with a PlayStation 1 look: realistic textures degraded to chunky
pixels, simple low-poly shapes, 360p point-upscaled rendering with dither, but modern sun + hard shadows.

**Play in the browser:** https://valtielchan.github.io/gta-ps1/

Controls: `W A S D` (`Z Q S D` on AZERTY) / arrows to drive, `Space` handbrake, `R` reset the car.
Gamepad: triggers, left stick, A.

## What's inside

- `Tools/citygen/` – the whole city is generated in Blender by Python (road graph with junctions, roundabout,
  elevated ring highway with interchanges, modular buildings, street props, palms/trees with billboard LODs)
  and exported to FBX.
- `Tools/texture/` – turns realistic source images into PS1 textures (16 px/m, reduced palette).
- `Assets/GTA/` – Unity side: PS1 shader + dither pass, import rules, prop prefabs placer, arcade car.
- `Assets/Scenes/CityDemo.unity` – main scene · `DAScene.unity` – art-direction test scene.

Unity 6000.0.85f1 (URP). See `CLAUDE.md` for the pipeline details.
