"""Blood stain atlas for BloodFX: a realistic photo of 4 blood splatters on white (2x2) -> T_Blood.png.

    python -I Tools/texture/blood.py <source.png> [--cell 32]

Source quadrants (image order): pool, splash flying to the right, smear dragged to the right, round spatter.
White is keyed out to alpha (blood has almost no green), each splatter is trimmed, squared, turned so its
direction points up (+V, BloodFX lays stains along their direction), box-downscaled premultiplied to `cell`
pixels (16 px/m -> a 2 m stain) and its colors reduced. Atlas cells: 0 pool, 1 splash (top row), 2 smear, 3 spatter.
"""
import argparse
import os

import numpy as np
from PIL import Image

OUT = os.path.join(os.path.dirname(__file__), '..', '..', 'Assets', 'GTA', 'Textures', 'T_Blood.png')


def key_white(rgb):
    a = np.clip((255 - rgb[..., 1]) / 215.0, 0, 1)                       # green: 255 on white, ~30 in blood
    c = (rgb - (1 - a[..., None]) * 255) / np.maximum(a[..., None], 1e-3)  # un-blend the white
    return np.clip(c, 0, 255), a


def cell(rgb, a, size, turn):
    ys, xs = np.nonzero(a > 0.5)
    y0, y1, x0, x1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
    side = int(max(y1 - y0, x1 - x0) * 1.04)
    cy, cx = (y0 + y1) // 2, (x0 + x1) // 2
    sq = np.zeros((side, side, 4), np.float32)                            # premultiplied
    h, w = a.shape
    sy0, sx0 = cy - side // 2, cx - side // 2
    ya, yb, xa, xb = max(sy0, 0), min(sy0 + side, h), max(sx0, 0), min(sx0 + side, w)
    sq[ya - sy0:yb - sy0, xa - sx0:xb - sx0, :3] = rgb[ya:yb, xa:xb] * a[ya:yb, xa:xb, None]
    sq[ya - sy0:yb - sy0, xa - sx0:xb - sx0, 3] = a[ya:yb, xa:xb]
    sq = np.rot90(sq, turn)
    k = side // size
    sq = sq[:k * size, :k * size].reshape(size, k, size, k, 4).mean((1, 3))  # box filter
    alpha = sq[..., 3]
    col = sq[..., :3] / np.maximum(alpha[..., None], 1e-3)
    return np.concatenate([col, (alpha > 0.3)[..., None] * 255.0], -1)    # hard cut-out edge, thin streaks kept


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('source')
    ap.add_argument('--cell', type=int, default=32)
    args = ap.parse_args()
    rgb = np.asarray(Image.open(args.source).convert('RGB'), np.float32)
    col, a = key_white(rgb)
    h, w = a.shape
    n = args.cell
    atlas = np.zeros((2 * n, 2 * n, 4), np.float32)
    for i, turn in enumerate((0, 1, 1, 0)):                               # splash and smear: right -> up
        r, c = divmod(i, 2)
        sl = np.s_[r * h // 2:(r + 1) * h // 2, c * w // 2:(c + 1) * w // 2]
        atlas[r * n:(r + 1) * n, c * n:(c + 1) * n] = cell(col[sl], a[sl], n, turn)
    img = Image.fromarray(atlas.astype(np.uint8))
    rgb8 = img.convert('RGB').quantize(24, method=Image.Quantize.MEDIANCUT).convert('RGB')
    rgb8.putalpha(img.getchannel('A'))
    rgb8.save(OUT)
    rgb8.resize((16 * n, 16 * n), Image.NEAREST).save(os.path.splitext(args.source)[0] + '_preview.png')


if __name__ == '__main__':
    main()
