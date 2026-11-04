#!/usr/bin/env python3
"""selfcheck.py — the demo-video Blender helpers' own cases.

    python3 selfcheck.py            the kit cases here, then the scene cases inside `blender -b` (BLENDER overrides it)

Each case builds its own fixture and checks both what is kept and what is refused. The scene cases need Blender, so
this runs on the box (LANDING.toml keeps it there); a missing Blender is a failure, never a skip."""
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
RESULTS = []


def check(name, ok, got=''):
    RESULTS.append(bool(ok))
    print('%s %s%s' % ('ok  ' if ok else 'FAIL', name, '' if ok else '  (got %r)' % (got,)), flush=True)


def raises(fn):
    try:
        fn()
    except ValueError:
        return True
    return False


def kit_cases():
    import kit
    check('K1 every easing runs 0 to 1, and an unknown one is refused',
          all(kit.ease(0, k) == 0 and abs(kit.ease(1, k) - 1) < 1e-9 for k in kit.KINDS) and raises(lambda: kit.ease(0.5, 'bounce')))
    check('K1b snap is past 90% a fifth of the way in and never overshoots',
          kit.ease(0.4, 'snap') > 0.9 and max(kit.ease(i / 100, 'snap') for i in range(101)) <= 1.0, kit.ease(0.4, 'snap'))
    pts = [(10, (0.0, 0.0), 'linear'), (20, (10.0, 2.0), 'linear'), (30, (10.0, 2.0), 'inout')]
    check('K2 a track holds before its first key and after its last, and mixes tuples between',
          kit.track(pts, 0) == (0.0, 0.0) and kit.track(pts, 99) == (10.0, 2.0) and kit.track(pts, 15) == (5.0, 1.0), kit.track(pts, 15))
    (cx, cy), (w, h) = kit.plane_for_pixels((0, 0, 1280, 720), (1280, 720), lens=50, sensor=36, depth=10)
    check('K3 the full frame maps to a centred plane as wide as the view', abs(cx) < 1e-9 and abs(cy) < 1e-9 and abs(w - 7.2) < 1e-9 and abs(h - 4.05) < 1e-9, (cx, cy, w, h))
    (cx, cy), (w, h) = kit.plane_for_pixels((500, 50, 720, 610), (1280, 720), lens=50, sensor=36, depth=10)
    check('K3b a rect right of centre and high in the frame sits at +x and +y', cx > 0 and cy > 0 and abs(w - 4.05) < 1e-9, (cx, cy, w))
    holes71 = [(12.5, 12.5), (83.5, 12.5), (12.5, 83.5), (83.5, 83.5)]
    check('K5 holes on 71 mm fit a 71 mm mount and not a 60 mm one',
          kit.fits_mount(holes71, 71.0) and not kit.fits_mount(holes71, 60.0), kit.hole_pitch(holes71))
    skew = [(0, 0), (60, 0), (0, 60), (63, 61)]
    check('K5b four holes that are not a square fit no mount', not kit.fits_mount(skew, 60.0) and raises(lambda: kit.hole_pitch(skew[:3])), kit.hole_pitch(skew))
    roots = [('a', 9), ('b', 6), ('c', 1)]
    t1, t2 = kit.tree_layout(roots), kit.tree_layout(roots)
    check('K6 a forest has every node, the planner spans both columns, and a seed repeats it',
          sum(len(t['nodes']) for t in t1) == 16 and t1[0]['nodes'][0]['w'] == 2 * 84 + 4 and t1[0]['nodes'][1]['w'] == 84
          and t1 == t2 and kit.tree_layout(roots, seed=3) != t1)
    ev = kit.traffic(12, 1.0, 3.0, 0.2)
    check('K7 traffic never sends a tree a message from itself and stays in its window',
          len(ev) == 10 and all(a != b and 0 <= a < 12 and 0 <= b < 12 and 1.0 <= t < 3.0 for t, a, b in ev), ev[:3])
    st = kit.gds_stack({'22/0': [], '34/0': []}, [('22/0', 0.3, 0.0), ('30/0', 0.2, 0.1), ('34/0', 0.5, 0.4)])
    check('K8 a layer the GDS lacks is skipped and takes no height', st == [('22/0', 0.0, 0.3), ('34/0', 0.7, 0.5)], st)
    kicad_cases()


