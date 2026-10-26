"""Art-direction test scene: one compact California street corner with every asset family
(roads + signals + stop, elevated highway, 4 building styles, street furniture, park, parking lots,
vacant lot, palms / trees / bushes with billboard LODs). Run inside Blender:

    import sys; sys.path.insert(0, r'<project>/Tools/citygen')
    import importlib, roadnet, kit, da_scene
    for m in (roadnet, kit, da_scene): importlib.reload(m)
    da_scene.build(export=r'<project>/Assets/GTA/DA/DAScene.fbx', impostors=True)

The scene FBX holds the unique geometry; repeated props are prefabs (Assets/GTA/Props/*.fbx) placed in Unity
from DAScene_placements.json by Assets/GTA/Editor/PropPlacer.cs (menu GTA > Place Props In Open Scene).
"""
import math
import random

import bpy

import kit
import roadnet as rn
from city_demo import avenue, highway, street
from roadnet import V

Z = rn.CURB_H   # sidewalk / lot top


def lot_poly(items, center):
    """Lot outline: 2D points, or junction nodes replaced by their sidewalk corner facing `center`."""
    poly = []
    for it in items:
        if isinstance(it, rn.Node):
            d = (center - it.p).normalized()
            poly += max(it.block_corners, key=lambda bc: bc[0].dot(d))[1][::-1]
        else:
            poly.append(V(*it))
    poly = rn.dedupe(poly)
    if (poly[0] - poly[-1]).length < 0.01:
        poly.pop()
    return poly


class Placer:
    """One-off objects (buildings, fences, hedge) go to the DA collection and are exported in the scene FBX.
    Repeated props are recorded as prefab placements (Unity instantiates kit.PREFABS assets) and only
    previewed in Blender in the DA_Preview collection."""

    def __init__(self, col, preview):
        self.col, self.preview, self.placements = col, preview, []

    def static(self, name, mesh, x, y, z=Z, yaw=0.0):
        ob = bpy.data.objects.new(name, mesh.data())
        ob.location, ob.rotation_euler = (x, y, z), (0, 0, yaw)
        self.col.objects.link(ob)
        return ob

    def prefab(self, name, x, y, z=Z, yaw=0.0):
        self.placements.append((name, x, y, z, yaw))
        ob = bpy.data.objects.new(name, kit.prefab_data(name))
        ob.location, ob.rotation_euler = (x, y, z), (0, 0, yaw)
        self.preview.objects.link(ob)


def build_net():
    net = rn.Net()
    A, J1 = net.node(-100, 0, kind='plain'), net.node(-50, 0, control='stop')
    J0, B = net.node(0, 0, control='signal'), net.node(90, 0, kind='plain')
    for a, b in ((A, J1), (J1, J0), (J0, B)):
        net.edge(a, b, avenue())
    net.edge(J1, net.node(-50, 60, kind='plain'), street())
    net.edge(J0, net.node(0, 60, kind='plain'), street())
    net.edge(J0, net.node(0, -80, kind='plain'), street())
    hw = net.edge(net.node(-100, -45, 7.5, kind='plain'), net.node(90, -45, 7.5, kind='plain'), highway())
    net.exit_sign(hw, 60, 'R')
    return net, J0, J1


