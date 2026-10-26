"""cars: bring Fabien's car models (Art/Cars/*.blend) into Unity.

    import cars; cars.export_car('W123i')   # -> Assets/GTA/Cars/W123i.fbx + T_<material>.png (the player's car)
    cars.export_car('W110', traffic=True)   # -> Assets/GTA/Cars/Traffic/W110.fbx (GTA > Build Traffic Cars)

The car is appended into a 'Car' scene, turned so its front points to Blender -Y (Unity +Z), rotations baked
(wheel origins stay at the wheel centers, wheels keep their names *_Wheel_FL/FR/RL/RR), white vertex colors added
for PS1Lit, atlases saved as T_<material>.png. Semi-transparent materials are renamed
'<atlas material>__Glass' so the import rules make them see-through with the same atlas. When the .blend holds
several cars, only the objects named '<name>_*' are taken.
"""
import math
import os
import shutil
import subprocess

import bpy

import roadnet as rn

ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), '..', '..'))
CARS_DIR = os.path.join(ROOT, 'Assets', 'GTA', 'Cars')


def export_car(name, front_axis='+X', traffic=False):
    path = os.path.join(ROOT, 'Art', 'Cars', name + '.blend')
    col = rn.collection('Car')
    with bpy.data.libraries.load(path, link=False) as (src, dst):
        names = set(src.objects) | set(src.materials) | set(src.images) | set(src.meshes)
    for coll in (bpy.data.objects, bpy.data.meshes, bpy.data.materials, bpy.data.images):   # previous imports
        for d in [d for d in coll if d.name.split('.')[0] in names and d.users == 0]:
            coll.remove(d)
    with bpy.data.libraries.load(path, link=False) as (src, dst):
        dst.objects = list(src.objects)
    objs = [o for o in dst.objects if o and o.type == 'MESH']
    objs = [o for o in objs if o.name.startswith(name + '_')] or objs
    yaw = {'+X': -math.pi / 2, '-X': math.pi / 2, '+Y': math.pi, '-Y': 0.0}[front_axis]
    for ob in objs:
        col.objects.link(ob)
        ob.location = (ob.location.x * math.cos(yaw) - ob.location.y * math.sin(yaw),
                       ob.location.x * math.sin(yaw) + ob.location.y * math.cos(yaw), ob.location.z)
        ob.rotation_euler.z += yaw
    bpy.ops.object.select_all(action='DESELECT')
    for ob in objs:
        ob.select_set(True)
    bpy.context.view_layer.objects.active = objs[0]
    bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)
    textures = set()
    for ob in objs:
        me = ob.data
        if not me.color_attributes:
            c = me.color_attributes.new('Col', 'FLOAT_COLOR', 'CORNER')
            c.data.foreach_set('color', [1.0] * (4 * len(me.loops)))
        for m in me.materials:
            bsdf = m.node_tree.nodes.get('Principled BSDF') if m and m.use_nodes else None
            img = next((n.image for n in m.node_tree.nodes if n.type == 'TEX_IMAGE' and n.image), None) if bsdf else None
            if img is None:
                continue
            base = m.name.split('__')[0]
            if bsdf.inputs['Alpha'].default_value < 0.99 and '__' not in m.name:   # glass: same atlas, see-through
                owner = next(o for o in bpy.data.materials if o is not m and any(
                    n.type == 'TEX_IMAGE' and n.image == img for n in (o.node_tree.nodes if o.use_nodes else [])))
                base = owner.name
                m.name = base + '__Glass'
            textures.add((base, img))
    for base, img in textures:   # opaque RGB copy of the atlas (alpha would make the importer cut it out)
        out = os.path.join(rn.TEX_DIR, 'T_%s.png' % base)
        if img.packed_file:
            with open(out, 'wb') as f:
                f.write(img.packed_file.data)
        else:
            shutil.copyfile(bpy.path.abspath(img.filepath), out)
        subprocess.run(['python', '-I', '-c', 'import sys; from PIL import Image; '
                        'Image.open(sys.argv[1]).convert("RGB").save(sys.argv[1])', out], check=True)
    out_dir = os.path.join(CARS_DIR, 'Traffic') if traffic else CARS_DIR
    os.makedirs(out_dir, exist_ok=True)
    rn.export_fbx(os.path.join(out_dir, name + '.fbx'), objs)
    return {'objects': [o.name for o in objs], 'textures': sorted(t for t, _ in textures)}
