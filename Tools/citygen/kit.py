"""kit: art-direction asset kit (California city) - modular buildings, street props, vegetation.

Every builder returns a roadnet.Mesh in local space: origin on the ground, front facing -Y, meters.
UVs follow the texel rule (1 UV = 4 m) except fitted cards (signs, fronds, billboards).
Material names follow the Unity contract: 'Foo' -> T_Foo.png, 'Foo__Tint' -> T_Foo.png x tint.
"""
import math
import os
import subprocess

import bpy

import roadnet as rn
from roadnet import V, Mesh

FLOOR = 4.0   # one floor = one 4 m texture row

TINTS = {'Beige': (0.95, 0.85, 0.70), 'Pink': (0.98, 0.78, 0.72), 'Peach': (1.0, 0.86, 0.70),
         'Mint': (0.82, 0.93, 0.84), 'Sky': (0.84, 0.90, 0.98), 'White': (1, 1, 1)}
TINTABLE = ('Stucco', 'StuccoBay', 'AptBay', 'AptEntry', 'AptGround', 'SpanishBay', 'StuccoService')   # neutral white textures
rn.COLORS.update({'%s__%s' % (b, t): c for b in TINTABLE for t, c in TINTS.items()})
rn.COLORS.update({
    'Leaves__Bush': (0.75, 0.85, 0.70), 'LeafCard__Bush': (0.75, 0.85, 0.70),
    'PalmTrunk__Dark': (0.55, 0.45, 0.35), 'PoleMetal__Dark': (0.30, 0.30, 0.32),
    'Awning__Green': (0.35, 0.62, 0.42), 'Awning__Blue': (0.38, 0.52, 0.80), 'Awning__Wine': (0.62, 0.24, 0.26),
})


def grime(lo=0.65, h=2.5, base=0.0):
    """Vertex shade: darker near the ground (dirt, fake AO), full brightness above h."""
    return lambda p: lo + (1 - lo) * rn.clamp((p.z - base) / h)


def oface(m, pts, mat, center, uvs=None):
    """Face whose normal points away from `center` (blobs, irregular shapes)."""
    n = (pts[1] - pts[0]).cross(pts[2] - pts[0])
    if n.dot(sum(pts, V(0, 0, 0)) / len(pts) - center) < 0:
        pts = pts[::-1]
        uvs = uvs[::-1] if uvs else None
    m.face(pts, mat, uvs)


# ------------------------------------------------------------------ buildings
SHOPS = ('Shopfront', 'ShopDonuts', 'ShopLaundry', 'ShopLiquor', 'ShopTacos', 'ShopPharmacy', 'ShopBarber',
         'ShopPawn', 'ShopNails', 'ShopPizza', 'ShopPhone', 'ShopBurger', 'ShopCafe', 'ShopMercado', 'ShopVideo',
         'ShopChinese', 'ShopCheck')   # 4 m x 4 m storefronts, sign band 2.7-3.9 m
WIDE_SHOPS = ('ShopMarket', 'ShopBank')   # 8 m x 4 m: a whole store front
AWNINGS = ('AwningStripes', 'AwningGreen', 'AwningBlue', 'Awning__Green', 'Awning__Blue', 'Awning__Wine')
_last_shops = []


def next_shop(rnd, pool=SHOPS):
    """Random storefront, never one of the last 3 used (no shop twice in a row, little visible repetition)."""
    shop = rnd.choice([s for s in pool if s not in _last_shops[-3:]])
    _last_shops.append(shop)
    return shop


STYLES = {
    # One material family per building (textures color-matched by Tools/texture/facades.py): upper floor bay,
    # wall (blind walls / parapet), entry / ground (ground-floor bays), service door and garage in the same material.
    # prog: ground-floor program (ground_program); tints: random tint of the neutral stucco textures.
    'strip':     dict(upper=None, wall='Stucco', entry=None, ground=None, service='StuccoService', garage=None,
                      prog='shops', tints=('Beige', 'White', 'Peach', 'Pink')),
    'apartment': dict(upper='AptBay', wall='Stucco', entry='AptEntry', ground='AptGround', service='StuccoService', garage=None,
                      prog='residential', tints=('White', 'Beige', 'Mint', 'Sky', 'Peach')),
    'stucco':    dict(upper='StuccoBay', wall='Stucco', entry='AptEntry', ground='AptGround', service='StuccoService', garage=None,
                      prog='mixed', tints=('Pink', 'Beige', 'Peach')),
    'spanish':   dict(upper='SpanishBay', wall='Stucco', entry='AptEntry', ground='AptGround', service='StuccoService', garage=None,
                      prog='mixed', tints=('White', 'Beige', 'Peach')),
    'brick':     dict(upper='BrickBay', wall='Brick', entry='BrickEntry', ground='BrickGround', service='BrickService', garage=None,
                      prog='mixed'),
    'brickb':    dict(upper='BrickBayB', wall='BrickB', entry=None, ground=None, service='BrickBService', garage=None, prog='shops'),
    'deco':      dict(upper='DecoBay', wall='DecoWall', entry='DecoEntry', ground='OfficeGround', service='GraniteService',
                      garage='GraniteGarage', prog='mixed'),
    'office':    dict(upper='OfficeBay', wall='Concrete', entry='OfficeLobby', ground='OfficeGround', service='GraniteService',
                      garage='GraniteGarage', prog='office'),
    'concrete':  dict(upper='ConcreteBay', wall='Concrete', entry='OfficeLobby', ground='OfficeGround', service='GraniteService',
                      garage='GraniteGarage', prog='office'),
    'glass':     dict(upper='GlassBay', wall='Concrete', entry='OfficeLobby', ground='OfficeGround', service='GraniteService',
                      garage='GraniteGarage', prog='office'),
}


