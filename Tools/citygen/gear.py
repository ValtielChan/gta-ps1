"""gear: what the event characters hold or wear (riot police helmet, shield, baton; protest sign), one FBX
Assets/GTA/NPC/Gear/Gear.fbx with one mesh per item. Run inside Blender (or `blender -b --python-expr`):

    import gear; gear.export()

Meshes are built in Unity axes (+Y up, +Z forward = the side facing away from the wearer) around the grip
point; NpcPrefabs.cs glues them to a bone and bakes them into the crowd body. UVs are in the "gear half" of the
character atlas (u, v in 0..1; the atlas is 512 x 256: body on the left half, gear on the right half), see REGIONS
and Tools/texture/gear_atlas.py.
"""
import math
import os

import bpy
from mathutils import Vector

import roadnet as rn

ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), '..', '..'))
OUT = os.path.join(ROOT, 'Assets', 'GTA', 'NPC', 'Gear', 'Gear.fbx')

# u0, v0, u1, v1 in the gear half (v up); same table in Tools/texture/gear_atlas.py
REGIONS = {
    'shield': (0.0, 0.0, 0.5, 1.0), 'shield_back': (0.5, 0.0, 1.0, 0.25), 'visor': (0.5, 0.25, 0.75, 0.5),
    'baton': (0.75, 0.25, 1.0, 0.5), 'helmet': (0.5, 0.5, 1.0, 1.0),
    'sign': (0.0, 0.375, 1.0, 1.0), 'sign_back': (0.0, 0.125, 1.0, 0.375), 'stick': (0.0, 0.0, 1.0, 0.125),
}


def U(x, y, z):
    """Unity point -> Blender point (export: Unity = (-x, z, -y) of Blender)."""
    return Vector((-x, -z, y))


def R(region, s, t):
    u0, v0, u1, v1 = REGIONS[region]
    return (u0 + (u1 - u0) * s, v0 + (v1 - v0) * t)


def quad(m, pts, region, st=((0, 0), (1, 0), (1, 1), (0, 1))):
    m.face([U(*p) for p in pts], 'Gear', [R(region, s, t) for s, t in st])


def box(m, c, sx, sy, sz, front, rest, back=None):
    """Box centered on c (Unity axes); +Z face gets `front` fitted, the -Z face `back` (read from behind, default
    `rest`), the rim `rest`."""
    x, y, z = c
    hx, hy, hz = sx / 2, sy / 2, sz / 2
    P = lambda i, j, k: (x + hx * i, y + hy * j, z + hz * k)
    # (each face is seen through the board from the other side: the +Z quad shows on the back, the -Z quad on the front)
    quad(m, [P(-1, -1, 1), P(1, -1, 1), P(1, 1, 1), P(-1, 1, 1)][::-1], back or rest, ((0, 0), (1, 0), (1, 1), (0, 1))[::-1])
    quad(m, [P(-1, -1, -1), P(1, -1, -1), P(1, 1, -1), P(-1, 1, -1)], front, ((1, 0), (0, 0), (0, 1), (1, 1)))
    for a, b, c_, d in ((P(-1, -1, -1), P(-1, -1, 1), P(-1, 1, 1), P(-1, 1, -1)), (P(1, -1, 1), P(1, -1, -1), P(1, 1, -1), P(1, 1, 1)),
                        (P(-1, 1, -1), P(-1, 1, 1), P(1, 1, 1), P(1, 1, -1)), (P(-1, -1, 1), P(-1, -1, -1), P(1, -1, -1), P(1, -1, 1))):
        quad(m, [a, b, c_, d], rest)


def shield(m, w=0.56, h=1.0, bulge=0.06, cols=4, t=0.012):
    """Riot shield, slightly curved around its vertical axis, convex side +Z; grip at the origin (back face)."""
    xs = [-w / 2 + w * i / cols for i in range(cols + 1)]
    zf = lambda x: bulge * (1 - (2 * x / w) ** 2)
    for i in range(cols):
        x0, x1 = xs[i], xs[i + 1]
        s0, s1 = i / cols, (i + 1) / cols
        for side, z in ((1, t), (-1, 0.0)):
            pts = [(x0, -h / 2, zf(x0) + z), (x1, -h / 2, zf(x1) + z), (x1, h / 2, zf(x1) + z), (x0, h / 2, zf(x0) + z)]
            if side > 0:   # seen from the front: u runs right to left in Unity x (mirror for the reader in front)
                quad(m, pts[::-1], 'shield', ((1 - s0, 0), (1 - s1, 0), (1 - s1, 1), (1 - s0, 1))[::-1])
            else:
                quad(m, pts, 'shield_back', ((s0, 0), (s1, 0), (s1, 1), (s0, 1)))
        for y in (-h / 2, h / 2):   # top / bottom rim
            a, b = (x0, y, zf(x0)), (x1, y, zf(x1))
            pts = [a, b, (b[0], y, b[2] + t), (a[0], y, a[2] + t)]
            quad(m, pts if y > 0 else pts[::-1], 'shield_back')
    for x in (-w / 2, w / 2):
        pts = [(x, -h / 2, 0), (x, -h / 2, t), (x, h / 2, t), (x, h / 2, 0)]
        quad(m, pts if x > 0 else pts[::-1], 'shield_back')


