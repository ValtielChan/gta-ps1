"""Outfit / face variants of the pedestrian atlas Art/NPC/man_t256.png (hero.fbx UV layout, 256 px).

  python -I Tools/texture/npc_variants.py crop <region> <out_dir>            # crop_<region>_x8.png + the API size
  python -I Tools/texture/npc_variants.py compose <Name> [--torso f.png] [--legs f.png] [--arms f.png]
                                                 [--head f.png] [--hands f.png] [--feet f.png] [--base T.png]
  python -I Tools/texture/npc_variants.py recolor <Name> [--shirt H S V] [--pants H S V] [--shoes H S V] [--base T.png]
  python -I Tools/texture/npc_variants.py tint <region> <arms_edit.png> <out.png> [--base T.png]   # skin tone follower

-> Assets/GTA/Textures/T_hero_<Name>.png (+ T_hero_<Name>_x3.png preview in $NPC_PREVIEW, default %TEMP%/npc_variants).
Woman: --base Assets/GTA/Textures/T_hero_f.png and a name starting with f_ (skins of hero_f.fbx are T_hero_f*.png).

Regions are the UV islands of hero.fbx (pixel rects, y down). An AI image edit of ONE region (crop upscaled x8,
prompt "same geometry, new garment") keeps the layout; editing the whole atlas does not. `compose` pastes the
edits back (box downscale). `tint` re-tones the skin pixels of a region (hands, arms) to match an AI skin edit of the arms, so a
skin-tone change costs two AI edits (head, arms) and keeps any sleeve (the hands API call is rejected: too small). `recolor` makes cheap palette-swap variants: H = hue shift in degrees, S and V =
multipliers, applied to the fabric pixels of the region (skin tones are spared). See .claude/skills/ps1-npc.
"""
import argparse
import os
import sys

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.normpath(os.path.join(HERE, '..', '..', 'Art', 'NPC', 'man_t256.png'))
TEX_DIR = os.path.normpath(os.path.join(HERE, '..', '..', 'Assets', 'GTA', 'Textures'))

REGIONS = {   # x0, y0, x1, y1 (pixels, y down)
    'torso': (0, 0, 144, 124),      # shirt front | shirt back, with the trouser waist at the bottom
    'legs': (0, 117, 96, 256),      # two trouser leg strips
    'arms': (95, 114, 177, 256),    # sleeve (top) + bare arm skin (bottom)
    'head': (144, 0, 256, 112),     # face, hair, neck
    'hands': (174, 150, 228, 218),
    'feet': (170, 187, 254, 256),
}
MASKS = {   # recolor targets: rects of fabric
    'shirt': [(0, 0, 144, 76), (95, 114, 177, 178)],
    'pants': [(0, 76, 144, 124), (0, 117, 96, 256)],
    'shoes': [(170, 187, 254, 256)],
}
SCALE = 8


def api_size(w, h):
    """gpt-image custom sizes: multiples of 16, aspect 1:3..3:1 - the crop is upscaled x8 to this size."""
    return (round(w * SCALE / 16) * 16, round(h * SCALE / 16) * 16)


def crop(region, out_dir, base=BASE):
    x0, y0, x1, y1 = REGIONS[region]
    im = Image.open(base).convert('RGB').crop((x0, y0, x1, y1))
    W, H = api_size(x1 - x0, y1 - y0)
    path = os.path.join(out_dir, 'crop_%s_x8.png' % region)
    im.resize((W, H), Image.LANCZOS).save(path)
    return path, '%dx%d' % (W, H)


def compose(name, edits, base=BASE):
    atlas = Image.open(base).convert('RGB')
    for region, path in edits.items():
        x0, y0, x1, y1 = REGIONS[region]
        atlas.paste(Image.open(path).convert('RGB').resize((x1 - x0, y1 - y0), Image.BOX), (x0, y0))
    return save(name, atlas)


