---
name: chatgpt-images
description: Generate textures, sprites, decals, reference images or concept art through ChatGPT (image generation) driven with Playwright, then convert them to PS1 textures. Use whenever the project needs a new image asset (asphalt, sidewalk, facades, windows, signs, car skins, transparent decals...).
---

# ChatGPT image generation via Playwright

The user is logged in to chatgpt.com in the Playwright browser (`mcp__playwright__*`). If the page shows a
login button, ask the user to log in in that window and wait.

## Generate

1. `browser_navigate https://chatgpt.com/` (new chat for each asset family; reuse a chat to iterate).
2. `browser_snapshot` → find the textbox "Demander à ChatGPT", `browser_type` with `submit: true`.
3. **Busy indicator = the composer button `button[aria-label="Arrêter"]`** (there is no `stop-button` testid). It
   can vanish for a moment between "réflexion" and "esquisse", and a half-rendered "Aperçu" image is already in the
   DOM, so a download must wait for: not busy **and** a last image visually different from the one before the prompt.
   - Send (`browser_run_code_unsafe`): wait while busy, store the 8x8 signature of the last image in
     `window.__prevSig`, fill the textbox, press Enter, check it became busy (else it was not sent):
     `async (page) => { const box = page.getByRole('textbox', { name: 'Demander à ChatGPT' }); const busy = async () => (await page.locator('button[aria-label="Arrêter"]').count()) > 0; for (let i = 0; i < 60 && await busy(); i++) await page.waitForTimeout(3000); await page.evaluate(() => { const img = [...document.querySelectorAll('main img')].filter(i => i.alt.startsWith('Image générée')).pop(); if (!img) return; const c = document.createElement('canvas'); c.width = c.height = 8; c.getContext('2d').drawImage(img, 0, 0, 8, 8); window.__prevSig = Array.from(c.getContext('2d').getImageData(0, 0, 8, 8).data).map(v => v >> 5).join(''); }); await box.fill(PROMPT); await box.press('Enter'); await page.waitForTimeout(3000); return (await busy()) ? 'sent' : 'NOT SENT'; }`
   - Download (`browser_evaluate` + `filename: "raw_<Name>.b64.txt"`, lands in the project root – move it out),
     polls up to 170 s:
     `async () => { const busy = () => !!document.querySelector('button[aria-label="Arrêter"]'); const sig = img => { const c = document.createElement('canvas'); c.width = c.height = 8; c.getContext('2d').drawImage(img, 0, 0, 8, 8); return Array.from(c.getContext('2d').getImageData(0, 0, 8, 8).data).map(v => v >> 5).join(''); }; const prev = window.__prevSig; const t0 = Date.now(); while (Date.now() - t0 < 170000) { const img = [...document.querySelectorAll('main img')].filter(i => i.alt.startsWith('Image générée')).pop(); if (!busy() && img && img.complete && img.naturalWidth > 0 && sig(img) !== prev) { await new Promise(r => setTimeout(r, 2500)); if (busy()) continue; window.__prevSig = sig(img); const b = await (await fetch(img.src)).blob(); return await new Promise(r => { const f = new FileReader(); f.onload = () => r(f.result); f.readAsDataURL(b); }); } await new Promise(r => setTimeout(r, 3000)); } return 'TIMEOUT'; }`
   - Always look at a 256 px review image before installing: getting the previous image does happen.
4. One chat per asset family, two tabs in parallel (alternate send / download between tabs).
5. **When done, delete the conversations you created** (Fabien's request): open the chat, "…" menu (top
   right) → Supprimer → confirm. Never touch his other conversations.

## Prompt template (French works well)

**Always ask for a REALISTIC photo texture.** The PS1 look comes only from `ps1ify.py` (downscale + palette),
exactly like 90s artists reducing real textures for the hardware. Never write "PS1", "pixel art", "basse
résolution" or "stylisé" in a prompt: it produces cartoon textures.

Chat opener (style brief, once per chat):
> On crée les textures sources d'un jeu se déroulant à Los Angeles. Chaque image est une photo-texture
> réaliste haute définition (comme une bibliothèque de textures photo type textures.com) : matériaux réels,
> couleurs naturelles, éclairage diffus et uniforme sans ombre portée, vue parfaitement orthogonale (de face ou
> de dessus), aucune perspective, pas de stylisation, pas de pixel art. Noms de commerces inventés.

Then: "Image suivante : <matière / objet>, tileable seamless, image carrée."
- Transparent assets (signs, decals, foliage cards, bench, props): add "sur fond TRANSPARENT (PNG avec canal
  alpha, pas de fond blanc ni damier)".
