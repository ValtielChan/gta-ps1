"""Demo city: US grid downtown with a central roundabout, an elevated ring highway with
four diamond interchanges, a rural outer loop, residential districts outside the loop (DISTRICTS: bungalows,
ranch houses, mansions on their lots) and rolling green hills with wind turbines beyond. Run inside Blender:

    import sys; sys.path.insert(0, r'<project>/Tools/citygen')
    import importlib, roadnet, city_demo; importlib.reload(roadnet); importlib.reload(city_demo)
    city_demo.build(export=r'<project>/Assets/GTA/City/CityDemo.fbx')
    city_demo.export_peds(r'<project>/Assets/GTA/City/CityDemo_peds.json')   # pedestrian graph only
    city_demo.export_traffic(r'<project>/Assets/GTA/City/CityDemo_traffic.json')   # traffic lane graph only
"""
import json
import math
import random

import bpy
from mathutils import noise

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


def residential():
    side = [('lane', 3.2), ('shoulder', 2.2), ('sidewalk', 2.0)]   # quiet suburban street, no centre line
    return Profile(side, side, [(-3.2, 'none', 'W'), (3.2, 'none', 'W')])


def highway(aux_l=0.0, aux_r=0.0, gore=False):
    """3+3 lanes with median barrier. aux_* widens a side by a ramp lane (taper / gore).
    gore: the edge barriers stand on the shoulders, back to back with the ramps' barriers."""
    def side(aux):
        k = aux / RAMP_W
        return [('mbarrier', 0.3), ('shoulder', 1.2), ('lane', 3.7), ('lane', 3.7), ('lane', 3.7),
                ('shoulder', 2.5 if gore else 3.0), ('shoulder', 1.5 * k), ('lane', 4.0 * k), ('shoulder', 1.5 * k),
                ('barrier', 0.5)]

    def marks(aux, sg):
        k, aux_style = aux / RAMP_W, 'solid' if aux else 'none'
        return [(sg * 1.5, 'solid', 'Y'), (sg * 5.2, 'dashed', 'W'), (sg * 8.9, 'dashed', 'W'),
                (sg * 12.6, 'solid', 'W'),
                (sg * (HW_EDGE + 1.5 * k), aux_style, 'Y'), (sg * (HW_EDGE + 5.5 * k), aux_style, 'W')]
    return Profile(side(aux_l), side(aux_r), marks(aux_l, -1) + marks(aux_r, 1))


def ramp():
    """The left barrier faces the highway at the gore: it stands on the shoulder, back to back with the highway's."""
    left, right = [('lane', 2.0), ('shoulder', 1.0), ('barrier', 0.5)], [('lane', 2.0), ('shoulder', 1.5), ('barrier', 0.5)]
    return Profile(left, right, [(-2.0, 'solid', 'Y'), (2.0, 'solid', 'W')], oneway=True)


# ------------------------------------------------------------------ layout
XS = [-390, -260, -130, 0, 130, 260, 390]
YS = [-300, -200, -100, 0, 100, 200, 300]
AVX, AVY = {-260, 0, 260}, {-200, 0, 200}
HX, HY, HR, HZ = 520, 440, 120, 7.5   # ring highway: half sizes, corner radius, deck height
OUT = 150                              # rural loop distance outside the highway
SPLIT, TAPER, RAMP_V = 220, 290, 32    # gore at +-SPLIT, taper from +-TAPER, ramps at +-RAMP_V
GAP = 1                                # gore: back-to-back highway / ramp barriers rise from the nose over 10 m

