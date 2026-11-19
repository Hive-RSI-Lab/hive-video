"""Research shot: the first pages of the real datasheets the design read, dealt onto the table as sheets of
paper (a rigid-body drop with air drag, baked to keyframes). The front pages land first, in the middle; the dealing
speeds up to a pour and the camera pulls back with it, the picture moving as fast on the last frame as on the
first, so the cut out of it lands on full movement.

    blender -b -P pages.py -- OUTDIR FRAMES pages=DIR [quality=preview|final] [stills=..]

pages=DIR holds the page images (pages.py prep writes them, vendor logos blanked; NAME-p1 is a front page).

The sheets lie in balanced rows (13 sheets: 4, 5, 4), each row half a pitch beside the one behind it and lying on its
lower edge, and are dealt from the middle outward, never a sheet before the ones it lies on: every top edge, where
the title is, stays uncovered. The camera is set from where the sheets really came to rest: it opens close on the
first one and ends with the whole spread in frame, and pulls back just early enough that no sheet lands outside the
picture.

  first=TEXT     the sheet dealt first is the one with TEXT in its file name (default: the first front page)
  dx= dy=        the pitch of the grid in metres (0.25, 0.225; a sheet is 0.216 wide)       rows=N  not the best fit
  fly=14         frames a sheet takes to arrive       glide=0.12   how much of its speed it still has when let go
  pour=150       frames between the first and the last sheet       first_at=15   frame the first sheet is let go
  open=0.36      part of the frame's width the first sheet fills at the start
  from=20,36     the opening view: degrees to the right of straight in front, degrees above the table
  tilt=23        the closing view: degrees off straight down       margin=0.07   free rim round the spread at the end
"""
import glob
import math
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
W, TH = 0.216, 0.0012
DX, DY = float(kv.get('dx', 0.25)), float(kv.get('dy', 0.225))
FLY, GLIDE = int(kv.get('fly', 14)), float(kv.get('glide', 0.12))
FIRST = int(kv.get('first_at', 15))

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