def ground_program(s, role, n, rnd):
    """Ground-floor bays of one facade (n bays of 4 m): material names, 'shop' (a storefront), 'wide' (an 8 m
    store over this bay and the next) or None (rest of a wide store).
    role: 'front' (street side), 'side', 'back' (block interior: service door, garage, blind wall)."""
    wall, ground, entry = s['wall'], s['ground'] or s['wall'], s['entry']
    if role == 'back':
        out = [ground] * n
        out[rnd.randrange(n)] = s['service']
        if s['garage'] and n >= 3 and rnd.random() < 0.5:
            out[rnd.randrange(n)] = s['garage']
        return out
    prog = s['prog']
    if role == 'side':   # the corner bay continues the front (corner store), then quieter bays
        out = [ground] * n
        if prog == 'shops' and n > 1:
            out[1:] = [wall] * (n - 1)
            out[-1] = s['service']
        if prog in ('shops', 'mixed') and rnd.random() < 0.6:
            out[0] = 'shop'
        return out
    if prog == 'shops':
        out = ['shop'] * n
        if n >= 2 and rnd.random() < (0.5 if n == 2 else 0.65):   # a whole store (supermarket, bank)
            k = rnd.randrange(n - 1)
            out[k:k + 2] = ['wide', None]
        return out
    out = [ground] * n
    doors = [int((i + 0.5) * n / max(1, round(n / 5))) for i in range(max(1, round(n / 5)))]   # one entrance per ~20 m
    for k in doors if entry else ():
        out[k] = entry
    if prog in ('residential', 'office'):
        if n >= 3 and rnd.random() < (0.3 if prog == 'residential' else 0.5):   # corner store / cafe
            out[rnd.choice((0, n - 1))] = 'shop'
    else:   # mixed use: storefronts around the residents' entrances, some plain bays
        for k in range(n):
            if k not in doors or not entry:
                out[k] = 'shop' if (k in (0, n - 1) or rnd.random() < 0.65) else ground
    return out


def awning(m, a, b, mat, top=2.7, low=2.25, depth=1.0, valance=0.25, inset=0.3):
    """Fabric awning over a storefront between 2D wall points a -> b (outward = right of a -> b), hung just
    under the sign band: sloped canvas + valance + side cheeks, stripes running down the slope."""
    d = (b - a).normalized()
    o = rn.right(d)
    a, b = a + d * inset, b - d * inset
    A, B = V(a.x, a.y, top), V(b.x, b.y, top)
    C, D = V(b.x + o.x * depth, b.y + o.y * depth, low), V(a.x + o.x * depth, a.y + o.y * depth, low)
    dv = V(0, 0, valance)
    m.face([D, C, B, A], mat, [(0, 0), (1, 0), (1, 1), (0, 1)])
    m.face([D - dv, C - dv, C, D], mat, [(0, 0), (1, 0), (1, 0.25), (0, 0.25)])
    for p, q in ((A, D), (B, C)):          # side cheeks, double-sided
        tri = [q - dv, q, p]
        m.face(tri, mat, [(0, 0), (0, 0.3), (0.3, 1)])
        m.face(tri[::-1], mat, [(0.3, 1), (0, 0.3), (0, 0)])


def ac_unit(m, c):
    """Rooftop AC unit: photo of the grille on the 4 sides, metal lid."""
    m.box(c, V(1, 0), 2.4, 1.6, 1.4, 'PoleMetal', {k: 'ACUnit' for k in ('px', 'nx', 'py', 'ny')})


def bay(m, a, b, z0, z1, mat):
    """Facade panel a -> b (2D) from z0 to z1, texture fitted once (4 m bay, or 8 m wide store)."""
    m.face([V(a.x, a.y, z0), V(b.x, b.y, z0), V(b.x, b.y, z1), V(a.x, a.y, z1)], mat, [(0, 0), (1, 0), (1, 1), (0, 1)])


