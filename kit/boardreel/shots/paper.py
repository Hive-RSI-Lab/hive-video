"""Paper shot: a drawing on a sheet on the table, the camera moving over it. The drawing is a frame sequence
(schematic.py, layout.py, prompt.py write 00000.png, 00001.png ...), one still, every schematic sheet laid out
side by side, or each copper layer lifting off the board on its own clear sheet.

    blender -b -P paper.py -- OUTDIR FRAMES [seq=DIR | still=PNG | tiles=DIR] [layers=DIR] [cam=A:B] ...

cam=tx,ty,dist,azimuth,elevation:tx,ty,dist,azimuth,elevation (metres, degrees) moves the camera between two
poses (ease=in|out, else steady). seq0/rate or seq0/seqn/ramp map shot frames to drawing frames: ramp>1 makes
the drawing speed up through the shot. aspect= the sheet's height/width (default: the drawing's own).
track=FILE.json follows a list of [x, y] points (smoothed), e.g. the head of a trace as it grows.
"""
import glob
import json
import os
import sys

import bpy
from mathutils import Vector

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _shot as K  # noqa: E402
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import common as C  # noqa: E402

pos, kv = K.args()
OUT, NF = pos[0], int(pos[1])
S = K.setup(kv, NF)
f_ = lambda k, d: float(kv.get(k, d))  # noqa: E731
W = 0.594
SEQ, STILL, TILES, LAYERS = kv.get('seq'), kv.get('still'), kv.get('tiles'), kv.get('layers')


def _aspect():
    """the sheet's height/width: aspect=, else the drawing's own (its first image), else A-series"""
    if 'aspect' in kv:
        return float(kv['aspect'])
    found = [STILL] if STILL else sorted(glob.glob(os.path.join(SEQ or LAYERS or '//none', '*.png')))
    first = found[0] if found else None
    if first:
        im = bpy.data.images.load(first)
        w, h = im.size
        bpy.data.images.remove(im)
        if w:
            return h / w
    return 0.707


H = W * _aspect()
RAMP, EASE = f_('ramp', 0), kv.get('ease')
SEQ0, RATE, SEQN = int(kv.get('seq0', 0)), f_('rate', 1), int(kv.get('seqn', 10 ** 6))
if SEQ:
    SEQN = min(SEQN, len(glob.glob(os.path.join(SEQ, '[0-9]*.png'))))

K.ground()


def tex(m, path, seq):
    t = m.node_tree.nodes.new('ShaderNodeTexImage')
    t.image = bpy.data.images.load(path)
    t.interpolation = 'Cubic'
    if seq:                               # file 00000.png on frame 1, one file a frame, re-pointed by pose()
        t.image.source = 'SEQUENCE'
        t.image_user.frame_duration = 10 ** 6
        t.image_user.frame_start = 1
        t.image_user.frame_offset = -1
        t.image_user.use_auto_refresh = True
    return t


def plane(loc, w, h):
    bpy.ops.mesh.primitive_plane_add(size=1, location=loc)
    o = bpy.context.object
    o.scale = (w, h, 1)
    return o


# the main sheet: paper multiplied a touch warm, gamma so thin amber ink reads on camera
main = plane((0, 0, 0), W, H)
m, b = K.mat('paper', (1, 1, 1), 0.7)
T = None
if SEQ or STILL:
    T = tex(m, STILL or os.path.join(SEQ, '00000.png'), not STILL)
    N, L = m.node_tree.nodes, m.node_tree.links
    mul = N.new('ShaderNodeMixRGB')
    mul.blend_type = 'MULTIPLY'
    mul.inputs[0].default_value = 1
    mul.inputs[2].default_value = (0.85, 0.85, 0.83, 1)
    gm = N.new('ShaderNodeGamma')
    gm.inputs[1].default_value = f_('gamma', 1.5)
    L.new(T.outputs['Color'], gm.inputs[0])
    L.new(gm.outputs[0], mul.inputs[1])
    L.new(mul.outputs[0], b.inputs['Base Color'])
main.data.materials.append(m)