def ring(y, rx, rz, n, a0=0.0, a1=2 * math.pi):
    return [(rx * math.sin(a0 + (a1 - a0) * i / n), y, rz * math.cos(a0 + (a1 - a0) * i / n)) for i in range(n + 1)]


def helmet(m, n=10):
    """Riot helmet shell around the head pivot + the visor down in front (smoked, opaque at PS1 scale)."""
    rings = [(-0.09, 0.128, 0.145), (0.0, 0.138, 0.155), (0.08, 0.124, 0.14), (0.14, 0.088, 0.1), (0.175, 0.035, 0.04)]
    R_ = [ring(y, rx, rz, n) for y, rx, rz in rings]
    for k in range(len(R_) - 1):
        for i in range(n):
            a, b, c, d = R_[k][i], R_[k][i + 1], R_[k + 1][i + 1], R_[k + 1][i]
            quad(m, [a, b, c, d][::-1], 'helmet', ((i / n, k / 4), ((i + 1) / n, k / 4), ((i + 1) / n, (k + 1) / 4), (i / n, (k + 1) / 4))[::-1])
    top = R_[-1]
    for i in range(n):
        m.face([U(*top[i + 1]), U(*top[i]), U(0, 0.185, 0)], 'Gear', [R('helmet', 0.5, 1), R('helmet', 0.5, 1), R('helmet', 0.5, 1)])
    # visor: a band in front of the face, from the chin to the brow
    vn, a = 6, 1.25
    lo, hi = ring(-0.2, 0.15, 0.17, vn, -a, a), ring(0.03, 0.15, 0.175, vn, -a, a)
    for i in range(vn):
        quad(m, [lo[i], lo[i + 1], hi[i + 1], hi[i]][::-1], 'visor', ((i / vn, 0), ((i + 1) / vn, 0), ((i + 1) / vn, 1), (i / vn, 1))[::-1])
        quad(m, [lo[i], lo[i + 1], hi[i + 1], hi[i]], 'visor', ((i / vn, 0), ((i + 1) / vn, 0), ((i + 1) / vn, 1), (i / vn, 1)))


def prism(m, p0, p1, r, sides, region, rot=0.0):
    p0, p1 = Vector(p0), Vector(p1)
    ax = (p1 - p0).normalized()
    ref = Vector((1, 0, 0)) if abs(ax.x) < 0.9 else Vector((0, 0, 1))
    u = (ref - ax * ref.dot(ax)).normalized()
    w = ax.cross(u)
    ring_ = lambda c: [c + (u * math.cos(rot + 2 * math.pi * i / sides) + w * math.sin(rot + 2 * math.pi * i / sides)) * r for i in range(sides)]
    A, B = ring_(p0), ring_(p1)
    for i in range(sides):
        j = (i + 1) % sides
        quad(m, [tuple(A[j]), tuple(A[i]), tuple(B[i]), tuple(B[j])], region, ((i / sides, 0), ((i + 1) / sides, 0), ((i + 1) / sides, 1), (i / sides, 1))[::-1])
    for cap in (A, B[::-1]):
        m.face([U(*c) for c in (cap[::-1] if cap is A else cap)], 'Gear', [R(region, 0.5, 0.5)] * sides)


def baton(m):
    """Tonfa: grip at the origin, the long arm along +Y, the side handle along +Z."""
    prism(m, (0, -0.12, 0), (0, 0.48, 0), 0.02, 6, 'baton')
    prism(m, (0, 0.0, 0), (0, 0.0, 0.12), 0.015, 5, 'baton')


def sign(m):
    """Protest sign: stick from the grip (origin) up +Y, cardboard board on top, the slogan on both faces."""
    prism(m, (0, -0.25, -0.02), (0, 1.0, -0.02), 0.016, 4, 'stick', rot=math.pi / 4)
    box(m, (0, 1.02, 0), 0.72, 0.45, 0.012, 'sign', 'sign_back', back='sign')


def pave(m):
    """Thrown paving stone (granite sett), centred; plain material: drawn on its own by CrowdSystem."""
    m.box(U(0, 0, 0), Vector((1, 0)), 0.14, 0.11, 0.1, 'Concrete')


def export(path=OUT):
    col = rn.collection('Gear')
    for ob in list(col.objects):
        bpy.data.objects.remove(ob)
    objs = []
    for name, fn in (('Shield', shield), ('Helmet', helmet), ('Baton', baton), ('Sign', sign), ('Pave', pave)):
        m = rn.Mesh(name)
        fn(m)
        objs.append(m.to_object(col))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    rn.export_fbx(path, objs)
    return {o.name: len(o.data.polygons) for o in objs}
