"""Phone shot: a generic phone lying on the table, its screen playing a frame sequence (an app filmed at 390x844,
or any portrait capture), the camera moving over it.

    blender -b -P phone.py -- OUTDIR FRAMES seq=DIR [cam=A:B] [seq0= seqn= rate= ramp=] [lens= fstop=] ...

A dark slab 71 x 150 x 8 mm with rounded corners and a small bevel, a glass front and a thin bezel. The screen is
emission: glow= sets its strength (default 1.0: the app's white a touch brighter than paper, short of clipping);
the glass over it keeps a faint soft reflection of the studio light. cam=tx,ty,dist,azimuth,elevation:... as in
paper.py (metres, degrees; ease=in|out|fast|even). yaw= turns the phone on the table (degrees).
"""
import glob
import math
import os
import sys

import bmesh
import bpy

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _shot as K  # noqa: E402
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import common as C  # noqa: E402
from mathutils import Vector  # noqa: E402

pos, kv = K.args()
OUT, NF = pos[0], int(pos[1])
S = K.setup(kv, NF)
f_ = lambda k, d: float(kv.get(k, d))  # noqa: E731
SEQ = kv.get('seq')
RAMP, EASE = f_('ramp', 0), kv.get('ease')
SEQ0, RATE, SEQN = int(kv.get('seq0', 0)), f_('rate', 1), int(kv.get('seqn', 10 ** 6))
if SEQ:
    SEQN = min(SEQN, len(glob.glob(os.path.join(SEQ, '[0-9]*.png'))))

PW, PH, PT, PR = 0.071, 0.150, 0.008, 0.0095        # the body: width, height, thickness, corner radius
SW, SR = 0.0665, 0.0072                             # the screen: width, corner radius (height from the capture)
YAW = math.radians(f_('yaw', 0))

K.ground()


def rounded(w, h, r, seg=14):
    """a rounded rectangle's outline, centred, counter-clockwise"""
    pts = []
    for cx, cy, a0 in ((w / 2 - r, h / 2 - r, 0), (-w / 2 + r, h / 2 - r, 90), (-w / 2 + r, -h / 2 + r, 180),
                       (w / 2 - r, -h / 2 + r, 270)):
        for i in range(seg + 1):
            a = math.radians(a0 + 90 * i / seg)
            pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return pts


def slab(name, w, h, r, z0, z1, mat):
    bm = bmesh.new()
    vs = [bm.verts.new((x, y, z0)) for x, y in rounded(w, h, r)]
    f = bm.faces.new(vs)
    ex = bmesh.ops.extrude_face_region(bm, geom=[f])
    for v in ex['geom']:
        if isinstance(v, bmesh.types.BMVert):
            v.co.z = z1
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    o = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(o)
    me.materials.append(mat)
    return o


def face(name, w, h, r, z, mat):
    """a flat rounded rectangle at height z, UVs spanning it 0..1"""
    bm = bmesh.new()
    vs = [bm.verts.new((x, y, z)) for x, y in rounded(w, h, r)]
    f = bm.faces.new(vs)
    uv = bm.loops.layers.uv.new()
    for lp in f.loops:
        lp[uv].uv = (lp.vert.co.x / w + 0.5, lp.vert.co.y / h + 0.5)
    bmesh.ops.triangulate(bm, faces=[f])
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    for p in me.polygons:
        p.use_smooth = False
    o = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(o)
    me.materials.append(mat)
    return o


# the body: dark anodised slab, the edges caught by a small bevel
body_m, bb = K.mat('body', (0.018, 0.018, 0.02), 0.32, 0.6)
body = slab('body', PW, PH, PR, 0, PT, body_m)
bv = body.modifiers.new('bevel', 'BEVEL')
bv.width, bv.segments, bv.limit_method, bv.angle_limit = 0.0011, 4, 'ANGLE', math.radians(40)
for p in body.data.polygons:
    p.use_smooth = True
body.modifiers.new('wn', 'WEIGHTED_NORMAL')

# the glass front over the bezel: black, glossy, a soft reflection
glass_m, gb = K.mat('glass', (0.004, 0.004, 0.005), 0.12)
gb.inputs['IOR'].default_value = 1.5
front = face('front', PW - 0.0026, PH - 0.0026, PR - 0.0013, PT + 0.00005, glass_m)


def _aspect():
    first = sorted(glob.glob(os.path.join(SEQ or '//none', '[0-9]*.png')))
    if first:
        im = bpy.data.images.load(first[0])
        w, h = im.size
        bpy.data.images.remove(im)
        if w:
            return h / w
    return 844 / 390


SH = SW * _aspect()
if SH > PH - 0.005:
    SW, SH = (PH - 0.005) / _aspect(), PH - 0.005

# the screen: the capture as light, under the same glass
scr_m = bpy.data.materials.new('screen')
scr_m.use_nodes = True
N, L = scr_m.node_tree.nodes, scr_m.node_tree.links
N.clear()
out = N.new('ShaderNodeOutputMaterial')
em = N.new('ShaderNodeEmission')
em.inputs['Strength'].default_value = f_('glow', 1.0)
gl = N.new('ShaderNodeBsdfPrincipled')
gl.inputs['Base Color'].default_value = (0, 0, 0, 1)
gl.inputs['Roughness'].default_value = f_('gloss', 0.14)
gl.inputs['IOR'].default_value = 1.5
add = N.new('ShaderNodeAddShader')
L.new(em.outputs[0], add.inputs[0])
L.new(gl.outputs[0], add.inputs[1])
L.new(add.outputs[0], out.inputs['Surface'])
T = None
if SEQ:
    T = N.new('ShaderNodeTexImage')
    T.image = bpy.data.images.load(sorted(glob.glob(os.path.join(SEQ, '[0-9]*.png')))[0])
    T.interpolation = 'Cubic'
    T.extension = 'EXTEND'
    T.image.source = 'SEQUENCE'
    T.image_user.frame_duration = 10 ** 6
    T.image_user.frame_start = 1
    T.image_user.frame_offset = -1
    T.image_user.use_auto_refresh = True
    L.new(T.outputs['Color'], em.inputs['Color'])
screen = face('screen', SW, SH, SR, PT + 0.0001, scr_m)
screen.visible_shadow = False
for o in (front, screen):
    o.visible_diffuse = False                     # the screen lights the table only as a real one would: barely

for o in (body, front, screen):
    o.rotation_euler.z = YAW

K.area((-0.5, 0.5, 0.8), (0.9, 0.6), 16, (0, 0, 0))
K.area((0.6, -0.4, 0.4), (0.6, 0.6), 3, (0, 0, 0))
K.world()
cam, cd = K.camera(f_('lens', 50), f_('fstop', 8))
C0, C1 = [[float(v) for v in c.split(',')] for c in kv.get('cam', '0.01,0.02,0.34,-20,52:0,0,0.5,0,74').split(':')]


def pose(scene, *_):
    f = scene.frame_current
    if T is not None:
        T.image_user.frame_offset = C.seq_frame(f, NF, SEQ0, SEQN, RATE, RAMP) - f
    u = (f - 1) / max(1, NF - 1)
    tx, ty, dist, az, el = K.move(C0, C1, u, EASE)
    tg = Vector((tx, ty, PT))
    cam.location = tg + K.sph(az, el, dist)
    K.aim(cam, tg)


bpy.app.handlers.frame_change_pre.append(pose)
pose(S)
K.render(OUT, kv)