def build(export=None, impostors=True):
    """export: path of the scene FBX; also writes <export>_placements.json and the prefab FBX files."""
    rnd = random.Random(3)
    kit.reset_prefab_cache()
    kit._last_shops.clear()
    net, J0, J1 = build_net()
    meshes = net.build()
    col, preview = rn.collection('DA'), rn.collection('DA_Preview')
    for m in meshes.values():
        m.to_object(col)
    P = Placer(col, preview)
    for name, x, y, z, yaw in net.placements:   # lamps, signal heads, stop signs from the road generator
        P.prefab(name, x, y, z, yaw)

    # ---- lots
    lots, marks = rn.Mesh('Lots', kit.grime(0.8, 0.5)), rn.Mesh('LotMarkings')
    av = 10.8   # avenue sidewalk outer edge
    for items, c, mat in (
            ([J1, J0, (-8.7, 60), (-41.3, 60)], V(-25, 35), 'Asphalt'),      # strip mall + parking
            ([J0, (90, av), (90, 60), (8.7, 60)], V(45, 35), 'Sidewalk'),     # plaza with buildings
            ([(-100, av), J1, (-58.7, 60), (-100, 60)], V(-80, 35), 'Dirt'),  # vacant lot
            ([(-100, -27), (-8.7, -27), J0, (-100, -av)], V(-50, -18), 'Grass'),   # park
            ([(8.7, -27), (90, -27), (90, -av), J0], V(50, -18), 'Asphalt')):     # parking lot
        poly = lot_poly(items, c)
        lots.fill([poly], Z, mat)
        lots.wall(poly + [poly[0]], Z, rn.GROUND_Z, 'Concrete__Curb')
    for x0, y0, y1, n in ((-38, 14, 19, 11), (-38, 39, 44, 11), (20, -25, -20, 25)):   # parking stalls
        for k in range(n + 1):
            x = x0 + k * 2.7
            marks.mark([V(x, y0, Z + rn.MARK_Z), V(x, y1, Z + rn.MARK_Z)], 0.12)
    ground = rn.Mesh('Ground')
    ground.fill([[V(*p) for p in ((-120, -100), (110, -100), (110, 80), (-120, 80))]], rn.GROUND_Z, 'Grass')
    for m in (lots, marks, ground):
        m.to_object(col)

    # ---- buildings (unique, front = -Y faces the avenue)
    for style, w, d, fl, x, y in (('strip', 28, 12, 1, -25, 52), ('brick', 12, 16, 5, 16, 19.8),
                                  ('deco', 12, 16, 8, 29, 19.8), ('office', 16, 20, 10, 44, 21.8),
                                  ('apartment', 12, 14, 3, 59, 18.8), ('spanish', 12, 12, 2, 72, 17.8),
                                  ('brickb', 8, 12, 3, 83.5, 17.8)):
        P.static('Bldg_' + style, kit.building(style, w, d, fl, rnd), x, y)

    # ---- street furniture on the north avenue sidewalk (curb at y=6.8)
    for x in (-30, 35):
        P.prefab('Hydrant', x, 7.5)
    for x in (24, 27, 30):
        P.prefab('ParkingMeter', x, 7.3)
    P.prefab('BusStop', 55, 8.9)
    P.prefab('NewsBox', 18, 10.1)
    P.prefab('Mailbox', 19.4, 10.1)
    P.prefab('TrashCan', 21.5, 7.5)
    P.prefab('TrashCan', -20, -7.5)
    for x in (-38, -26):
        P.prefab('Bench', x, -10.1, yaw=math.pi)
    p = kit.corner_spot(J1, V(1, 1).normalized(), 2.2)
    P.prefab('StreetSign', p.x, p.y)
    p = kit.corner_spot(J0, V(-1, -1).normalized(), 2.2)
    P.prefab('StreetSign', p.x, p.y, yaw=0.5)

    # ---- power poles + wires along the south sidewalk
    wires = rn.Mesh('Wires')
    poles = [-95, -65, -35, 25, 55, 85]
    for x in poles:
        P.prefab('PowerPole', x, -10.4, yaw=math.pi / 2)   # crossarm across the line
    for a, b in zip(poles, poles[1:]):
        for dx in (-1.1, 0.0, 1.1):
            kit.wire(wires, V(a, -10.4 + dx, Z + 10.6), V(b, -10.4 + dx, Z + 10.6), sag=0.5 + 0.01 * (b - a))
    wires.to_object(col)

    # ---- fences, hedge (sized to their spot: one-off)
    for i, (x, y, L, yaw) in enumerate(((-99, 11.6, 39.5, 0), (10, -26.6, 79, 0), (89.4, -26.6, 15, math.pi / 2))):
        P.static('Fence_%d' % i, kit.fence(L), x, y, yaw=yaw)
    P.static('Hedge', kit.hedge(60), 22, -12.2)

    # ---- vegetation (prefabs with billboard LODs)
    for i, x in enumerate((-92, -76, -60, -44, -28)):
        P.prefab('Palm_A' if i % 2 else 'Palm_B', x, -13.5, yaw=rnd.uniform(0, 6.3))
    for x in (-84, -52, -20):
        P.prefab('Broadleaf_A', x, -21, yaw=rnd.uniform(0, 6.3))
    for x in (32, 72):   # street trees on the sidewalk
        P.prefab('Broadleaf_B', x, 8.3, yaw=rnd.uniform(0, 6.3))
    for x in (-40, -12):  # palms in the strip mall parking
        P.prefab('Palm_A', x, 29, yaw=rnd.uniform(0, 6.3))
    for _ in range(14):
        P.prefab('Bush_A', rnd.uniform(-98, -12), rnd.uniform(-25, -16), yaw=rnd.uniform(0, 6.3))
    for _ in range(40):
        x, y = (rnd.uniform(-98, -12), rnd.uniform(-25, -13)) if rnd.random() < 0.6 else (rnd.uniform(-98, -62), rnd.uniform(13, 58))
        P.prefab('GrassTuft', x, y, yaw=rnd.uniform(0, 6.3))

    if export:
        rn.export_fbx(export, list(col.objects))
        kit.export_prefabs({p[0] for p in P.placements}, impostors)
        kit.write_placements(export[:-4] + '_placements.json', P.placements)
    return {'warnings': net.warnings, 'static': len(col.objects), 'placed': len(P.placements)}
