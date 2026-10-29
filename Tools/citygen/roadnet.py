"""roadnet: PS1-style road network generator for Blender.

A Net is a graph: Nodes (x, y, z in meters) linked by Edges (centerline polyline +
cross-section Profile). Net.build() lofts every edge, builds junctions (fillet curbs,
corner sidewalks, crosswalks, signals / stop signs), roundabouts, elevated decks with
pillars, lamps, and returns Mesh builders that become Blender objects.

Conventions: Blender Z-up, meters, drive on the right, lateral > 0 = right of the edge
direction. UVs are world-scale: 1 UV unit = UV_M meters (see ps1-art-direction skill).
Usage and recipes: .claude/skills/city-roadnet/SKILL.md
"""
import bisect
import math
import os
from types import SimpleNamespace as NS

import bpy
from mathutils import Vector, geometry

UV_M = 4.0          # 1 UV unit = 4 m -> a 128 px texture gives 32 px/m
CURB_H = 0.15
GROUND_Z = -0.10
DECK_T = 1.2        # deck thickness under elevated roads
SOLID_BELOW = 3.0   # below this height an elevated road sits on a solid embankment
MARK_Z = 0.03
MAX_SEG = 6.0       # max road segment length (vertex lighting / affine warping)
ARC_STEP = math.radians(10)
ASPHALT = ('lane', 'shoulder', 'mbarrier')
MARKS = (('MarkThin', 0.25, 0.2), ('MarkWide', 0.5, 0.5), ('MarkBar', 1.0, 9.0))   # texture, strip width, max paint
TEX_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), '..', '..', 'Assets', 'GTA', 'Textures'))

COLORS = {
    'Asphalt': (0.16, 0.16, 0.17), 'Sidewalk': (0.55, 0.54, 0.50), 'Concrete__Curb': (0.95, 0.95, 0.92),
    'Concrete': (0.47, 0.46, 0.43), 'MarkThin__Yellow': (1.0, 0.68, 0.08),
    'Grass': (0.20, 0.33, 0.14), 'Lot': (0.40, 0.39, 0.37), 'StopSign': (0.7, 0.05, 0.05), 'SignGreen': (0.05, 0.35, 0.15),
    'LampLens': (1.0, 0.95, 0.85), 'SignalMetal__Aged': (0.80, 0.70, 0.48), 'SignalHead': (0.30, 0.28, 0.10),
}


# ------------------------------------------------------------------ 2D helpers
def V(x, y, z=None):
    return Vector((x, y)) if z is None else Vector((x, y, z))


def left(d): return Vector((-d.y, d.x))
def right(d): return Vector((d.y, -d.x))
def angle(d): return math.atan2(d.y, d.x)
def lerp(a, b, t): return a + (b - a) * t
def clamp(x, a=0.0, b=1.0): return a if x < a else b if x > b else x
def smooth(t): t = clamp(t); return t * t * (3 - 2 * t)
def wrap(a): return (a + math.pi) % (2 * math.pi) - math.pi


def arc(c, r0, a0, a1, r1=None, step=ARC_STEP):
    """Points around c from angle a0 to a1 (signed sweep), radius lerped r0 -> r1."""
    r1 = r0 if r1 is None else r1
    n = max(1, math.ceil(abs(a1 - a0) / step))
    return [c + V(math.cos(lerp(a0, a1, i / n)), math.sin(lerp(a0, a1, i / n))) * lerp(r0, r1, i / n)
            for i in range(n + 1)]


def arc_to(c, p0, p1, ccw=False, step=ARC_STEP):
    """Arc around c from p0 to p1: shortest way, or counter-clockwise if ccw."""
    a0, a1 = angle(p0 - c), angle(p1 - c)
    da = (a1 - a0) % (2 * math.pi) if ccw else wrap(a1 - a0)
    pts = arc(c, (p0 - c).length, a0, a0 + da, (p1 - c).length, step)
    pts[0], pts[-1] = p0.copy(), p1.copy()
    return pts


def dedupe(pts, eps=0.01):
    out = [pts[0]]
    for p in pts[1:]:
        if (p - out[-1]).length > eps:
            out.append(p)
    return out


def offset_right(pts, w0, w1, n_first=None, n_last=None):
    """Offset a 2D polyline to its right, width lerped w0 -> w1 (mitered joints)."""
    n, out = len(pts), []
    for i, p in enumerate(pts):
        w = lerp(w0, w1, i / (n - 1))
        if i == 0 and n_first is not None:
            out.append(p + n_first * w)
        elif i == n - 1 and n_last is not None:
            out.append(p + n_last * w)
        else:
            ns = []
            if i > 0: ns.append(right((p - pts[i - 1]).normalized()))
            if i < n - 1: ns.append(right((pts[i + 1] - p).normalized()))
            m = (ns[0] + ns[-1]).normalized()
            out.append(p + m * (w / max(0.3, m.dot(ns[0]))))
    return out


def line_cross(p, d, q, e):
    """(s, t) such that p + d*s == q + e*t, or None if parallel."""
    det = -d.x * e.y + e.x * d.y
    if abs(det) < 1e-9:
        return None
    r = q - p
    return (-r.x * e.y + e.x * r.y) / det, (d.x * r.y - d.y * r.x) / det


def seg_dist(p, a, b):
    ab = b - a
    t = clamp((p - a).dot(ab) / max(ab.length_squared, 1e-9))
    return (a + ab * t - p).length


def point_in_poly(p, poly):
    inside, j = False, len(poly) - 1
    for i in range(len(poly)):
        a, b = poly[i], poly[j]
        if (a.y > p.y) != (b.y > p.y) and p.x < (b.x - a.x) * (p.y - a.y) / (b.y - a.y) + a.x:
            inside = not inside
        j = i
    return inside