PCB = '''(kicad_pcb (version 20240108)
  (gr_line (start 10 20) (end 50 20) (layer "Edge.Cuts")) (gr_line (start 50 20) (end 50 50) (layer "Edge.Cuts"))
  (gr_arc (start 10 50) (mid 9.4 49.4) (end 10 48) (layer "Edge.Cuts")) (gr_line (start 10 48) (end 10 20) (layer "Edge.Cuts"))
  (footprint "x:R" (layer "F.Cu") (at 30 30 90)
    (property "Reference" "R1" (at 0 -1 90) (layer "F.SilkS"))
    (pad "1" smd rect (at -1 0 90) (size 1 1) (layers "F.Cu" "F.Mask"))
    (pad "" np_thru_hole circle (at 2 0) (size 3.2 3.2) (drill 3.2) (layers "*.Cu" "*.Mask"))
    (model "/somewhere/else/BOX.wrl" (offset (xyz 0 0 0.5)) (scale (xyz 1 1 1)) (rotate (xyz 0 0 270))))
  (footprint "x:Q" (layer "F.Cu") (at 20 40)
    (property "Reference" "Q1" (at 0 0 0) (layer "F.SilkS") (hide yes))
    (model "/x/GONE.wrl")
    (model "/x/BOX.step" (hide yes)))
)'''
WRL = '''#VRML V2.0 utf8
Shape{ appearance Appearance { material Material { diffuseColor 0.8 0.8 0.8 specularColor 0.9 0.9 0.9 } }
  geometry IndexedFaceSet { coord DEF co Coordinate { point [ 0 0 0, 1 0 0, 1 1 0, 0 1 0 ] }
    coordIndex [ 0,1,2,-1,0,2,3,-1, ] } }
Shape{ appearance Appearance { material Material { diffuseColor 0.1 0.1 0.1 specularColor 0.9 0.9 0.9 } }
  geometry IndexedFaceSet { coord DEF co Coordinate { point [ 0 0 1, 1 0 1, 1 1 1 ] } coordIndex [ 0,1,2,-1 ] } }
'''


def kicad_cases():
    import io
    import contextlib
    import kicad
    tmp = tempfile.mkdtemp(prefix='dv-kicad-')
    try:
        os.mkdir(os.path.join(tmp, 'm'))
        with open(os.path.join(tmp, 'b.kicad_pcb'), 'w') as f:
            f.write(PCB)
        with open(os.path.join(tmp, 'm', 'BOX.wrl'), 'w') as f:
            f.write(WRL)
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            imgs, d = kicad.board(os.path.join(tmp, 'b.kicad_pcb'), os.path.join(tmp, 'm'), ppm=4)
        check('K9 kicad.py: the outline runs to the arc, the NPTH is a hole turned with its footprint, mm from the corner',
              d['size'] == [40.6, 30.0] and d['holes'] == [[20.6, 8.0, 3.2]], (d['size'], d['holes']))
        p = d['parts']
        check('K9b a model is found by name in the models dir, transform kept; a missing one is reported, a hidden one skipped',
              [(q['ref'], q['model'], q['x'], q['y'], q['rot'], q['offset'], q['rotate']) for q in p]
              == [('R1', 'BOX', 20.6, 10.0, 90.0, [0, 0, 0.5], [0, 0, 270])] and 'GONE' in err.getvalue() and 'BOX.step' not in err.getvalue(),
              (p, err.getvalue()))
        sh = d['meshes']['BOX']
        check('K9c a VRML shape is in mm (0.1 inch units), a grey with a bright highlight is metal and a black is not',
              len(sh) == 2 and sh[0][2][1] == [2.54, 0, 0] and sh[0][3] == [[0, 1, 2], [0, 2, 3]] and sh[0][1] and not sh[1][1], sh)
        if imgs is not None:   # Pillow present: the pad is gold where the footprint's turn puts it, the board is mask
            top = imgs['top']
            px = lambda x, y: top.getpixel((int((x - 9.4) * 4), int((y - 20) * 4)))[:3]  # noqa: E731
            check('K9d the drawn top: a pad turned with its footprint is gold, bare board is mask green, hole black',
                  top.size == (162, 120) and px(30, 31) == kicad.PAD[:3] and px(40, 45) == kicad.MASK[:3] and px(30, 28) == kicad.HOLE[:3],
                  (top.size, px(30, 31), px(40, 45), px(30, 28)))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    slot_case()


