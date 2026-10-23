"""Demo city: US grid downtown with a central roundabout, an elevated ring highway with
four diamond interchanges, and a rural outer loop. Run inside Blender:

    import sys; sys.path.insert(0, r'<project>/Tools/citygen')
    import importlib, roadnet, city_demo; importlib.reload(roadnet); importlib.reload(city_demo)
    city_demo.build(export=r'<project>/Assets/GTA/City/CityDemo.fbx')
"""
import math
import random

import bpy

import kit
import roadnet as rn
from roadnet import V, Profile

# ------------------------------------------------------------------ profiles (meters)
RAMP_W = 7.0     # ramp asphalt: shoulder 1.5 + lane 4.0 + shoulder 1.5
HW_EDGE = 15.6   # highway asphalt half width (median 0.3 + 1.2 + 3 x 3.7 + 3.0)


def street():
    side = [('lane', 3.3), ('shoulder', 2.4), ('sidewalk', 3.0)]   # shoulder = parking lane
    return Profile(side, side, [(0, 'double', 'Y'), (-3.3, 'solid', 'W'), (3.3, 'solid', 'W')])


def avenue():
    side = [('lane', 3.4), ('lane', 3.4), ('sidewalk', 4.0)]
    return Profile(side, side, [(0, 'double', 'Y'), (-3.4, 'dashed', 'W'), (3.4, 'dashed', 'W')])


def rural():
    side = [('lane', 3.6), ('shoulder', 1.5)]
    return Profile(side, side, [(0, 'dashed', 'Y'), (-3.6, 'solid', 'W'), (3.6, 'solid', 'W')])


def highway(aux_l=0.0, aux_r=0.0):
    """3+3 lanes with median barrier. aux_* widens a side by a ramp lane (taper / gore)."""
    def side(aux):
        k = aux / RAMP_W
        return [('mbarrier', 0.3), ('shoulder', 1.2), ('lane', 3.7), ('lane', 3.7), ('lane', 3.7),
                ('shoulder', 3.0), ('shoulder', 1.5 * k), ('lane', 4.0 * k), ('shoulder', 1.5 * k),
                ('barrier', 0.5)]

    def marks(aux, sg):
        k, aux_style = aux / RAMP_W, 'solid' if aux else 'none'
        return [(sg * 1.5, 'solid', 'Y'), (sg * 5.2, 'dashed', 'W'), (sg * 8.9, 'dashed', 'W'),
                (sg * 12.6, 'solid', 'W'),
                (sg * (HW_EDGE + 1.5 * k), aux_style, 'Y'), (sg * (HW_EDGE + 5.5 * k), aux_style, 'W')]
    return Profile(side(aux_l), side(aux_r), marks(aux_l, -1) + marks(aux_r, 1))


def ramp():
    side = [('lane', 2.0), ('shoulder', 1.5), ('barrier', 0.5)]
    return Profile(side, side, [(-2.0, 'solid', 'Y'), (2.0, 'solid', 'W')], oneway=True)


# ------------------------------------------------------------------ layout
XS = [-390, -260, -130, 0, 130, 260, 390]
YS = [-300, -200, -100, 0, 100, 200, 300]
AVX, AVY = {-260, 0, 260}, {-200, 0, 200}
HX, HY, HR, HZ = 520, 440, 120, 7.5   # ring highway: half sizes, corner radius, deck height
OUT = 150                              # rural loop distance outside the highway
SPLIT, TAPER, RAMP_V = 220, 290, 32    # gore at +-SPLIT, taper from +-TAPER, ramps at +-RAMP_V


def loop_sides(X, Y, R):
    """CCW rectangle sides: (midpoint, u = travel dir, v = outward, half straight length)."""
    return [(V(0, -Y), V(1, 0), V(0, -1), X - R), (V(X, 0), V(0, 1), V(1, 0), Y - R),
            (V(0, Y), V(-1, 0), V(0, 1), X - R), (V(-X, 0), V(0, -1), V(-1, 0), Y - R)]


def corner_pts(p0, p1, v0, R):
    c = p0 - v0 * R
    a0 = rn.angle(p0 - c)
    return rn.arc(c, R, a0, a0 + math.pi / 2, step=math.radians(4))[1:-1]


