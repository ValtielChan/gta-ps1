"""car_paint: paint variants of a car atlas for the traffic (T_<Car>.png -> T_<Car>_<Paint>.png).

    python -I Tools/texture/car_paint.py Assets/GTA/Textures/T_W123i_PS1.png

The body paint is every saturated pixel whose hue sits within HUE_TOL of the atlas' dominant hue (the W123 is
blue); those pixels get a new hue / saturation / value, everything else (chrome, glass, lights, tires, interior)
is kept. GTA > Build Traffic Cars picks up every T_<atlas>_*.png as one paint.
"""
import colorsys
import os
import sys

from PIL import Image

HUE_TOL = 28                                    # degrees
PAINTS = {                                      # name: (hue in degrees or None = keep, saturation x, value x)
    'Red': (2, 1.0, 0.85), 'White': (None, 0.05, 1.45), 'Black': (None, 0.15, 0.32), 'Beige': (42, 0.45, 1.2),
    'Green': (135, 0.7, 0.7), 'Silver': (None, 0.06, 1.0), 'Brown': (22, 0.8, 0.62),
}


def dominant_hue(px):
    hist = [0] * 36
    for r, g, b in px:
        h, s, v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
        if s > 0.3 and v > 0.2:
            hist[int(h * 36) % 36] += 1
    return (max(range(36), key=hist.__getitem__) + 0.5) * 10


def paint(src, name, hue, sat, val, ref):
    im = Image.open(src).convert('RGB')
    px = list(im.getdata())
    out = []
    for r, g, b in px:
        h, s, v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
        dh = abs((h * 360 - ref + 180) % 360 - 180)
        if s > 0.22 and dh < HUE_TOL:
            h2 = h if hue is None else hue / 360
            r, g, b = (int(min(1, c) * 255 + 0.5) for c in colorsys.hsv_to_rgb(h2, min(1, s * sat), min(1, v * val)))
        out.append((r, g, b))
    res = Image.new('RGB', im.size)
    res.putdata(out)
    dst = src[:-4] + '_' + name + '.png'
    res.save(dst)
    return dst


if __name__ == '__main__':
    src = sys.argv[1]
    ref = dominant_hue(Image.open(src).convert('RGB').getdata())
    print('paint hue %.0f deg' % ref)
    for name, (hue, sat, val) in PAINTS.items():
        print(os.path.basename(paint(src, name, hue, sat, val, ref)))