SLOT = '''(kicad_pcb (version 20240108)
  (gr_rect (start 0 0) (end 20 10) (layer "Edge.Cuts"))
  (footprint "x:USB" (layer "F.Cu") (at 10 5 90)
    (pad "S1" thru_hole oval (at 0 0 90) (size 1.2 2.4) (drill oval 0.6 1.8) (layers "*.Cu" "*.Mask"))
    (pad "" np_thru_hole oval (at 0 3 90) (size 1 2) (drill oval 1 2) (layers "*.Cu" "*.Mask")))
)'''


def slot_case():
    import kicad
    tmp = tempfile.mkdtemp(prefix='dv-slot-')
    try:
        with open(os.path.join(tmp, 's.kicad_pcb'), 'w') as f:
            f.write(SLOT)
        imgs, d = kicad.board(os.path.join(tmp, 's.kicad_pcb'), os.path.join(tmp, 'none'), ppm=10)
        check('K9e an NPTH slot is drilled as a round hole as wide as the slot, where its footprint puts it',
              d['holes'] == [[13.0, 5.0, 1.0]], d['holes'])
        if imgs is not None:   # the slot runs along the pad's turned long side: hole at its end, pad beside it
            px = lambda x, y: imgs['top'].getpixel((int(x * 10), int(y * 10)))[:3]  # noqa: E731
            check('K9f a plated slot is drawn turned with its pad: black along the long side, gold across it',
                  px(10.7, 5) == kicad.HOLE[:3] and px(10, 5.45) == kicad.PAD[:3] and px(11.1, 5) == kicad.PAD[:3],
                  (px(10.7, 5), px(10, 5.45), px(11.1, 5)))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