def building(style, w, d, floors, rnd, blind=('N',), awnings=0.25):
    """Box building w (x) x d (y), front = -Y. Widths should be multiples of 4 m so window bays line up.
    blind: back sides (block interior). Ground floors follow the style's program per side (ground_program);
    upper floors keep windows on every side (towers rise above their neighbours and are seen from all around).
    awnings: share of storefronts with a fabric awning (fabric picked per shop)."""
    s = STYLES[style]
    tint = rnd.choice(s.get('tints') or ('',))
    T = lambda mat: '%s__%s' % (mat, tint) if mat in TINTABLE and tint else mat
    upper, wall = T(s['upper'] or s['wall']), T(s['wall'])
    m = Mesh('Bldg_' + style, grime(0.7, 3.0))
    H = floors * FLOOR
    c = [V(-w / 2, -d / 2), V(w / 2, -d / 2), V(w / 2, d / 2), V(-w / 2, d / 2)]
    for (a, b), side in zip(zip(c, c[1:] + c[:1]), ('S', 'E', 'N', 'W')):
        n = max(1, int(round((b - a).length / FLOOR)))
        P = lambda k: a.lerp(b, k / n)
        role = 'front' if side == 'S' else 'back' if side in blind else 'side'
        for k, mat in enumerate(ground_program(s, role, n, rnd)):
            if mat is None:
                continue
            span = 2 if mat == 'wide' else 1
            face = next_shop(rnd, WIDE_SHOPS) if mat == 'wide' else next_shop(rnd) if mat == 'shop' else T(mat)
            bay(m, P(k), P(k + span), 0, FLOOR, face)
            if mat in ('shop', 'wide') and rnd.random() < awnings:
                awning(m, P(k), P(k + span), rnd.choice(AWNINGS))
        for f in range(1, floors):
            for k in range(n):
                bay(m, P(k), P(k + 1), f * FLOOR, (f + 1) * FLOOR, upper)
    par, t = 0.9, 0.3   # parapet height / thickness
    inner = [V(p.x - math.copysign(t, p.x), p.y - math.copysign(t, p.y)) for p in c]
    m.wall(c + c[:1], H + par, H, wall)
    m.wall(inner + inner[:1], H + par, H, wall, face_left=True)
    for (a, b), (ia, ib) in zip(zip(c, c[1:] + c[:1]), zip(inner, inner[1:] + inner[:1])):
        m.face([V(a.x, a.y, H + par), V(b.x, b.y, H + par), V(ib.x, ib.y, H + par), V(ia.x, ia.y, H + par)][::-1], 'Concrete')
    m.fill([inner], H, 'Roof')
    for _ in range(rnd.randint(1, 3)):
        ac_unit(m, V(rnd.uniform(-w / 2 + 3, w / 2 - 3), rnd.uniform(-d / 2 + 3, d / 2 - 3), H + 0.7))
    if style in ('brick', 'brickb') and floors > 2:  # wooden water tank on steel legs
        x, y = w / 4, d / 4
        for i in range(4):
            a = math.pi / 4 + i * math.pi / 2
            m.cyl(V(x + math.cos(a), y + math.sin(a), H), V(x + math.cos(a), y + math.sin(a), H + 2.5), 0.08, 4, 'PoleMetal__Dark')
        m.cyl(V(x, y, H + 2.5), V(x, y, H + 5.5), 1.5, 8, 'WaterTank')
        m.cyl(V(x, y, H + 5.5), V(x, y, H + 6.6), 1.6, 8, 'Roof', r1=0.1)
    return m


def corner_spot(n, toward, inset=1.0):
    """Point on the corner sidewalk of junction n facing direction `toward`, `inset` m behind the curb."""
    c = max((c for c in n.corners if c.kind == 'fillet'), key=lambda c: (c.a.d + c.b.d).normalized().dot(toward))
    u = ((c.ta - c.C).normalized() + (c.tb - c.C).normalized()).normalized()
    return c.C + u * (n.curb_r - inset)


# ------------------------------------------------------------------ street props (prefabs: front = -Y)
def hydrant():
    m, c = Mesh('Hydrant', grime(0.6, 0.6)), 'SignalMetal'
    m.cyl(V(0, 0, 0), V(0, 0, 0.08), 0.17, 8, c)
    m.cyl(V(0, 0, 0.08), V(0, 0, 0.55), 0.12, 8, c)
    m.cyl(V(0, 0, 0.55), V(0, 0, 0.62), 0.15, 8, c)
    m.cyl(V(0, 0, 0.62), V(0, 0, 0.74), 0.13, 8, c, r1=0.04)
    for p0, p1, r in ((V(-0.1, 0, 0.42), V(-0.22, 0, 0.42), 0.05), (V(0.1, 0, 0.42), V(0.22, 0, 0.42), 0.05),
                      (V(0, -0.1, 0.38), V(0, -0.22, 0.38), 0.07)):
        m.cyl(p0, p1, r, 6, c)
    return m


def trash_can():
    """Slatted city trash can: unrolled side photo wrapped once around, dark metal rim and lid."""
    m = Mesh('TrashCan', grime(0.6, 0.9))
    m.cyl(V(0, 0, 0), V(0, 0, 0.92), 0.3, 10, 'TrashCan', wrap=True)
    m.cyl(V(0, 0, 0.92), V(0, 0, 0.98), 0.32, 10, 'PoleMetal__Dark')
    m.cyl(V(0, 0, 0.98), V(0, 0, 1.08), 0.3, 10, 'PoleMetal__Dark', r1=0.2)
    return m


