"""Board shots from the real design: the board and its part models as KiCad exports them, lit like a product
photo on the pale table.

    blender -b -P board.py -- OUTDIR FRAMES real=DIR fall [land0= burst= pow= slow=A,B orbit= path= early= blur=]
    blender -b -P board.py -- OUTDIR FRAMES real=DIR case=DIR [land1= land2= slowmo= path= lens= fstop=]

real=DIR holds board.glb (board only) and parts.glb (models only), made by `reel.py prep`.

fall: every part drops onto its own footprint under gravity, in slow motion, with two small bounces. The
parts go left to right and back to front, and each later part falls in less slow motion than the one before
(slow=A,B), so the drops speed up drop by drop: the film's rule, built in. burst= bunches the arrivals into
waves. path=az,el,dist:az,el,dist[:az,el,dist] moves the camera; with orbit=N a third pose orbits the finished
board for N more frames.

case: the printed enclosure (case=DIR: base.stl, lid.stl, any btn_*.stl and board.json from the enclosure
tool, all in the enclosure frame: mm, origin at the board's lower-left, y up). The base stands on the table,
the board drops into it, then the lid with its buttons. Where the frame sits on the board comes from
board.json's kicad_origin, so nothing about one board is written here.
"""
import json
import math
import os
import random
import sys

import bpy
from mathutils import Euler, Vector

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _shot as K  # noqa: E402

pos, kv = K.args()
OUT, NF = pos[0], int(pos[1])
EVENTS = dict(lands=[], hits=[], refs=0)
FALL, CASE = 'fall' in pos, kv.get('case')
ORB = int(kv.get('orbit', 0))
S = K.setup(kv, NF + ORB, samples=48 if kv.get('quality', 'preview') == 'preview' else 160)
S.cycles.use_adaptive_sampling = True
S.cycles.adaptive_threshold = 0.02
S.cycles.max_bounces = 8
S.cycles.sample_clamp_indirect = 6
REAL = kv['real']


def imp(name):
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=os.path.join(REAL, name))
    return [o for o in bpy.data.objects if o not in before]


def tune(objs, kind):
    """KiCad's flat CAD colours to finishes: green mask, gold copper, laminate; parts metal, gold or moulded"""
    seen = set()
    for o in objs:
        if o.type != 'MESH':
            continue
        for sl in o.material_slots:
            m = sl.material
            if not m or m.name in seen:
                continue
            seen.add(m.name)
            b = K.bsdf(m)
            if not b:
                continue
            r, g, bl = list(b.inputs['Base Color'].default_value)[:3]
            v = max(r, g, bl)
            sat = (v - min(r, g, bl)) / v if v else 0
            I = b.inputs
            if kind == 'board':
                if v > 0.85 and sat < 0.12:                               # silkscreen
                    I['Base Color'].default_value = (0.82, 0.82, 0.80, 1)
                    I['Roughness'].default_value, I['Alpha'].default_value = 0.6, 1
                elif g > r * 1.3 and g > bl * 1.2:                        # solder mask, a little see-through
                    I['Base Color'].default_value = (0.002, 0.028, 0.012, 1)
                    I['Alpha'].default_value, I['Roughness'].default_value = 0.95, 0.5
                    I['Coat Weight'].default_value, I['Coat Roughness'].default_value = 0.12, 0.2
                elif m.name in ('mat_0', 'mat_1') or r > bl * 3:          # copper and pads: gold finish
                    I['Base Color'].default_value = (0.95, 0.70, 0.30, 1)
                    I['Metallic'].default_value, I['Roughness'].default_value = 1, 0.3
                else:                                                     # laminate
                    I['Base Color'].default_value = (0.20, 0.17, 0.07, 1)
                    I['Roughness'].default_value, I['Alpha'].default_value = 0.55, 1
            else:
                I['Metallic'].default_value = 0
                if sat < 0.25 and v > 0.4:                                # leads, shields, shells
                    I['Metallic'].default_value, I['Roughness'].default_value = 1, 0.26
                    I['Base Color'].default_value = (v * 0.95 + 0.05,) * 3 + (1,)
                elif r > bl * 1.6 and v > 0.5 and g > bl * 1.2:           # gold contacts
                    I['Metallic'].default_value, I['Roughness'].default_value = 1, 0.25
                elif v < 0.25:                                            # moulded packages
                    I['Roughness'].default_value = 0.42
                    I['Base Color'].default_value = (0.022, 0.022, 0.024, 1)
                else:
                    I['Roughness'].default_value = 0.5


board, parts = imp('board.glb'), imp('parts.glb')
tune(board, 'board')
tune(parts, 'part')
for o in board + parts:
    if o.type == 'MESH':
        for p in o.data.polygons:
            p.use_smooth = False

pts = [o.matrix_world @ Vector(c) for o in board if o.type == 'MESH' for c in o.bound_box]
lo = Vector([min(p[i] for p in pts) for i in range(3)])
hi = Vector([max(p[i] for p in pts) for i in range(3)])
C = (lo + hi) / 2
print('BOARD', tuple(round(v, 4) for v in lo), tuple(round(v, 4) for v in hi))
span = max(hi.x - lo.x, hi.y - lo.y)          # camera distances scale with the board: the poses are for 0.1 m

