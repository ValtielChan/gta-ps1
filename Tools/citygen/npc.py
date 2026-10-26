"""npc: pedestrian bodies derived from Fabien's base model Art/NPC/hero.fbx (952 tris, rigged, A-pose).

    import npc
    npc.load()                     # appends hero.fbx into the 'NPC' collection (mesh 'male_player' + armature 'rig')
    npc.female('female_player')    # female proportions from the male mesh (same rig, same UVs, same weights)
    npc.export('female_player', 'hero_f')   # -> Assets/GTA/NPC/hero_f.fbx (Unity: Humanoid, same clips)
    npc.inspect('female_player', out_dir)   # Workbench renders front / 3/4 / back

Textures are variants of Art/NPC/man_t256.png made by Tools/texture/npc_variants.py (same UV layout).
See .claude/skills/ps1-npc.
"""
import math
import os

import bpy
from mathutils import Vector as V

import roadnet as rn

ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), '..', '..'))
HERO = os.path.join(ROOT, 'Art', 'NPC', 'hero.fbx')
TEX = os.path.join(ROOT, 'Art', 'NPC', 'man_t256.png')
NPC_DIR = os.path.join(ROOT, 'Assets', 'GTA', 'NPC')


def load():
    """Fresh import of hero.fbx into the NPC collection; the material previews man_t256.png (point sampled)."""
    col = rn.collection('NPC')
    for a in [a for a in bpy.data.armatures if a.users == 0]:
        bpy.data.armatures.remove(a)
    before = set(bpy.data.objects)
    bpy.ops.import_scene.fbx(filepath=HERO)
    new = [o for o in bpy.data.objects if o not in before]
    for o in new:
        for c in o.users_collection:
            c.objects.unlink(o)
        col.objects.link(o)
    mesh = next(o for o in new if o.type == 'MESH')
    img = bpy.data.images.load(TEX, check_existing=True)
    for n in mesh.data.materials[0].node_tree.nodes:
        if n.type == 'TEX_IMAGE':
            n.image, n.interpolation = img, 'Closest'
    return mesh, next(o for o in new if o.type == 'ARMATURE')


def _weights(ob):
    names = {g.index: g.name for g in ob.vertex_groups}
    return [{names[g.group]: g.weight for g in v.groups} for v in ob.data.vertices]


def female(name='female_player', height=0.95):
    """Copy of the male mesh reshaped in world space: narrower shoulders and arms, hourglass waist, wider hips,
    bust, smaller head; the whole character scaled to `height` (1.80 m -> 1.71 m). Same rig, UVs and weights."""
    src = bpy.data.objects['male_player']
    ob = src.copy()
    ob.data = src.data.copy()
    ob.name = ob.data.name = name
    src.users_collection[0].objects.link(ob)
    me, M, W = ob.data, ob.matrix_world, _weights(src)
    Mi = M.inverted()
    front = V((0, -1, 0))                       # the rig faces -Y
    for v, w in zip(me.vertices, W):
        p = M @ v.co
        x, y, z = p
        g = lambda *keys: sum(w.get(k, 0.0) for k in keys)
        # shoulders / arms: pull toward the body axis and slim the limbs
        arm = g('shoulder_left', 'shoulder_right', 'upper_arm_left', 'upper_arm_right', 'forearm_left', 'forearm_right',
                'hand_left', 'hand_right', 'f_middle.01.L', 'f_middle.01.R')
        x *= 1 - 0.12 * arm
        y = (y - 0.05) * (1 - 0.12 * arm) + 0.05
        # chest / shoulders narrower
        upper = g('chest', 'shoulder_left', 'shoulder_right') * max(0.0, min(1.0, (z - 1.25) / 0.15))
        x *= 1 - 0.08 * upper
        # waist: hourglass between the ribs and the hips
        waist = max(0.0, 1 - abs(z - 1.12) / 0.2) * g('spine', 'pelvis', 'chest')
        x *= 1 - 0.16 * waist
        y = (y - 0.02) * (1 - 0.10 * waist) + 0.02
        # hips and thighs wider and rounder
        hips = max(0.0, 1 - abs(z - 0.95) / 0.25) * g('pelvis', 'thigh_left', 'thigh_right')
        x *= 1 + 0.10 * hips
        y = (y - 0.03) * (1 + 0.05 * hips) + 0.03
        # bust: push the upper front chest forward
        bust = max(0.0, 1 - abs(z - 1.36) / 0.1) * g('chest') * (1 if p.y < 0.03 else 0.15) * max(0.0, 1 - abs(x) / 0.15)
        y -= 0.05 * bust
        # smaller head, finer neck
        head = g('head', 'neck')
        x *= 1 - 0.06 * head
        y = (y - (-0.02)) * (1 - 0.05 * head) + (-0.02)
        v.co = Mi @ V((x, y, z))
    me.update()
    ob.scale = src.scale * height           # keeps the rig: Unity's Humanoid avatar absorbs the size
    return ob


def export(obj_name, file_name):
    """FBX for Unity: the mesh + the shared armature 'rig' (no animation: clips come from the mocap library)."""
    ob, arm = bpy.data.objects[obj_name], bpy.data.objects['rig']
    os.makedirs(NPC_DIR, exist_ok=True)
    bpy.ops.object.select_all(action='DESELECT')
    ob.select_set(True); arm.select_set(True)
    bpy.context.view_layer.objects.active = arm
    path = os.path.join(NPC_DIR, file_name + '.fbx')
    bpy.ops.export_scene.fbx(filepath=path, use_selection=True, object_types={'ARMATURE', 'MESH'},
                             apply_scale_options='FBX_SCALE_ALL', axis_forward='-Z', axis_up='Y',
                             bake_space_transform=False, mesh_smooth_type='FACE', add_leaf_bones=False,
                             use_armature_deform_only=True, bake_anim=False)
    return path


def inspect(obj_name, out_dir, px=700):
    ob, arm = bpy.data.objects[obj_name], bpy.data.objects['rig']
    sc = bpy.context.scene
    cam = bpy.data.objects.get('npc_cam') or bpy.data.objects.new('npc_cam', bpy.data.cameras.new('npc_cam'))
    if cam.name not in sc.collection.objects:
        sc.collection.objects.link(cam)
    old = sc.camera, sc.render.engine, (sc.render.resolution_x, sc.render.resolution_y)
    hidden = [o for o in sc.objects if o not in (ob, cam) and not o.hide_render]
    for o in hidden:
        o.hide_render = True
    sc.camera, sc.render.engine = cam, 'BLENDER_WORKBENCH'
    sc.display.shading.light, sc.display.shading.color_type = 'STUDIO', 'TEXTURE'
    sc.view_settings.view_transform = 'Standard'
    sc.render.resolution_x = sc.render.resolution_y = px
    cam.data.type, cam.data.ortho_scale = 'ORTHO', 2.1
    outs = []
    for tag, d in (('front', V((0.0, -1, 0.05))), ('quarter', V((0.6, -0.7, 0.3))), ('back', V((-0.4, 1, 0.2)))):
        d = d.normalized()
        cam.location = V((0, 0, 0.92)) + d * 30
        cam.rotation_euler = (-d).to_track_quat('-Z', 'Y').to_euler()
        sc.render.filepath = os.path.join(out_dir, 'inspect_%s_%s.png' % (obj_name, tag))
        bpy.ops.render.render(write_still=True)
        outs.append(sc.render.filepath)
    for o in hidden:
        o.hide_render = False
    sc.camera, sc.render.engine, (sc.render.resolution_x, sc.render.resolution_y) = old
    return outs