# Residential districts outside the rural loop, one per loop side (0 = S, 1 = E, 2 = N, 3 = W): streets leave the
# loop at `streets` (u along the side), cross streets at `rows` (v beyond the loop). Every block is cut into lots
# `lot` m wide along its two cross-street sides, back to back (houses()): house prefab (`houses`: name -> weight) set
# back `setback` m, closed yards: `front` boundary along the sidewalk and between the front yards, `back` boundary
# between the back yards and along the lot backs (kinds: picket, hedge, tallhedge, wood, chain; name -> weight).
DISTRICTS = {
    0: dict(kind='modest', streets=(-360, -240, -120, 0, 120, 240, 360), rows=(80, 160, 240), lot=15, setback=7,
            houses={'HouseA': 3, 'HouseB': 2}, front={'picket': 3, 'hedge': 2}, back={'wood': 2, 'chain': 1},
            trees=('Broadleaf_B', 'Palm_B')),
    3: dict(kind='modest', streets=(-240, -120, 0, 120, 240), rows=(80, 160), lot=15, setback=7,
            houses={'HouseA': 2, 'HouseB': 3}, front={'picket': 2, 'hedge': 3}, back={'wood': 1, 'chain': 2},
            trees=('Broadleaf_B', 'Broadleaf_A')),
    1: dict(kind='ranch', streets=(-240, -120, 0, 120, 240), rows=(90, 180), lot=24, setback=8,
            houses={'RanchA': 3, 'RanchB': 2}, front={'hedge': 3, 'picket': 1}, back={'wood': 1},
            trees=('Palm_A', 'Broadleaf_B')),
    2: dict(kind='rich', streets=(-300, -100, 100, 300), rows=(140, 280), lot=50, setback=16,
            houses={'MansionA': 1, 'MansionB': 1}, front={'tallhedge': 1}, back={'tallhedge': 1},
            trees=('Palm_A', 'Palm_B', 'Broadleaf_A')),
}
FLAT = (900, 920)      # half extent of the flat land (city + districts); the hills rise beyond
WORLD = 2048           # half extent of the terrain


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
    net.blocks = []   # residential blocks: (district, corner nodes, u axis, v axis, along the rural loop)
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
        hg = net.edge(hn[-SPLIT], hn[SPLIT], highway(gore=True), no_barrier={'L': (GAP, GAP), 'R': (GAP, GAP)})
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
        net.gore(hg, net.edge(g(-SPLIT, 1), j_out, ramp(), pts=path(fwd, 1), flat=(0, 45), no_barrier={'L': (GAP, 0)}))
        net.gore(hg, net.edge(j_out, g(SPLIT, 1), ramp(), pts=path(back, 1), flat=(45, 0), no_barrier={'L': (0, GAP)}))
        net.gore(hg, net.edge(g(SPLIT, -1), j_in, ramp(), pts=path(back[::-1], -1), flat=(0, 45), no_barrier={'L': (GAP, 0)}))
        net.gore(hg, net.edge(j_in, g(-SPLIT, -1), ramp(), pts=path(fwd[::-1], -1), flat=(45, 0), no_barrier={'L': (0, GAP)}))
        # rural loop side, with the residential streets leaving it (DISTRICTS)
        Wo = lambda u, v=0.0: Oo + U * u + Vd * v
        k = len(hw_ends) - 1
        district = DISTRICTS.get(k)
        loop_nodes = {0: t}
        if district:
            N = {}
            for u in district['streets']:
                for v in (0,) + tuple(district['rows']):
                    N[u, v] = t if (u, v) == (0, 0) else net.node(*Wo(u, v), control='stop' if v else None)
                loop_nodes[u] = N[u, 0]
            for u in district['streets']:
                vs = (0,) + tuple(district['rows'])
                for v0, v1 in zip(vs, vs[1:]):
                    net.edge(N[u, v0], N[u, v1], residential())
            for v in district['rows']:
                for u0, u1 in zip(district['streets'], district['streets'][1:]):
                    net.edge(N[u0, v], N[u1, v], residential())
            vs = (0,) + tuple(district['rows'])
            for u0, u1 in zip(district['streets'], district['streets'][1:]):
                for v0, v1 in zip(vs, vs[1:]):
                    net.blocks.append((district, (N[u0, v0], N[u1, v0], N[u1, v1], N[u0, v1]), U, Vd, v0 == 0))
        a, b = net.node(*Wo(-half_o)), net.node(*Wo(half_o))
        chain = [a] + [loop_nodes[u] for u in sorted(loop_nodes)] + [b]
        for n0, n1 in zip(chain, chain[1:]):
            net.edge(n0, n1, rural())
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
    """Downtown towers (glass, concrete, offices, art deco) in the middle, brick mixed-use and stucco apartments
    around, low apartments / spanish revival / strip malls outside."""
    pick = lambda table: rnd.choices([t for t, _ in table], [w for _, w in table])[0]
    if dist < 200:
        style = pick((('office', 3), ('glass', 2), ('concrete', 1.5), ('deco', 2), ('brick', 1.5)))
        floors = {'office': (10, 22), 'glass': (12, 24), 'concrete': (6, 14), 'deco': (6, 12), 'brick': (5, 8)}[style]
    elif dist < 330:
        style = pick((('brick', 2.5), ('brickb', 2), ('stucco', 2), ('apartment', 2), ('spanish', 1.5)))
        floors = {'brick': (3, 6), 'brickb': (2, 5), 'stucco': (2, 4), 'apartment': (2, 4), 'spanish': (2, 3)}[style]
    else:
        style = pick((('apartment', 3), ('stucco', 2), ('spanish', 2), ('strip', 3)))
        floors = (1, 1) if style == 'strip' else (2, 3)
    return style, rnd.randint(*floors)


RESIDENTIAL = ('apartment', 'stucco', 'spanish')


def edge_line(statics, kind, a, b, z, rnd=None):
    """One-off linear feature from 2D a to b (kit.fence / kit.hedge, built along +X) stamped into `statics`."""
    L = (b - a).length
    if L < 2:
        return
    m = kit.fence(L) if kind == 'fence' else kit.hedge(L)
    kit.stamp(statics[kind], m, V(a.x, a.y, z), rn.angle(b - a))


