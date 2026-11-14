"""Research shot: the first pages of the real datasheets the design read, dealt onto the table as sheets of
paper (a rigid-body drop with air drag, baked to keyframes). The dealing speeds up to a pour and the camera is
still pulling back at the end, so the cut out of it lands on movement.

    blender -b -P pages.py -- OUTDIR FRAMES pages=DIR [quality=preview|final] [stills=..]

pages=DIR holds the page images (pages.py prep writes them, vendor logos blanked).
"""
import glob
import os
import random
import sys

import bpy
from mathutils import Vector

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _shot as K  # noqa: E402

pos, kv = K.args()
OUT, NF = pos[0], int(pos[1])
random.seed(int(kv.get('seed', 7)))
S = K.setup(kv, NF)
bpy.context.preferences.edit.keyframe_new_interpolation_type = 'LINEAR'

bpy.ops.rigidbody.world_add()
rw = S.rigidbody_world
rw.substeps_per_frame, rw.solver_iterations = 20, 30
rw.point_cache.frame_start, rw.point_cache.frame_end = 1, NF
bpy.ops.mesh.primitive_cube_add(size=1, location=(0, 0, -0.05))
g = bpy.context.object
g.scale = (6, 6, 0.1)
g.data.materials.append(K.mat('ground', (0.62, 0.62, 0.61), 0.5)[0])
bpy.ops.rigidbody.object_add(type='PASSIVE')
g.rigid_body.friction, g.rigid_body.collision_margin = 0.9, 0.0005

pages = sorted(glob.glob(os.path.join(kv['pages'], '*.png')) + glob.glob(os.path.join(kv['pages'], '*.jpg')))
pages = pages[:int(kv.get('max', 30))]
random.shuffle(pages)
COLS = int(kv.get('cols', 6))
DX, DY, TH = 0.185, 0.215, 0.0012
rows = (len(pages) + COLS - 1) // COLS
last = max(1, len(pages) - 1)
pour = int(kv.get('pour', min(150, NF - 40)))
for i, p in enumerate(pages):
    img = bpy.data.images.load(p)
    w = 0.216
    h = w * img.size[1] / img.size[0]
    c, r = i % COLS, i // COLS
    x = (c - (COLS - 1) / 2) * DX + random.uniform(-0.02, 0.02) + (0.09 if r % 2 else 0)
    y = ((rows - 1) / 2 - r) * DY + random.uniform(-0.02, 0.02)
    bpy.ops.mesh.primitive_cube_add(size=1, location=(x - 0.05, y + 0.03, 0.16 + 0.02 * (i % 3)))
    o = bpy.context.object
    o.scale = (w, h, TH)
    o.rotation_euler = (random.uniform(-0.04, 0.04), random.uniform(0.03, 0.09), random.uniform(-0.14, 0.14))
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    uv = o.data.uv_layers.active or o.data.uv_layers.new()          # the page projected straight down, upright
    for lp in o.data.loops:
        v = o.data.vertices[lp.vertex_index].co
        uv.data[lp.index].uv = (v.x / w + 0.5, v.y / h + 0.5)
    m, b = K.mat('page', (1, 1, 1), 0.65)
    t = m.node_tree.nodes.new('ShaderNodeTexImage')
    t.image, t.interpolation = img, 'Cubic'
    mul = m.node_tree.nodes.new('ShaderNodeMixRGB')
    mul.blend_type = 'MULTIPLY'
    mul.inputs[0].default_value = 1
    mul.inputs[2].default_value = (0.9, 0.9, 0.88, 1)
    m.node_tree.links.new(t.outputs['Color'], mul.inputs[1])
    m.node_tree.links.new(mul.outputs[0], b.inputs['Base Color'])
    o.data.materials.append(m)
    bpy.ops.rigidbody.object_add(type='ACTIVE')
    rb = o.rigid_body
    rb.mass, rb.friction, rb.restitution = 0.005, 0.8, 0.0
    rb.linear_damping, rb.angular_damping = 0.86, 0.97
    rb.collision_shape, rb.use_margin, rb.collision_margin = 'BOX', True, 0.0004
    # dealt faster and faster: each sheet flies in from beyond the far edge, is let go just above the table
    f0 = 14 + round(pour * (1 - (1 - i / last) ** 1.9))
    rel = o.location.copy()
    rb.kinematic = True
    for f, k in ((1, 0.0), (f0 - 12, 0.0), (f0, 1.0)):
        o.location = Vector((rel.x * 0.6, rel.y + 1.5, 0.32)).lerp(rel, k)   # low: high, a sheet crosses the lens as a dark blur
        o.keyframe_insert('location', frame=f)
    rb.keyframe_insert('kinematic', frame=1)
    rb.keyframe_insert('kinematic', frame=f0 - 1)
    rb.kinematic = False
    rb.keyframe_insert('kinematic', frame=f0)

K.area((-0.7, 0.6, 1.6), (1.2, 0.8), 34, (0, 0, 0))
K.area((0.9, -0.6, 0.7), (0.8, 0.8), 10, (0, 0, 0))
K.world()
cam, cd = K.camera(35, float(kv.get('fstop', 11)))
sc = max(1.0, rows / 4)            # more rows: the end pose stands further back
T0, T1 = Vector((-0.10, 0.26, 0)), Vector((0.02, -0.06, 0))
O0, O1 = Vector((0.42, -0.62, 0.50)), Vector((0.06, -0.84, 1.98)) * sc


def pose(scene, *_):
    u = (scene.frame_current - 1) / max(1, NF - 1)
    u = 0.45 * u + 0.55 * u ** 2.2
    tg = T0.lerp(T1, u)
    cam.location = tg + O0.lerp(O1, u)
    K.aim(cam, tg)


# bake the simulation to plain keyframes: the render plays back exactly what was simulated, frame for frame
sheets = [o for o in S.objects if o.rigid_body and o.rigid_body.type == 'ACTIVE']
rec = {o.name: [] for o in sheets}
for f in range(1, NF + 1):
    S.frame_set(f)
    for o in sheets:
        rec[o.name].append(o.matrix_world.copy())
bpy.ops.rigidbody.world_remove()
for o in sheets:
    o.animation_data_clear()
    o.rotation_mode = 'QUATERNION'
    for f, mw in enumerate(rec[o.name], 1):
        o.location = mw.translation
        o.rotation_quaternion = mw.to_quaternion()
        o.keyframe_insert('location', frame=f)
        o.keyframe_insert('rotation_quaternion', frame=f)
bpy.app.handlers.frame_change_pre.append(pose)
pose(S)
K.render(OUT, kv)