steel = K.mat('steel', (0.75, 0.75, 0.76), 0.3, 1)[0]
case_objs, case_frame = [], None
if CASE:
    spec = json.load(open(os.path.join(CASE, 'board.json')))
    ox, oy = spec['kicad_origin']
    case_frame = Vector((ox / 1000, -oy / 1000, lo.z))     # enclosure frame -> scene

    def stl(path, m):
        bpy.ops.wm.stl_import(filepath=path, global_scale=0.001)
        o = bpy.context.selected_objects[0]
        o.location = case_frame
        o.data.materials.append(m)
        try:
            bpy.context.view_layer.objects.active = o
            bpy.ops.object.shade_auto_smooth(angle=0.5)
        except Exception as e:   # older Blender
            print('smooth', e)
        return o
    body = tuple(float(v) for v in kv.get('petg', '0.30,0.40,0.55').split(','))
    accent = tuple(float(v) for v in kv.get('accent', '0.93,0.55,0.36').split(','))
    pet, acc = K.mat('petg', body, 0.46)[0], K.mat('petg_btn', accent, 0.45)[0]
    for m in (pet, acc):
        b = K.bsdf(m)
        b.inputs['Subsurface Weight'].default_value = 0.08
        b.inputs['Subsurface Radius'].default_value = (0.002, 0.002, 0.002)
    base = stl(os.path.join(CASE, 'base.stl'), pet)
    lid = stl(os.path.join(CASE, 'lid.stl'), pet)
    btns = [stl(os.path.join(CASE, f), acc) for f in sorted(os.listdir(CASE)) if f.startswith('btn_') and f.endswith('.stl')]
    bpy.context.view_layer.update()
    floor = min((base.matrix_world @ Vector(c)).z for c in base.bound_box)
    case_objs = [base, lid] + btns
else:
    floor = lo.z - 0.006
    for h in kv.get('holes', '') and json.load(open(kv['holes'])) or []:   # standoffs under the mounting holes
        bpy.ops.mesh.primitive_cylinder_add(vertices=6, radius=0.003, depth=0.006, location=(h[0] / 1000, -h[1] / 1000, lo.z - 0.003))
        bpy.context.object.data.materials.append(steel)
K.ground(floor, 40, (C.x, C.y))   # wide enough that a low camera never sees its edge
K.area((C.x - 0.35, C.y + 0.25, C.z + 0.55), (0.7, 0.5), 10, C, (1.0, 0.97, 0.93))
K.area((C.x + 0.5, C.y - 0.3, C.z + 0.3), (0.6, 0.6), 4, C, (0.93, 0.96, 1.0))
K.area((C.x + 0.15, C.y + 0.6, C.z + 0.18), (0.9, 0.12), 7, C, (1.0, 0.93, 0.82))
K.world(0.12)
cam, cd = K.camera(float(kv.get('lens', 85)), float(kv.get('fstop', 20)))
cd.sensor_width = 36
tgt = C + Vector((0.004, -0.004, 0.0))
blur = kv.get('blur', '0.5' if CASE else '')
if blur:   # a falling part smears over its real travel, so a landing is not a one-frame snap
    S.render.use_motion_blur = True
    S.render.motion_blur_shutter = float(blur)
path = [[float(v) for v in k.split(',')] for k in kv.get('path', '28,52,0.34:5,34,0.36:-32,13,0.33' if CASE else '40,40,0.36:28,34,0.30').split(':')]
for k in path:
    k[2] *= span / 0.1 if kv.get('scale', '1') == '1' else 1


def sph(k):
    return K.sph(k[0], k[1], k[2])


def bounce(t, G, T0, H0, rest):
    """seconds after release -> height above the seat: free fall, then two small bounces"""
    if t < T0:
        return H0 - 0.5 * G * t * t
    v = G * T0
    t -= T0
    for _ in range(2):
        v *= rest
        tb = 2 * v / G
        if t < tb:
            return v * t - 0.5 * G * t * t
        t -= tb
    return 0.0


def refs_of(parts):
    """one object per footprint: the empties KiCad's glb puts over each footprint's model(s)"""
    r = [o for o in parts if o.parent and o.parent.parent is None and o.children]
    return r or [o for o in parts if o.children and o.type == 'EMPTY' and o.parent]