def blocks(G, col, place, rnd, stalls=None):
    """Lots matching the sidewalks; per block: 4 kit buildings (one per quadrant, ground floor program facing the
    street, service side to the block center), or a park (hedged, prefab trees and bushes) or a fenced parking
    lot. Returns the static objects. stalls: list that receives the parking-lot stalls (x, y, z, nose dx, dy)."""
    lots, marks = rn.Mesh('Lots', kit.grime(0.8, 0.5)), rn.Mesh('LotMarkings')
    statics = {'fence': rn.Mesh('Fences', kit.grime(0.6, 0.8)), 'hedge': rn.Mesh('Hedges', lambda p: 0.6 + 0.4 * rn.clamp(p.z / 1.1))}
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
            if kind in ('park', 'parking'):   # border: hedge (gaps at the middle = park entrances) / chain-link fence
                m, corner, gap = (2.5, 14, 5) if kind == 'park' else (1.5, 12, 0)
                ring = [V(x0 + m, y0 + m), V(x1 - m, y0 + m), V(x1 - m, y1 - m), V(x0 + m, y1 - m)]
                for a, b in zip(ring, ring[1:] + ring[:1]):
                    d = (b - a).normalized()
                    a, b = a + d * corner, b - d * corner   # rounded lot corners stay open (entrances)
                    mid = a.lerp(b, 0.5)
                    for p, q in (((a, mid - d * gap), (mid + d * gap, b)) if gap else ((a, b),)):
                        edge_line(statics, 'hedge' if kind == 'park' else 'fence', p, q, Z)
                    if kind == 'parking':   # shrubs along the fence, inside
                        n_in = rn.left(d)
                        for k in range(int((b - a).length / 7)):
                            if rnd.random() < 0.5:
                                p = a + d * (3.5 + 7 * k) + n_in * 1.0
                                place('Bush_A', p.x, p.y, Z, rnd.uniform(0, 6.3))
            if kind == 'park':
                for _ in range(55):
                    p = V(rnd.uniform(x0, x1), rnd.uniform(y0, y1))
                    if inside(p, 6):
                        name = rnd.choice(('Broadleaf_A', 'Broadleaf_A', 'Palm_A', 'Palm_B', 'Bush_A', 'Bush_A', 'Bush_A', 'GrassTuft', 'GrassTuft'))
                        place(name, p.x, p.y, Z, rnd.uniform(0, 6.3))
                        if name == 'Bush_A':   # shrubs grow in small groups
                            for _ in range(rnd.randint(1, 2)):
                                q = p + V(rnd.uniform(-2, 2), rnd.uniform(-2, 2))
                                if inside(q, 6):
                                    place('Bush_A', q.x, q.y, Z, rnd.uniform(0, 6.3))
                for k in range(2):   # benches facing the middle of the park
                    p = c + V((-1) ** k * rnd.uniform(8, 15), rnd.uniform(-6, 6))
                    place('Bench', p.x, p.y, Z, rn.angle(c - p) + math.pi / 2)
                continue
            if kind == 'parking':
                for row in (y0 + 8, y1 - 13):
                    xs = []
                    for k in range(int((x1 - x0 - 16) / 2.7) + 1):
                        x = x0 + 8 + k * 2.7
                        if inside(V(x, row), 3) and inside(V(x, row + 5), 3):
                            marks.mark([V(x, row, Z + rn.MARK_Z), V(x, row + 5, Z + rn.MARK_Z)], 0.12)
                            xs.append(x)
                    if stalls is not None:   # nose in: away from the aisle between the two rows
                        nose = -1 if row < (y0 + y1) / 2 else 1
                        stalls += [((a + b) / 2, row + 2.5, Z, 0.0, nose) for a, b in zip(xs, xs[1:]) if b - a < 3]
                for x in (x0 + 5, x1 - 5):
                    if inside(V(x, (y0 + y1) / 2), 2):
                        place(rnd.choice(('Palm_A', 'Palm_B')), x, (y0 + y1) / 2, Z, rnd.uniform(0, 6.3))
                continue
            xm = (x0 + x1) / 2 + rnd.uniform(-6, 6)
            ym = (y0 + y1) / 2 + rnd.uniform(-4, 4)
            for (a, b), (cy0, cy1), north in (((x0, xm), (y0, ym), False), ((xm, x1), (y0, ym), False),
                                              ((x0, xm), (ym, y1), True), ((xm, x1), (ym, y1), True)):
                D0 = rnd.uniform(14, 26)
                for g in (1.0, 2.0, 3.0, 4.0, 6.0):   # lot corners are rounded: widen the margin until it fits
                    W = math.floor((b - a - 2 * g) / 4) * 4
                    D = min(cy1 - cy0 - 2 * g, D0)
                    cx = (a + b) / 2
                    cy = cy1 - g - D / 2 if north else cy0 + g + D / 2
                    q = [V(cx - W / 2, cy - D / 2), V(cx + W / 2, cy - D / 2), V(cx + W / 2, cy + D / 2), V(cx - W / 2, cy + D / 2)]
                    if W >= 8 and D >= 8 and all(rn.point_in_poly(p, poly) for p in q):
                        break
                else:
                    continue
                style, floors = style_for(dist, rnd)
                ob = bpy.data.objects.new('Bldg_%d_%d_%d' % (i, j, len(objs)), kit.building(style, W, D, floors, rnd).data())
                ob.location, ob.rotation_euler = (cx, cy, Z), (0, 0, math.pi if north else 0.0)   # shops face the street
                col.objects.link(ob)
                objs.append(ob)
                if style in RESIDENTIAL:   # shrubs at the front corners of apartment buildings
                    s = 1 if north else -1
                    for x in (cx - W / 2 + 1.0, cx + W / 2 - 1.0):
                        p = V(x, cy + s * (D / 2 + 0.9))
                        if inside(p, 1):
                            place('Bush_A', p.x, p.y, Z, rnd.uniform(0, 6.3))
    return objs + tiled(lots.tiles() + marks.tiles() + [t for m in statics.values() for t in m.tiles()], col)