SCENE_CASES = r'''
import json, math, os, sys
sys.dont_write_bytecode = True
sys.path.insert(0, os.environ['SC_HERE'])
import bpy, mathutils
import scene, kit
T = os.environ['SC_TMP']
def out(name, ok, got=''):
    print('SC %s %s\t%s' % ('1' if ok else '0', name, json.dumps(str(got))[:200]), flush=True)
def png(path, w, h, rgba):
    im = bpy.data.images.new(os.path.basename(path), w, h, alpha=True)
    px = []
    for j in range(h):
        for i in range(w):
            px += rgba(i, h - 1 - j)
    im.pixels = px
    im.filepath_raw = path
    im.file_format = 'PNG'
    im.save()

scene.reset(res=(64, 36), frames=(1, 1))
try:
    scene.render_settings('draft'); out('B0 render_settings refuses a quality it does not know', False)
except ValueError:
    s = scene.render_settings('preview')
    out('B0 render_settings refuses a quality it does not know, and preview is Cycles RGBA with motion blur',
        s.render.engine == 'CYCLES' and s.render.image_settings.color_mode == 'RGBA' and s.render.use_motion_blur)

scene.reset(res=(64, 36))
top, bot = os.path.join(T, 'top.png'), os.path.join(T, 'bot.png')
png(top, 40, 30, lambda i, j: [0.1, 0.5, 0.1, 1] if 5 <= i < 35 and 0 <= j < 30 else [0, 0, 0, 0])
png(bot, 40, 30, lambda i, j: [0.1, 0.4, 0.1, 1] if 5 <= i < 35 and 0 <= j < 30 else [0, 0, 0, 0])
b = scene.board_from_images(top, bot, size_mm=(78, 78), holes=[(12.5, 12.5), (83.5 - 18, 12.5), (12.5, 65.5), (65.5, 65.5)], scale=0.01)
idx = set(p.material_index for p in b.data.polygons)
uvs = [d.uv for d in b.data.uv_layers['uv'].data]
top_u = [b.data.uv_layers['uv'].data[li].uv.x for p in b.data.polygons if p.material_index == 0 for li in p.loop_indices]
out('B1 a board has top, bottom, edge and plated-hole faces, and its top maps only onto the board pixels',
    idx == {0, 1, 2, 3} and [m.name for m in b.data.materials][:1] == ['board-top'] and min(top_u) >= 5 / 40 - 1e-4 and max(top_u) <= 35 / 40 + 1e-4, (idx, min(top_u), max(top_u)))
scene.reset(res=(64, 36))
b2 = scene.board_from_images(top, bot, holes=[], scale=0.01)
out('B1b with no holes the board has no plated faces', set(p.material_index for p in b2.data.polygons) == {0, 1, 2})
bp = [b2.data.materials[i].node_tree.nodes['Principled BSDF'] for i in (0, 1)]
out('B1c a board face is opaque: no alpha link, no transmission, no subsurface',
    all(not p.inputs['Alpha'].is_linked and p.inputs['Transmission Weight'].default_value == 0
        and p.inputs['Subsurface Weight'].default_value == 0 for p in bp))
scene.reset(res=(64, 36))
b3 = scene.board_from_images(top, bot, size_mm=(40, 30), holes=[(10, 15, 2.0), (30, 15)], drill=4.0, scale=0.01)
def bore(hx, hy):
    c = ((hx - 20) * 0.01, (15 - hy) * 0.01)
    r = [math.hypot(b3.data.vertices[v].co.x - c[0], b3.data.vertices[v].co.y - c[1])
         for p in b3.data.polygons if p.material_index == 3 for v in p.vertices]
    return max(d for d in r if d < 0.05)
out('B1d a hole given as (x, y, d) is drilled d wide, one given as (x, y) takes drill',
    abs(bore(10, 15) - 0.01) < 1e-4 and abs(bore(30, 15) - 0.02) < 1e-4, (bore(10, 15), bore(30, 15)))
scene.reset(res=(64, 36))
bs = scene.board_from_images(top, bot, size_mm=(40, 30), holes=[(10, 15)], scale=0.01, finish='satin')
sp = bs.data.materials[0].node_tree.nodes['Principled BSDF']
gp = scene.board_from_images(top, bot, size_mm=(40, 30), scale=0.01, name='gloss').data.materials[0].node_tree.nodes['Principled BSDF']
out('B1e a satin board has no coat and takes its metal from the image (the pads); a gloss one keeps its coat and no metal',
    sp.inputs['Coat Weight'].default_value == 0 and sp.inputs['Metallic'].is_linked and sp.inputs['Roughness'].is_linked
    and bs.data.materials[3].node_tree.nodes['Principled BSDF'].inputs['Roughness'].default_value >= 0.35
    and gp.inputs['Coat Weight'].default_value > 0 and not gp.inputs['Metallic'].is_linked,
    (sp.inputs['Coat Weight'].default_value, sp.inputs['Metallic'].is_linked, gp.inputs['Coat Weight'].default_value))
try:
    scene.board_from_images(top, bot, size_mm=(40, 30), scale=0.01, finish='matte'); out('B1f an unknown finish is refused', False)
except ValueError:
    out('B1f an unknown finish is refused', True)

scene.reset(res=(64, 36))
plate, so = scene.mount(pitch=60, scale=0.01)
xs = sorted(round(o.location.x, 4) for o in so)
out('B2 the standoffs sit on the pitch square, centred', xs == [-0.3, -0.3, 0.3, 0.3] and len(so) == 4, xs)

scene.reset(res=(64, 36))
doc = {'bbox': [0, 0, 10, 10], 'layers': {'34/0': [[0, 0, 4, 0, 4, 4, 0, 4], [5, 5, 9, 5, 9, 6]], '36/0': [[1, 1, 2, 1, 2, 2]]}}
st = kit.gds_stack(doc['layers'], [('34/0', 0.5, 0), ('99/0', 1, 0)])
root, objs = scene.gds_extrude(doc, st, {'34/0': (0.2, 0.4, 0.9, 1)})
me = objs[0].data
out('B3 each polygon becomes a closed prism, and only the stacked layers are built',
    len(objs) == 1 and len(me.vertices) == 14 and len(me.polygons) == 4 + 3 + 2 * 2,
    (len(objs), len(me.vertices), len(me.polygons)))

scene.reset(res=(1280, 720))
cam = scene.camera(lens=50)
im = os.path.join(T, 'ui.png'); png(im, 8, 8, lambda i, j: [1, 1, 1, 1])
ui = scene.ui_plane(im, (280, 50, 720, 610), cam, (1280, 720))
bpy.context.scene.render.resolution_percentage = 100
w = ui.data.vertices
co = [ui.matrix_world @ v.co for v in w]
pts = {'c%d' % i: (ui, tuple(v.co)) for i, v in enumerate(w)}
tr = scene.track(cam, pts, 1, 1)['frames'][1]
xs, ys = sorted(round(p[0]) for p in tr.values()), sorted(round(p[1]) for p in tr.values())
out('B4 a UI plane covers exactly its pixel rect, and track reports where its corners land',
    xs[0] == 280 and xs[-1] == 1000 and ys[0] == 50 and ys[-1] == 660 and all(p[2] for p in tr.values()), (xs, ys))

scene.reset(res=(1280, 720))
cam = scene.camera(lens=50)
im = os.path.join(T, 'frame.png'); png(im, 16, 9, lambda i, j: [1, 0, 0, 1] if i < 4 else [0, 0, 1, 1])
win = scene.ui_plane(im, (320, 0, 960, 720), cam, (1280, 720), crop=True, fixed=True, edge=0.05)
before = win.matrix_world.copy()
cam.location = (3, 0, 0)
bpy.context.view_layer.update()
uv = sorted(round(d.uv.x, 4) for d in win.data.uv_layers.active.data)
rider = scene.ui_plane(im, (0, 0, 1280, 720), cam, (1280, 720), name='rider')
bpy.context.view_layer.update()
out('B4b a fixed, cropped window stays put when the camera moves, shows only its rect, and has a slab behind it',
    win.parent is None and win.matrix_world == before and uv[0] == 0.25 and uv[-1] == 1.0 and len(win.children) == 1
    and rider.parent == cam and rider.data.uv_layers.active.data[0].uv.x in (0.0, 1.0), (uv, win.parent, len(win.children)))

scene.reset(res=(1280, 720))
cam = scene.camera(lens=50)
win = scene.ui_plane(im, (320, 0, 960, 720), cam, (1280, 720), crop=True, fixed=True)
near = scene.empty('near', (0, 0, -5)); far = scene.empty('far', (0, 0, -20)); aside = scene.empty('aside', (-5, 0, -20))
bpy.context.view_layer.update()
hid = scene.track(cam, {'near': near, 'far': far, 'aside': aside}, 1, 1, occluders=[win])['frames'][1]
bare = scene.track(cam, {'far': far}, 1, 1)['frames'][1]
out('B4c track hides a point behind an occluder, and keeps one in front of it, one beside it, and one with none',
    hid['near'][2] == 1 and hid['far'][2] == 0 and hid['aside'][2] == 1 and bare['far'][2] == 1, (hid, bare))

scene.reset(res=(64, 36))
trees = kit.tree_layout([('a', 3), ('b', 2), ('c', 4)], cols=3)
g = scene.node_graph(trees, blocks={'Slack': (0, 0, 40, 60), 'GitHub': (400, 0, 40, 60)})
x1, x2 = g['arc']('a', (10, 20), (300, 40), lift=1.0, bend=50), g['arc']('b', (300, 40), (10, 20), lift=0)
c1 = [tuple(round(v, 4) for v in p.co[:3]) for p in x1.data.splines[0].points]
c2 = [round(p.co[2], 4) for p in x2.data.splines[0].points]
out('B5 the map has a node per agent, an edge per non-root node, its named blocks, and an arc from a to b lifted mid-way',
    [len(r) for r in g['nodes']] == [3, 2, 4] and [len(e) for e in g['edges']] == [2, 1, 3]
    and sorted(g['blocks']) == ['GitHub', 'Slack'] and x1.name != x2.name
    and c1[0] == (0.1, -0.2, 0.12) and c1[-1] == (3.0, -0.4, 0.12) and c1[16][2] > 0.12 and abs(c1[16][1] + 0.3) > 0.1
    and set(c2) == {0.12}, (c1[0], c1[16], c1[-1], sorted(g['blocks'])))
g2 = scene.node_graph([{'nodes': trees[0]['nodes'][:1]}], name='bare')
out('B5b a lone root has no edges, and without blocks there are none', g2['edges'] == [[]] and g2['blocks'] == {})

scene.reset(res=(64, 36), frames=(1, 2))
cam = scene.camera(lens=35)
cam.location = (0, -4, 1); scene.bake(cam, lambda f: {'aim': (0, 0, 0)}, 1, 1)
scene.studio_rig(size=1)
scene.backdrop()
o = scene.empty('mover')
scene.bake(o, lambda f: {'location': (f * 1.0, 0, 0)}, 1, 2)
bpy.context.scene.frame_set(2)
scene.render_settings('preview', out=os.path.join(T, 'r'))
bpy.context.scene.cycles.samples = 1
bpy.context.scene.frame_end = 1
bpy.ops.render.render(animation=True)
f1 = os.path.join(T, 'r', '0001.png')
out('B6 a baked key holds its frame, and a studio scene renders an RGBA PNG',
    abs(o.location.x - 2.0) < 1e-6 and os.path.exists(f1) and not os.path.exists(os.path.join(T, 'r', '0002.png')), os.listdir(os.path.join(T, 'r')))
scene.reset(res=(64, 36))
bd = scene.board_from_images(top, bot, size_mm=(40, 30), scale=0.01)
pj = {'size': [40, 30], 'holes': [], 'meshes': {'BOX': [[[0.8, 0.8, 0.8, 1], True, [[0, 0, 0], [2, 0, 0], [2, 1, 0]], [[0, 1, 2]]],
                                                        [[0.1, 0.1, 0.1, 1], False, [[0, 0, 1], [1, 0, 1], [1, 1, 1]], [[0, 1, 2]]]]},
      'parts': [dict(ref='R%d' % i, model='BOX', x=10, y=5, rot=90, side=s, offset=[0, 0, 0], rotate=[0, 0, 90], scale=[1, 1, 1]) for i, s in ((1, 'F'), (2, 'F'), (3, 'B'))]}
ps = scene.board_parts(pj, bd, scale=0.01)
bpy.context.view_layer.update()
# (2, 0, 0) mm: the model's rotate z 90 turns it by -90 to (0, -2), the footprint's 90 back to (2, 0)
v1 = ps[0].matrix_world @ ps[0].data.vertices[1].co
out('B7 board_parts: one shared mesh per model, a part sits on its footprint turned by its angle, a back part hangs under',
    len(ps) == 3 and ps[0].data is ps[1].data and ps[0].parent is bd and len(ps[0].data.materials) == 2
    and abs(ps[0].location.x + 0.10) < 1e-6 and abs(ps[0].location.y - 0.10) < 1e-6 and abs(ps[0].location.z - 0.008) < 1e-6
    and ps[2].location.z < 0 and abs(v1.x + 0.08) < 1e-6 and abs(v1.y - 0.10) < 1e-6,
    (len(ps), tuple(ps[0].location), tuple(v1)))
ss = scene.board_parts(pj, bd, scale=0.01, name='satin', finish='satin')
sm = {m.name: m.node_tree.nodes['Principled BSDF'].inputs for m in ss[0].data.materials}
gm = {m.name: m.node_tree.nodes['Principled BSDF'].inputs for m in ps[0].data.materials}
out('B7b satin parts: matte, uncoated plastic and metal that stays metal; gloss parts keep their coat',
    sm['satin-metal0']['Metallic'].default_value == 1 and sm['satin-mat1']['Coat Weight'].default_value == 0
    and sm['satin-mat1']['Roughness'].default_value >= 0.6 and gm['parts-mat1']['Coat Weight'].default_value > 0,
    sorted(sm))

'''