def layout(n, h):
    """where the sheets lie: (row, centre) for each, the far row first, rows balanced and centred"""
    def shape(r):
        return ((-(-n // r) - 1) * DX + W) / ((r - 1) * DY + h)
    nr = int(kv['rows']) if 'rows' in kv else min(range(1, n + 1), key=lambda r: abs(math.log(shape(r) / 1.7)))
    count = [n // nr] * nr
    for j in sorted(range(nr), key=lambda j: (abs(j - (nr - 1) / 2), j))[:n % nr]:
        count[j] += 1                                   # the longer rows in the middle
    shift = [0.0] * nr                                  # rows of equal length would line up: push them apart
    for j in range(1, nr):
        shift[j] = shift[j - 1] + (0 if (count[j] - count[j - 1]) % 2 else DX / 2 * (-1) ** j)
    mid = sum(shift) / nr
    return [(j, Vector(((k - (c - 1) / 2) * DX + shift[j] - mid, ((nr - 1) / 2 - j) * DY, 0)))
            for j, c in enumerate(count) for k in range(c)]


def deal(spots, h):
    """the order the spots are filled in: nearest the middle first, a sheet never before those it lies on"""
    under = [[k for k, (jk, pk) in enumerate(spots) if DY < h and jk == j - 1 and abs(pk.x - p.x) < W + 0.03]
             for j, p in spots]
    order = []
    while len(order) < len(spots):
        free = [i for i in range(len(spots)) if i not in order and all(k in order for k in under[i])]
        order.append(min(free, key=lambda i: (round(spots[i][1].length, 4), spots[i][1].x)))
    return order


pages = sorted(glob.glob(os.path.join(kv['pages'], '*.png')) + glob.glob(os.path.join(kv['pages'], '*.jpg')))
pages = pages[:int(kv.get('max', 30))]
random.shuffle(pages)
want = kv.get('first')
pages.sort(key=lambda p: (not (want and want in os.path.basename(p)), not os.path.splitext(p)[0].endswith('-p1')))
imgs = [bpy.data.images.load(p) for p in pages]
HT = [W * im.size[1] / im.size[0] for im in imgs]
spots = layout(len(pages), max(HT))
order = deal(spots, max(HT))
last = max(1, len(pages) - 1)
pour = int(kv.get('pour', min(150, NF - 40)))
sheets, F0, REL = [], [], []            # in dealing order: the object, the frame it is let go, where it is let go
speed = 0.0
for i, (img, h) in enumerate(zip(imgs, HT)):
    spot = spots[order[i]][1]
    rel = Vector((spot.x + random.uniform(-0.015, 0.015), spot.y + random.uniform(-0.012, 0.012), 0.07 + 0.012 * (i % 3)))
    rot = Vector((random.uniform(-0.03, 0.03), random.uniform(0.02, 0.06), random.uniform(-0.12, 0.12)))
    bpy.ops.mesh.primitive_cube_add(size=1, location=rel)
    o = bpy.context.object
    o.scale = (W, h, TH)
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    uv = o.data.uv_layers.active or o.data.uv_layers.new()          # the page projected straight down, upright
    for lp in o.data.loops:
        v = o.data.vertices[lp.vertex_index].co
        uv.data[lp.index].uv = (v.x / W + 0.5, v.y / h + 0.5)
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
    # dealt faster and faster: each sheet flies in from beyond the far edge, front edge up, slowing as a dealt sheet
    # does, and is let go just above the table with a little speed left (fast, it would slide a metre)
    f0 = FIRST + round(pour * (1 - (1 - i / last) ** 1.9))
    start = Vector((rel.x * 0.6, rel.y + 1.5, 0.32))               # low: high, a sheet crosses the lens as a dark blur
    rot0 = rot + Vector((-0.10, 0, random.uniform(-0.3, 0.3)))
    rb.kinematic = True
    was = 0.0
    for f in sorted({1} | set(range(max(1, f0 - FLY), f0 + 1))):
        u = max(0.0, (f - (f0 - FLY)) / FLY)
        k = GLIDE * u + (1 - GLIDE) * (1 - (1 - u) ** 2)
        o.location = start.lerp(rel, k)
        o.rotation_euler = rot0.lerp(rot, k)
        o.keyframe_insert('location', frame=f)
        o.keyframe_insert('rotation_euler', frame=f)
        speed, was = max(speed, (k - was) * (rel - start).length * S.render.fps) if f == f0 else speed, k
    rb.keyframe_insert('kinematic', frame=1)
    rb.keyframe_insert('kinematic', frame=f0 - 1)
    rb.kinematic = False
    rb.keyframe_insert('kinematic', frame=f0)
    sheets.append(o)
    F0.append(f0)
    REL.append(rel)

K.area((-0.7, 0.6, 1.6), (1.2, 0.8), 34, (0, 0, 0))
K.area((0.9, -0.6, 0.7), (0.8, 0.8), 10, (0, 0, 0))
K.world()
cam, cd = K.camera(35, float(kv.get('fstop', 11)))

# bake the simulation to plain keyframes: the render plays back exactly what was simulated, frame for frame
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

# the camera, from where the sheets came to rest
ASPECT = S.render.resolution_x / S.render.resolution_y
KX = cd.lens / cd.sensor_width


def seen(loc, tg, p):
    """where the point p is in the frame (0..1 across, 0..1 up) for a camera at loc looking at tg"""
    v = (tg - loc).to_track_quat('-Z', 'Y').inverted() @ (p - loc)
    return Vector((0.5 + KX * v.x / -v.z, 0.5 + KX * ASPECT * v.y / -v.z))


def table(loc, tg, c):
    """the point of the table seen at frame position c"""
    d = (tg - loc).to_track_quat('-Z', 'Y') @ Vector(((c.x - 0.5) / KX, (c.y - 0.5) / (KX * ASPECT), -1))
    return loc - d * (loc.z / d.z)


def off(yaw, el):
    yaw, el = math.radians(yaw), math.radians(el)
    return Vector((math.sin(yaw) * math.cos(el), -math.cos(yaw) * math.cos(el), math.sin(el)))


def flat(v):
    return Vector((v.x, v.y, 0))


rest = [flat(rec[o.name][-1].translation) for o in sheets]
edge = [rec[o.name][-1] @ Vector((sx * W / 2, sy * h / 2, 0)) for o, h in zip(sheets, HT) for sx in (-1, 1) for sy in (-1, 1)]
MARGIN = float(kv.get('margin', 0.07))
yaw0, el0 = (float(v) for v in kv.get('from', '20,36').split(','))
D0, D1 = off(yaw0, el0), off(4, 90 - float(kv.get('tilt', 23)))
T0 = rest[0].lerp(rest[1], 0.4) if len(rest) > 1 else rest[0]
O0 = D0 * (W * KX / float(kv.get('open', 0.36)))
T1 = flat(sum(edge, Vector()) / len(edge))
for _ in range(8):                      # the closing view: the whole spread centred, MARGIN of the frame free round it
    lo, hi = 0.2, 30.0
    for _ in range(40):
        d = (lo + hi) / 2
        cs = [seen(T1 + D1 * d, T1, p) for p in edge]
        if max(max(abs(c.x - 0.5), abs(c.y - 0.5)) for c in cs) > 0.5 - MARGIN:
            lo = d
        else:
            hi = d
    cs = [seen(T1 + D1 * hi, T1, p) for p in edge]
    T1 = table(T1 + D1 * hi, T1, Vector(((min(c.x for c in cs) + max(c.x for c in cs)) / 2,
                                         (min(c.y for c in cs) + max(c.y for c in cs)) / 2)))
O1 = D1 * hi


def at(u):
    """camera position and target with the part u of the pull-back done"""
    tg = T0.lerp(T1, u)
    return tg + O0.lerp(O1, u), tg


R = O1.length / O0.length


def part(f, share):
    """the part of the pull-back done at frame f. It is even on screen: the distance grows by the same factor every
    frame, so the picture moves as fast on the last frame as on the first (at a steady rate in metres it would crawl
    by the end, the spread being small in the frame by then). `share` of it is done at a steady rate in metres all
    the same, which is earlier: that much more of the table is in the picture when a sheet lands."""
    u = (f - 1) / max(1, NF - 1)
    g = (R ** u - 1) / (R - 1) if abs(R - 1) > 1e-6 else u
    return share * u + (1 - share) * g


def view(f, share):
    """camera position and target at frame f"""
    return at(part(f, share))


def inside(c, rim):
    return rim <= c.x <= 1 - rim and rim <= c.y <= 1 - rim


def rim(f, f0):
    """how far inside the picture a sheet's middle has to be at frame f: in it at all while the sheet is still
    arriving (it comes in over the far edge), clear of the edge from three frames after it is let go"""
    return 0.03 if f >= f0 + 3 else 0.0


def misses(share):
    """what the pull-back lets out of the picture first, or None: every sheet has to land inside it, and the whole
    spread to be in it soon after the last one"""
    for f in range(1, NF + 1):
        loc, tg = view(f, share)
        for i, (o, f0) in enumerate(zip(sheets, F0)):
            c = seen(loc, tg, rec[o.name][f - 1].translation)
            if f >= f0 and not inside(c, rim(f, f0)):
                return 'sheet %d, let go at frame %d, is at %.2f, %.2f of the frame at frame %d' % (i + 1, f0, c.x, c.y, f)
        if f >= F0[-1] + 8:
            for c in (seen(loc, tg, p) for p in edge):
                if not inside(c, 0.004):
                    return 'a corner of the spread is at %.3f, %.3f of the frame at frame %d' % (c.x, c.y, f)
    return None


def need(i):
    """the part of the pull-back that has to be done when sheet i is let go for it to land and slide inside the picture"""
    worst = 0.0
    for f in range(F0[i], min(NF, F0[i] + 25) + 1):
        p = rec[sheets[i].name][f - 1].translation
        if inside(seen(*at(0.0), p), rim(f, F0[i])):
            continue
        lo, hi = 0.0, 1.0
        for _ in range(30):
            m = (lo + hi) / 2
            lo, hi = (lo, m) if inside(seen(*at(m), p), rim(f, F0[i])) else (m, hi)
        worst = max(worst, hi)
    return worst


SHARE = float(kv['share']) if 'share' in kv else next((s / 20 for s in range(0, 21) if not misses(s / 20)), 1.0)


def pose(scene, *_):
    cam.location, tg = view(scene.frame_current, SHARE)
    K.aim(cam, tg)


slide = [(flat(rec[o.name][-1].translation) - flat(r)).length for o, r in zip(sheets, REL)]
print('pages: %d sheets, dealt %s' % (len(sheets), ' '.join(os.path.splitext(os.path.basename(p))[0] for p in pages)))
print('pages: let go at frames %s, at up to %.2f m/s; slid %.0f mm on average, %.0f mm at most'
      % (' '.join(str(f) for f in F0), speed, 1000 * sum(slide) / len(slide), 1000 * max(slide)))
MISS = misses(SHARE)
print('pages: camera %.2f m from the first sheet to %.2f m from the spread, the pull-back %.0f%% even on screen%s'
      % (O0.length, O1.length, 100 * (1 - SHARE), '; ' + MISS if MISS else ''))
if kv.get('tell'):
    for i, o in enumerate(sheets):
        c0, c1 = seen(*view(F0[i], SHARE), rec[o.name][F0[i] - 1].translation), seen(*at(1.0), rec[o.name][-1].translation)
        print('pages: sheet %2d %-22s let go at %3d at %.2f, %.2f of the frame, rests at %.2f, %.2f of the last; pull-back '
              'needed %.2f, done %.2f' % (i + 1, os.path.splitext(os.path.basename(pages[i]))[0][:22], F0[i], c0.x, c0.y,
                                           c1.x, c1.y, need(i), part(F0[i], SHARE)))
    sys.exit(0)
bpy.app.handlers.frame_change_pre.append(pose)
pose(S)
K.render(OUT, kv)