def bench(w=1.7, seat=0.46, depth=0.42, back=0.5):
    """PS1-style bench in one piece: seat card, backrest card hinged on the seat's back edge, leg cards
    reaching the seat, all from T_Bench (front photo, trimmed). Texture bands (v): legs 0-0.38,
    seat slats 0.38-0.52, backrest 0.55-1."""
    m = Mesh('Bench', grime(0.6, 0.5))
    X, Y, Z = V(1, 0, 0), V(0, 1, 0), V(0, 0, 1)
    m.card(V(0, 0, seat), X, Y, w, depth, 'Bench', (0, 0.38, 1, 0.52))                       # seat
    up = (Z * 0.97 + Y * 0.24).normalized()
    m.card(V(0, depth / 2, seat) + up * (back / 2), X, up, w, back, 'Bench', (0, 0.55, 1, 1))   # backrest
    for y in (-depth / 2 + 0.03, depth / 2 - 0.03):                                         # legs up to the seat
        m.card(V(0, y, seat / 2), X, Z, w, seat, 'Bench', (0, 0, 1, 0.38))
    return m


def news_box():
    """Coin-op newspaper rack: box with the front photo and a lid sloping back, coin box on top, four thin legs."""
    m = Mesh('NewsBox', grime(0.6, 0.6))
    w, d, z0, z1, z2 = 0.5, 0.42, 0.34, 0.88, 1.0   # width, depth, box bottom, front top, back top
    m.box(V(0, 0, (z0 + z1) / 2), V(1, 0), w, d, z1 - z0, 'NewsBoxSide', {'ny': 'NewsBoxFront'})
    a, b = V(-w / 2, -d / 2), V(w / 2, d / 2)   # sloped lid (prism over the box top)
    m.face([V(a.x, a.y, z1), V(b.x, a.y, z1), V(b.x, b.y, z2), V(a.x, b.y, z2)], 'NewsBoxSide')
    m.face([V(a.x, b.y, z1), V(b.x, b.y, z1), V(b.x, b.y, z2), V(a.x, b.y, z2)][::-1], 'NewsBoxSide')
    for x in (a.x, b.x):
        tri = [V(x, a.y, z1), V(x, b.y, z1), V(x, b.y, z2)]
        m.face(tri if x > 0 else tri[::-1], 'NewsBoxSide')
    m.box(V(0.15, 0.12, z2), V(1, 0), 0.1, 0.08, 0.07, 'PoleMetal__Dark')    # coin mechanism
    for x in (-0.21, 0.21):
        for y in (-0.17, 0.17):
            m.box(V(x, y, z0 / 2), V(1, 0), 0.035, 0.035, z0, 'PoleMetal__Dark')
    for y in (-0.17, 0.17):                                                           # stretchers
        m.box(V(0, y, 0.08), V(1, 0), 0.42, 0.03, 0.03, 'PoleMetal__Dark')
    return m


def mailbox():
    """Blue mailbox: body + rounded top extruded from its front profile; front/back show the photo."""
    m = Mesh('Mailbox', grime(0.6, 0.6))
    for x in (-0.24, 0.24):
        for y in (-0.22, 0.22):
            m.box(V(x, y, 0.15), V(1, 0), 0.06, 0.06, 0.3, 'MailboxSide')
    # profile proportions match the photo (0.6 x 1.0 m) so its pixels stay square
    prof = [(-0.3, 0.3), (0.3, 0.3)] + [(0.3 * math.cos(a), 1.0 + 0.3 * math.sin(a))
                                       for a in (i * math.pi / 6 for i in range(7))]
    m.extrude(prof, 0.55, 'Mailbox', 'MailboxSide')
    return m


def parking_meter():
    """Single-space dome meter: head extruded from its front outline (straight sides, domed top, rounded
    bottom) with the photo on both faces, collar, galvanized post and base plate."""
    m = Mesh('ParkingMeter', grime(0.6, 0.8))
    m.cyl(V(0, 0, 0), V(0, 0, 0.03), 0.09, 8, 'PoleMetal__Dark')
    m.cyl(V(0, 0, 0.03), V(0, 0, 1.08), 0.04, 8, 'PoleMetal')
    m.cyl(V(0, 0, 1.08), V(0, 0, 1.13), 0.07, 8, 'PoleMetal', r1=0.09)
    z0, r, h = 1.13, 0.12, 0.25   # head: 0.24 x 0.25 m like the photo (31 x 32 px)
    prof = [(-r + 0.03, z0), (r - 0.03, z0), (r, z0 + 0.03), (r, z0 + h - r)]
    prof += [(r * math.cos(a), z0 + h - r + r * math.sin(a)) for a in (i * math.pi / 8 for i in range(1, 8))]
    prof += [(-r, z0 + h - r), (-r, z0 + 0.03)]
    m.extrude(prof, 0.15, 'ParkingMeter', 'PoleMetal')
    return m