def scene_cases():
    blender = os.environ.get('BLENDER') or shutil.which('blender')
    if not blender:
        check('B* Blender is on PATH (the scene cases need it)', False, None)
        return
    tmp = tempfile.mkdtemp(prefix='dv-blender-sc-')
    try:
        script = os.path.join(tmp, 'cases.py')
        with open(script, 'w') as f:
            f.write(SCENE_CASES)
        env = dict(os.environ, SC_HERE=HERE, SC_TMP=tmp)
        p = subprocess.run([blender, '-b', '--factory-startup', '--python-exit-code', '1', '--python', script],
                           capture_output=True, text=True, env=env, timeout=600)
        got = [l for l in p.stdout.splitlines() if l.startswith('SC ')]
        for l in got:
            _, ok, rest = l.split(' ', 2)
            name, _, detail = rest.partition('\t')
            check(name, ok == '1', json.loads(detail))
        check('B* Blender ran every scene case and exited clean', p.returncode == 0 and len(got) == len(set(re.findall(r"out\('(B\w+) ", SCENE_CASES))),
              (p.returncode, len(got), p.stderr[-800:] or p.stdout[-800:]))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == '__main__':
    kit_cases()
    scene_cases()
    bad = RESULTS.count(False)
    print('demo-video blender selfcheck: %d passed, %d failed' % (len(RESULTS) - bad, bad))
    sys.exit(1 if bad else 0)