# ------------------------------------------------------------------ mesh builder
class Mesh:
    """Unshared-vertex (flat shaded) mesh with one material name per face.
    shade: optional f(position) -> brightness baked into vertex colors (grime / fake AO)."""

    def __init__(self, name, shade=None, smooth=False):
        self.name, self.shade, self.smooth = name, shade, smooth   # smooth: welded, smooth shaded (terrain); a
        # callable f(p) -> normal gives exact normals (no seam between tiles)
        self.verts, self.faces, self.uvs, self.mats, self.cols = [], [], [], [], []

    def face(self, pts, mat, uvs=None):
        pts = [p if len(p) == 3 else p.to_3d() for p in pts]
        n = (pts[1] - pts[0]).cross(pts[2] - pts[0])
        if len(pts) == 4:
            n += (pts[2] - pts[0]).cross(pts[3] - pts[0])
        if n.length < 1e-6:
            return
        if uvs is None:  # box mapping in world meters
            ax = max(range(3), key=lambda i: abs(n[i]))
            uvs = [((p.x, p.y), (p.y, p.z), (p.x, p.z))[(2, 0, 1).index(ax)] for p in pts]
            uvs = [(u / UV_M, v / UV_M) for u, v in uvs]
        i = len(self.verts)
        self.verts += pts
        self.faces.append(tuple(range(i, i + len(pts))))
        self.uvs += uvs
        self.mats.append(mat)
        self.cols += [self.shade(p) if self.shade else 1.0 for p in pts]

    def card(self, c, rgt, up, w, h, mat, uv=(0, 0, 1, 1)):
        """Quad centered on 3D c spanning rgt (width w) and up (height h), UVs fitted to the uv rect.
        Faces rgt x up. Use for signs, foliage cards, billboards."""
        r, u = rgt.normalized() * (w / 2), up.normalized() * (h / 2)
        u0, v0, u1, v1 = uv
        self.face([c - r - u, c + r - u, c + r + u, c - r + u], mat, [(u0, v0), (u1, v0), (u1, v1), (u0, v1)])

    def fill(self, loops, z, mat):
        """Horizontal polygon (2D loops, extra loops are holes) at height z, facing up."""
        loops3 = [[V(p.x, p.y, z) for p in loop] for loop in loops]
        flat = [p for loop in loops3 for p in loop]
        for t in geometry.tessellate_polygon(loops3):
            a, b, c = flat[t[0]], flat[t[1]], flat[t[2]]
            if (b - a).cross(c - a).z < 0:
                b, c = c, b
            self.face([a, b, c], mat)

    def cap(self, loop3, mat, want):
        """Planar polygon from 3D points, oriented toward `want`."""
        for t in geometry.tessellate_polygon([loop3]):
            a, b, c = loop3[t[0]], loop3[t[1]], loop3[t[2]]
            if (b - a).cross(c - a).dot(want) < 0:
                b, c = c, b
            self.face([a, b, c], mat)

    def wall(self, pts, z_top, z_bot, mat, face_left=False):
        """Vertical strip along a 2D polyline (faces right of the direction by default)."""
        u = 0.0
        for a, b in zip(pts, pts[1:]):
            q = [V(a.x, a.y, z_bot), V(b.x, b.y, z_bot), V(b.x, b.y, z_top), V(a.x, a.y, z_top)]
            L = (b - a).length
            uv = [(u, z_bot), (u + L, z_bot), (u + L, z_top), (u, z_top)]
            if face_left:
                q.reverse(); uv.reverse()
            self.face(q, mat, [(x / UV_M, y / UV_M) for x, y in uv])
            u += L

    def mark(self, pts, paint, yellow=False):
        """Road-marking decal along a 3D polyline. The strip is wider than the paint: the cutout texture
        (Tools/texture/marks.py) draws ragged pixel edges. U spans the strip, V runs along it (1 UV = 4 m)."""
        if len(pts) < 2:
            return
        name, w = next(c for c in MARKS if paint <= c[2])[:2]
        mat = name + ('__Yellow' if yellow else '')
        nrm = []
        for i in range(len(pts)):
            d = (pts[min(i + 1, len(pts) - 1)] - pts[max(i - 1, 0)]).to_2d().normalized()
            nrm.append(right(d).to_3d() * (w / 2))
        v = 0.0
        for i in range(len(pts) - 1):
            p0, p1, n0, n1 = pts[i], pts[i + 1], nrm[i], nrm[i + 1]
            v1 = v + (p1 - p0).length / UV_M
            self.face([p0 - n0, p0 + n0, p1 + n1, p1 - n1], mat, [(0, v), (1, v), (1, v1), (0, v1)])
            v = v1

    def box(self, c, fwd, sx, sy, sz, mat, faces=None):
        """Box centered on 3D c; local X = 2D fwd, sizes along X, Y (left), Z.
        faces: optional {'top'|'bottom'|'px'|'nx'|'py'|'ny': material} with UVs fitted 0..1 on that face
        (texture upright, seen from outside); other faces use `mat` with world UVs. 'ny' = front (-Y)."""
        f = V(fwd.x, fwd.y, 0) * (sx / 2)
        l = V(-fwd.y, fwd.x, 0) * (sy / 2)
        u = V(0, 0, sz / 2)
        P = lambda i, j, k: c + f * i + l * j + u * k
        fit = [(0, 0), (1, 0), (1, 1), (0, 1)]
        for name, q in (('top', ((-1, -1, 1), (1, -1, 1), (1, 1, 1), (-1, 1, 1))),
                        ('bottom', ((-1, 1, -1), (1, 1, -1), (1, -1, -1), (-1, -1, -1))),
                        ('px', ((1, -1, -1), (1, 1, -1), (1, 1, 1), (1, -1, 1))),
                        ('nx', ((-1, 1, -1), (-1, -1, -1), (-1, -1, 1), (-1, 1, 1))),
                        ('py', ((1, 1, -1), (-1, 1, -1), (-1, 1, 1), (1, 1, 1))),
                        ('ny', ((-1, -1, -1), (1, -1, -1), (1, -1, 1), (-1, -1, 1)))):
            if faces and name in faces:
                self.face([P(*v) for v in q], faces[name], fit)
            else:
                self.face([P(*v) for v in q], mat)

    def extrude(self, profile, depth, front, side):
        """Prism of a 2D profile [(x, z)] (CCW seen from the front, -Y) extruded along Y, centered on y=0.
        Front/back faces map the texture `front` over the profile bounding box (photo of the object's face),
        the rim uses `side` with world UVs."""
        x0, x1 = min(p[0] for p in profile), max(p[0] for p in profile)
        z0, z1 = min(p[1] for p in profile), max(p[1] for p in profile)
        uvp = lambda x, z: ((x - x0) / (x1 - x0), (z - z0) / (z1 - z0))
        h = depth / 2
        for sgn in (-1, 1):
            pts = [V(x, sgn * h, z) for x, z in profile]
            for t in geometry.tessellate_polygon([pts]):
                tri = [pts[i] for i in t]
                if (tri[1] - tri[0]).cross(tri[2] - tri[0]).y * sgn < 0:
                    tri = [tri[0], tri[2], tri[1]]
                # back face: mirror U so the photo reads correctly from behind
                self.face(tri, front, [(uvp(p.x, p.z)[0] if sgn < 0 else 1 - uvp(p.x, p.z)[0], uvp(p.x, p.z)[1]) for p in tri])
        n = len(profile)
        u = 0.0
        for i in range(n):
            (ax, az), (bx, bz) = profile[i], profile[(i + 1) % n]
            L = math.hypot(bx - ax, bz - az)
            q = [V(ax, -h, az), V(ax, h, az), V(bx, h, bz), V(bx, -h, bz)]
            self.face(q, side, [(u / UV_M, 0), (u / UV_M, depth / UV_M), ((u + L) / UV_M, depth / UV_M), ((u + L) / UV_M, 0)])
            u += L

    def cyl(self, p0, p1, r, sides, mat, rot=0.0, r1=None, cap_uv=False, back_mat=None, wrap=False):
        """Prism (or frustum if r1) between 3D points p0 and p1, capped.
        cap_uv: the p1 cap gets UVs fitted 0..1 (sign faces); back_mat: material of the p0 cap;
        wrap: side UVs span the texture exactly once around and along (unrolled photo of the object)."""
        r1 = r if r1 is None else r1
        ax = (p1 - p0).normalized()
        ref = V(0, 0, 1) if abs(ax.z) < 0.9 else V(1, 0, 0)
        u = (ref - ax * ref.dot(ax)).normalized()
        w = ax.cross(u)
        ring = lambda c, rr: [c + (u * math.cos(rot + 2 * math.pi * i / sides) +
                                   w * math.sin(rot + 2 * math.pi * i / sides)) * rr for i in range(sides)]
        A, B = ring(p0, r), ring(p1, r1)
        cu = 2 * math.pi * max(r, r1) / sides / UV_M          # cylindrical UVs, world scale
        va, vb = p0.dot(ax) / UV_M, p1.dot(ax) / UV_M          # continuous across stacked segments
        if wrap:
            cu, va, vb = 1 / sides, 0.0, 1.0
        for i in range(sides):
            j = (i + 1) % sides
            self.face([A[i], A[j], B[j], B[i]], mat, [(i * cu, va), ((i + 1) * cu, va), ((i + 1) * cu, vb), (i * cu, vb)])
        uv = None
        if cap_uv:   # fit the texture on the cap's bounding box (sign photo filling its image)
            angs = [rot + 2 * math.pi * i / sides for i in range(sides)]
            us, vs = [-math.sin(a) for a in angs], [math.cos(a) for a in angs]
            uv = [((x - min(us)) / (max(us) - min(us)), (y - min(vs)) / (max(vs) - min(vs))) for x, y in zip(us, vs)]
        self.face(B, mat, uv)
        self.face(A[::-1], back_mat or mat)

    def loft(self, p0, fwd, up, rings, sides, mat, bottom=None, rot=0.0):
        """Closed elliptic tube along fwd: rings = [(t, half_width, half_height)] (lamp heads, rounded props).
        bottom: material for the downward faces, UVs projected from below over the whole shape (u across,
        v along fwd) so a photo of the object's underside lands on the model itself."""
        side = fwd.cross(up)
        ang = [rot + 2 * math.pi * i / sides for i in range(sides)]
        R = [[p0 + fwd * t + side * (math.cos(a) * rw) + up * (math.sin(a) * rh) for a in ang] for t, rw, rh in rings]
        L, W = rings[-1][0] - rings[0][0], max(r[1] for r in rings)
        proj = lambda p: (0.5 + (p - p0).dot(side) / (2 * W), ((p - p0).dot(fwd) - rings[0][0]) / L)
        for A, B in zip(R, R[1:]):
            for i in range(sides):
                j = (i + 1) % sides
                q = [A[i], B[i], B[j], A[j]]
                n = (q[1] - q[0]).cross(q[3] - q[0])
                if bottom and n.normalized().dot(up) < -0.6:
                    self.face(q, bottom, [proj(p) for p in q])
                else:
                    self.face(q, mat)
        self.face(R[0], mat)
        self.face(R[-1][::-1], mat)

    def tiles(self, size=128.0, layer=None):
        """Split into one Mesh per `size` m cell named '<Name>_<i>_<j>' (faces by centroid): small renderers
        (frustum culling) whose lightmap charts keep the full texel density. layer(pts) -> name suffix groups faces
        into separate layers first (city_demo.road_layer: ground / deck / vertical). Empty mesh -> []."""
        out = {}
        for f, mat in zip(self.faces, self.mats):
            pts = [self.verts[i] for i in f]
            c = sum(pts, Vector((0, 0, 0))) / len(pts)
            name = '%s%s_%d_%d' % (self.name, layer(pts) if layer else '', math.floor(c.x / size), math.floor(c.y / size))
            m = out.get(name)
            if m is None:
                m = out[name] = Mesh(name, smooth=self.smooth)
            k = len(m.verts)
            m.verts += pts
            m.faces.append(tuple(range(k, k + len(f))))
            m.uvs += [self.uvs[i] for i in f]
            m.mats.append(mat)
            m.cols += [self.cols[i] for i in f]
        return list(out.values())

    def to_object(self, collection):
        ob = bpy.data.objects.new(self.name, self.data())
        collection.objects.link(ob)
        return ob

    def data(self):
        me = bpy.data.meshes.new(self.name)
        me.from_pydata([tuple(v) for v in self.verts], [], self.faces)
        names = sorted(set(self.mats))
        for n in names:
            me.materials.append(material(n))
        idx = {n: i for i, n in enumerate(names)}
        me.polygons.foreach_set('material_index', [idx[m] for m in self.mats])
        me.uv_layers.new(name='UVMap').data.foreach_set('uv', [c for uv in self.uvs for c in uv])
        col = me.color_attributes.new('Col', 'FLOAT_COLOR', 'CORNER')
        col.data.foreach_set('color', [c for v in self.cols for c in (v, v, v, 1.0)])
        me.color_attributes.active_color = col
        if self.smooth:
            import bmesh
            bm = bmesh.new()
            bm.from_mesh(me)
            bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=0.01)
            bm.to_mesh(me)
            bm.free()
            me.polygons.foreach_set('use_smooth', [True] * len(me.polygons))
            if callable(self.smooth):
                me.normals_split_custom_set_from_vertices([tuple(self.smooth(v.co)) for v in me.vertices])
        me.update()
        return me