def bus_stop():
    m = Mesh('BusStop', grime(0.65, 1.0))
    for x in (-1.9, 1.9):
        for y in (-0.6, 0.6):
            m.box(V(x, y, 1.25), V(1, 0), 0.08, 0.08, 2.5, 'PoleMetal')
    m.box(V(0, 0, 2.55), V(1, 0), 4.2, 1.7, 0.12, 'PoleMetal')
    m.box(V(0, 0.62, 1.3), V(1, 0), 3.8, 0.04, 1.8, 'PoleMetal', {'ny': 'BusStopGlass', 'py': 'BusStopGlass'})
    m.box(V(1.95, 0, 1.3), V(1, 0), 0.06, 1.2, 1.8, 'PoleMetal', {'px': 'BusStopAd', 'nx': 'BusStopAd'})
    m.card(V(0, 0.35, 0.47), V(1, 0, 0), V(0, 1, 0), 2.6, 0.4, 'Bench', (0, 0.38, 1, 0.52))
    for x in (-1.1, 1.1):
        m.box(V(x, 0.35, 0.23), V(1, 0), 0.06, 0.35, 0.46, 'PoleMetal__Dark')
    return m


def power_pole(h=11.0):
    m = Mesh('PowerPole', grime(0.6, 1.5))
    m.cyl(V(0, 0, 0), V(0, 0, h), 0.16, 6, 'Wood', r1=0.12)
    m.box(V(0, 0, h - 0.7), V(1, 0), 2.6, 0.1, 0.12, 'Wood')
    for x in (-1.1, 0.0, 1.1):
        m.cyl(V(x, 0, h - 0.64), V(x, 0, h - 0.4), 0.05, 4, 'PoleMetal')
    m.cyl(V(0.25, 0, h - 3.2), V(0.25, 0, h - 2.0), 0.3, 6, 'PoleMetal')   # transformer
    return m


def wire(m, p0, p1, sag=0.6, n=8):
    pts = [p0.lerp(p1, i / n) - V(0, 0, sag * 4 * (i / n) * (1 - i / n)) for i in range(n + 1)]
    for a, b in zip(pts, pts[1:]):
        m.cyl(a, b, 0.02, 3, 'PoleMetal__Dark')


def street_sign(rows=(0, 2)):
    """Corner street-name sign: two crossing blades showing rows of the T_StreetSign atlas (4 rows)."""
    m = Mesh('StreetSign', grime(0.6, 0.8))
    m.cyl(V(0, 0, 0), V(0, 0, 3.2), 0.04, 6, 'PoleMetal')
    for row, (r, z) in zip(rows, ((V(1, 0, 0), 3.05), (V(0, 1, 0), 2.8))):
        uv = (0, row / 4, 1, (row + 1) / 4)
        nrm = V(0, 0, 1).cross(r)
        c = V(0, 0, z) + r * 0.45
        m.card(c + nrm * 0.011, r, V(0, 0, 1), 0.9, 0.2, 'StreetSign', uv)
        m.card(c - nrm * 0.011, -r, V(0, 0, 1), 0.9, 0.2, 'StreetSign', uv)
    return m


def stop_sign():
    m = Mesh('StopSign', grime(0.6, 0.8))
    rn.sign(m, V(0, 0), 0.0, V(0, -1), 'stop')
    return m


def yield_sign():
    m = Mesh('YieldSign', grime(0.6, 0.8))
    rn.sign(m, V(0, 0), 0.0, V(0, -1), 'yield')
    return m


def signal_head():
    m = Mesh('SignalHead')
    rn.signal_head(m, V(0, 0, 0), V(0, -1))
    return m


def street_lamp():
    m = Mesh('StreetLamp', grime(0.6, 1.0))
    rn.lamp(m, V(0, 0), 0.0, V(1, 0))
    return m


def highway_lamp():
    m = Mesh('HighwayLamp')
    rn.lamp(m, V(0, 0), 0.0, V(1, 0), h=10.0, heads=2)
    return m


def stamp(dst, src, p, yaw):
    """Append mesh `src` (local space) to `dst`, rotated by yaw (radians) and moved to 3D p: one-off pieces
    (fences, hedges sized to their spot) merged into one scene object."""
    c, s = math.cos(yaw), math.sin(yaw)
    i = len(dst.verts)
    dst.verts += [V(p.x + v.x * c - v.y * s, p.y + v.x * s + v.y * c, p.z + v.z) for v in src.verts]
    dst.faces += [tuple(k + i for k in f) for f in src.faces]
    dst.uvs += src.uvs
    dst.mats += src.mats
    dst.cols += src.cols


def fence(length, h=1.9):
    """Chain-link fence along +X from the origin (texture tiles every 2 m, cutout)."""
    m = Mesh('Fence', grime(0.6, 0.8))
    n = max(1, round(length / 3))
    for i in range(n + 1):
        x = length * i / n
        m.cyl(V(x, 0, 0), V(x, 0, h + 0.05), 0.04, 6, 'PoleMetal')
    m.cyl(V(0, 0, h), V(length, 0, h), 0.03, 4, 'PoleMetal')
    m.card(V(length / 2, 0, h / 2), V(1, 0, 0), V(0, 0, 1), length, h, 'ChainLink', (0, 0, length / 2, h / 2))
    return m