def build_net():
    net = rn.Net()
    G = {}
    for x in XS:
        for y in YS:
            corner = abs(x) == XS[-1] and abs(y) == YS[-1]
            if (x, y) == (0, 0):
                G[x, y] = net.node(0, 0, ring=(16, 26, 10), control='yield')
            elif corner:
                G[x, y] = net.node(x, y, curb_r=12)
            else:
                G[x, y] = net.node(x, y, control='signal' if x in AVX or y in AVY else 'stop')
    for y in YS:
        for x0, x1 in zip(XS, XS[1:]):
            net.edge(G[x0, y], G[x1, y], avenue() if y in AVY else street())
    for x in XS:
        for y0, y1 in zip(YS, YS[1:]):
            net.edge(G[x, y0], G[x, y1], avenue() if x in AVX else street())

    city_edge = [G[0, YS[0]], G[XS[-1], 0], G[0, YS[-1]], G[XS[0], 0]]
    hw_sides, out_sides = loop_sides(HX, HY, HR), loop_sides(HX + OUT, HY + OUT, HR + OUT)
    hw_ends, out_ends = [], []
    for (O, U, Vd, half), (Oo, _, _, half_o), city in zip(hw_sides, out_sides, city_edge):
        W = lambda u, v: O + U * u + Vd * v
        # highway side: plain nodes along u
        hn = {u: net.node(*W(u, 0), z=HZ, kind='plain') for u in (-half, -TAPER, -SPLIT, SPLIT, TAPER, half)}
        e0 = net.edge(hn[-half], hn[-TAPER], highway())
        net.edge(hn[-TAPER], hn[-SPLIT], highway(), prof_b=highway(RAMP_W, RAMP_W))
        net.edge(hn[-SPLIT], hn[SPLIT], highway(), no_barrier={'L': (70, 70), 'R': (70, 70)})
        net.edge(hn[SPLIT], hn[TAPER], highway(RAMP_W, RAMP_W), prof_b=highway())
        e4 = net.edge(hn[TAPER], hn[half], highway())
        net.exit_sign(e0, e0.L - 60, 'R')
        net.exit_sign(e4, 60, 'L')
        hw_ends.append((hn[-half], hn[half], Vd))
        # diamond interchange: avenue passes under, ramps land at v = +-RAMP_V
        j_in = net.node(*W(0, -RAMP_V), control='signal')
        j_out = net.node(*W(0, RAMP_V), control='signal')
        t = net.node(*W(0, OUT), control='stop')
        net.edge(city, j_in, avenue())
        net.edge(j_in, j_out, avenue())
        net.edge(j_out, t, avenue())
        r0 = HW_EDGE + RAMP_W / 2
        vm = lambda u: r0 + (RAMP_V - r0) * rn.smooth((SPLIT - abs(u)) / 130)
        path = lambda us, sg: [W(u, sg * vm(u)) for u in us]
        fwd, back = range(-SPLIT + 5, 0, 5), range(5, SPLIT, 5)
        g = lambda u, sg: net.node(*W(u, sg * r0), z=HZ, kind='plain')
        net.edge(g(-SPLIT, 1), j_out, ramp(), pts=path(fwd, 1), flat=(0, 45), no_barrier={'L': (70, 0)})
        net.edge(j_out, g(SPLIT, 1), ramp(), pts=path(back, 1), flat=(45, 0), no_barrier={'L': (0, 70)})
        net.edge(g(SPLIT, -1), j_in, ramp(), pts=path(back[::-1], -1), flat=(0, 45), no_barrier={'L': (70, 0)})
        net.edge(j_in, g(-SPLIT, -1), ramp(), pts=path(fwd[::-1], -1), flat=(45, 0), no_barrier={'L': (0, 70)})
        # rural loop side
        Wo = lambda u: Oo + U * u
        a, b = net.node(*Wo(-half_o)), net.node(*Wo(half_o))
        net.edge(a, t, rural())
        net.edge(t, b, rural())
        out_ends.append((a, b, Vd))
    for ends, R, prof in ((hw_ends, HR, highway), (out_ends, HR + OUT, rural)):
        for i, (_, end, v0) in enumerate(ends):
            start = ends[(i + 1) % 4][0]
            net.edge(end, start, prof(), pts=corner_pts(end.p, start.p, v0, R))
    return net, G