def outline(ring):
    """Block polygon (sidewalk back edges) of the nodes around a block, CCW."""
    c = sum((n.p for n in ring), V(0, 0)) / len(ring)
    poly = []
    for n in ring:
        d = (c - n.p).normalized()
        poly += max(n.block_corners, key=lambda bc: bc[0].dot(d))[1][::-1]
    poly = rn.dedupe(poly)
    if (poly[0] - poly[-1]).length < 0.01:
        poly.pop()
    if sum(a.x * b.y - b.x * a.y for a, b in zip(poly, poly[1:] + poly[:1])) < 0:
        poly.reverse()
    return poly, c


def clip(a, b, poly, m=0.5, step=0.5):
    """Longest part of segment a -> b lying inside poly at least m from its edges (block corners are rounded)."""
    def ok(p):
        return rn.point_in_poly(p, poly) and all(rn.seg_dist(p, q, r) > m for q, r in zip(poly, poly[1:] + poly[:1]))
    if ok(a) and ok(b):
        return a, b
    n = max(1, int((b - a).length / step))
    best, cur = None, None
    for i in range(n + 1):
        if ok(a.lerp(b, i / n)):
            cur = (cur[0], i) if cur else (i, i)
            if best is None or cur[1] - cur[0] > best[1] - best[0]:
                best = cur
        else:
            cur = None
    if not best or best[1] == best[0]:
        return None
    return a.lerp(b, best[0] / n), a.lerp(b, best[1] / n)


def boundary(statics, kind, a, b, poly, Z):
    """One stretch of yard boundary (kit fences / hedges, built along +X from the origin) from 2D a to b."""
    ab = clip(a, b, poly)
    if not ab or (ab[1] - ab[0]).length < 1.0:
        return
    a, b = ab
    L = (b - a).length
    m = {'picket': lambda: kit.picket(L), 'hedge': lambda: kit.hedge(L, 1.0, 0.7),
         'tallhedge': lambda: kit.hedge(L, 1.8, 1.0), 'wood': lambda: kit.wood_fence(L),
         'chain': lambda: kit.fence(L, 1.5)}[kind]()
    kit.stamp(statics['hedge' if 'hedge' in kind else 'fence'], m, V(a.x, a.y, Z), rn.angle(b - a))