def material(name):
    """Material naming contract with Unity (ImportRules.cs): 'Foo' uses T_Foo.png if it exists, else its
    color; 'Foo__Tint' uses T_Foo.png multiplied by the COLORS tint. Blender preview mirrors that."""
    m = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    tex = os.path.join(TEX_DIR, 'T_%s.png' % name.split('__')[0])
    has_tex = os.path.exists(tex)
    col = (1, 1, 1) if has_tex and '__' not in name else COLORS.get(name, (1, 0, 1))
    m.diffuse_color = (*col, 1)
    m.use_nodes = True
    nt = m.node_tree
    for n in [n for n in nt.nodes if n.type in ('TEX_IMAGE', 'MIX', 'MATH')]:
        nt.nodes.remove(n)
    bsdf = nt.nodes.get('Principled BSDF')
    bsdf.inputs['Base Color'].default_value = (*col, 1)
    bsdf.inputs['Roughness'].default_value = 1.0
    bsdf.inputs['Alpha'].default_value = 1.0
    if has_tex:
        img = nt.nodes.new('ShaderNodeTexImage')
        img.image = bpy.data.images.load(tex, check_existing=True)
        img.image.reload()
        img.interpolation = 'Closest'
        mix = nt.nodes.new('ShaderNodeMix')
        mix.data_type, mix.blend_type = 'RGBA', 'MULTIPLY'
        mix.inputs['Factor'].default_value = 1.0
        nt.links.new(img.outputs['Color'], mix.inputs['A'])
        mix.inputs['B'].default_value = (*col, 1)
        nt.links.new(mix.outputs['Result'], bsdf.inputs['Base Color'])
        cut = nt.nodes.new('ShaderNodeMath')
        cut.operation = 'GREATER_THAN'
        cut.inputs[1].default_value = 0.5
        nt.links.new(img.outputs['Alpha'], cut.inputs[0])
        nt.links.new(cut.outputs['Value'], bsdf.inputs['Alpha'])
    return m


def signal_head(mb, c, face):
    """US 3-section signal head centered on 3D c, facing 2D `face`: housing box, textured front, 3 visors."""
    f3, side = face.to_3d(), V(-face.y, face.x, 0)
    mb.box(c, face, 0.25, 0.34, 1.0, 'SignalMetal__Aged')
    mb.card(c + f3 * 0.13, side, V(0, 0, 1), 0.34, 1.0, 'SignalHead')
    for dz in (0.31, 0.0, -0.31):          # visors: top + two cheeks, double-sided
        top = c + f3 * 0.13 + V(0, 0, dz + 0.14)
        for q in ([top - side * 0.14, top + side * 0.14, top + side * 0.14 + f3 * 0.22 - V(0, 0, 0.03),
                   top - side * 0.14 + f3 * 0.22 - V(0, 0, 0.03)],
                  [top - side * 0.14, top - side * 0.14 + f3 * 0.2 - V(0, 0, 0.03), top - side * 0.14 + f3 * 0.08 - V(0, 0, 0.2),
                   top - side * 0.14 - V(0, 0, 0.22)],
                  [top + side * 0.14, top + side * 0.14 - V(0, 0, 0.22), top + side * 0.14 + f3 * 0.08 - V(0, 0, 0.2),
                   top + side * 0.14 + f3 * 0.2 - V(0, 0, 0.03)]):
            mb.face(q, 'SignalMetal__Aged')
            mb.face(q[::-1], 'SignalMetal__Aged')


def lamp(mb, base, z, toward, h=7.5, heads=1):
    """Cobra-head street light: tapered pole, curved davit arm(s), rounded head with a textured lens."""
    mb.cyl(V(base.x, base.y, z), V(base.x, base.y, z + h), 0.13, 6, 'PoleMetal', r1=0.08)
    for k in range(heads):
        d = (toward if k == 0 else -toward).to_3d()
        arm = [V(base.x, base.y, z + h - 0.8) + d * x + V(0, 0, dz) for x, dz in ((0, 0), (0.25, 0.55), (0.8, 0.85), (1.9, 0.95))]
        for a, b in zip(arm, arm[1:]):
            mb.cyl(a, b, 0.05, 4, 'PoleMetal')
        # flat-bottomed hexagonal head, the underside photo is mapped on its bottom face
        mb.loft(arm[-1] - V(0, 0, 0.02), d, V(0, 0, 1), ((0, 0.07, 0.05), (0.22, 0.2, 0.1), (0.72, 0.13, 0.07)), 6,
                'PoleMetal', bottom='LampLens')


def sign(mb, p, z, face, kind):
    """Traffic sign on a post at 2D p, ground z, facing 2D `face`. kind: stop | yield."""
    mb.cyl(V(p.x, p.y, z), V(p.x, p.y, z + 2.5), 0.04, 4, 'PoleMetal')
    c, f = V(p.x, p.y, z + 2.3), face.to_3d()
    if kind == 'stop':
        mb.cyl(c + f * 0.05, c + f * 0.08, 0.4, 8, 'StopSign', math.pi / 8, cap_uv=True, back_mat='PoleMetal')
    else:
        mb.cyl(c + f * 0.05, c + f * 0.08, 0.5, 3, 'YieldSign', math.pi, cap_uv=True, back_mat='PoleMetal')


def hermite(p0, t0, p1, t1):
    """Cubic Hermite from 3D point p0 (2D tangent t0) to p1 (tangent t1), sampled every ~2 m, z lerped."""
    P0, P1 = V(*p0), V(*p1)
    m = (P1 - P0).to_2d().length
    T0, T1 = V(t0.x, t0.y, 0) * m, V(t1.x, t1.y, 0) * m
    k = max(3, math.ceil(m / 2.0))
    pts = []
    for i in range(k + 1):
        t = i / k
        q = P0 * (2 * t ** 3 - 3 * t * t + 1) + T0 * (t ** 3 - 2 * t * t + t) + P1 * (-2 * t ** 3 + 3 * t * t) + T1 * (t ** 3 - t * t)
        pts.append((q.x, q.y, lerp(p0[2], p1[2], t)))
    return pts


