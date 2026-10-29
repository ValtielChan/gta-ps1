"""Procedural smoke puff for the damaged traffic cars' particles (white, tinted per particle).

    python -I Tools/texture/smoke.py

T_Smoke 32 x 32 RGBA: a lumpy cloud (a few overlapping blobs + pixel noise), alpha in 4 hard steps so it reads
like a PS1 sprite once point-filtered.
"""
import os

import numpy as np
from PIL import Image

OUT = os.path.join(os.path.dirname(__file__), '..', '..', 'Assets', 'GTA', 'Textures', 'T_Smoke.png')


def main(n=32):
    rng = np.random.default_rng(3)
    y, x = np.mgrid[0:n, 0:n] / (n - 1) * 2 - 1
    d = np.zeros((n, n))
    for _ in range(6):   # lumps around the centre
        cx, cy, r = rng.uniform(-0.35, 0.35), rng.uniform(-0.35, 0.35), rng.uniform(0.35, 0.55)
        d = np.maximum(d, 1 - ((x - cx) ** 2 + (y - cy) ** 2) / r ** 2)
    d = np.clip(d + rng.uniform(-0.15, 0.15, d.shape), 0, 1)
    a = np.floor(d * 4) / 4                                  # 0, .25, .5, .75 (1 only at the dense core)
    v = 0.78 + 0.22 * d + rng.uniform(-0.06, 0.06, d.shape)   # lighter core, grainy
    img = np.dstack([v, v, v * 0.98, a])
    Image.fromarray((np.clip(img, 0, 1) * 255).astype(np.uint8)).save(OUT)


if __name__ == '__main__':
    main()