def houses(net, col, place, rnd, lots, drives, statics):
    """Residential blocks (build_net DISTRICTS): lawn lot cut into lots along its two cross-street sides, back to
    back. Per lot: a house prefab centred on its lot, set back from the sidewalk; a concrete driveway to the garage
    bay (or along the house to the back yard); a walkway to the door; foundation shrubs; trees in the front and
    back yards. Every yard is closed: front boundary along the sidewalk (gaps at the driveway and the walkway), low
    boundaries between the front yards, fences / tall hedges between the back yards and along the lot backs."""
    Z, FO = rn.CURB_H, 1.0   # FO: boundaries 1 m inside the sidewalk back edge (hedges are up to 1 m wide)
    pick = lambda table: rnd.choices(list(table), list(table.values()))[0]
    for district, ring, U, Vd, arterial in net.blocks:
        poly, c = outline(ring)
        lots.fill([poly], Z, 'Grass')
        lots.wall(poly + [poly[0]], Z, rn.GROUND_Z, 'Concrete__Curb')
        L = lambda p: ((p - c).dot(U), (p - c).dot(Vd))          # block coords (u along the side, v outward)
        loc = [L(p) for p in poly]

        def span(k):   # straight block edges: where the middle line of the other axis crosses the outline
            hits = []
            for (a0, a1), (b0, b1) in zip(loc, loc[1:] + loc[:1]):
                pa, pb, qa, qb = (a1, b1, a0, b0) if k == 0 else (a0, b0, a1, b1)
                if (pa < 0) != (pb < 0):
                    hits.append(qa + (qb - qa) * pa / (pa - pb))
            return min(hits), max(hits)
        (ue0, ue1), (v0, v1) = span(0), span(1)
        # lot depth: back to back at the block middle; along the rural loop (no sidewalk) one row only, facing
        # the inner street, backing onto the loop behind a fence and a row of trees
        depth = (v1 - v0) - FO if arterial else (v1 - v0) / 2
        setback = district['setback']
        n = max(1, round((ue1 - ue0) / district['lot']))
        lot = (ue1 - ue0) / n
        backs = [pick(district['back']) for _ in range(n)]       # one back kind per pair of back-to-back lots
        if arterial:
            for i in range(n):
                a_, b_ = c + U * (ue0 + lot * i) + Vd * (v0 + FO), c + U * (ue0 + lot * (i + 1)) + Vd * (v0 + FO)
                boundary(statics, 'tallhedge' if 'tallhedge' in district['back'] else 'wood', a_, b_, poly, Z)
            for k in range(int((ue1 - ue0) / 9)):
                p = c + U * (ue0 + 4.5 + 9 * k + rnd.uniform(-1.5, 1.5)) + Vd * (v0 + FO + rnd.uniform(2.5, 4))   # inside: the power line runs outside
                if clip(p, p, poly, 2.5):
                    place(rnd.choice(district['trees']), p.x, p.y, Z, rnd.uniform(0, 6.3))
        for vf, sg in ((v1, -1),) if arterial else ((v0, 1), (v1, -1)):   # lots facing the street at v0 (front -Vd) / v1 (+Vd)
            P = lambda u, d, vf=vf, sg=sg: c + U * u + Vd * (vf + sg * d)   # u along the block, d = depth from the sidewalk
            front = -Vd * sg
            yaw = rn.angle(front) + math.pi / 2
            ru = V(-front.y, front.x).dot(U)                     # prefab +X along +u (1) or -u (-1)

            def quad(ua, ub, d0, d1):
                q = [P(ua, d0), P(ub, d0), P(ub, d1), P(ua, d1)]
                if sum(p.x * r.y - r.x * p.y for p, r in zip(q, q[1:] + q[:1])) < 0:
                    q = q[::-1]
                drives.fill([q], Z + 0.02, 'Concrete')

            fronts = [pick(district['front']) for _ in range(n)]
            for i in range(n):
                ua, ub = ue0 + lot * i, ue0 + lot * (i + 1)
                name = pick(district['houses'])
                if name.startswith('House'):
                    name += '_' + rnd.choice(kit.HOUSE_TINTS)
                plan = HOUSE_PLANS[name.split('_')[0]]
                w, d = plan['w'], plan['d']
                uh = (ua + ub) / 2 - ru * (plan['x0'] + plan['x1']) / 2   # footprint (with a side driveway) centred
                X = lambda x: uh + ru * x                                # u of a prefab x offset
                hp = P(uh, setback + d / 2)
                place(name, hp.x, hp.y, Z, yaw)
                # driveway: to the garage bay, or along the house side to the back yard; walkway to the door
                gx, gw = plan['garage'], plan.get('gw', 3.0)
                dx = gx if gx is not None else w / 2 + 1.9
                quad(X(dx - gw / 2), X(dx + gw / 2), 0, setback if gx is not None else setback + d + 3)
                wx = plan['door']
                quad(X(wx - 0.6), X(wx + 0.6), 0, setback - 0.1)
                # front boundary along the sidewalk, open at the driveway and the walkway
                gaps = sorted([sorted((X(dx - gw / 2) - 0.4, X(dx + gw / 2) + 0.4)), sorted((X(wx) - 0.9, X(wx) + 0.9))])
                u = ua
                for g0, g1 in gaps + [(ub, ub)]:
                    if g0 - u > 1.0:
                        boundary(statics, fronts[i], P(u, FO), P(g0, FO), poly, Z)
                    u = max(u, g1)
                # side boundaries (this lot's start; the last lot also closes its end): low between the front
                # yards, back kind beside the house and between the back yards; back boundary at the block middle
                ends = ((ua + FO if i == 0 else ua, i),) + (((ub - FO, i),) if i == n - 1 else ())   # block ends: off the sidewalk
                for ub_, k in ends:
                    boundary(statics, fronts[k], P(ub_, FO), P(ub_, setback), poly, Z)
                    boundary(statics, backs[k], P(ub_, setback), P(ub_, depth), poly, Z)
                if sg > 0 and not arterial:
                    boundary(statics, backs[i], P(ua, depth), P(ub, depth), poly, Z)
                # planting: foundation shrubs along the house front (not at the door / garage), front and back trees
                for x in (-w / 2 + 1.0, w / 2 - 1.0):
                    if abs(x - wx) > 2.2 and (gx is None or abs(x - gx) > gw / 2 + 0.8) and rnd.random() < 0.8:
                        p = P(X(x), setback - 0.9)
                        place('Bush_A', p.x, p.y, Z, rnd.uniform(0, 6.3))
                free = [u for u in (ua + 2.5, (ua + ub) / 2, ub - 2.5)
                        if abs(u - X(dx)) > gw / 2 + 2 and abs(u - X(wx)) > 2.5]
                if free and rnd.random() < 0.75:
                    p = P(rnd.choice(free), rnd.uniform(2.5, setback - 2.5))
                    place(rnd.choice(district['trees']), p.x, p.y, Z, rnd.uniform(0, 6.3))
                for _ in range(rnd.randint(1, 2)):
                    p = P(rnd.uniform(ua + 2.5, ub - 2.5), rnd.uniform(setback + d + 3, depth - 2.5))
                    if depth - setback - d > 7 and clip(p, p, poly, 2.5):
                        place(rnd.choice(district['trees']), p.x, p.y, Z, rnd.uniform(0, 6.3))