def lane_speed(prof):
    """Traffic speed limit (m/s) by road type: highway 100 km/h, rural 70, avenue 50, street 40, ramp 45."""
    kinds = [k for k, _ in prof.left + prof.right]
    if 'mbarrier' in kinds:
        return 28.0
    if prof.oneway:
        return 12.5
    if 'sidewalk' not in kinds:
        return 20.0
    return 14.0 if sum(1 for k, w in prof.right if k == 'lane') >= 2 else 11.0


# ------------------------------------------------------------------ profiles
class Profile:
    """Cross-section. left/right: [(kind, width)] from the centerline outward.
    kinds: lane, shoulder, mbarrier (half median barrier), sidewalk, barrier (deck edge).
    marks: [(lateral, 'solid'|'dashed'|'double'|'none', 'W'|'Y')], lateral > 0 = right.
    'none' keeps mark counts equal between tapered profiles."""

    def __init__(self, left, right, marks=(), oneway=False):
        self.left = [tuple(s) for s in left]
        self.right = [tuple(s) for s in right]
        self.marks = [tuple(m) for m in marks]
        self.oneway = oneway

    def side(self, s): return self.left if s == 'L' else self.right
    def asphalt(self, s): return sum(w for k, w in self.side(s) if k in ASPHALT)
    def walk(self, s): return sum(w for k, w in self.side(s) if k == 'sidewalk')
    def width(self, s): return sum(w for k, w in self.side(s))

    def lanes(self, s):
        x, out = 0.0, []
        for k, w in self.side(s):
            if k == 'lane' and w > 0.5:
                out.append(x + w / 2)
            x += w
        return out

    def lerp(self, o, t):
        if o is self or t <= 0:
            return self
        mix = lambda A, B: [(k, lerp(w, w2, t)) for (k, w), (_, w2) in zip(A, B)]
        marks = [(lerp(a[0], b[0], t), a[1] if a[1] != 'none' else b[1], a[2])
                 for a, b in zip(self.marks, o.marks)]
        return Profile(mix(self.left, o.left), mix(self.right, o.right), marks, self.oneway)

    def section(self, fl=1.0, fr=1.0):
        """Closed section [(lat, h)] left->right over the top then back under; h None = bottom.
        mats[i] is the material of segment i -> i+1 (cyclic). fl/fr fade edge barrier heights."""
        def half(strips, f):
            pts = [(0.0, 0.85 if strips and strips[0][0] == 'mbarrier' else 0.0)]
            mats, x = [], 0.0
            for kind, w in strips:
                if kind == 'mbarrier':
                    pts += [(0.08, 0.85), (0.16, 0.3), (w, 0.0)]; mats += ['Concrete'] * 3
                elif kind in ('lane', 'shoulder'):
                    pts.append((x + w, 0.0)); mats.append('Asphalt')
                elif kind == 'sidewalk':
                    pts += [(x, CURB_H), (x + w, CURB_H)]; mats += ['Concrete__Curb', 'Sidewalk']
                elif kind == 'barrier':   # fades by height only (down to a flat strip), never by width
                    pts += [(x + 0.2 * w, 0.3 * f), (x + 0.4 * w, 0.85 * f), (x + w, 0.85 * f)]
                    mats += ['Concrete'] * 3
                x += w
            pts.append((x, None))
            mats.append('Concrete__Curb' if strips and strips[-1][0] == 'sidewalk' else 'Concrete')
            return pts, mats

        lp, lm = half(self.left, fl)
        rp, rm = half(self.right, fr)
        pts = [(-x, h) for x, h in lp[::-1]]
        mats = lm[::-1]
        if rp[0] == lp[0]:
            pts += rp[1:]
        else:
            mats.append('Concrete'); pts += rp
        return pts, mats + rm + ['Concrete']


# ------------------------------------------------------------------ graph
class Node:
    def __init__(self, x, y, z, kind, control, curb_r, ring):
        self.p, self.z = V(x, y), z
        self.kind, self.control, self.curb_r, self.ring = kind, control, curb_r, ring
        self.edges, self.arms, self.corners, self.block_corners = [], [], [], []


class Edge:
    def __init__(self, a, b, prof, prof_b=None, pts=(), flat=(0.0, 0.0), no_barrier=None):
        self.a, self.b, self.pa, self.pb = a, b, prof, prof_b or prof
        self.line = dedupe([a.p] + [V(*p[:2]) for p in pts] + [b.p])
        self.cum = [0.0]
        for p, q in zip(self.line, self.line[1:]):
            self.cum.append(self.cum[-1] + (q - p).length)
        self.L = self.cum[-1]
        self.flat, self.no_barrier = flat, no_barrier or {}
        self.t = {'A': 0.0, 'B': 0.0}          # junction setbacks
        self.mark_from = {'A': 0.0, 'B': 0.0}  # lane markings start (from each end)

    def at(self, s):
        s = clamp(s, 0.0, self.L)
        i = min(bisect.bisect_right(self.cum, s) - 1, len(self.line) - 2)
        seg = max(self.cum[i + 1] - self.cum[i], 1e-9)
        return self.line[i].lerp(self.line[i + 1], (s - self.cum[i]) / seg)

    def frame(self, s):
        return self.at(s), (self.at(s + 0.5) - self.at(s - 0.5)).normalized()

    def z(self, s):
        fa, fb = self.flat
        return lerp(self.a.z, self.b.z, smooth((s - fa) / max(self.L - fa - fb, 1e-6)))

    def prof(self, s):
        return self.pa.lerp(self.pb, s / self.L)

    def barrier_f(self, s, side):
        """Barrier scale: full height everywhere (also at grade), sloped ends at junctions and no_barrier gaps."""
        f = 1.0
        sa, sb = self.no_barrier.get(side, (0.0, 0.0))
        if sa: f *= clamp((s - sa) / 10.0)
        if sb: f *= clamp((self.L - sb - s) / 10.0)
        if self.t['A']: f *= clamp((s - self.t['A']) / 3.0)
        if self.t['B']: f *= clamp((self.L - self.t['B'] - s) / 3.0)
        return f

    def samples(self):
        s0, s1 = self.t['A'], self.L - self.t['B']
        ss = [s0] + [c for c in self.cum[1:-1] if s0 < c < s1] + [s1]
        out = [ss[0]]
        for a, b in zip(ss, ss[1:]):
            k = max(1, math.ceil((b - a) / MAX_SEG))
            out += [lerp(a, b, i / k) for i in range(1, k + 1)]
        return out


