"""car_paint: paint variants of a car atlas for the traffic (T_<Car>.png -> T_<Car>_<Paint>.png).

    python -I Tools/texture/car_paint.py Assets/GTA/Textures/T_W123_PS1.png [--preview <dir>]

The body paint is found in the atlas itself:
- a colored car (W123 blue, W110 burgundy): the hue window grown around the dominant hue of the saturated pixels
  (neighbouring 10-degree bins holding >= 5 % of the peak), minus pixels much brighter than the paint (red tail
  lights on a red car); those pixels get a new hue / saturation / value, relative to the paint's median (PAINTS are
  tuned on the light blue W123: a dark burgundy W110 gets the same light colors);
- a white car (the bus: more bright grey pixels than in the hue window): the bright, unsaturated pixels, tinted.
Everything else (chrome, glass, lights, tires, interior) is kept. GTA > Build Traffic Cars picks up every
T_<atlas>_*.png as one paint.
"""
import argparse
import os

import numpy as np
from PIL import Image
from scipy import ndimage

PAINTS = {                                      # name: (hue in degrees or None = keep, saturation x, value x)
    'Red': (2, 1.0, 0.85), 'White': (None, 0.05, 1.45), 'Black': (None, 0.15, 0.32), 'Beige': (42, 0.45, 1.2),
    'Green': (135, 0.7, 0.7), 'Silver': (None, 0.06, 1.0), 'Brown': (22, 0.8, 0.62),
}
REF_S, REF_V = 0.54, 0.75                       # median saturation / value of the W123 paint (PAINTS tuned on it)
WHITE_SAT = 0.6                                 # saturation a white body takes for a paint of saturation x 1


def hsv_of(rgb):
    hsv = np.asarray(Image.fromarray(rgb).convert('HSV'), np.float32) / 255
    return hsv[..., 0] * 360, hsv[..., 1], hsv[..., 2]


def paint_mask(h, s, v):
    """mask of the body paint, True for a white body"""
    chroma = (s > 0.3) & (v > 0.2)
    hist = np.histogram(h[chroma], bins=36, range=(0, 360))[0]
    peak = int(hist.argmax())
    bins = {peak}
    for step in (1, -1):
        b = (peak + step) % 36
        while hist[b] >= 0.02 * hist[peak] and b not in bins:
            bins.add(b)
            b = (b + step) % 36
    in_hue = np.isin((h // 10).astype(int) % 36, list(bins)) & (s > 0.12)
    white = (s < 0.15) & (v > 0.55)
    if white.sum() > in_hue.sum():
        # the chrome rims are bright and unsaturated too: keep only the big patches (body panels), drop the
        # small islands (rims, trim, badges)
        labels, n = ndimage.label(white)
        sizes = ndimage.sum(white, labels, range(1, n + 1))
        keep = np.zeros(n + 1, bool)
        keep[1:] = sizes >= 0.1 * white.sum()
        return keep[labels], True
    cap = np.percentile(v[in_hue & chroma], 90) * 1.5   # lights are far brighter than the paint around them
    return in_hue & (v <= cap), False


def paint(rgb, mask, is_white, hue, sat, val):
    h, s, v = hsv_of(rgb)
    if is_white:
        h2, s2 = np.full_like(h, hue or 0), np.full_like(s, min(1, WHITE_SAT * sat) if hue is not None else 0)
    else:
        h2, s2 = (h if hue is None else np.full_like(h, hue)), np.minimum(1, s * sat * REF_S / np.median(s[mask]))
        med = np.median(v[mask])
        # brought to the W123's brightness, the reflections of a dark paint flattened on the way (else the dark
        # burgundy W110 turns into rusty streaks)
        v = REF_V * (v / med) ** min(1, (med / REF_V) ** 0.5)
    v2 = np.minimum(1, v * val)
    hsv = np.stack([h2 / 360 * 255, s2 * 255, v2 * 255], -1).round().clip(0, 255).astype(np.uint8)
    out = np.asarray(Image.merge('HSV', [Image.fromarray(hsv[..., k]) for k in range(3)]).convert('RGB'))
    return np.where(mask[..., None], out, rgb)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('atlas')
    ap.add_argument('--preview', help='also write a contact sheet of the base and every paint there')
    args = ap.parse_args()
    rgb = np.asarray(Image.open(args.atlas).convert('RGB'))
    mask, is_white = paint_mask(*hsv_of(rgb))
    print('%s body, %.0f %% of the atlas painted' % ('white' if is_white else 'colored', 100 * mask.mean()))
    sheet = [rgb]
    for name, (hue, sat, val) in PAINTS.items():
        if is_white and hue is None and val >= 1:   # white / silver of a white car: the base already
            continue
        out = paint(rgb, mask, is_white, hue, sat, val)
        dst = args.atlas[:-4] + '_' + name + '.png'
        Image.fromarray(out).save(dst)
        sheet.append(out)
        print(os.path.basename(dst))
    if args.preview:
        Image.fromarray(np.concatenate(sheet, 1)).save(os.path.join(args.preview, os.path.basename(args.atlas)[:-4] + '_paints.png'))


if __name__ == '__main__':
    main()
