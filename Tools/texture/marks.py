"""Procedural road-marking decal textures (white, neutral: yellow comes from a material tint).

    python -I Tools/texture/marks.py

Each texture spans the full decal strip across (U) and 4 m along (V) at 16 px/m, like the asphalt:
  T_MarkThin  4 x 64  -> 0.25 m strip, ~0.125 m paint (lane lines, edge lines, double yellow)
  T_MarkWide  8 x 64  -> 0.5 m strip,  ~0.375 m paint (stop lines)
  T_MarkBar  16 x 64  -> 1.0 m strip,  ~0.625 m paint (crosswalk bars)
Paint edges are ragged at the pixel level, the paint is not a flat color and has a little wear,
so marks sit in the road like the rest of the textures (see ps1-art-direction).
"""
import os

import numpy as np
from PIL import Image

OUT = os.path.join(os.path.dirname(__file__), '..', '..', 'Assets', 'GTA', 'Textures')


def mark(width, paint, rng, rows=64):
    lo = (width - paint) / 2
    img = np.zeros((rows, width, 4), np.uint8)
    for y in range(rows):
        a, b = lo + rng.uniform(-0.3, 0.3), lo + paint + rng.uniform(-0.3, 0.3)   # slightly ragged edges
        for x in range(width):
            cov = min(x + 1, b) - max(x, a)            # pixel coverage of the paint band
            if cov <= rng.uniform(0.4, 0.6) or rng.random() < 0.015:   # partial pixels + rare wear holes
                continue
            v = rng.uniform(0.82, 0.96) - (0.1 if rng.random() < 0.1 else 0)  # nuance + grime specks
            img[y, x] = (int(v * 255), int(v * 252), int(v * 240), 255)
    return Image.fromarray(img)


def main():
    rng = np.random.default_rng(7)
    for name, w, p in (('MarkThin', 4, 2.0), ('MarkWide', 8, 6.0), ('MarkBar', 16, 10.0)):
        mark(w, p, rng).save(os.path.join(OUT, 'T_%s.png' % name))


if __name__ == '__main__':
    main()