# ------------------------------------------------------------------ vegetation
def blob(m, c, r, mat, rnd, squash=0.8, segs=7, rings=4):
    """Lumpy low-poly sphere (canopy / bush clump)."""
    top, bot = c + V(0, 0, r * squash), c - V(0, 0, r * squash * 0.55)
    grid = []
    for i in range(1, rings):
        phi = math.pi * i / rings
        row = []
        for j in range(segs):
            th = 2 * math.pi * j / segs + (i % 2) * math.pi / segs
            k = rnd.uniform(0.82, 1.12)
            row.append(c + V(math.sin(phi) * math.cos(th) * r * k, math.sin(phi) * math.sin(th) * r * k,
                             math.cos(phi) * r * squash * k))
        grid.append(row)
    for j in range(segs):
        j2 = (j + 1) % segs
        oface(m, [top, grid[0][j], grid[0][j2]], mat, c)
        oface(m, [bot, grid[-1][j], grid[-1][j2]], mat, c)
        for a, b in zip(grid, grid[1:]):
            oface(m, [a[j], a[j2], b[j2]], mat, c)
            oface(m, [a[j], b[j2], b[j]], mat, c)


def leaf_cards(m, c, r, mat, rnd, n=6, size=1.3):
    """Cutout cards sticking out of a clump: crunchy silhouette."""
    for _ in range(n):
        th, z = rnd.uniform(0, 2 * math.pi), rnd.uniform(-0.3, 0.9)
        d = V(math.cos(th) * math.sqrt(1 - z * z), math.sin(th) * math.sqrt(1 - z * z), z)
        rgt = d.cross(V(0, 0, 1)).normalized() if abs(d.z) < 0.95 else V(1, 0, 0)
        up = rgt.cross(d)
        s = r * size * rnd.uniform(0.8, 1.2)
        m.card(c + d * r * 0.8, rgt, up, s, s, mat)


def broadleaf(rnd, h=8.0):
    """Street tree (ficus / sycamore look): trunk, 3 branches, 4 lumpy clumps + leaf cards. ~250 tris."""
    m = Mesh('Broadleaf', lambda p: 0.55 + 0.45 * rn.clamp(p.z / h))
    tz = h * 0.42
    m.cyl(V(0, 0, 0), V(0, 0, tz), 0.24, 6, 'Bark', r1=0.18)
    clumps = [(V(0, 0, h * 0.78), h * 0.26)]
    a0 = rnd.uniform(0, 2 * math.pi)
    for i in range(3):
        a = a0 + i * 2.1 + rnd.uniform(-0.3, 0.3)
        c = V(math.cos(a) * h * 0.2, math.sin(a) * h * 0.2, h * rnd.uniform(0.6, 0.7))
        clumps.append((c, h * rnd.uniform(0.2, 0.25)))
        m.cyl(V(0, 0, tz - 0.3), c, 0.12, 5, 'Bark', r1=0.06)
    for c, r in clumps:
        blob(m, c, r, 'Leaves', rnd)
        leaf_cards(m, c, r, 'LeafCard', rnd)
    return m


def palm(rnd, h=14.0, fronds=14):
    """Washingtonia palm: slightly curved 6-sided trunk, dead-frond skirt, fan fronds (cutout cards
    bent in 3 segments, stem at the crown)."""
    m = Mesh('Palm', lambda p: 0.6 + 0.4 * rn.clamp(p.z / h))
    lean = V(rnd.uniform(-1, 1), rnd.uniform(-1, 1)).normalized() * rnd.uniform(0.4, 1.0)
    spine = [V(lean.x * (i / 6) ** 2, lean.y * (i / 6) ** 2, h * i / 6) for i in range(7)]
    for i, (a, b) in enumerate(zip(spine, spine[1:])):
        m.cyl(a, b, rn.lerp(0.32, 0.22, i / 6), 6, 'PalmTrunk', r1=rn.lerp(0.32, 0.22, (i + 1) / 6))
    top = spine[-1]
    m.cyl(top - V(0, 0, 1.8), top + V(0, 0, 0.3), 0.32, 6, 'PalmTrunk__Dark', r1=0.55)
    for k in range(fronds):
        a = 2 * math.pi * k / fronds + rnd.uniform(-0.15, 0.15)
        d = V(math.cos(a), math.sin(a), 0)
        side = V(-d.y, d.x, 0)
        pitch = rnd.uniform(0.2, 0.7)
        L = rnd.uniform(2.6, 3.3)
        pts = [top + V(0, 0, 0.3)]
        for i in range(1, 4):   # arching frond: up then drooping
            t = i / 3
            pts.append(pts[-1] + (d * math.cos(pitch - 1.6 * t) + V(0, 0, math.sin(pitch - 1.6 * t))) * (L / 3))
        for i, (p0, p1) in enumerate(zip(pts, pts[1:])):
            w0 = w1 = 2.3
            v0, v1 = i / 3, (i + 1) / 3
            m.face([p0 - side * w0 / 2, p0 + side * w0 / 2, p1 + side * w1 / 2, p1 - side * w1 / 2], 'PalmFrond',
                   [(0, v0), (1, v0), (1, v1), (0, v1)])
    return m