def _hsv(im):
    hsv = np.asarray(im.convert('HSV'), dtype=np.float32)
    return hsv[..., 0] * 360 / 255, hsv[..., 1] / 255, hsv[..., 2] / 255


def _skin(im):
    h, s, v = _hsv(im)
    return (h > 5) & (h < 45) & (s > 0.15) & (s < 0.65) & (v > 0.45)


def tint(region, arms_edit, out, base=BASE):
    """Scale the region's skin pixels by the mean skin color ratio (arms edit / base arms): the sleeve stays."""
    atlas = Image.open(base).convert('RGB')
    ax0, ay0, ax1, ay1 = REGIONS['arms']
    src = atlas.crop((ax0, ay0, ax1, ay1))
    ref = np.asarray(Image.open(arms_edit).convert('RGB').resize(src.size, Image.BOX), np.float32)
    skin = _skin(src)
    ratio = ref[skin].mean(0) / np.asarray(src, np.float32)[skin].mean(0)
    crop = atlas.crop(REGIONS[region])
    px = np.asarray(crop, np.float32)
    px[_skin(crop)] *= ratio
    Image.fromarray(np.clip(px, 0, 255).astype(np.uint8)).save(out)
    return out


def recolor(name, shifts, base=BASE):
    im = Image.open(base).convert('RGB')
    h, s, v = _hsv(im)
    skin = _skin(im)   # spare the collar / arm skin
    for target, (dh, ms, mv) in shifts.items():
        m = np.zeros(h.shape, bool)
        for x0, y0, x1, y1 in MASKS[target]:
            m[y0:y1, x0:x1] = True
        m &= ~skin if target != 'shoes' else m
        h[m] = (h[m] + dh) % 360
        s[m] = np.clip(s[m] * ms, 0, 1)
        v[m] = np.clip(v[m] * mv, 0, 1)
    out = np.stack([h * 255 / 360, s * 255, v * 255], -1).astype(np.uint8)
    return save(name, Image.fromarray(out, 'HSV').convert('RGB'))


PREVIEW_DIR = os.environ.get('NPC_PREVIEW', os.path.join(os.environ.get('TEMP', '.'), 'npc_variants'))


def save(name, atlas):
    """-> Assets/GTA/Textures/T_hero_<name>.png (+ x3 preview in $NPC_PREVIEW, never next to the assets)."""
    os.makedirs(TEX_DIR, exist_ok=True)
    os.makedirs(PREVIEW_DIR, exist_ok=True)
    path = os.path.join(TEX_DIR, 'T_hero_%s.png' % name)
    atlas.save(path)
    atlas.resize((768, 768), Image.NEAREST).save(os.path.join(PREVIEW_DIR, 'T_hero_%s_x3.png' % name))
    return path


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest='cmd', required=True)
    c = sub.add_parser('crop'); c.add_argument('region', choices=REGIONS); c.add_argument('out_dir'); c.add_argument('--base', default=BASE)
    p = sub.add_parser('compose'); p.add_argument('name'); p.add_argument('--base', default=BASE)
    for r in REGIONS:
        p.add_argument('--' + r)
    q = sub.add_parser('recolor'); q.add_argument('name'); q.add_argument('--base', default=BASE)
    for t in MASKS:
        q.add_argument('--' + t, nargs=3, type=float, metavar=('H', 'S', 'V'))
    t = sub.add_parser('tint'); t.add_argument('region', choices=REGIONS); t.add_argument('arms_edit'); t.add_argument('out'); t.add_argument('--base', default=BASE)
    a = ap.parse_args()
    if a.cmd == 'crop':
        print(*crop(a.region, a.out_dir, a.base))
    elif a.cmd == 'tint':
        print(tint(a.region, a.arms_edit, a.out, a.base))
    elif a.cmd == 'compose':
        print(compose(a.name, {r: getattr(a, r) for r in REGIONS if getattr(a, r)}, a.base))
    else:
        print(recolor(a.name, {t: getattr(a, t) for t in MASKS if getattr(a, t)}, a.base))


if __name__ == '__main__':
    main()
