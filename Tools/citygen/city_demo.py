"""Demo city: US grid downtown with a central roundabout, an elevated ring highway with
four diamond interchanges, and a rural outer loop. Run inside Blender:

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
    return objs + [lots.to_object(col), marks.to_object(col)] + [m.to_object(col) for m in statics.values()]


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


def build(export=None, traffic=None):
    """export: scene FBX path; also writes <export>_placements.json, _peds.json, _traffic.json and the prefab FBX
    files. traffic: write only the traffic lane graph + parking spots there (nothing else exported)."""
    rnd = random.Random(7)
    kit.reset_prefab_cache()
    kit._last_shops.clear()
    net, G = build_net()
    meshes = net.build()
    col = rn.collection('City')
    objs = [m.to_object(col) for m in meshes.values()]
    placements = list(net.placements)
    place = lambda name, x, y, z, yaw: placements.append((name, x, y, z, yaw))
    stalls = []
    objs += blocks(G, col, place, rnd, stalls)
    furnish(net, place, rnd)
    street_signs(G, place, rnd)
    wires = rn.Mesh('Wires')
    power_lines(net, place, wires)
    objs.append(wires.to_object(col))
    gr = rn.Mesh('Ground')
    ground(gr, -900, -800, 900, 800)
    objs.append(gr.to_object(col))
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