# house prefab footprints (kit.PREFABS): width, depth, x of the garage bay centre (None: driveway along the house
# side) / door bay centre, footprint x range with the garage wing or the side driveway, in prefab space (front -Y)
HOUSE_PLANS = {
    'HouseA': dict(w=8, d=10, garage=None, door=2, x0=-4, x1=7.4),
    'HouseB': dict(w=12, d=10, garage=-4, door=0, x0=-6, x1=6),
    'RanchA': dict(w=16, d=10, garage=-6, door=2, x0=-8, x1=8),
    'RanchB': dict(w=12, d=12, garage=8, door=0, x0=-6, x1=10),
    'MansionA': dict(w=12, d=14, garage=10, door=0, gw=7, x0=-6, x1=14),
    'MansionB': dict(w=16, d=12, garage=12, door=2, gw=7, x0=-8, x1=16),
}


def street_signs(G, place, rnd):
    """A street-name sign on one corner of every grid junction."""
    for n in G.values():
        if n.kind == 'roundabout' or not any(c.kind == 'fillet' for c in n.corners):
            continue
        toward = V(rnd.choice((-1, 1)), rnd.choice((-1, 1))).normalized()
        p = kit.corner_spot(n, toward, 2.2)
        place('StreetSign', p.x, p.y, n.z + rn.CURB_H, rnd.uniform(0, 6.3))


def power_lines(net, place, wires):
    """Wooden power poles every 40 m along the rural loop (outer side), three wires between them."""
    for e in net.edges:
        if e.pa.left != [('lane', 3.6), ('shoulder', 1.5)] or e.a.z or e.b.z:
            continue
        s0, s1 = e.t['A'] + 8, e.L - e.t['B'] - 8
        poles = []
        for k in range(int((s1 - s0) / 40) + 1):
            p, tan = e.frame(s0 + 40 * k)
            q = p + rn.right(tan) * (e.prof(s0).width('R') + 3.0)
            yaw = rn.angle(tan) + math.pi / 2   # crossarm across the line
            place('PowerPole', q.x, q.y, 0.0, yaw)
            poles.append((q, rn.right(tan)))
        for (a, na), (b, nb) in zip(poles, poles[1:]):
            for dx in (-1.1, 0.0, 1.1):
                kit.wire(wires, V(a.x + na.x * dx, a.y + na.y * dx, 10.6), V(b.x + nb.x * dx, b.y + nb.y * dx, 10.6),
                         sag=0.5 + 0.01 * (b - a).length)