# ------------------------------------------------------------------ blocks, buildings, street furniture
def block_poly(G, i, j):
    ring = [G[XS[i], YS[j]], G[XS[i + 1], YS[j]], G[XS[i + 1], YS[j + 1]], G[XS[i], YS[j + 1]]]
    c = V((XS[i] + XS[i + 1]) / 2, (YS[j] + YS[j + 1]) / 2)
    poly = []
    for n in ring:
        d = (c - n.p).normalized()
        poly += max(n.block_corners, key=lambda bc: bc[0].dot(d))[1][::-1]
    poly = rn.dedupe(poly)
    if (poly[0] - poly[-1]).length < 0.01:
        poly.pop()
    return poly, c


def style_for(dist, rnd):
    """Downtown towers in the middle, brick / stucco mid-rise around, low stucco and strip malls outside."""
    if dist < 200:
        return ('office', rnd.randint(8, 22)) if rnd.random() < 0.6 else ('brick', rnd.randint(5, 8))
    if dist < 330:
        return ('brick', rnd.randint(3, 6)) if rnd.random() < 0.5 else ('stucco', rnd.randint(2, 4))
    return ('stucco', rnd.randint(2, 3)) if rnd.random() < 0.6 else ('strip', 1)


def blocks(G, col, place, rnd):
    """Lots matching the sidewalks; per block: 4 kit buildings (one per quadrant, shopfront on the street,
    blind back to the block center), or a park (prefab trees) or a parking lot. Returns the static objects."""
    lots, marks = rn.Mesh('Lots', kit.grime(0.8, 0.5)), rn.Mesh('LotMarkings')
    objs, Z = [], rn.CURB_H
    for i in range(len(XS) - 1):
        for j in range(len(YS) - 1):
            poly, c = block_poly(G, i, j)
            dist, r = c.length, rnd.random()
            kind = 'park' if r < (0.08 if dist < 250 else 0.16) else 'parking' if r < (0.12 if dist < 250 else 0.26) else 'city'
            lots.fill([poly], Z, {'park': 'Grass', 'parking': 'Asphalt'}.get(kind, 'Sidewalk'))
            lots.wall(poly + [poly[0]], Z, rn.GROUND_Z, 'Concrete__Curb')
            x0, x1 = min(p.x for p in poly), max(p.x for p in poly)
            y0, y1 = min(p.y for p in poly), max(p.y for p in poly)
            inside = lambda p, m=4: rn.point_in_poly(p, poly) and x0 + m < p.x < x1 - m and y0 + m < p.y < y1 - m
            if kind == 'park':
                for _ in range(45):
                    p = V(rnd.uniform(x0, x1), rnd.uniform(y0, y1))
                    if inside(p, 5):
                        name = rnd.choice(('Broadleaf_A', 'Broadleaf_A', 'Palm_A', 'Palm_B', 'Bush_A', 'Bush_A', 'GrassTuft', 'GrassTuft'))
                        place(name, p.x, p.y, Z, rnd.uniform(0, 6.3))
                continue
            if kind == 'parking':
                for row in (y0 + 8, y1 - 13):
                    for k in range(int((x1 - x0 - 16) / 2.7) + 1):
                        x = x0 + 8 + k * 2.7
                        if inside(V(x, row), 3) and inside(V(x, row + 5), 3):
                            marks.mark([V(x, row, Z + rn.MARK_Z), V(x, row + 5, Z + rn.MARK_Z)], 0.12)
                for x in (x0 + 4, x1 - 4):
                    if inside(V(x, (y0 + y1) / 2), 2):
                        place(rnd.choice(('Palm_A', 'Palm_B')), x, (y0 + y1) / 2, Z, rnd.uniform(0, 6.3))
                continue
            xm = (x0 + x1) / 2 + rnd.uniform(-6, 6)
            ym = (y0 + y1) / 2 + rnd.uniform(-4, 4)
            for (a, b), (cy0, cy1), north in (((x0, xm), (y0, ym), False), ((xm, x1), (y0, ym), False),
                                              ((x0, xm), (ym, y1), True), ((xm, x1), (ym, y1), True)):
                g = 1.0
                W = math.floor((b - a - 2 * g) / 4) * 4
                D = min(cy1 - cy0 - 2 * g, rnd.uniform(14, 26))
                if W < 8 or D < 8:
                    continue
                cx = (a + b) / 2
                cy = cy1 - g - D / 2 if north else cy0 + g + D / 2
                q = [V(cx - W / 2, cy - D / 2), V(cx + W / 2, cy - D / 2), V(cx + W / 2, cy + D / 2), V(cx - W / 2, cy + D / 2)]
                if not all(rn.point_in_poly(p, poly) for p in q):
                    continue
                style, floors = style_for(dist, rnd)
                ob = bpy.data.objects.new('Bldg_%d_%d_%d' % (i, j, len(objs)), kit.building(style, W, D, floors, rnd).data())
                ob.location, ob.rotation_euler = (cx, cy, Z), (0, 0, math.pi if north else 0.0)   # shops face the street
                col.objects.link(ob)
                objs.append(ob)
    return objs + [lots.to_object(col), marks.to_object(col)]