def sheet(path, loc, w, h, alpha=False, seq=False):
    o = plane(loc, w, h)
    mm, bb = K.mat('s', (1, 1, 1), 0.7)
    tt = tex(mm, path, seq)
    N, L = mm.node_tree.nodes, mm.node_tree.links
    L.new(tt.outputs['Color'], bb.inputs['Base Color'])
    if alpha:                             # a thin clear sheet carrying one copper layer
        mx = N.new('ShaderNodeMixRGB')
        mx.inputs[1].default_value = (1, 1, 1, 1)
        lg = N.new('ShaderNodeGamma')
        lg.inputs[1].default_value = f_('lgam', 1)          # >1: deeper layer colours
        L.new(tt.outputs['Color'], lg.inputs[0])
        ap = N.new('ShaderNodeMath')
        ap.operation = 'POWER'
        ap.inputs[1].default_value = f_('apow', 1)          # <1: thin traces more solid
        L.new(tt.outputs['Alpha'], ap.inputs[0])
        L.new(ap.outputs[0], mx.inputs[0])
        L.new(lg.outputs[0], mx.inputs[2])
        L.new(mx.outputs[0], bb.inputs['Base Color'])
        ma = N.new('ShaderNodeMath')
        ma.operation = 'MULTIPLY_ADD'
        hz = f_('haze', 0.12)                               # how milky each clear sheet is
        ma.inputs[1].default_value = 1 - hz
        ma.inputs[2].default_value = hz
        L.new(ap.outputs[0], ma.inputs[0])
        L.new(ma.outputs[0], bb.inputs['Alpha'])
    o.data.materials.append(mm)
    return o


SEQS = []
if TILES:   # every schematic sheet side by side, each drawing in (folders p1..pN) or still (*.png)
    main.location.z = -1
    num = lambda p: int(''.join(c for c in os.path.basename(p.rstrip('/').rsplit('/', 1)[-1]) if c.isdigit()) or 0)  # noqa: E731
    dirs = sorted(glob.glob(os.path.join(TILES, 'p*/00000.png')), key=lambda f: num(os.path.dirname(f)))
    files = dirs or sorted(glob.glob(os.path.join(TILES, '*.png')), key=num)
    per = int(kv.get('per', 5))
    rows = (len(files) + per - 1) // per
    for i, f in enumerate(files):
        im = bpy.data.images.load(f)
        a = im.size[1] / im.size[0]
        sheet(f, ((i % per - (per - 1) / 2) * 0.30, ((rows - 1) / 2 - i // per) * 0.23, 0.0002), 0.27, 0.27 * a, seq=bool(dirs))

LIFT = []
if LAYERS:  # copper layers bottom first, as layout.py names them
    from_json = os.path.join(LAYERS, 'order.json')
    names = json.load(open(from_json)) if os.path.exists(from_json) else \
        ['B.Cu', 'In6.Cu', 'In5.Cu', 'In4.Cu', 'In3.Cu', 'In2.Cu', 'In1.Cu', 'F.Cu']
    for n in names:
        p = os.path.join(LAYERS, n + '.png')
        if os.path.exists(p):
            LIFT.append(sheet(p, (0, 0, 0.0003), W, H, alpha=True))

K.area((-0.5, 0.5, 0.8), (0.9, 0.6), 16, (0, 0, 0))
K.area((0.6, -0.4, 0.4), (0.6, 0.6), 3, (0, 0, 0))
K.world()
cam, cd = K.camera(f_('lens', 50), f_('fstop', 8))
C0, C1 = [[float(v) for v in c.split(',')] for c in kv.get('cam', '0,0,0.9,0,50:0,0,0.7,0,55').split(':')]
GAP = f_('gap', 0.035)
TRK = None
if kv.get('track'):
    _t = json.load(open(kv['track']))
    _n, _w = len(_t), 7
    TRK = [[sum(_t[min(_n - 1, max(0, i + j))][c] for j in range(-_w, _w + 1)) / (2 * _w + 1) for c in (0, 1)] for i in range(_n)]


def pose(scene, *_):
    f = scene.frame_current
    if T is not None and not STILL:
        T.image_user.frame_offset = C.seq_frame(f, NF, SEQ0, SEQN, RATE, RAMP) - f
    u = (f - 1) / max(1, NF - 1)
    v = u * u * (3 - 2 * u)
    tx, ty, dist, az, el = [a + (b_ - a) * K.ease(u, EASE) for a, b_ in zip(C0, C1)]
    if TRK:
        tx, ty = TRK[min(len(TRK) - 1, f - 1)]
    tg = Vector((tx, ty, GAP * len(LIFT) * 0.5 * v))
    cam.location = tg + K.sph(az, el, dist)
    K.aim(cam, tg)
    for i, o in enumerate(LIFT):
        k = min(1, max(0, (v - 0.12) / 0.6))
        o.location.z = 0.0003 + 0.0002 * i + (i + 1) * GAP * k * k * (3 - 2 * k)


bpy.app.handlers.frame_change_pre.append(pose)
pose(S)
K.render(OUT, kv)
