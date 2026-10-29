"""Atlases of the event characters (protesters, riot police): 512 x 256, the pedestrian atlas on the left half
(hero.fbx UV layout, see npc_variants.py), the gear on the right half (UV regions of Tools/citygen/gear.py).

  python -I Tools/texture/gear_atlas.py <raw dir>

<raw dir> holds the generated sources (scratchpad):
  signs1.png, signs2.png, signs3.png   2 x 2 sheets of protest signs on a grey floor (12 slogans)
  shield.png                           riot shield, front-on, dark background
  mats.png                             3 x 2 swatches: helmet shell, visor, baton rubber / cardboard, wood, shield back
  edit_crs_torso.png, _arms, _legs     AI edits of the pedestrian atlas regions (npc_variants.py crop ...)
->  Assets/GTA/Textures/T_crs.png                    riot police (CRS) uniform + helmet, shield, baton
    Assets/GTA/Textures/T_demo_NN.png / T_demo_f_NN  protester: a pedestrian outfit (man / woman) + sign NN
"""
import glob
import os
import sys

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from npc_variants import REGIONS as BODY  # noqa: E402

TEX = os.path.normpath(os.path.join(HERE, '..', '..', 'Assets', 'GTA', 'Textures'))
G = 256   # gear half size
GEAR = {   # u0, v0, u1, v1 (v up), = gear.REGIONS
    'shield': (0.0, 0.0, 0.5, 1.0), 'shield_back': (0.5, 0.0, 1.0, 0.25), 'visor': (0.5, 0.25, 0.75, 0.5),
    'baton': (0.75, 0.25, 1.0, 0.5), 'helmet': (0.5, 0.5, 1.0, 1.0),
    'sign': (0.0, 0.375, 1.0, 1.0), 'sign_back': (0.0, 0.125, 1.0, 0.375), 'stick': (0.0, 0.0, 1.0, 0.125),
}
MATS = {'helmet': (0, 0), 'visor': (1, 0), 'baton': (2, 0), 'sign_back': (0, 1), 'stick': (1, 1), 'shield_back': (2, 1)}


def rect(region):
    u0, v0, u1, v1 = GEAR[region]
    return int(u0 * G), int((1 - v1) * G), int(u1 * G), int((1 - v0) * G)


def put(half, region, img):
    x0, y0, x1, y1 = rect(region)
    half.paste(img.convert('RGB').resize((x1 - x0, y1 - y0), Image.BOX), (x0, y0))


def swatch(mats, key, inset=0.06):
    i, j = MATS[key]
    w, h = mats.width / 3, mats.height / 2
    return mats.crop((int((i + inset) * w), int((j + inset) * h), int((i + 1 - inset) * w), int((j + 1 - inset) * h)))


def signs(sheet):
    """The 4 signs of a 2 x 2 sheet: per quadrant, the bounding box of what differs from the grey floor."""
    a = np.asarray(sheet.convert('RGB')).astype(int)
    H, W = a.shape[:2]
    out = []
    for qy in range(2):
        for qx in range(2):
            q = a[qy * H // 2:(qy + 1) * H // 2, qx * W // 2:(qx + 1) * W // 2]
            floor = np.median(q[:8].reshape(-1, 3), 0)
            m = np.abs(q - floor).sum(-1) > 60
            rows, cols = np.where(m.mean(1) > 0.4)[0], np.where(m.mean(0) > 0.4)[0]
            y0, y1, x0, x1 = rows[0], rows[-1], cols[0], cols[-1]
            dy, dx = (y1 - y0) // 25, (x1 - x0) // 50   # keep inside the board edge
            box = (qx * W // 2 + x0 + dx, qy * H // 2 + y0 + dy, qx * W // 2 + x1 - dx, qy * H // 2 + y1 - dy)
            out.append(sheet.crop(box))
    return out


def palette(img, colors=48):
    return img.quantize(colors, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE).convert('RGB')


def atlas(body, half):
    out = Image.new('RGB', (2 * G, G))
    out.paste(body.convert('RGB'), (0, 0))
    out.paste(palette(half), (G, 0))
    return out


def crs_body(raw):
    body = Image.open(os.path.join(TEX, 'T_hero.png')).convert('RGB')
    for region in ('torso', 'arms', 'legs'):
        x0, y0, x1, y1 = BODY[region]
        body.paste(Image.open(os.path.join(raw, 'edit_crs_%s.png' % region)).convert('RGB').resize((x1 - x0, y1 - y0), Image.BOX), (x0, y0))
    a = np.asarray(body).astype(float)
    for region, k in (('hands', 0.18), ('feet', 0.35)):   # black gloves, black boots
        x0, y0, x1, y1 = BODY[region]
        if region == 'feet':
            x0, y0 = 170, 187
        a[y0:y1, x0:x1] = a[y0:y1, x0:x1].mean(-1, keepdims=True) * k + np.array([4, 5, 9])
    return Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))


def main(raw):
    mats = Image.open(os.path.join(raw, 'mats.png')).convert('RGB')
    # riot police
    half = Image.new('RGB', (G, G))
    s = Image.open(os.path.join(raw, 'shield.png')).convert('RGB')
    put(half, 'shield', s.crop((int(0.12 * s.width), int(0.01 * s.height), int(0.88 * s.width), int(0.985 * s.height))))
    for k in ('helmet', 'visor', 'baton', 'shield_back'):
        put(half, k, swatch(mats, k))
    atlas(crs_body(raw), half).save(os.path.join(TEX, 'T_crs.png'))
    # protesters: sign n with man outfit n % men, woman outfit n % women
    all_signs = [sg for f in sorted(glob.glob(os.path.join(raw, 'signs*.png'))) for sg in signs(Image.open(f))]
    men = sorted(p for p in glob.glob(os.path.join(TEX, 'T_hero*.png')) if not os.path.basename(p).startswith('T_hero_f'))
    women = sorted(glob.glob(os.path.join(TEX, 'T_hero_f*.png')))
    for old in glob.glob(os.path.join(TEX, 'T_demo_*.png')):
        os.remove(old)
    for n, sg in enumerate(all_signs):
        half = Image.new('RGB', (G, G))
        put(half, 'sign', sg)
        put(half, 'sign_back', swatch(mats, 'sign_back'))
        put(half, 'stick', swatch(mats, 'stick').rotate(90, expand=True))
        atlas(Image.open(men[n % len(men)]), half).save(os.path.join(TEX, 'T_demo_%02d.png' % n))
        atlas(Image.open(women[(n * 5) % len(women)]), half).save(os.path.join(TEX, 'T_demo_f_%02d.png' % n))
    print('T_crs + %d signs (%d men, %d women outfits)' % (len(all_signs), len(men), len(women)))


if __name__ == '__main__':
    main(sys.argv[1])