# (prefab, lateral offset from the curb, weight) per sidewalk slot; front of the prefab faces the road
FURNITURE = {
    'avenue': (('Palm_A', 2.0, 3), ('Palm_B', 2.0, 3), ('Broadleaf_B', 2.0, 2), ('TrashCan', 0.7, 1.5),
               ('Hydrant', 0.6, 1), ('Bench', 3.2, 1), ('NewsBox', 3.5, 0.6), ('Mailbox', 3.5, 0.6),
               ('BusStop', 2.6, 0.4), (None, 0, 5)),
    'street': (('Broadleaf_B', 1.6, 3), ('ParkingMeter', 0.5, 3), ('Hydrant', 0.6, 0.8), ('TrashCan', 0.6, 1),
               ('Mailbox', 2.5, 0.4), (None, 0, 4)),
}


def furnish(net, place, rnd):
    """Street furniture and street trees on every at-grade sidewalk, in 10 m slots that dodge the lamps."""
    for e in net.edges:
        if e.a.z or e.b.z:
            continue
        s0, s1 = e.t['A'], e.L - e.t['B']
        for side, sg, off in (('R', 1, 0.0), ('L', -1, 17.0)):
            walk = e.pa.walk(side)
            if not walk or not e.pb.walk(side):
                continue
            items = FURNITURE['avenue' if walk >= 4 else 'street']
            lamps = [s0 + 9.0 + off + 34.0 * k for k in range(int(e.L / 34) + 2)]
            s = s0 + 14.0 + rnd.uniform(0, 5)
            while s < s1 - 14.0:
                if all(abs(s - l) > 3.0 for l in lamps):
                    name, lat, _ = rnd.choices(items, [w for *_, w in items])[0]
                    p, tan = e.frame(s)
                    r = rn.right(tan) * sg
                    q = p + r * (e.prof(s).asphalt(side) + lat)
                    if name and not net._under_deck(q):
                        tree = name.startswith(('Palm', 'Broadleaf'))
                        yaw = rnd.uniform(0, 6.3) if tree else rn.angle(-r) + math.pi / 2
                        place(name, q.x, q.y, e.z(s) + rn.CURB_H, yaw)
                s += 10.0


def ground(mb, x0, y0, x1, y1, step=100):
    for x in range(x0, x1, step):
        for y in range(y0, y1, step):
            mb.face([V(x, y, rn.GROUND_Z), V(x + step, y, rn.GROUND_Z), V(x + step, y + step, rn.GROUND_Z),
                     V(x, y + step, rn.GROUND_Z)], 'Grass')


def build(export=None):
    """export: scene FBX path; also writes <export>_placements.json and the prefab FBX files."""
    rnd = random.Random(7)
    kit.reset_prefab_cache()
    kit._last_shops.clear()
    net, G = build_net()
    meshes = net.build()
    col = rn.collection('City')
    objs = [m.to_object(col) for m in meshes.values()]
    placements = list(net.placements)
    place = lambda name, x, y, z, yaw: placements.append((name, x, y, z, yaw))
    objs += blocks(G, col, place, rnd)
    furnish(net, place, rnd)
    gr = rn.Mesh('Ground')
    ground(gr, -900, -800, 900, 800)
    objs.append(gr.to_object(col))
    if export:
        rn.export_fbx(export, objs)
        kit.export_prefabs({p[0] for p in placements})
        kit.write_placements(export[:-4] + '_placements.json', placements)
    return {'warnings': net.warnings, 'static': len(objs), 'placed': len(placements)}