- Facades: "exactement 4 m de large × 4 m de haut (UN étage)", "bords gauche/droite raccordables", "pas de trottoir".
- Objects mapped on a few quads (bench, signal head): "vu exactement de face, remplit toute l'image".
- Ask for variations in the same chat to keep a coherent set, and **name the exact wall** of the family in every
  prompt of a family ("le même mur en briques ROUGE-BRUN avec le même soubassement..."). Then convert the family
  with `Tools/texture/facades.py` (color transfer onto the reference bay): never ship a bay that does not match.

## Convert to a PS1 texture

```
python -I Tools/texture/ps1ify.py <name>.b64.txt Assets/GTA/Textures/T_<Name>.png [--size 64] [--colors 32] [--trim] [--seamless] --preview
```
- `--size`: from the texel density rule (16 px/m): 64 for a 4 m tile (default), 32 for 2 m, 128 for 8 m.
- `--trim`: crop a cut-out object to its opaque bounding box (the mesh restores the aspect).
- `--match T_Ref.png`: shift the colors so the wall seen on the side strips matches the reference (families).
- `--crop x0 y0 x1 y1` (fractions) to cut what the model added around the tile (e.g. a sidewalk strip under a
  shopfront: `--crop 0 0 1 0.875`).
- `--seamless` only if the raw image does not tile (check the `_tile.png` preview first without it; the
  cross-fade softens contrast).
- Read the `_tile.png` preview (then move it out of Assets): seams, repetition, pixel size, average color close
  to the matching `roadnet.COLORS` entry.
- `Assets/GTA/Editor/ImportRules.cs` sets point filter + no compression for `Assets/GTA/Textures/`.

## Existing textures (64 px per 4 m unless noted; raw sources kept in the session scratchpad `raw/`)

| Group | Textures |
|---|---|
| Ground | Asphalt, Sidewalk (3x3 slabs), Grass (dry), Dirt (mulch), Concrete (also curbs via `Concrete__Curb`), Roof, Shingles, TileRoof (roofs) |
| Facade families (4 m bay = 1 floor, converted by `Tools/texture/facades.py`) | red brick: BrickBay, Brick, BrickGround, BrickEntry, BrickService · buff brick: BrickBayB, BrickB, BrickBService · white stucco (tintable): AptBay, Stucco, StuccoBay, SpanishBay, AptEntry, AptGround, StuccoService · granite: OfficeGround, OfficeLobby, GraniteService, GraniteGarage · deco: DecoBay, DecoEntry, DecoWall · OfficeBay, ConcreteBay, GlassBay |
| Storefronts (4 m) | Shopfront (`--crop 0 0 1 0.875`), ShopDonuts, ShopLaundry, ShopLiquor, ShopTacos, ShopPharmacy, ShopBarber, ShopPawn, ShopNails, ShopPizza, ShopPhone, ShopBurger, ShopCafe, ShopMercado, ShopVideo, ShopChinese, ShopCheck · 8 m × 4 m (`--crop 0 0 1 1 --width 128`): ShopMarket, ShopBank |
| Fabrics / roof | AwningStripes (red/white), AwningGreen, AwningBlue, Awning (neutral, `__Green`/`__Blue`/`__Wine`), ACUnit (32), WaterTank |
| Metals | PoleMetal (galvanized; `__Dark` tint), SignalMetal (yellow, `__Aged` tint on signals), MetalPaint (legacy neutral) |
| Props (fitted photos) | Bench (64, `--trim`), Mailbox (32, `--trim`) + MailboxSide, NewsBoxFront (32) + NewsBoxSide, ParkingMeter (32), TrashCan (32, unrolled side, `wrap=True`), BusStopAd (32), BusStopGlass, SignalHead (32, `--trim`), LampLens (32, `--trim`, arm end at the bottom) |
| Signs | StopSign (32), YieldSign (32, `--trim`), StreetSign (atlas of 4 rows), ExitSign (128, `--trim`) |
| Vegetation (alpha) | LeafCard, PalmFrond (fan, stem at bottom), GrassTuft (32); Bark, PalmTrunk |
| Houses (`kit.HOUSES`, one floor = 4 m wide bay; 3 m floors use 64x48 bays: `--crop 0 0.2 1 0.95 --width 64 --size 48`) | siding (neutral, tintable `Siding__<Tint>`): Siding, SidingBay, SidingDoor, SidingGarage · ranch (painted brick): Ranch, RanchBay, RanchDoor, RanchGarage · mansion (cream stucco + stone plinth): Mansion, MansionBay, MansionEntry, MansionGarage · Picket (32x16, alpha: crop the source to its opaque band, a transparent margin makes the fence float) · WoodFence (32x32 for 2 m x 1.8 m) |
| Procedural / derived | MarkThin/Wide/Bar (`Tools/texture/marks.py`), `T_Leaves` (LeafCard composited 4x on dark green), `T_Imp_*` (`kit.render_impostor`) |

The first batch (ground, facades, vegetation, signs) came from stylized prompts before the "realistic source"
rule; Fabien judged them fine once degraded - keep them.