if CASE:
    def rig(name, objs):
        e = bpy.data.objects.new(name, None)
        S.collection.objects.link(e)
        bpy.context.view_layer.update()
        for o in objs:
            o.parent = e
            o.matrix_parent_inverse = e.matrix_world.inverted()
        return e
    brd = rig('board_rig', [o for o in board + parts if o.parent is None])
    top = rig('lid_rig', case_objs[1:])
    SLOW = float(kv.get('slowmo', 4))
    G = 9.81 / SLOW ** 2

    def drop(e, land, H0, rest=0.10, tilt=(0, 0, 0)):
        T0 = math.sqrt(2 * H0 / G)
        f0 = land - T0 * 30
        e.rotation_mode = 'XYZ'
        for f in range(1, NF + 1):
            h = bounce(max(0.0, (f - f0) / 30), G, T0, H0, rest)
            k = min(1.0, h / 0.05)
            e.location.z = h
            e.keyframe_insert('location', index=2, frame=f)
            e.rotation_euler = (tilt[0] * k, tilt[1] * k, tilt[2] * k)
            e.keyframe_insert('rotation_euler', frame=f)
    drop(brd, int(kv.get('land1', 62)), 0.11, tilt=(0.10, -0.06, 0.0))
    drop(top, int(kv.get('land2', 128)), 0.13, tilt=(-0.08, 0.05, 0.0))
    EVENTS['hits'] = [int(kv.get('land1', 62)), int(kv.get('land2', 128))]
    sz = spec.get('size') or [(hi.x - lo.x) * 1000, (hi.y - lo.y) * 1000]
    ct = case_frame + Vector((sz[0] / 2000, sz[1] / 2000, -0.004))
    cd.lens, cd.dof.aperture_fstop = float(kv.get('lens', 60)), float(kv.get('fstop', 18))

    def pose(scene, *_):
        u = (scene.frame_current - 1) / max(1, NF - 1)
        s = 0.55 * u + 0.45 * u * u * (3 - 2 * u)        # always moving, a little faster through the middle
        k = [(1 - s) ** 2 * a + 2 * s * (1 - s) * b + s * s * c for a, b, c in zip(*path)]
        cam.location = ct + sph(k)
        K.aim(cam, ct)
elif FALL:
    random.seed(4)
    LAND0, BURST, POW = int(kv.get('land0', 46)), float(kv.get('burst', 0)), float(kv.get('pow', 0.85))
    H0, REST = 0.30, 0.12
    SL = [float(v) for v in kv.get('slow', '7,2.2').split(',')]
    refs = refs_of(parts)
    print('REFS', len(refs))
    refs.sort(key=lambda o: (o.matrix_world.translation.x - lo.x) + 0.5 * (hi.y - o.matrix_world.translation.y))
    n = len(refs)
    EVENTS['refs'] = n
    for i, o in enumerate(refs):
        x = i / max(1, n - 1)
        G = 9.81 / (SL[0] + (SL[1] - SL[0]) * x) ** 2
        T0 = math.sqrt(2 * H0 / G)
        land = LAND0 + (x ** POW + BURST * math.sin(2 * math.pi * 5 * x)) * (NF - LAND0 - 50)
        f0 = land - T0 * 30
        EVENTS['lands'].append(round(land, 2))
        o.rotation_mode = 'QUATERNION'
        z0, q0 = o.location.z, o.rotation_quaternion.copy()
        tilt = Euler((random.uniform(-.5, .5), random.uniform(-.5, .5), random.uniform(-.3, .3)))
        fa = max(1, int(math.floor(f0)))
        for ob in [o] + list(o.children_recursive):      # unseen until released: nothing hangs in the air
            ob.hide_render = True
            ob.keyframe_insert('hide_render', frame=1)
            ob.hide_render = False
            ob.keyframe_insert('hide_render', frame=fa)
        for f in range(fa, NF + ORB + 1):
            h = bounce(max(0.0, (f - f0) / 30), G, T0, H0, REST)
            k = min(1.0, h / 0.03)
            o.location.z = z0 + h
            o.keyframe_insert('location', index=2, frame=f)
            o.rotation_quaternion = Euler((tilt.x * k, tilt.y * k, tilt.z * k)).to_quaternion() @ q0
            o.keyframe_insert('rotation_quaternion', frame=f)
            if h == 0.0 and f > land + 12:
                break
    E0 = float(kv.get('early', 0.5))

    def pose(scene, *_):
        f = scene.frame_current
        if f <= NF or len(path) < 3:       # first leg gathers speed and is still moving at its end
            u = max(0., min(1., (f - 1) / max(1, NF - 1)))
            s = (E0 * u + (1 - E0) * u ** 2.4) if len(path) > 2 else K.ease(u)
            k = [a + (b - a) * s for a, b in zip(path[0], path[1])]
        else:                              # then the orbit round the finished board, slowing, never stopping
            u = (f - NF) / max(1, ORB)
            s = 0.6 * u + 0.4 * (1 - (1 - u) ** 2)
            k = [a + (b - a) * s for a, b in zip(path[1], path[2])]
        cam.location = tgt + sph(k)
        K.aim(cam, tgt)
else:
    def pose(scene, *_):
        u = K.ease((scene.frame_current - 1) / max(1, NF - 1))
        k = [a + (b - a) * u for a, b in zip(path[0], path[1])]
        cam.location = tgt + sph(k)
        K.aim(cam, tgt)

bpy.app.handlers.frame_change_pre.append(pose)
pose(S)
os.makedirs(OUT, exist_ok=True)       # the score lands its ticks and hits on these frames (score.mjs)
json.dump(EVENTS, open(os.path.join(OUT, 'events.json'), 'w'))
K.render(OUT, kv)