# (prefab, lateral offset from the curb, weight) per sidewalk slot; front of the prefab faces the road
FURNITURE = {
    'avenue': (('Palm_A', 2.0, 3), ('Palm_B', 2.0, 3), ('Broadleaf_B', 2.0, 2), ('TrashCan', 0.7, 1.5),
               ('Hydrant', 0.6, 1), ('Bench', 3.2, 1), ('NewsBox', 3.5, 0.6), ('Mailbox', 3.5, 0.6),
               ('BusStop', 2.6, 0.4), (None, 0, 5)),
    'street': (('Broadleaf_B', 1.6, 3), ('ParkingMeter', 0.5, 3), ('Hydrant', 0.6, 0.8), ('TrashCan', 0.6, 1),
               ('Mailbox', 2.5, 0.4), (None, 0, 4)),
    'residential': (('Broadleaf_B', 1.2, 2), ('Palm_B', 1.2, 1.5), ('Hydrant', 0.6, 0.5), (None, 0, 5)),
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
            items = FURNITURE['avenue' if walk >= 4 else 'street' if walk >= 3 else 'residential']
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


def road_layer(pts):
    """Roads mesh layers (Mesh.tiles): '' = ground-level top faces, 'Deck' = elevated top faces, 'V' = the rest
    (curbs, barriers, pillars, deck sides). Top-face tiles get a planar lightmap UV in Unity (ImportRules):
    road, sidewalk and markings then share one shadow grid; 'V' keeps Unity's generated charts."""
    n = (pts[1] - pts[0]).cross(pts[2] - pts[0])
    if n.z < 0.5 * n.length:
        return 'V'
    return 'Deck' if max(p.z for p in pts) >= rn.SOLID_BELOW else ''


def tiled(meshes, col):
    """Blender objects of the tiles (Mesh.tiles): objects named <Layer>_<i>_<j>."""
    return [m.to_object(col) for m in meshes]


def height(x, y):
    """Terrain height: flat inside FLAT (city and districts), rolling green hills beyond (Bliss)."""
    d = max(abs(x) - FLAT[0], abs(y) - FLAT[1], 0.0)
    t = rn.smooth(d / 320)
    n = 28 + 40 * noise.noise((x / 420, y / 420, 0.7)) + 12 * noise.noise((x / 150, y / 150, 1.3))
    return rn.GROUND_Z + t * max(n, 2.0)


def normal(p, e=2.0):
    """Terrain normal from the height field (exact, so the tiles shade without seams)."""
    return V(height(p.x - e, p.y) - height(p.x + e, p.y), height(p.x, p.y - e) - height(p.x, p.y + e), 2 * e).normalized()


def ground(mb, step=32):
    """Terrain quads over the whole world (smooth shaded tiles, see Mesh(smooth))."""
    for x in range(-WORLD, WORLD, step):
        for y in range(-WORLD, WORLD, step):
            mb.face([V(x, y, height(x, y)), V(x + step, y, height(x + step, y)),
                     V(x + step, y + step, height(x + step, y + step)), V(x, y + step, height(x, y + step))], 'Grass')


def turbines(place, rnd, n=14, spacing=200.0):
    """Wind turbines on the hill crests (1.05-1.7 km out), rotors facing the city, at least `spacing` apart."""
    pts = []
    for _ in range(4000):
        if len(pts) >= n:
            break
        p = V(rnd.uniform(-1700, 1700), rnd.uniform(-1700, 1700))
        r = p.length
        if not 1050 < r < 1700 or height(p.x, p.y) < 40:
            continue
        if all((p - q).length > spacing for q in pts):
            pts.append(p)
    for p in pts:
        place('WindTurbine', p.x, p.y, height(p.x, p.y) - 0.5, rn.angle(-p) + math.pi / 2)


def build(export=None, traffic=None):
    """export: scene FBX path; also writes <export>_placements.json, _peds.json, _traffic.json and the prefab FBX
    files. traffic: write only the traffic lane graph + parking spots there (nothing else exported)."""
    rnd = random.Random(7)
    kit.reset_prefab_cache()
    kit._last_shops.clear()
    net, G = build_net()
    meshes = net.build()
    col = rn.collection('City')
    objs = tiled(meshes['Props'].tiles() + meshes['Roads'].tiles(layer=road_layer) + meshes['Markings'].tiles(), col)
    placements = list(net.placements)
    place = lambda name, x, y, z, yaw: placements.append((name, x, y, z, yaw))
    stalls = []
    objs += blocks(G, col, place, rnd, stalls)
    furnish(net, place, rnd)
    street_signs(G, place, rnd)
    rnd2 = random.Random(23)   # districts and hills: their own stream, the downtown stays identical
    lots, drives = rn.Mesh('Lots', kit.grime(0.8, 0.5)), rn.Mesh('Drives', kit.grime(0.8, 0.5))
    statics = {'fence': rn.Mesh('Fences', kit.grime(0.7, 0.6)), 'hedge': rn.Mesh('Hedges', lambda p: 0.6 + 0.4 * rn.clamp(p.z / 1.8))}
    houses(net, col, place, rnd2, lots, drives, statics)
    objs += tiled(lots.tiles() + drives.tiles() + [t for m in statics.values() for t in m.tiles()], col)
    turbines(place, rnd2)
    wires = rn.Mesh('Wires')
    power_lines(net, place, wires)
    objs += tiled(wires.tiles(), col)
    gr = rn.Mesh('Ground', smooth=normal)
    ground(gr)
    objs += tiled(gr.tiles(512), col)
    if export:
        rn.export_fbx(export, objs)
        kit.export_prefabs({p[0] for p in placements})
        kit.write_placements(export[:-4] + '_placements.json', placements)
        write_peds(export[:-4] + '_peds.json', net)
        traffic = export[:-4] + '_traffic.json'
    out = {'warnings': net.warnings, 'static': len(objs), 'placed': len(placements)}
    if traffic:
        out['traffic'] = write_traffic(traffic, net, parking_spots(net, placements, stalls))
    return out


def write_peds(path, net):
    """Pedestrian graph read by Assets/GTA/Scripts/CrowdSystem.cs, in Unity coordinates (x, y, z) = (-x, z, -y):
    points flat [x, y, z, ...], links flat [i, j, crossing, ...] (net.build() must have run)."""
    pts, links = net.ped_graph()
    data = {'points': [round(v, 3) for x, y, z in pts for v in (-x, z, -y)],
            'links': [v for a, b, c in links for v in (a, b, int(c))]}
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, separators=(',', ':'))
    return {'points': len(pts), 'links': len(links), 'crossings': sum(1 for l in links if l[2])}