def bush(rnd, r=0.8):
    """Shrub: 3-4 small offset clumps (opaque core) bristling with leaf cards that make the silhouette."""
    m = Mesh('Bush', lambda p: 0.55 + 0.45 * rn.clamp(p.z / (2 * r)))
    for i in range(rnd.randint(3, 4)):
        a = rnd.uniform(0, 2 * math.pi)
        c = V(math.cos(a) * r * 0.45, math.sin(a) * r * 0.45, r * rnd.uniform(0.45, 0.75)) if i else V(0, 0, r * 0.8)
        rr = r * rnd.uniform(0.5, 0.7)
        blob(m, c, rr * 0.8, 'Leaves__Bush', rnd, squash=0.75, segs=6, rings=3)
        leaf_cards(m, c, rr, 'LeafCard__Bush', rnd, n=10, size=1.6)
    return m


def hedge(length, h=1.1, w=0.9):
    """Trimmed hedge along +X from the origin, cutout fringe on top."""
    m = Mesh('Hedge', lambda p: 0.6 + 0.4 * rn.clamp(p.z / h))
    m.box(V(length / 2, 0, h / 2), V(1, 0), length, w, h, 'Leaves__Bush')
    n = max(1, round(length / 1.2))
    for i in range(n):
        x = (i + 0.5) * length / n
        for sg in (-1, 1):   # outside the box faces, staggered so overlapping cards are never coplanar
            y = sg * (w / 2 + 0.06 + 0.04 * (i % 2))
            m.card(V(x, y, h - 0.05), V(sg, 0, 0), V(0, 0, 1), length / n * 1.2, 0.6, 'LeafCard__Bush', (0, 0.45, 1, 1))
    return m


def grass_tuft(rnd):
    m = Mesh('GrassTuft')
    for k in range(3):
        a = k * math.pi / 3 + rnd.uniform(0, 0.4)
        m.card(V(0, 0, 0.22), V(math.cos(a), math.sin(a), 0), V(0, 0, 1), 0.6, 0.45, 'GrassTuft')
    return m


def billboard(name, S, cz):
    """LOD1 impostor: two crossed S x S cards centered at height cz, using T_Imp_<name>.png
    (same framing as render_impostor)."""
    m = Mesh(name + '_LOD1', lambda p: 0.6 + 0.4 * rn.clamp(p.z / (2 * cz)))
    for r in (V(1, 0, 0), V(0, 1, 0)):
        m.card(V(0, 0, cz), r, V(0, 0, 1), S, S, 'Imp_' + name)
    return m


def render_impostor(mesh_data, name, S, cz, px=128):
    """Front orthographic albedo view (S x S m centered at height cz) with alpha
    -> Assets/GTA/Textures/T_Imp_<name>.png."""
    sc = bpy.data.scenes.get('Impostor') or bpy.data.scenes.new('Impostor')
    for ob in list(sc.collection.objects):
        bpy.data.objects.remove(ob, do_unlink=True)
    ob = bpy.data.objects.new('imp', mesh_data)
    sc.collection.objects.link(ob)
    cam = bpy.data.objects.new('imp_cam', bpy.data.cameras.new('imp_cam'))
    sc.collection.objects.link(cam)
    cam.data.type, cam.data.ortho_scale = 'ORTHO', S
    cam.location, cam.rotation_euler = (0, -60, cz), (math.pi / 2, 0, 0)
    sc.camera = cam
    sc.render.engine = 'BLENDER_WORKBENCH'
    sc.display.shading.light = 'FLAT'
    sc.display.shading.color_type = 'TEXTURE'
    sc.render.film_transparent = True
    sc.view_settings.view_transform = 'Standard'
    sc.render.resolution_x = sc.render.resolution_y = px * 4
    raw = os.path.join(bpy.app.tempdir, 'imp_%s.png' % name)
    sc.render.filepath = raw
    bpy.ops.render.render(write_still=True, scene=sc.name)
    bpy.data.objects.remove(cam, do_unlink=True)
    bpy.data.objects.remove(ob, do_unlink=True)
    out = os.path.join(rn.TEX_DIR, 'T_Imp_%s.png' % name)
    tool = os.path.join(os.path.dirname(__file__), '..', 'texture', 'ps1ify.py')
    subprocess.run(['python', '-I', tool, raw, out, '--size', str(px), '--colors', '32'], check=True)
    return out


# ------------------------------------------------------------------ prefabs (one FBX per repeated object)
import json
import random

