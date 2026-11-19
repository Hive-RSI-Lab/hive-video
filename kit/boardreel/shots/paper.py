"""Paper shot: a drawing on a sheet on the table, the camera moving over it. The drawing is a frame sequence
(schematic.py, layout.py, prompt.py write 00000.png, 00001.png ...), one still, every schematic sheet laid out
side by side, or each copper layer lifting off the board on its own clear sheet.

    blender -b -P paper.py -- OUTDIR FRAMES [seq=DIR | still=PNG | tiles=DIR] [layers=DIR] [cam=A:B] ...

cam=tx,ty,dist,azimuth,elevation:tx,ty,dist,azimuth,elevation (metres, degrees) moves the camera between two
poses (ease=in|out|fast|even, else steady; even: the picture moves at one speed from the first frame to the last,
a pull-back included, so the cuts on both sides land on full movement). of=N at=K: the shot is frames K+1.. of a
move N frames long, so the next shot (same cam= and ease=, at= this shot's length) takes the move up exactly where
this one leaves it: one camera move across a cut. from=PNG fade=N (with still=): the sheet shows that drawing on the shot's first frame, the one
the shot before ended on, and turns into the still and its layers over N frames (default 8): a dissolve the camera
moves through. seq0/rate or seq0/seqn/ramp map shot frames to drawing frames: ramp>1 makes
the drawing speed up through the shot. aspect= the sheet's height/width (default: the drawing's own).
track=FILE.json follows a list of [x, y] points, one a drawing frame (smoothed), e.g. the head of a trace as it
grows; with ease=even the camera runs along that path at one speed, to the last frame of the shot.
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
W = C.SHEET_W
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
OF, AT = int(kv.get('of', 0)), int(kv.get('at', 0))    # the camera's move is OF frames long and this shot starts AT frames into it
FROM, FADE = kv.get('from'), int(kv.get('fade', 8))    # the sheet shows this drawing first and turns into the still and its layers over FADE frames
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


TINT = (0.85, 0.85, 0.83, 1)                # the paper under a drawing


FADES = []   # one value a material that pose() turns from 0 (the from= drawing) to 1 (the still and its layers)


def fade(mm):
    v = mm.node_tree.nodes.new('ShaderNodeValue')
    v.outputs[0].default_value = 0.0
    FADES.append(v)
    return v.outputs[0]


def paper_look(mm, bb, col):
    """paper multiplied a touch warm, gamma so thin amber ink reads on camera"""
    N, L = mm.node_tree.nodes, mm.node_tree.links
    mul = N.new('ShaderNodeMixRGB')
    mul.blend_type = 'MULTIPLY'
    mul.inputs[0].default_value = 1
    mul.inputs[2].default_value = TINT
    gm = N.new('ShaderNodeGamma')
    gm.inputs[1].default_value = f_('gamma', 1.5)
    L.new(col, gm.inputs[0])
    L.new(gm.outputs[0], mul.inputs[1])
    L.new(mul.outputs[0], bb.inputs['Base Color'])


main = plane((0, 0, 0), W, H)             # the main sheet
m, b = K.mat('paper', (1, 1, 1), 0.7)
T = None
if SEQ or STILL:
    T = tex(m, STILL or os.path.join(SEQ, '00000.png'), not STILL)
    col = T.outputs['Color']
    if FROM:                              # the drawing the shot before ended on, dissolving into this one's own picture
        mx = m.node_tree.nodes.new('ShaderNodeMixRGB')
        m.node_tree.links.new(fade(m), mx.inputs[0])
        m.node_tree.links.new(tex(m, FROM, False).outputs['Color'], mx.inputs[1])
        m.node_tree.links.new(col, mx.inputs[2])
        col = mx.outputs[0]
    paper_look(m, b, col)
main.data.materials.append(m)


def sheet(path, loc, w, h, alpha=False, seq=False, look=False):
    o = plane(loc, w, h)
    mm, bb = K.mat('s', (1, 1, 1), 0.7)
    tt = tex(mm, path, seq)
    N, L = mm.node_tree.nodes, mm.node_tree.links
    if look:                              # a sheet of the same paper as the main one
        paper_look(mm, bb, tt.outputs['Color'])
        o.data.materials.append(mm)
        return o, tt
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
        a = ma.outputs[0]
        if FROM:                                            # not there while the from= drawing shows
            fd = N.new('ShaderNodeMath')
            fd.operation = 'MULTIPLY'
            L.new(a, fd.inputs[0])
            L.new(fade(mm), fd.inputs[1])
            a = fd.outputs[0]
        L.new(a, bb.inputs['Alpha'])
    o.data.materials.append(mm)
    return o


SEQS = []   # the tiles' textures that pose() re-points as the main sheet's
if TILES and os.path.exists(os.path.join(TILES, 'layout.json')):
    # sheets.py's: each sheet where the film put it, at its own size, on the main sheet's paper; or all of them
    # written on one big sheet, which is the main one at that size
    lay = json.load(open(os.path.join(TILES, 'layout.json')))
    big = lay.get('sheet') if isinstance(lay, dict) else None
    if big:
        main.location = (big['x'], big['y'], 0)
        main.scale = (big['w'], big['h'], 1)
        b.inputs['Base Color'].default_value = TINT
    else:
        main.location.z = -1
    for s in (lay['tiles'] if isinstance(lay, dict) else lay):
        o, tt = sheet(os.path.join(TILES, s['dir'], '00000.png'), (s['x'], s['y'], 0.0002), s['w'], s['h'], seq=True, look=True)
        if big:                                    # a drawing on the big sheet is ink on it, not a sheet lying on it:
            o.visible_shadow = o.visible_diffuse = o.visible_glossy = o.visible_transmission = False   # only the camera sees it,
            # else the light caught between it and the sheet shows as a bright line along its edges
        SEQS.append(tt)
    SEQN = min(SEQN, len(glob.glob(os.path.join(TILES, 'p1', '[0-9]*.png'))))
elif TILES:  # every schematic sheet side by side, each drawing in (folders p1..pN) or still (*.png)
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


def follow(t, even, w=7):
    """the camera's target on each frame of the shot, from the head's place in each drawing frame: the head's path
    with its corners rounded (the mean of w frames either side). ease=even: the target runs along that path at one
    speed from the first frame to the last, the path carried straight on past both ends before it is rounded, so the
    camera neither gathers speed at the start nor brakes where the head turns or stops."""
    p = [t[min(len(t) - 1, C.seq_frame(f, NF, SEQ0, SEQN, RATE, RAMP))] for f in range(1, NF + 1)]
    n = len(p)
    if not even or n < 3:
        return [[sum(p[min(n - 1, max(0, i + j))][c] for j in range(-w, w + 1)) / (2 * w + 1) for c in (0, 1)] for i in range(n)]
    k = min(3, n - 1)
    v0 = [(p[k][c] - p[0][c]) / k for c in (0, 1)]
    v1 = [(p[-1][c] - p[-1 - k][c]) / k for c in (0, 1)]

    def ext(i):
        if i < 0:
            return [p[0][c] + i * v0[c] for c in (0, 1)]
        if i >= n:
            return [p[-1][c] + (i - n + 1) * v1[c] for c in (0, 1)]
        return p[i]
    q = [[sum(ext(i + j)[c] for j in range(-w, w + 1)) / (2 * w + 1) for c in (0, 1)] for i in range(n)]
    run = [0.0]
    for a_, b_ in zip(q, q[1:]):
        run.append(run[-1] + ((b_[0] - a_[0]) ** 2 + (b_[1] - a_[1]) ** 2) ** 0.5)
    out, j = [], 0
    for i in range(n):
        want = run[-1] * i / (n - 1)
        while j < n - 2 and run[j + 1] < want:
            j += 1
        e = (want - run[j]) / max(1e-12, run[j + 1] - run[j])
        out.append([q[j][c] + (q[j + 1][c] - q[j][c]) * e for c in (0, 1)])
    return out


if kv.get('track'):
    TRK = follow(json.load(open(kv['track'])), EASE == 'even')


def pose(scene, *_):
    f = scene.frame_current
    for t in ([T] if T is not None and not STILL else []) + SEQS:
        t.image_user.frame_offset = C.seq_frame(f, NF, SEQ0, SEQN, RATE, RAMP) - f
    for n in FADES:
        n.outputs[0].default_value = min(1.0, f / (FADE + 1.0))
    u = (f - 1) / max(1, NF - 1)
    v = u * u * (3 - 2 * u)
    m = (AT + f - 1) / max(1, OF - 1) if OF else u
    tx, ty, dist, az, el = K.move(C0, C1, m, EASE)
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