class Net:
    def __init__(self):
        self.nodes, self.edges, self.signs, self.warnings = [], [], [], []
        self.gores = []        # (highway edge, ramp edge): solid median between their facing barriers
        self.placements = []   # (prefab, x, y, z, yaw): repeated props become Unity prefab instances

    def node(self, x, y, z=0.0, kind='auto', control=None, curb_r=8.0, ring=None):
        """kind: auto | plain (no junction) | roundabout (ring=(r_island, r_outer, r_fillet)).
        control: None | 'signal' | 'stop' | 'yield'."""
        n = Node(x, y, z, 'roundabout' if ring else kind, control, curb_r, ring)
        self.nodes.append(n)
        return n

    def edge(self, a, b, prof, **kw):
        """kw: prof_b (taper to), pts (intermediate centerline points), flat (flat lengths at
        each end for the z easing), no_barrier ({'L'|'R': (len_from_A, len_from_B)})."""
        e = Edge(a, b, prof, **kw)
        a.edges.append((e, 'A'))
        b.edges.append((e, 'B'))
        self.edges.append(e)
        return e

    def place(self, prefab, p, z, yaw):
        """Record a prefab instance (kit.PREFABS name) at 2D p, height z, Blender yaw in radians."""
        self.placements.append((prefab, p.x, p.y, z, yaw))

    def exit_sign(self, e, s, side='R'):
        self.signs.append((e, s, side))

    def gore(self, hw, ramp):
        """Ramp leaving / joining hw side by side: its facing barrier and hw's sit back to back from the nose;
        the gap between them is capped into one solid median until the decks are apart."""
        self.gores.append((hw, ramp))

    # -------------------------------------------------------------- build
    def build(self):
        out = {'Roads': Mesh('Roads'), 'Markings': Mesh('Markings'), 'Props': Mesh('Props')}
        for n in self.nodes:
            self._prepare(n)
        self._index()
        for n in self.nodes:
            self._junction(n, out)
        for e in self.edges:
            self._edge(e, out)
        self._pillars(out['Roads'])
        self._lamps(out['Props'])
        for e, s, side in self.signs:
            self._exit_sign(out['Props'], e, s, side)
        for hw, rp in self.gores:
            self._gore(out['Roads'], hw, rp)
        return out

    # -------------------------------------------------------------- pedestrians
    def ped_graph(self, cross_at=2.5):
        """Pedestrian network for the Unity crowd (call after build()): the middle line of every sidewalk along the
        edges, around every junction corner, through plain nodes, and across every crosswalk (cross_at m past the
        setback, where the bars are). Returns (points [(x, y, z)], links [(i, j, crossing)]), Blender coordinates."""
        pts, links, ends = [], [], {}

        def chain(poly, cross=False):
            ids = []
            for p, z in poly:
                pts.append((p.x, p.y, z))
                ids.append(len(pts) - 1)
            links.extend((a, b, cross) for a, b in zip(ids, ids[1:]))
            return ids

        for e in self.edges:
            s0, s1 = e.t['A'], e.L - e.t['B']
            if s1 - s0 < 0.5:
                continue
            anchors = {'A': s0 + cross_at, 'B': s1 - cross_at}
            ss = sorted(set(e.samples() + [s for s in anchors.values() if s0 < s < s1]))
            for side in 'LR':
                if any(e.prof(s).walk(side) <= 0 for s in ss):
                    continue
                poly = []
                for s in ss:
                    p, d = e.frame(s)
                    pr = e.prof(s)
                    poly.append((p + (left(d) if side == 'L' else right(d)) * (pr.asphalt(side) + pr.walk(side) / 2), e.z(s) + CURB_H))
                ids = chain(poly)
                ends[(id(e), side, 'A')], ends[(id(e), side, 'B')] = ids[0], ids[-1]
                for end, s in anchors.items():
                    if s in ss:
                        ends[(id(e), side, end, 'x')] = ids[ss.index(s)]

        def link(ka, kb, cross=False):
            if ka in ends and kb in ends:
                links.append((ends[ka], ends[kb], cross))

        for n in self.nodes:
            if n.k == 'plain':   # straight through: left of one arm continues on the right of the other
                if len(n.edges) == 2:
                    a, b = [self._arm(n, e, end) for e, end in n.edges]
                    link((id(a.e), a.ls, a.end), (id(b.e), b.rs, b.end))
                    link((id(a.e), a.rs, a.end), (id(b.e), b.ls, b.end))
                continue
            z = n.z + CURB_H
            for c in n.corners:
                a, b = c.a, c.b
                ka, kb = (id(a.e), a.ls, a.end), (id(b.e), b.rs, b.end)
                if not c.outer or ka not in ends or kb not in ends:
                    continue
                wa, wb = a.swL or b.swR, b.swR or a.swL
                mid = dedupe(offset_right(c.curb, wa / 2, wb / 2, a.l, -b.l))
                ids = chain([(p, z) for p in mid[1:-1]]) if len(mid) > 2 else []
                path = [ends[ka]] + ids + [ends[kb]]   # chain() already linked the inner points
                links.append((path[0], path[1], False))
                if len(path) > 2:
                    links.append((path[-2], path[-1], False))
            if n.control:
                for a in n.arms:
                    if a.swL and a.swR:
                        link((id(a.e), a.ls, a.end, 'x'), (id(a.e), a.rs, a.end, 'x'), True)
        return pts, links

    # -------------------------------------------------------------- traffic
    def traffic_graph(self):
        """Lane graph for the Unity traffic (call after build()). One polyline per lane in travel order (drive on
        the right: right-side lanes run A->B, left-side B->A, one-way edges A->B with one centre lane), tapered
        lanes (highway exits / entrances) start or end on their neighbour lane, junction connectors (straight /
        right / left Hermite curves), roundabout ring + entries / exits. A lane whose last point lies on another
        lane's first point continues into it ('next'). Blender coordinates.
        Returns (lanes [{'pts', 'speed', 'junction', 'turn', 'arm', 'next'}], junctions [{'control', 'x', 'y'}]);
        turn: 0 straight, 1 right, 2 left, 3 ring, 5 exit, 6 merge (tapered lanes); arm: signal group (0 = E-W, 1 = N-S)."""
        MIN, BLEND = 2.0, 40.0
        lanes, junctions = [], []
        arrive, depart = {}, {}   # (id(e), end) -> [(distance from the centre, lane id)] ending at / starting from that end

        def add(pts, speed, junction=-1, turn=0, arm=-1):
            lanes.append({'pts': pts, 'speed': speed, 'junction': junction, 'turn': turn, 'arm': arm, 'next': []})
            return len(lanes) - 1

        for e in self.edges:
            if e.L - e.t['A'] - e.t['B'] < 0.5:
                continue
            ss = e.samples()
            s0, s1 = ss[0], ss[-1]
            speed = lane_speed(e.pa)
            w_at = lambda side, k, s: lerp(e.pa.side(side)[k][1], e.pb.side(side)[k][1], s / e.L)
            merged = e.pa.oneway and e.pa.left and e.pa.right and e.pa.left[0][0] == e.pa.right[0][0] == 'lane'

            def W(d, s):
                side, k, _ = d
                return w_at('L', 0, s) + w_at('R', 0, s) if side == 'C' else w_at(side, k, s)

            def X(d, s):   # lane centre, + = right of the edge direction
                side, k, _ = d
                if side == 'C':
                    return (w_at('R', 0, s) - w_at('L', 0, s)) / 2
                x = sum(w_at(side, j, s) for j in range(k)) + w_at(side, k, s) / 2
                return x if side == 'R' else -x

            descs = [('C', 0, True)] if merged else []
            for side in 'LR':
                for k, (kind, _) in enumerate(e.pa.side(side)):
                    if kind == 'lane' and not (merged and k == 0):
                        descs.append((side, k, side == 'R' or e.pa.oneway))   # (side, strip, travels A->B)
            spans, splits = {}, {}
            for d in descs:
                w0, w1 = W(d, 0), W(d, e.L)
                if w0 >= MIN and w1 >= MIN:
                    spans[d] = (s0, s1, None)
                elif w0 >= MIN or w1 >= MIN:
                    sc = (MIN - w0) / (w1 - w0) * e.L
                    if w1 >= MIN and sc > s0:
                        spans[d] = (sc, s1, sc)
                    elif w0 >= MIN and sc < s1:
                        spans[d] = (s0, sc, sc)
                    else:
                        spans[d] = (s0, s1, None)
            full = [d for d, (_, _, sa) in spans.items() if sa is None]
            nbr = {}
            for d, (lo, hi, sa) in spans.items():
                if sa is not None:
                    nbr[d] = min((f for f in full if f[0] == d[0]), key=lambda f: abs(X(f, sa) - X(d, sa)))
                    splits.setdefault(nbr[d], set()).add(sa)
            for d, (lo, hi, sa) in spans.items():
                S = sorted({s for s in ss if lo <= s <= hi} | {lo, hi} | {sp for sp in splits.get(d, ()) if lo < sp < hi})
                pts = []
                for s in S:
                    x = X(d, s)
                    if sa is not None:   # tapered lane: leaves / joins its neighbour smoothly
                        x = lerp(X(nbr[d], s), x, smooth(abs(s - sa) / min(BLEND, hi - lo)))
                    p, t = e.frame(s)
                    q = p + right(t) * x
                    pts.append(((q.x, q.y, e.z(s)), s))
                if not d[2]:
                    pts.reverse()
                cuts = [i for i, (_, s) in enumerate(pts) if s in splits.get(d, ())]
                turn = 0 if sa is None else (5 if (hi == s1) == d[2] else 6)   # tapered: leaving (exit) or joining (merge)
                for i0, i1 in zip([0] + cuts, cuts + [len(pts) - 1]):
                    piece = pts[i0:i1 + 1]
                    li = add([p for p, _ in piece], speed, turn=turn)
                    dist = abs(X(d, piece[0][1]))
                    if piece[0][1] == (s0 if d[2] else s1):
                        depart.setdefault((id(e), 'A' if d[2] else 'B'), []).append((dist, li))
                    if piece[-1][1] == (s1 if d[2] else s0):
                        arrive.setdefault((id(e), 'B' if d[2] else 'A'), []).append((dist, li))

        for n in self.nodes:
            if n.k == 'plain':
                continue
            j = len(junctions)
            ctl = {'signal': 1, 'stop': 2, 'yield': 3}.get(n.control, 0)
            junctions.append({'control': ctl, 'x': n.p.x, 'y': n.p.y})
            if n.k == 'roundabout':
                self._ring_lanes(n, j, lanes, add, arrive, depart)
                continue
            for a in n.arms:
                ins = sorted(arrive.get((id(a.e), a.end), []))
                grp = 0 if abs(a.d.x) >= abs(a.d.y) else 1
                for b in n.arms:
                    outs = sorted(depart.get((id(b.e), b.end), []))
                    if b is a or not ins or not outs:
                        continue
                    ang = wrap(angle(b.d) - angle(-a.d))
                    if abs(ang) > 2.6:   # U-turn
                        continue
                    turn = 0 if abs(ang) < 0.5 else (1 if ang < 0 else 2)
                    if turn == 0:
                        pairs = {(ins[min(i, len(ins) - 1)][1], outs[min(i, len(outs) - 1)][1]) for i in range(max(len(ins), len(outs)))}
                    else:
                        pairs = {(ins[-1][1], outs[-1][1]) if turn == 1 else (ins[0][1], outs[0][1])}
                    for li, lo in sorted(pairs):
                        add(hermite(lanes[li]['pts'][-1], -a.d, lanes[lo]['pts'][0], b.d), (10.0, 5.0, 6.0)[turn], j, turn,
                            grp if ctl == 1 else -1)

        starts = {}
        for i, l in enumerate(lanes):
            x, y, _ = l['pts'][0]
            starts.setdefault((int(x // 2), int(y // 2)), []).append(i)
        for i, l in enumerate(lanes):
            x, y, _ = l['pts'][-1]
            cx, cy = int(x // 2), int(y // 2)
            l['next'] = sorted(k for dx in (-1, 0, 1) for dy in (-1, 0, 1) for k in starts.get((cx + dx, cy + dy), ())
                               if k != i and math.hypot(lanes[k]['pts'][0][0] - x, lanes[k]['pts'][0][1] - y) < 0.6)
        return lanes, junctions

    def _ring_lanes(self, n, j, lanes, add, arrive, depart):
        """Roundabout: one lane around the outer ring (counter-clockwise, drive on the right), cut at every arm's
        exit (before the arm) and entry (after it); Hermite entries / exits from the arms' lanes."""
        # ponytail: one ring lane (the outer one); add the inner lane when the roundabout jams
        R, z = n.ring[1] - 2.5, n.z
        d = math.asin(3.5 / R)
        pt = lambda th: (n.p.x + R * math.cos(th), n.p.y + R * math.sin(th), z)
        tang = lambda th: V(-math.sin(th), math.cos(th))
        ring = lambda a0, a1: [(p.x, p.y, z) for p in arc(n.p, R, a0, a1, step=math.radians(5))]
        m = len(n.arms)
        for i, a in enumerate(n.arms):
            b = n.arms[(i + 1) % m]
            th_exit, th_entry = a.ang - d, a.ang + d
            nb_exit = (b.ang if i + 1 < m else b.ang + 2 * math.pi) - d
            add(ring(th_exit, th_entry), 7.0, j, 3)
            add(ring(th_entry, nb_exit), 7.0, j, 3)
            for _, li in arrive.get((id(a.e), a.end), []):
                add(hermite(lanes[li]['pts'][-1], -a.d, pt(th_entry), tang(th_entry)), 6.0, j, 0)
            for _, lo in depart.get((id(a.e), a.end), []):
                add(hermite(pt(th_exit), tang(th_exit), lanes[lo]['pts'][0], a.d), 5.0, j, 1)

    def _arm(self, n, e, end):
        if end == 'A':
            p0, p1, prof, ls, rs = e.at(0), e.at(min(3, e.L)), e.pa, 'L', 'R'
        else:
            p0, p1, prof, ls, rs = e.at(e.L), e.at(max(0, e.L - 3)), e.pb, 'R', 'L'
        d = (p1 - p0).normalized()
        return NS(e=e, end=end, d=d, l=left(d), ang=angle(d), prof=prof, ls=ls, rs=rs,
                  hwL=prof.asphalt(ls), hwR=prof.asphalt(rs), swL=prof.walk(ls), swR=prof.walk(rs),
                  incoming=not prof.oneway or end == 'B', t=0.0)

    def _kind(self, n):
        if n.kind != 'auto':
            return n.kind
        if len(n.edges) >= 3:
            return 'junction'
        if len(n.edges) == 2:
            a, b = [self._arm(n, e, end) for e, end in n.edges]
            return 'plain' if a.d.dot(b.d) < -0.999 else 'junction'
        return 'plain'

    def P(self, n, a, s, lat):
        return n.p + a.d * s + a.l * lat

    def _prepare(self, n):
        n.k = self._kind(n)
        if n.k == 'plain':
            return
        n.arms = sorted((self._arm(n, e, end) for e, end in n.edges), key=lambda a: a.ang)
        (self._prep_ring if n.k == 'roundabout' else self._prep_junction)(n)
        for a in n.arms:
            a.e.t[a.end] = a.t
            a.e.mark_from[a.end] = a.t + (5.5 if n.control else 0.0)

    def _prep_junction(self, n):
        arms, R, m, P = n.arms, n.curb_r, len(n.arms), self.P
        for k in range(m):
            a, b = arms[k], arms[(k + 1) % m]
            th = (b.ang - a.ang) % (2 * math.pi) if m > 1 else 2 * math.pi
            c = NS(a=a, b=b, kind='straight', outer=None)
            if th < math.pi - 0.09:
                s = line_cross(n.p + a.l * (a.hwL + R), a.d, n.p - b.l * (b.hwR + R), b.d)
                c.kind, c.s1, c.s2 = 'fillet', s[0], s[1]
                c.C = n.p + a.l * (a.hwL + R) + a.d * s[0]
                a.t, b.t = max(a.t, s[0]), max(b.t, s[1])
            elif th > math.pi + 0.09:
                c.kind = 'reflex'
            n.corners.append(c)
        for a in arms:
            a.t = max(a.t, 1.0)
        for c in n.corners:
            a, b = c.a, c.b
            pa, pb = P(n, a, a.t, a.hwL), P(n, b, b.t, -b.hwR)
            if c.kind == 'fillet':
                ta, tb = c.ta, c.tb = P(n, a, c.s1, a.hwL), P(n, b, c.s2, -b.hwR)
                c.curb = dedupe([pa, ta] + arc_to(c.C, ta, tb)[1:-1] + [tb, pb])
            elif c.kind == 'reflex' and m == 2:
                other = next(o for o in n.corners if o.kind == 'fillet')
                c.curb = dedupe(arc_to(other.C, pa, pb, ccw=True))
            else:
                c.curb = [pa, pb]
            wa, wb = a.swL, b.swR
            if wa > 0 or wb > 0:
                # back edge concentric with the curb: constant width around the corner; facing an arm
                # without sidewalk (ramp) the sidewalk keeps its width and is capped at that arm's setback
                c.outer = offset_right(c.curb, wa or wb, wb or wa, a.l, -b.l)
                if c.kind == 'fillet':
                    n.block_corners.append(((a.d + b.d).normalized(), c.outer))

    def _prep_ring(self, n):
        Ri, Ro, Rf = n.ring
        P, arms = self.P, n.arms
        x = lambda hw: math.sqrt(max(0.0, (Ro + Rf) ** 2 - (hw + Rf) ** 2))
        for a in arms:
            a.xL, a.xR = x(a.hwL), x(a.hwR)
            a.t = max(a.xL, a.xR)
        k = Ro / (Ro + Rf)
        for i, a in enumerate(arms):
            b = arms[(i + 1) % len(arms)]
            c1, ta = P(n, a, a.xL, a.hwL + Rf), P(n, a, a.xL, a.hwL)
            c2, tb = P(n, b, b.xR, -(b.hwR + Rf)), P(n, b, b.xR, -b.hwR)
            q1, q2 = n.p + (c1 - n.p) * k, n.p + (c2 - n.p) * k
            curb = ([P(n, a, a.t, a.hwL), ta] + arc_to(c1, ta, q1)[1:-1] + arc_to(n.p, q1, q2, ccw=True)
                    + arc_to(c2, q2, tb)[1:-1] + [tb, P(n, b, b.t, -b.hwR)])
            c = NS(a=a, b=b, kind='ring', curb=dedupe(curb), outer=None)
            if a.swL > 0 or b.swR > 0:
                c.outer = offset_right(c.curb, a.swL, b.swR, a.l, -b.l)
                n.block_corners.append(((a.d + b.d).normalized(), c.outer))
            n.corners.append(c)

    def _index(self):
        """Footprints used to keep pillars off roads and lamps out from under decks."""
        self.ground_segs, self.deck_segs = [], []
        for e in self.edges:
            ss = e.samples()
            for s0, s1 in zip(ss, ss[1:]):
                hw = max(e.prof(s0).width('L'), e.prof(s0).width('R'))
                z = min(e.z(s0), e.z(s1))
                (self.deck_segs if z > 2.0 else self.ground_segs).append((e.at(s0), e.at(s1), hw))
        self.node_r = [(n.p, max(a.t for a in n.arms) + max(a.hwL + a.swL for a in n.arms))
                       for n in self.nodes if n.arms]

    def _clear(self, p, r):
        return (all(seg_dist(p, a, b) > hw + r for a, b, hw in self.ground_segs) and
                all((p - c).length > nr + r for c, nr in self.node_r))

    def _under_deck(self, p):
        return any(seg_dist(p, a, b) < hw + 1.0 for a, b, hw in self.deck_segs)

    # -------------------------------------------------------------- junctions
    def _junction(self, n, out):
        if n.k == 'plain':
            return
        R, M, z = out['Roads'], out['Markings'], n.z
        loops = [dedupe([p for c in n.corners for p in c.curb])]
        if n.ring:
            island = arc(n.p, n.ring[0], 0, 2 * math.pi, step=math.radians(7.5))[:-1]
            loops.append(island)
            R.fill([island], z + CURB_H, 'Grass')
            R.wall(island + [island[0]], z + CURB_H, z, 'Concrete__Curb')
            Ri, Ro = n.ring[0], n.ring[1]
            if Ro - Ri >= 8:
                rr = (Ri + Ro) / 2
                for a0 in range(0, 360, 12):
                    pts = arc(n.p, rr, math.radians(a0), math.radians(a0 + 4), step=math.radians(2))
                    M.mark([V(p.x, p.y, z + MARK_Z) for p in pts], 0.12)
            P_ = out['Props']
            P_.box(V(n.p.x, n.p.y, z + 1.0), V(1, 0), 4, 4, 2.0, 'Concrete')
            P_.cyl(V(n.p.x, n.p.y, z + 2.0), V(n.p.x, n.p.y, z + 16), 0.9, 4, 'Concrete', math.pi / 4, 0.2)
        R.fill(loops, z, 'Asphalt')
        for c in n.corners:
            if c.outer:
                poly = dedupe(c.curb + c.outer[::-1])
                if (poly[0] - poly[-1]).length < 0.01:
                    poly.pop()
                R.fill([poly], z + CURB_H, 'Sidewalk')
                R.wall(c.curb, z + CURB_H, z, 'Concrete__Curb', face_left=True)
                cap_a, cap_b = c.curb[:1] * (not c.a.swL), c.curb[-1:] * (not c.b.swR)   # close a sidewalk facing a ramp
                R.wall(cap_a + c.outer + cap_b, z + CURB_H, GROUND_Z, 'Concrete__Curb')
            else:
                R.wall(c.curb, z, GROUND_Z, 'Concrete')
        ctl = n.control
        for a in n.arms:
            if ctl:
                self._arm_marks(n, a, M, ctl)
            if ctl in ('stop', 'yield') and a.incoming:
                p = self.P(n, a, a.t + 5.0, a.hwL + 0.8)
                self.place('StopSign' if ctl == 'stop' else 'YieldSign', p, z + (CURB_H if a.swL else 0.0),
                           angle(a.d) + math.pi / 2)   # prefabs face -Y
        if ctl == 'signal':
            self._signals(n, out['Props'])

    def _arm_marks(self, n, a, M, ctl):
        z = n.z + MARK_Z
        if a.swL or a.swR:  # crosswalk (continental bars)
            lat = -a.hwR + 0.4
            while lat + 0.6 <= a.hwL - 0.3:
                c = lat + 0.3
                M.mark([self.P(n, a, a.t + 1.0, c).to_3d() + V(0, 0, z), self.P(n, a, a.t + 4.0, c).to_3d() + V(0, 0, z)], 0.6)
                lat += 1.2
        if not a.incoming:
            return
        lo = -a.hwR if a.prof.oneway else 0.15
        s = a.t + 5.0
        if ctl == 'yield':
            lat = lo
            while lat + 0.6 <= a.hwL:
                M.mark([self.P(n, a, s, lat).to_3d() + V(0, 0, z), self.P(n, a, s, lat + 0.6).to_3d() + V(0, 0, z)], 0.4)
                lat += 1.0
        else:
            M.mark([self.P(n, a, s, lo).to_3d() + V(0, 0, z), self.P(n, a, s, a.hwL).to_3d() + V(0, 0, z)], 0.45)

    def _signals(self, n, mb):
        arms, corners, m = n.arms, n.corners, len(n.arms)
        for k, a in enumerate(arms):
            if not a.incoming:
                continue
            opp = [j for j in range(m) if arms[j].d.dot(a.d) < -0.9]
            if opp:  # far-side mast, on the right of the exit road
                j = opp[0]
                c, b = corners[(j - 1) % m], arms[j]
                arm_dir, face, lanes = b.l, -b.d, b.prof.lanes(b.rs)
                fallback = self.P(n, b, b.t, -(b.hwR + 1.0))
            else:    # near-side mast, right of the approach
                c = corners[k]
                arm_dir, face, lanes = -a.l, a.d, a.prof.lanes(a.ls)
                fallback = self.P(n, a, a.t, a.hwL + 1.0)
            if not lanes:
                continue
            if c.kind == 'fillet':
                u = ((c.ta - c.C).normalized() + (c.tb - c.C).normalized()).normalized()
                base = c.C + u * (n.curb_r - 1.2)
            else:
                base = fallback
            dist = (n.p - base).dot(arm_dir)
            self._mast(mb, base, n.z + CURB_H, arm_dir, face, [dist - x for x in lanes])

    def _mast(self, mb, base, z, arm_dir, face, heads):
        reach = max(heads) + 0.6
        mb.cyl(V(base.x, base.y, z), V(base.x, base.y, z + 6.2), 0.14, 6, 'PoleMetal')
        mid = base + arm_dir * (reach / 2)
        mb.box(V(mid.x, mid.y, z + 5.9), arm_dir, reach, 0.14, 0.14, 'PoleMetal')
        for h in heads:
            p = base + arm_dir * h
            mb.cyl(V(p.x, p.y, z + 5.83), V(p.x, p.y, z + 5.72), 0.04, 4, 'PoleMetal')
            self.place('SignalHead', p, z + 5.2, angle(face) + math.pi / 2)

    # -------------------------------------------------------------- edges
    def _edge(self, e, out):
        R, M = out['Roads'], out['Markings']
        if e.L - e.t['A'] - e.t['B'] < 0.5:
            self.warnings.append(f'edge {e.a.p[:]}->{e.b.p[:]} swallowed by its junctions')
            return
        rows = []
        for s in e.samples():
            p, tan = e.frame(s)
            r, z = right(tan), e.z(s)
            sec, mats = e.prof(s).section(e.barrier_f(s, 'L'), e.barrier_f(s, 'R'))
            bot = GROUND_Z if z < SOLID_BELOW else z - DECK_T
            row = [V(p.x + r.x * x, p.y + r.y * x, z + h if h is not None else bot) for x, h in sec]
            u = [0.0]
            for q0, q1 in zip(row, row[1:]):
                u.append(u[-1] + (q1 - q0).length)
            rows.append((row, u, s, mats, z))
        n = len(rows[0][0])
        for (r0, u0, s0, mats, z0), (r1, u1, s1, _, z1) in zip(rows, rows[1:]):
            for k in range(n):
                k2 = (k + 1) % n
                if k2 == 0:
                    if max(z0, z1) >= SOLID_BELOW:
                        R.face([r0[k], r0[k2], r1[k2], r1[k]], mats[k])
                    continue
                R.face([r0[k], r0[k2], r1[k2], r1[k]], mats[k],
                       [(u0[k] / UV_M, s0 / UV_M), (u0[k2] / UV_M, s0 / UV_M),
                        (u1[k2] / UV_M, s1 / UV_M), (u1[k] / UV_M, s1 / UV_M)])
        for end, (row, _, s, _, z) in (('A', rows[0]), ('B', rows[-1])):
            node = e.a if end == 'A' else e.b
            if len(node.edges) == 1 and z >= SOLID_BELOW:
                tan = e.frame(s)[1].to_3d()
                R.cap(row, 'Concrete', -tan if end == 'A' else tan)
        self._edge_marks(e, M)

    def _edge_marks(self, e, M):
        s0, s1 = e.mark_from['A'], e.L - e.mark_from['B']
        if s1 - s0 < 1:
            return
        for ma, mb in zip(e.pa.marks, e.pb.marks):
            style = ma[1] if ma[1] != 'none' else mb[1]
            if style == 'none':
                continue
            offs = (-0.12, 0.12) if style == 'double' else (0.0,)
            if style == 'dashed':
                ranges, s = [], s0 + 4.5
                while s < s1:
                    ranges.append((s, min(s + 3.0, s1))); s += 12.0
            else:
                ranges = [(s0, s1)]
            for a, b in ranges:
                k = max(1, math.ceil((b - a) / 4.0))
                for o in offs:
                    pts = []
                    for j in range(k + 1):
                        s = lerp(a, b, j / k)
                        p, tan = e.frame(s)
                        q = p + right(tan) * (lerp(ma[0], mb[0], s / e.L) + o)
                        pts.append(V(q.x, q.y, e.z(s) + MARK_Z))
                    M.mark(pts, 0.12 if style == 'dashed' else 0.15, ma[2] == 'Y')

    # -------------------------------------------------------------- props
    def _gore(self, R, hw, rp, max_gap=1.5):
        def proj(p):   # (distance, s, lateral) of 2D p on hw's centerline
            best = None
            for i, (a, b) in enumerate(zip(hw.line, hw.line[1:])):
                ab = b - a
                t = clamp((p - a).dot(ab) / ab.length_squared)
                q = a + ab * t
                c = ((p - q).length, hw.cum[i] + t * ab.length, right(ab.normalized()).dot(p - q))
                best = c if best is None or c[0] < best[0] else best
            return best

        def back(e, s, side):   # top / bottom of the barrier's back face
            p, tan = e.frame(s)
            p = p + right(tan) * ((1 if side == 'R' else -1) * e.prof(s).width(side))
            z = e.z(s)
            return V(p.x, p.y, z + 0.85 * e.barrier_f(s, side)), V(p.x, p.y, GROUND_Z if z < SOLID_BELOW else z - DECK_T)

        ss = rp.samples()
        if proj(rp.b.p)[0] < proj(rp.a.p)[0]:
            ss = ss[::-1]
        p, tan = rp.frame(ss[0])
        s1 = proj(p)[1]
        side_r = 'R' if right(tan).dot(hw.at(s1) - p) > 0 else 'L'
        side_h = 'R' if proj(p)[2] > 0 else 'L'
        rows = []
        for s in ss:
            rt, rb = back(rp, s, side_r)
            ht, hb = back(hw, proj(rt.to_2d())[1], side_h)
            rows.append([rt, ht, hb, rb])
            if (ht - rt).to_2d().length > max_gap:
                break

        def quad(q, want):
            n = (q[1] - q[0]).cross(q[2] - q[0]) + (q[2] - q[0]).cross(q[3] - q[0])
            R.face(q if n.dot(want) > 0 else q[::-1], 'Concrete')
        up = V(0, 0, 1)
        for a, b in zip(rows, rows[1:]):
            quad([a[0], a[1], b[1], b[0]], up)
            quad([a[3], a[2], b[2], b[3]], -up)
        quad(rows[-1], rows[-1][0] - rows[-2][0])

    def _pillars(self, R):
        for e in self.edges:
            s = e.t['A'] + 16.0
            while s < e.L - e.t['B'] - 4.0:
                z = e.z(s)
                if z >= SOLID_BELOW + 0.5:
                    p, tan = e.frame(s)
                    pr = e.prof(s)
                    W = pr.width('L') + pr.width('R')
                    c = p + right(tan) * ((pr.width('R') - pr.width('L')) / 2)
                    bot = z - DECK_T
                    if W > 14 and self._clear(c, 2.0):
                        cap = 1.4
                        R.box(V(c.x, c.y, (GROUND_Z + bot - cap) / 2), tan, 2.4, 2.4, bot - cap - GROUND_Z, 'Concrete')
                        R.box(V(c.x, c.y, bot - cap / 2), tan, 2.0, W * 0.7, cap, 'Concrete')
                    elif W <= 14 and self._clear(c, 1.2):
                        R.box(V(c.x, c.y, (GROUND_Z + bot) / 2), tan, 1.4, 1.4, bot - GROUND_Z, 'Concrete')
                s += 32.0

    def _lamps(self, mb):
        for e in self.edges:
            s0, s1 = e.t['A'], e.L - e.t['B']
            if e.pa.left and e.pa.left[0][0] == 'mbarrier':  # highway median lamps
                s = s0 + 20.0
                while s < s1 - 10:
                    p, tan = e.frame(s)
                    z = e.z(s)
                    self.place('HighwayLamp', p, z + 0.85, angle(right(tan)))
                    s += 64.0
                continue
            for side, sg, off in (('R', 1, 0.0), ('L', -1, 17.0)):
                if not (e.pa.walk(side) and e.pb.walk(side)) or e.a.z or e.b.z:
                    continue
                s = s0 + 9.0 + off
                while s < s1 - 6.0:
                    p, tan = e.frame(s)
                    r = right(tan) * sg
                    q = p + r * (e.prof(s).asphalt(side) + 0.6)
                    if not self._under_deck(q):
                        z = e.z(s) + CURB_H
                        self.place('StreetLamp', q, z, angle(-r))
                    s += 34.0

    def _exit_sign(self, mb, e, s, side):
        p, tan = e.frame(s)
        sg = 1 if side == 'R' else -1
        r, pr, z = right(tan) * sg, e.prof(s), e.z(s)
        post = p + r * (pr.width(side) - 0.25)
        mb.cyl(V(post.x, post.y, z + 0.85), V(post.x, post.y, z + 8.2), 0.2, 6, 'PoleMetal')
        reach = 10.0
        mid = post - r * (reach / 2)
        mb.box(V(mid.x, mid.y, z + 7.9), -r, reach, 0.25, 0.25, 'PoleMetal')
        board = post - r * (reach - 4.0)
        face = -tan * sg
        mb.box(V(board.x, board.y, z + 6.4), face, 0.2, 6.2, 3.2, 'PoleMetal', {'px': 'ExitSign'})   # photo aspect 1.94:1


# ------------------------------------------------------------------ scene helpers
def collection(name, clear=True):
    col = bpy.data.collections.get(name)
    if col is None:
        col = bpy.data.collections.new(name)
        bpy.context.scene.collection.children.link(col)
    lc = bpy.context.view_layer.layer_collection.children.get(name)
    if lc:
        lc.exclude = False   # objects must be in the view layer to be selected for export
    if clear:
        for ob in list(col.objects):
            bpy.data.objects.remove(ob, do_unlink=True)
        for me in [m for m in bpy.data.meshes if m.users == 0]:
            bpy.data.meshes.remove(me)
    return col


def export_fbx(path, objects):
    bpy.ops.object.select_all(action='DESELECT')
    for ob in objects:
        ob.select_set(True)
    bpy.ops.export_scene.fbx(filepath=path, use_selection=True, object_types={'MESH', 'EMPTY'},
                             apply_scale_options='FBX_SCALE_ALL', axis_forward='-Z', axis_up='Y',
                             bake_space_transform=True, mesh_smooth_type='FACE', add_leaf_bones=False,
                             colors_type='LINEAR')