def export_peds(path):
    """Rebuild the network (meshes discarded) and write only the pedestrian graph."""
    net, G = build_net()
    net.build()
    return write_peds(path, net)


def parking_spots(net, placements, stalls, slot=6.5, clear=12.0):
    """Parked cars: every street parking lane (a >= 2 m shoulder against the sidewalk), in 6.5 m slots facing the
    traffic of that side, `clear` m away from the junction setbacks (corners, crosswalks, stop lines) and 5 m from
    hydrants; plus the parking-lot stalls (a quarter backed in). Returns [(x, y, z, dx, dy)] (nose direction)."""
    hydrants = [(x, y) for name, x, y, z, yaw in placements if name == 'Hydrant']
    rnd = random.Random(11)
    out = []
    for e in net.edges:
        if e.a.z or e.b.z:
            continue
        for side, sg in (('R', 1), ('L', -1)):
            strips = e.pa.side(side)
            k = next((i for i in range(len(strips) - 1) if strips[i][0] == 'shoulder' and strips[i][1] >= 2.0
                      and strips[i + 1][0] == 'sidewalk'), None)
            if k is None or e.pb.side(side) != strips:
                continue
            lat = sum(w for _, w in strips[:k]) + strips[k][1] / 2
            s = e.t['A'] + clear
            while s + slot <= e.L - e.t['B'] - clear:
                sc = s + slot / 2 + rnd.uniform(-0.4, 0.4)
                p, tan = e.frame(sc)
                q = p + rn.right(tan) * (sg * (lat + rnd.uniform(-0.12, 0.12)))
                d = tan if side == 'R' else -tan
                if all(math.hypot(q.x - hx, q.y - hy) > 5.0 for hx, hy in hydrants) and not net._under_deck(q):
                    out.append((q.x, q.y, e.z(sc), d.x, d.y))
                s += slot
    for x, y, z, dx, dy in stalls:
        sg = -1 if rnd.random() < 0.25 else 1
        out.append((x + rnd.uniform(-0.1, 0.1), y + rnd.uniform(-0.15, 0.15), z, dx * sg, dy * sg))
    return out


def write_traffic(path, net, parked=None):
    """Lane graph + parking spots read by Assets/GTA/Scripts/TrafficSystem.cs (see roadnet.Net.traffic_graph),
    Unity coordinates. parked None keeps the spots of the existing file."""
    lanes, junctions = net.traffic_graph()
    data = {'lanes': [{'pts': [round(v, 3) for x, y, z in l['pts'] for v in (-x, z, -y)], 'speed': l['speed'],
                       'junction': l['junction'], 'turn': l['turn'], 'arm': l['arm'], 'next': l['next']} for l in lanes],
            'junctions': [{'control': j['control'], 'x': -j['x'], 'z': -j['y']} for j in junctions]}
    if parked is None:
        try:
            with open(path, encoding='utf-8') as f:
                data['parked'] = json.load(f).get('parked', [])
        except OSError:
            data['parked'] = []
    else:   # x, y, z, forward x, forward z (Unity)
        data['parked'] = [round(v, 3) for x, y, z, dx, dy in parked for v in (-x, z, -y, -dx, -dy)]
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, separators=(',', ':'))
    return {'lanes': len(lanes), 'junctions': len(junctions), 'km': round(sum(
        math.dist(a, b) for l in lanes for a, b in zip(l['pts'], l['pts'][1:])) / 1000, 1),
        'dead_ends': sum(1 for l in lanes if not l['next']), 'parked': len(data['parked']) // 5}


def export_traffic(path):
    """Rebuild the city in memory (nothing else exported) and write the lane graph + parking spots."""
    return build(traffic=path)