PROPS_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), '..', '..', 'Assets', 'GTA', 'Props'))
PREFABS = {   # name -> (builder, billboard LOD)
    'Hydrant': (hydrant, False), 'TrashCan': (trash_can, False), 'Bench': (bench, False),
    'NewsBox': (news_box, False), 'Mailbox': (mailbox, False), 'ParkingMeter': (parking_meter, False),
    'BusStop': (bus_stop, False), 'PowerPole': (power_pole, False), 'StreetSign': (street_sign, False),
    'StopSign': (stop_sign, False), 'YieldSign': (yield_sign, False), 'SignalHead': (signal_head, False),
    'StreetLamp': (street_lamp, False), 'HighwayLamp': (highway_lamp, False),
    'GrassTuft': (lambda: grass_tuft(random.Random(5)), False),
    'Palm_A': (lambda: palm(random.Random(11), 14), True), 'Palm_B': (lambda: palm(random.Random(12), 10), True),
    'Broadleaf_A': (lambda: broadleaf(random.Random(21), 8), True),
    'Broadleaf_B': (lambda: broadleaf(random.Random(22), 6.5), True),
    'Bush_A': (lambda: bush(random.Random(31), 0.8), True),
}


def billboard_frame(me):
    """Square impostor frame (size, center height) enclosing a mesh standing at the origin."""
    xs, ys, zs = ([v.co[i] for v in me.vertices] for i in range(3))
    return max(max(xs) - min(xs), max(ys) - min(ys), max(zs)) * 1.02, max(zs) / 2


def prefab_data(name):
    """Blender mesh data of a prefab's main mesh (LOD0), cached for previews."""
    me = bpy.data.meshes.get('PF_' + name)
    if me is None:
        me = PREFABS[name][0]().data()
        me.name = 'PF_' + name
    return me


def export_prefabs(names, impostors=True):
    """Export each prefab alone at the origin to Assets/GTA/Props/<Name>.fbx; trees get
    <Name> (empty) -> <Name>_LOD0 + <Name>_LOD1 (billboard, impostor re-rendered)."""
    os.makedirs(PROPS_DIR, exist_ok=True)
    for name in sorted(names):
        col = rn.collection('Prefab')
        me = prefab_data(name)
        if PREFABS[name][1]:
            S, cz = billboard_frame(me)
            if impostors:
                render_impostor(me, name, S, cz)
            root = bpy.data.objects.new(name, None)
            col.objects.link(root)
            for ob in (bpy.data.objects.new(name + '_LOD0', me), billboard(name, S, cz).to_object(col)):
                ob.name = name + ('_LOD0' if ob.data is me else '_LOD1')
                ob.parent = root
                if ob.name not in col.objects:
                    col.objects.link(ob)
        else:
            col.objects.link(bpy.data.objects.new(name, me))
        rn.export_fbx(os.path.join(PROPS_DIR, name + '.fbx'), list(col.objects))
    rn.collection('Prefab')


def write_placements(path, placements):
    """JSON read by Assets/GTA/Editor/PropPlacer.cs (Blender coordinates, yaw in radians)."""
    items = [dict(prefab=p, x=round(x, 3), y=round(y, 3), z=round(z, 3), yaw=round(yaw, 4)) for p, x, y, z, yaw in placements]
    with open(path, 'w', encoding='utf-8') as f:
        json.dump({'items': items}, f, indent=0)


def reset_prefab_cache():
    """Drop cached prefab meshes so a rebuild picks up code / texture changes."""
    for me in [m for m in bpy.data.meshes if m.name.startswith('PF_')]:
        bpy.data.meshes.remove(me)


def inspect(names, out_dir, px=384):
    """Close-up 3/4 render of each prefab alone (Workbench, textured) -> <out_dir>/inspect_<Name>.png.
    Check every object individually before placing it (coherent faces, parts touching, square pixels)."""
    sc = bpy.data.scenes.get('Inspect') or bpy.data.scenes.new('Inspect')
    sc.render.engine = 'BLENDER_WORKBENCH'
    sc.display.shading.light, sc.display.shading.color_type = 'STUDIO', 'TEXTURE'
    sc.view_settings.view_transform = 'Standard'
    sc.render.resolution_x = sc.render.resolution_y = px
    cam = bpy.data.objects.get('inspect_cam') or bpy.data.objects.new('inspect_cam', bpy.data.cameras.new('inspect_cam'))
    if cam.name not in sc.collection.objects:
        sc.collection.objects.link(cam)
    sc.camera = cam
    cam.data.type = 'ORTHO'
    for name in names:
        for ob in [o for o in sc.collection.objects if o is not cam]:
            sc.collection.objects.unlink(ob)
        me = prefab_data(name)
        ob = bpy.data.objects.new('inspect_' + name, me)
        sc.collection.objects.link(ob)
        S, cz = billboard_frame(me)
        cam.data.ortho_scale = S * 1.15
        d = V(0.62, -0.62, 0.48).normalized()
        cam.location = V(0, 0, cz) + d * 60
        cam.rotation_euler = (-d).to_track_quat('-Z', 'Y').to_euler()
        sc.render.filepath = os.path.join(out_dir, 'inspect_%s.png' % name)
        bpy.ops.render.render(write_still=True, scene=sc.name)
        sc.collection.objects.unlink(ob)
        bpy.data.objects.remove(ob)
