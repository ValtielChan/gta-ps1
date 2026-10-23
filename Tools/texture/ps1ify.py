"""Turn a generated image into a PS1 texture: square crop, optional seamless tiling,
box downscale to the target size, palette reduction.

  python Tools/texture/ps1ify.py <in.png | in.b64.txt> <out.png> [--size 64] [--colors 32] [--seamless] [--preview]
         [--crop x0 y0 x1 y1]   (fractions of the source, e.g. 0 0 1 0.88 drops the bottom 12 %)
         [--trim]               (crop to the opaque bounding box of a cut-out object; --size is then the
                                 longest side and the aspect ratio is kept, so pixels stay square)

<in.b64.txt> is what the Playwright `browser_evaluate(filename=...)` export of a data: URL looks like.
--preview also writes <out>_tile.png (2x2 tiling, nearest x4) to eyeball seams and pixel size.
See .claude/skills/chatgpt-images and ps1-art-direction.
"""
import argparse
import base64
import io
import json

import numpy as np
from PIL import Image


def load(path):
    if path.endswith('.txt'):
        s = open(path, encoding='utf-8').read().strip()
        if s.startswith('"'):
            s = json.loads(s)
        return Image.open(io.BytesIO(base64.b64decode(s.split(',', 1)[-1])))
    return Image.open(path)


def seamless(img):
    """Cross-fade with a half-offset copy: the copy's seams sit where the original is opaque."""
    a = np.asarray(img, dtype=np.float32)
    h, w = a.shape[:2]
    rolled = np.roll(a, (h // 2, w // 2), axis=(0, 1))
    wy = 1 - np.abs(np.linspace(-1, 1, h))
    wx = 1 - np.abs(np.linspace(-1, 1, w))
    m = np.clip(np.minimum.outer(wy, wx) * 3, 0, 1)[..., None]
    return Image.fromarray((a * m + rolled * (1 - m)).astype(np.uint8))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('src'); ap.add_argument('dst')
    ap.add_argument('--size', type=int, default=64)   # 16 px/m for a 4 m tile (ps1-art-direction)
    ap.add_argument('--colors', type=int, default=32)
    ap.add_argument('--seamless', action='store_true')
    ap.add_argument('--preview', action='store_true')
    ap.add_argument('--crop', type=float, nargs=4)
    ap.add_argument('--trim', action='store_true')
    a = ap.parse_args()

    img = load(a.src)
    alpha = img.mode in ('RGBA', 'LA') or 'transparency' in img.info
    img = img.convert('RGBA' if alpha else 'RGB')
    if a.trim and alpha:   # object card: keep only the object, the mesh restores its aspect ratio
        img = img.crop(img.getchannel('A').point(lambda v: 255 if v > 127 else 0).getbbox())
    elif a.crop:   # explicit crop, then stretched back to a square
        x0, y0, x1, y1 = a.crop
        img = img.crop((round(x0 * img.width), round(y0 * img.height), round(x1 * img.width), round(y1 * img.height)))
    else:
        s = min(img.size)
        img = img.crop(((img.width - s) // 2, (img.height - s) // 2, (img.width + s) // 2, (img.height + s) // 2))
    if a.seamless:
        img = seamless(img)
    w, h = (a.size, a.size)
    if a.trim and alpha:
        k = a.size / max(img.size)
        w, h = max(2, round(img.width * k)), max(2, round(img.height * k))
    img = img.resize((w, h), Image.BOX)
    if alpha:
        rgb, al = img.convert('RGB'), img.getchannel('A').point(lambda v: 255 if v > 127 else 0)
        rgb = rgb.quantize(a.colors, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE).convert('RGB')
        img = Image.merge('RGBA', (*rgb.split(), al))
    else:
        img = img.quantize(a.colors, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE).convert('RGB')
    img.save(a.dst)
    if a.preview:
        t = Image.new(img.mode, (w * 2, h * 2))
        for x in (0, w):
            for y in (0, h):
                t.paste(img, (x, y))
        t.resize((w * 8, h * 8), Image.NEAREST).save(a.dst[:-4] + '_tile.png')


if __name__ == '__main__':
    main()
