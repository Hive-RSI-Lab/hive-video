"""The design's board standing in filmed footage. A clip's camera, table and sun were solved beforehand (match.json:
one camera per frame, the table's plane, the way the sunlight travels, how deep the real shadows are, a clean picture
of the table for every frame), so the render has the clip's lens and light, throws its shadows on the real wood, and
at the end dissolves into the filmed board.

    blender -b -P match.py -- OUTDIR FRAMES real=DIR match=MATCH.json [fall] [k0= mix=A,B lut=FILE.cube look=FILE.json
                              land=A,B pow= slow=A,B h0= over= blur= sun= sky=R,G,B open= window=S,E,A,B gain=R,G,B level= fstop=
                              studio=1 floor=R,G,B pool=MM sweep=A,B[,TURN] upright=1 case=DIR petg=R,G,B
                              side=1 comp=1 probe=1]

Frame F of the shot is frame k0 + F of the clip. Up to mix A the picture is the render over the clean table, from A
to B it dissolves into the filmed frame, after B it is the filmed frame alone (so the cut never shows a seam). The
render is made at the clip's own size, never larger, and goes through the same grade (lut=) as the clip.

The render's light becomes the clip's pixel values the way the camera made them: times the camera's gain for each
colour (gain=, or "camera": {"gain": [r, g, b]} in the look file: how much of full white a white card in this sun
would have been given, found with probe=1 from something white on the board), then through the camera's curve
(taken to be the video standard's, Rec. 709). The clean table goes the other way through the same curve, is
darkened by the render's shadows as light, and comes back; so a shadow is as deep as light makes it, not as deep
as it looks in pixel values.

The clip's light is not the same on every frame (thin cloud over the sun while the camera's exposure was locked):
match.json has each frame's level as its "gain", the table against its clean picture, and a steadied film from
smooth.py has the filmed frame's own under "src". A look file says which level its camera gain was found at
("camera": {"gain": [...], "level": 0.805}, or level= here), and the render's light is multiplied by the frame's
level over that one, so the board dims with the table it stands on and with the filmed board that takes its place.
A frame before the first measured one takes the first one's level, one after the last the last one's.

fall: every part drops onto its footprint, left to right and back to front, each later one in less slow motion
(slow=A,B: how many times slower than life the first and the last fall; land=A,B: the frames the first and the last
land on). A part is let go from just above where it and its shadow come into the picture, over= metres higher so
that it comes in already moving, and never from under h0= metres; nothing appears in mid-air.

look=FILE.json names finishes the CAD colours cannot give: {"materials": {"mat_9": {"col": [r, g, b], "rough": 0.4}},
"refs": {"J[23]": {"mat_9": {...}}}, "spots": [{"name": "ring", "at": [[x, y], ...], "r": 3.6, "of": ["mat_1"],
"finish": {...}}]}. A finish under refs is given to those footprints alone; a spot gives one to the board's faces
within r millimetres of its points (a mounting hole's bare ring). A finish with "tint" is a clear coloured coat.

The room's own light is even from every side unless the look file says where the window is: "room": {"window":
[share, elevation, inner, outer], "open": 0.6}. The window stands where the sun comes from; share is how much of the
room light on the open table comes through it, elevation its middle above the table, and it is at full strength
within inner degrees of that middle and gone at outer. What mirrors the room (cans, leads, the mask's gloss) then
shows a dim room with one bright side, as filmed. open is how much of the room's light the shade beside the board
still gets; probe=1 prints what it is in the render, and it has to be set again when the window changes.

probe=1 prints, for every material, the render's light beside the clip's on the same pixels (both with the camera's
curve taken off, so clip over render is the factor a matt finish's colour is out by), which is how a look file is
tuned: the board in the render stands exactly where the filmed one does. It also reads the table beside the board,
in the shade and in the sun, the same way.

studio=1: the render stands on no table at all. Where the table is there is a dark floor that fades to black away from
the board (floor= its colour under the board, pool= the millimetres over which it fades), under the clip's own sun and
room light; what is not the camera still meets the wood, so the board is lit and mirrors exactly as on the table and
is the same board when the filmed one takes its place. No clean picture of the table is used.

sweep=A,B[,TURN] replaces the dissolve: from frame A to frame B a line of light crosses the picture, the render ahead
of it and the filmed frame behind it. The line is where a sheet of the clip's own sunlight would fall: a plane that
holds the sun's direction, so on the table it is straight and over every part it bends as that part's shadow does
(each pixel's place comes from the render's Position pass). The picture itself turns over by the table behind each
pixel, not by the part in front of it: a tall part the light has yet to climb would else stay a render in front of
filmed table, and read as a drawing laid over a photograph. It travels along the board's X, turned TURN degrees.
The line is light, not paint: it multiplies what it falls on, burns out where that is bright, blooms as a lens
blooms, and the filmed table behind it stays a little over-exposed for a moment and settles; a filmed pixel the
light has left is the filmed pixel, untouched. The frame the line is at the board's middle goes to events.json as
a hit for the score.

case=DIR: the board's printed case (base.stl and lid.stl from the enclosure tool, millimetres in the enclosure's frame,
which has the board's top-left corner at (0, 90, 1.6)) stands round the board, in petg= plastic, and match.json is the
solve of a take of the closed case. The base stands on the table from the first frame; the board drops into it and
the lid drops shut on it (land=A,B: the frames they land on; slow=, h0=, over= as for fall), both from above the
picture, and both go to events.json as hits. upright=1 then makes the line of light an upright sheet, not one that
holds the sun's direction: over a box as tall as a case a low sun's sheet leans most of the box's width, and the
picture would turn over by table that is far behind the box. An upright sheet cuts the box and the table in one
section, the picture turns over at each pixel's own place, and the line is drawn on all it meets.

match.json's "real" folder holds the filmed frames as NNNNN.jpg or NNNNN.png. If it has "fix" (3 by 3), the render's
pixel values go through it before they meet the filmed ones: a look tuned against frames that were decoded with one
video matrix, shown beside frames decoded with another.

Each frame is kept as OUTDIR/exr/NNNN.exr (the render and its passes), so comp=1 puts the picture together
again without rendering, and a killed run goes on where it stopped.
"""
import fnmatch
import json
import math
import os
import random
import sys

import bpy
import numpy as np
import OpenImageIO as oiio
from mathutils import Euler, Matrix, Vector

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _shot as K  # noqa: E402


def path(p):
    return os.path.expandvars(os.path.expanduser(p))


pos, kv = K.args()
OUT, NF = pos[0], int(pos[1])
Q = kv.get('quality', 'preview')
FALL = 'fall' in pos
M = json.load(open(path(kv['match'])))
FR = {r['k']: r for r in M['frames']}
K0 = int(kv.get('k0', min(k for k, r in FR.items() if 'gain' in r) - 1))
MIX = [int(v) for v in kv.get('mix', '%d,%d' % (NF + 1, NF + 2)).split(',')]
W, H = M['size']
RW = min(W, K.SIZES[Q][0])                      # the render is never larger than the clip it has to sit in
RH = int(round(RW * H / W))
GAMMA = 2.2                                     # the power the solver put on pixel values for match.json's shadow levels
EVENTS = dict(lands=[], hits=[], refs=0)
REAL = path(kv['real'])
LOOK = json.load(open(path(kv['look']))) if kv.get('look') else {}
EXPO = np.array([float(v) for v in kv['gain'].split(',')] if kv.get('gain') else LOOK.get('camera', {}).get('gain', [1.0, 1.0, 1.0]), np.float32)
LEVEL0 = float(kv.get('level', LOOK.get('camera', {}).get('level', 0)))        # the clip's level on the frame the camera gain was found on; 0: unknown, the render keeps one level
OWN = any('src' in r for r in FR.values())      # a steadied film: a frame's "gain" is the whole film's mean, its own level is the source frame's
LV = {k: float((r['src'] if OWN else r)['gain']) for k, r in FR.items() if ('src' in r if OWN else 'gain' in r)}
LV = {k: float(np.mean([LV[j] for j in range(k - 3, k + 4) if j in LV])) for k in LV}      # each was measured by itself: a per cent of jitter, which a board must not flicker with
STUDIO = bool(kv.get('studio'))
SW = [float(v) for v in kv['sweep'].split(',')] if kv.get('sweep') else None
FIX = np.array(M['fix'], np.float32) if M.get('fix') else None
LAST = int(SW[1]) - 1 if SW else MIX[1] - 1     # the last frame that needs the render


def level(k):
    """how bright the clip's light is on frame k, against the frame the look's camera gain was found on"""
    if not LEVEL0 or not LV:
        return 1.0
    return LV[min(LV, key=lambda j: abs(j - k))] / LEVEL0


def cam_x(v):
    """a pixel value of the clip (0..1) -> the light the camera took for it, as a share of what it writes as full white"""
    v = np.asarray(v, np.float32)
    return np.where(v < 0.081, v / 4.5, ((np.maximum(v, 0.081) + 0.099) / 1.099) ** (1 / 0.45))


def cam_v(x):
    """light -> the pixel value the camera writes for it (Rec. 709's curve; above full white it carries on, see shoulder)"""
    x = np.asarray(x, np.float32)
    return np.where(x < 0.018, 4.5 * x, 1.099 * np.maximum(x, 0.018) ** 0.45 - 0.099)


S = K.setup(kv, NF, samples=64 if Q == 'preview' else 192)
S.render.resolution_x, S.render.resolution_y = RW, RH
S.view_settings.view_transform, S.view_settings.look = 'Standard', 'None'
S.render.film_transparent = True
S.cycles.use_adaptive_sampling = True
S.cycles.adaptive_threshold = float(kv.get('noise', 0.02 if Q == 'preview' else 0.008))
S.cycles.denoising_prefilter = 'ACCURATE'
S.cycles.max_bounces = 8
S.cycles.sample_clamp_indirect = 6
S.cycles.caustics_reflective = S.cycles.caustics_refractive = False
VL = bpy.context.view_layer
VL.cycles.use_pass_shadow_catcher = not STUDIO  # the table's shadows as their own picture: the real table is multiplied by it
VL.use_pass_position = bool(SW)                 # where in the room each pixel is: the line of light falls by it
VL.use_pass_material_index = bool(kv.get('probe'))
img_set = S.render.image_settings
try:
    img_set.media_type = 'MULTI_LAYER_IMAGE'
except (AttributeError, TypeError):
    pass
img_set.file_format = 'OPEN_EXR_MULTILAYER'
img_set.color_depth = '16'
img_set.exr_codec = 'ZIP'


# ---------------------------------------------------------------- the board and its parts

def imp(name):
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=os.path.join(REAL, name))
    return [o for o in bpy.data.objects if o not in before]


KEYS = (('col', 'Base Color'), ('rough', 'Roughness'), ('metal', 'Metallic'), ('alpha', 'Alpha'), ('coat', 'Coat Weight'),
        ('coat_rough', 'Coat Roughness'), ('spec', 'Specular IOR Level'), ('ior', 'IOR'), ('sheen', 'Sheen Weight'))


def coat(m, d):
    """a clear coloured layer over what lies under it, as solder mask is over copper and laminate: the light goes
    through it on the way down and again on the way up (so 'tint' counts twice), and its surface mirrors the parts
    that stand on it"""
    nt = m.node_tree
    nt.nodes.clear()
    out, mix, tr = (nt.nodes.new(n) for n in ('ShaderNodeOutputMaterial', 'ShaderNodeMixShader', 'ShaderNodeBsdfTransparent'))
    try:
        gl = nt.nodes.new('ShaderNodeBsdfAnisotropic')          # the glossy node's name since Blender 4
    except RuntimeError:
        gl = nt.nodes.new('ShaderNodeBsdfGlossy')
    fr, mul = nt.nodes.new('ShaderNodeFresnel'), nt.nodes.new('ShaderNodeMath')
    tr.inputs['Color'].default_value = tuple(d['tint'])[:3] + (1,)
    gl.inputs['Color'].default_value = (1, 1, 1, 1)
    gl.inputs['Roughness'].default_value = d.get('rough', 0.15)
    geo, ior = nt.nodes.new('ShaderNodeNewGeometry'), nt.nodes.new('ShaderNodeMath')
    n = d.get('ior', 1.5)
    ior.operation = 'MULTIPLY_ADD'      # met from beneath (the sunlight's way down is traced upwards) the Fresnel node turns the index
    ior.inputs[1].default_value = 1.0 / n - n   # over and past 42 degrees mirrors everything, which left what is under the coat unlit:
    ior.inputs[2].default_value = n     # so from beneath it is handed the index already turned over
    nt.links.new(geo.outputs['Backfacing'], ior.inputs[0])
    nt.links.new(ior.outputs['Value'], fr.inputs['IOR'])
    mul.operation, mul.use_clamp = 'MULTIPLY', True
    mul.inputs[1].default_value = d.get('gloss', 1.0)
    nt.links.new(fr.outputs['Fac'], mul.inputs[0])
    nt.links.new(mul.outputs['Value'], mix.inputs['Fac'])
    nt.links.new(tr.outputs['BSDF'], mix.inputs[1])
    nt.links.new(gl.outputs['BSDF'], mix.inputs[2])
    nt.links.new(mix.outputs['Shader'], out.inputs['Surface'])


def finish(m, d):
    if 'tint' in d:
        return coat(m, d)
    b = K.bsdf(m)
    if not b:
        return
    for key, name in KEYS:
        if key in d and name in b.inputs:
            b.inputs[name].default_value = (tuple(d[key])[:3] + (1,)) if key == 'col' else d[key]


def auto(m, kind, big):
    """a finish for one of KiCad's flat CAD colours, as a filmed board has them (not a studio render: no gold, no
    chrome). The part models carry a colour and nothing else, so the colour decides: black and white are plastic,
    grey is metal, a strong colour is glossy plastic"""
    b = K.bsdf(m)
    r, g, bl = list(b.inputs['Base Color'].default_value)[:3]
    v = max(r, g, bl)
    sat = (v - min(r, g, bl)) / v if v else 0
    if kind == 'board':
        if v > 0.85 and sat < 0.12:                               # silkscreen
            return dict(col=(0.78, 0.78, 0.76), rough=0.55, alpha=1)
        if g > r * 1.3 and g > bl * 1.2:                          # solder mask: a clear green coat, what is under it shows through
            return dict(tint=(0.21, 0.78, 0.42), rough=0.16)
        if m.name == 'mat_0':                                     # copper under the mask: its tracks read a little lighter
            return dict(col=(0.56, 0.62, 0.36), metal=0, rough=0.5)
        if m.name == 'mat_1' or r > bl * 3:                       # pads: tinned
            return dict(col=(0.78, 0.78, 0.75), metal=1, rough=0.4)
        return dict(col=(0.46, 0.52, 0.27), rough=0.6, alpha=1)   # laminate: pale yellow green at the board's edge
    if v < 0.3 and sat < 0.5:                                     # moulded packages, ferrite, black plastic
        return dict(col=(0.022, 0.022, 0.024), rough=0.42, metal=0)
    if v > 0.85 and sat < 0.12:                                   # white plastic
        return dict(col=(0.80, 0.80, 0.78), rough=0.5, metal=0)
    if sat < 0.25:                                                # leads, shields, cans
        return dict(col=(v * 0.9 + 0.05,) * 3, metal=1, rough=0.42 if m.name in big else 0.3)
    if v > 0.3 and r > bl * 1.6 and g > bl * 1.2 and g > r * 0.5:  # gold contacts
        return dict(metal=1, rough=0.3)
    return dict(col=(r * 0.8, g * 0.8, bl * 0.8), rough=0.3, metal=0)   # coloured plastic


def refs_of(parts):
    """one object per footprint: the empties KiCad's glb puts over each footprint's model(s)"""
    r = [o for o in parts if o.parent and o.parent.parent is None and o.children]
    return r or [o for o in parts if o.children and o.type == 'EMPTY' and o.parent]


def tune(objs, kind):
    big = {sl.material.name for o in objs if o.type == 'MESH' and max(o.dimensions) > 0.008
           for sl in o.material_slots if sl.material}
    seen = set()
    for o in objs:
        if o.type != 'MESH':
            continue
        for sl in o.material_slots:
            m = sl.material
            if m and m.name not in seen and K.bsdf(m):
                seen.add(m.name)
                was, d = [round(v, 2) for v in K.bsdf(m).inputs['Base Color'].default_value][:3], auto(m, kind, big)
                finish(m, d)
                finish(m, LOOK.get('materials', {}).get(m.name, {}))
                if kv.get('probe'):
                    print('LOOK %-10s %s -> %s %s' % (m.name, was, d, LOOK.get('materials', {}).get(m.name, '')), flush=True)


board, parts = imp('board.glb'), imp('parts.glb')
tune(board, 'board')
tune(parts, 'part')
REFS = refs_of(parts)
K.heights(REFS, max((o.matrix_world @ Vector(c)).z for o in board if o.type == 'MESH' for c in o.bound_box),
          os.path.join(REAL, 'part_heights.json'))   # a model of the wrong size gets the part's real height
USE = {}                                            # material -> the footprints that wear it
for ref in REFS:
    for o in ref.children_recursive:
        for sl in o.material_slots if o.type == 'MESH' else ():
            if sl.material:
                USE.setdefault(sl.material.name, set()).add(ref.name.split('.')[0])
for pat, mats in LOOK.get('refs', {}).items():      # a finish for some footprints alone: they get their own copy of the material
    own = {}
    for ref in REFS:
        if not fnmatch.fnmatchcase(ref.name.split('.')[0], pat):
            continue
        for o in ref.children_recursive:
            for sl in o.material_slots if o.type == 'MESH' else ():
                src = sl.material.name if sl.material else None
                if src in mats:
                    if src not in own:
                        own[src] = sl.material.copy()
                        own[src].name = '%s@%s' % (src, pat)
                        finish(own[src], mats[src])
                    sl.material = own[src]
                    USE.setdefault(own[src].name, set()).add(ref.name.split('.')[0])
done = set()
for o in board + parts:                             # KiCad's models bring corner normals of their own that lean up to 45 degrees off
    me = o.data if o.type == 'MESH' else None       # their faces (a box's flat top shades like a pillow, and the flat flag does not
    if me is None or me.name in done:               # undo it): thrown away, and the normals made again, creased where faces meet
        continue                                    # at more than 30 degrees, so a box is flat and a can is round
    done.add(me.name)
    if 'custom_normal' in me.attributes:
        me.attributes.remove(me.attributes['custom_normal'])
    me.polygons.foreach_set('use_smooth', [True] * len(me.polygons))
    me.set_sharp_from_angle(angle=math.radians(30))
    me.update()

pts = [o.matrix_world @ Vector(c) for o in board if o.type == 'MESH' for c in o.bound_box]
lo = Vector([min(p[i] for p in pts) for i in range(3)])
hi = Vector([max(p[i] for p in pts) for i in range(3)])
print('BOARD', tuple(round(v, 5) for v in lo), tuple(round(v, 5) for v in hi), 'REFS', len(REFS), flush=True)

# the solver's frame: millimetres, origin on the top face at the outline's top-left corner, X right, Y away, Z up
ox, oy = M['board']['origin']
ORG = np.array([ox / 1000.0, -oy / 1000.0, hi.z])
MID = np.array([M['board']['size'][0] / 2.0, -M['board']['size'][1] / 2.0, 0.0])
TN, TD = np.array(M['table']['n']), float(M['table']['d'])
LIGHT = np.array(M['sun']['light'])
SUN = float(kv.get('sun', 2.67))
NORM = SUN * float(M['cos_sun']) / math.pi          # what a white table would show in the sun; the clean picture over this is the wood's colour

for i, sp in enumerate(LOOK.get('spots', [])):      # a finish for the board's faces near some points
    own, at = {}, np.array(sp['at'], float).reshape(-1, 2)
    for o in board:
        me = o.data if o.type == 'MESH' else None
        slots = [j for j, sl in enumerate(o.material_slots) if sl.material and sl.material.name in sp['of']] if me else []
        if not slots:
            continue
        n = len(me.polygons)
        c, mi = np.zeros(n * 3, np.float32), np.zeros(n, np.int32)
        me.polygons.foreach_get('center', c)
        me.polygons.foreach_get('material_index', mi)
        mw = np.array(o.matrix_world)
        c = (c.reshape(-1, 3) @ mw[:3, :3].T + mw[:3, 3] - ORG) * 1000.0
        near = (np.hypot(c[:, None, 0] - at[None, :, 0], c[:, None, 1] - at[None, :, 1]) < sp['r']).any(1)
        for j in slots:
            hit = near & (mi == j)
            if not hit.any():
                continue
            src = o.material_slots[j].material
            if src.name not in own:
                own[src.name] = src.copy()
                own[src.name].name = '%s@%s' % (src.name, sp.get('name', 'spot%d' % i))
                finish(own[src.name], sp['finish'])
            me.materials.append(own[src.name])
            mi[hit] = len(me.materials) - 1
            print('match: spot %s: %d faces of %s' % (own[src.name].name, int(hit.sum()), src.name), flush=True)
        me.polygons.foreach_set('material_index', mi)
        me.update()

WORN = sorted({sl.material.name for o in board + parts if o.type == 'MESH' for sl in o.material_slots if sl.material})
for i, n in enumerate(WORN):                        # every material its own number in the index pass (probe=1)
    bpy.data.materials[n].pass_index = i + 1


def scene(X):
    """solver millimetres -> scene metres"""
    return Vector(np.asarray(X, float) / 1000.0 + ORG)


def table_z(x, y, drop=0.0):
    return (TD - TN[0] * x - TN[1] * y) / TN[2] - drop


CASE = []                                           # the printed case round the board: its base, its lid
if kv.get('case'):
    pet = K.mat('petg', [float(v) for v in kv.get('petg', '0.30,0.40,0.55').split(',')], float(kv.get('petg_rough', 0.46)))[0]
    K.bsdf(pet).inputs['Subsurface Weight'].default_value = 0.08
    K.bsdf(pet).inputs['Subsurface Radius'].default_value = (0.002, 0.002, 0.002)
    if float(kv.get('petg_sheen', 0)):              # printed in layers: each wall is fine ridges lying flat, so a light's
        pb = K.bsdf(pet)                            # shine on it is a streak up the wall, seen from far off the mirror's line.
        pb.inputs['Anisotropic'].default_value = float(kv['petg_sheen'])     # The top (laid on the plate) keeps a narrow one.
        ptan = pet.node_tree.nodes.new('ShaderNodeCombineXYZ')
        for i, v in enumerate((0.05, 0.0, 1.0)):   # up, and a little along x so the top has a direction too
            ptan.inputs[i].default_value = v
        pet.node_tree.links.new(ptan.outputs[0], pb.inputs['Tangent'])
        if kv.get('petg_ior'):
            pb.inputs['IOR'].default_value = float(kv['petg_ior'])
        if kv.get('petg_spec'):                     # LEVEL[,R,G,B]: how strong the shine is (0.5 is plain plastic) and its tint:
            sp = [float(v) for v in kv['petg_spec'].split(',')]      # clear plastic sends light back from inside its ridges too
            pb.inputs['Specular IOR Level'].default_value = sp[0]
            if len(sp) == 4:
                pb.inputs['Specular Tint'].default_value = tuple(sp[1:]) + (1,)
    if kv.get('petg_wall') or kv.get('petg_grain'):
        # A print's walls and its top are different surfaces. A wall is ridges of clear plastic lying flat: where the sun
        # reaches them it gets inside and comes back out pale, so a sunlit wall is lighter and less blue than the top
        # (petg_wall=R,G,B, the colour of a wall that faces the sun; a wall turned from it keeps the top's colour, as the
        # filmed one does). The top is lines laid side by side and reads as a fine mottle (petg_grain=SHARE[,PER_METRE]:
        # its colour varies by that share, in patches 1/PER_METRE metres across). Both hold to the case as it moves.
        pb, nt = K.bsdf(pet), pet.node_tree
        ctop = [float(v) for v in kv.get('petg', '0.30,0.40,0.55').split(',')]
        cwall = [float(v) for v in kv['petg_wall'].split(',')] if kv.get('petg_wall') else ctop
        tc = nt.nodes.new('ShaderNodeTexCoord')
        rgb = nt.nodes.new('ShaderNodeRGB')
        rgb.outputs[0].default_value = tuple(ctop) + (1,)
        src = rgb.outputs[0]
        if kv.get('petg_grain'):
            gr = [float(v) for v in kv['petg_grain'].split(',')]
            noise = nt.nodes.new('ShaderNodeTexNoise')
            noise.inputs['Scale'].default_value = (gr[1] if len(gr) > 1 else 2200.0) * 0.001     # the case's own frame is in millimetres (stl_import scales the object)
            noise.inputs['Detail'].default_value = 2.0
            nt.links.new(tc.outputs['Object'], noise.inputs['Vector'])
            mg = nt.nodes.new('ShaderNodeMapRange')
            mg.clamp = True
            for k_, v_ in (('From Min', 0.0), ('From Max', 1.0), ('To Min', 1.0 - min(0.95, gr[0])), ('To Max', 1.0 + min(0.95, gr[0]))):
                mg.inputs[k_].default_value = v_
            nt.links.new(noise.outputs[0], mg.inputs[0])
            vm = nt.nodes.new('ShaderNodeVectorMath')
            vm.operation = 'SCALE'
            nt.links.new(rgb.outputs[0], vm.inputs[0])
            nt.links.new(mg.outputs[0], vm.inputs['Scale'])
            src = vm.outputs[0]
        sep = nt.nodes.new('ShaderNodeSeparateXYZ')
        nt.links.new(tc.outputs['Normal'], sep.inputs[0])
        ab = nt.nodes.new('ShaderNodeMath')
        ab.operation = 'ABSOLUTE'
        nt.links.new(sep.outputs[2], ab.inputs[0])
        mw = nt.nodes.new('ShaderNodeMapRange')         # 1 on a wall (its normal lies flat), 0 on the top and underneath
        mw.interpolation_type = 'SMOOTHSTEP'
        for k_, v_ in (('From Min', 0.4), ('From Max', 0.6), ('To Min', 1.0), ('To Max', 0.0)):
            mw.inputs[k_].default_value = v_
        nt.links.new(ab.outputs[0], mw.inputs[0])
        fac = mw.outputs[0]
        if np.linalg.norm(LIGHT[:2]) > 1e-6:            # ... and turned to the sun (the case's frame lies as the solver's does)
            dot = nt.nodes.new('ShaderNodeVectorMath')
            dot.operation = 'DOT_PRODUCT'
            nt.links.new(tc.outputs['Normal'], dot.inputs[0])
            dot.inputs[1].default_value = tuple(-LIGHT[:2] / np.linalg.norm(LIGHT[:2])) + (0.0,)
            ms = nt.nodes.new('ShaderNodeMapRange')
            ms.interpolation_type = 'SMOOTHSTEP'
            for k_, v_ in (('From Min', -0.1), ('From Max', 0.2), ('To Min', 0.0), ('To Max', 1.0)):
                ms.inputs[k_].default_value = v_
            nt.links.new(dot.outputs['Value'], ms.inputs[0])
            mul = nt.nodes.new('ShaderNodeMath')
            mul.operation = 'MULTIPLY'
            nt.links.new(mw.outputs[0], mul.inputs[0])
            nt.links.new(ms.outputs[0], mul.inputs[1])
            fac = mul.outputs[0]
        mx = nt.nodes.new('ShaderNodeMix')
        mx.data_type = 'RGBA'
        sk = {s_.identifier: s_ for s_ in mx.inputs}
        nt.links.new(fac, sk['Factor_Float'])
        nt.links.new(src, sk['A_Color'])
        sk['B_Color'].default_value = tuple(cwall) + (1,)
        nt.links.new(next(s_ for s_ in mx.outputs if s_.identifier == 'Result_Color'), pb.inputs['Base Color'])
    for name in ('base', 'lid'):
        bpy.ops.wm.stl_import(filepath=os.path.join(path(kv['case']), name + '.stl'), global_scale=0.001)
        o = bpy.context.selected_objects[0]
        o.name = 'case_' + name
        o.location = scene((0.0, -M['board']['size'][1], -M['board']['thickness']))     # the enclosure's frame: its origin is the board's bottom-left corner, underneath
        o.data.materials.append(pet)
        o.data.polygons.foreach_set('use_smooth', [True] * len(o.data.polygons))
        o.data.set_sharp_from_angle(angle=math.radians(30))
        o.data.update()
        CASE.append(o)
    bpy.context.view_layer.update()
    WORN.append('petg')
    pet.pass_index = len(WORN)
    cpts = (np.array([o.matrix_world @ Vector(c) for o in CASE for c in o.bound_box]) - ORG) * 1000.0
    print('match: case: x %.1f to %.1f, y %.1f to %.1f, z %.1f to %.1f mm; the table is at %.1f'
          % (cpts[:, 0].min(), cpts[:, 0].max(), cpts[:, 1].min(), cpts[:, 1].max(), cpts[:, 2].min(), cpts[:, 2].max(), table_z(*MID[:2])), flush=True)


# ---------------------------------------------------------------- pictures in and out

def load(p, size=None):
    """a picture as floats 0..1 (rows, columns, channels), resized if asked"""
    b = oiio.ImageBuf(p)
    b.read(0, 0, True, oiio.FLOAT)
    if b.has_error:
        raise SystemExit('match: cannot read %s: %s' % (p, b.geterror()))
    sp = b.spec()
    if size and (sp.width, sp.height) != tuple(size):
        b = oiio.ImageBufAlgo.resize(b, roi=oiio.ROI(0, size[0], 0, size[1], 0, 1, 0, sp.nchannels))
    return np.asarray(b.get_pixels(oiio.FLOAT), np.float32)[..., :3]


def save(p, a, size=None):
    h, w = a.shape[:2]
    b = oiio.ImageBuf(oiio.ImageSpec(w, h, 3, oiio.FLOAT))
    b.set_pixels(oiio.ROI(0, w, 0, h), np.ascontiguousarray(np.clip(a, 0, 1), np.float32))
    if size and (w, h) != tuple(size):
        b = oiio.ImageBufAlgo.resize(b, roi=oiio.ROI(0, size[0], 0, size[1], 0, 1, 0, 3))
    tmp = os.path.join(os.path.dirname(p), 'tmp_' + os.path.basename(p))
    b.set_write_format(oiio.UINT8)
    if not b.write(tmp):
        raise SystemExit('match: cannot write %s: %s' % (p, b.geterror()))
    os.replace(tmp, p)


def layers(p):
    """the render's passes from its EXR: (colour with the table left clear, how solid, the table's shadow picture,
    each pixel's material number if the render kept it, each pixel's place in the scene if the render kept it).
    Blender writes every pass as a part of its own, so all the file's parts are read"""
    got = {}
    for i in range(oiio.ImageBuf(p).nsubimages):
        b = oiio.ImageBuf(p, i, 0)
        px = np.asarray(b.get_pixels(oiio.FLOAT), np.float32)
        for j, n in enumerate(b.spec().channelnames):
            got[n.split('.', 1)[-1]] = px[..., j]

    def get(*names):
        miss = [n for n in names if n not in got]
        if miss:
            raise SystemExit('match: %s has no %s (it has %s)' % (p, miss, sorted(got)))
        return np.stack([got[n] for n in names], -1)
    idx = next((v for n, v in got.items() if n.startswith(('IndexMA', 'Material Index'))), None)     # the pass's name before and since Blender 5
    return (get('Combined.R', 'Combined.G', 'Combined.B'), get('Combined.A')[..., 0],
            None if STUDIO else get('Shadow Catcher.R', 'Shadow Catcher.G', 'Shadow Catcher.B'), idx,
            get('Position.X', 'Position.Y', 'Position.Z') if SW else None)


def soften(a, s):
    """Gaussian blur, s pixels"""
    if s < 0.2:
        return a
    r = max(1, int(3 * s + 0.5))
    x = np.arange(-r, r + 1)
    k = np.exp(-x * x / (2.0 * s * s)).astype(np.float32)
    k /= k.sum()
    for ax in (0, 1):
        n = a.shape[ax]
        p = np.pad(a, [(r, r) if i == ax else (0, 0) for i in range(a.ndim)], mode='edge')
        a = sum(k[j] * (p[j:j + n] if ax == 0 else p[:, j:j + n]) for j in range(2 * r + 1))
    return a


def shrink(m, r=2):
    """a mask without its outer r pixels"""
    out = m.copy()
    for dy in range(-r, r + 1):
        for dx in range(-r, r + 1):
            if dx or dy:
                out &= np.roll(m, (dy, dx), (0, 1))
    return out


def swatches(F, cg, a, idx, real):
    """probe=1: every material's light in the render beside the clip's on the same pixels (medians, so a highlight
    does not count; both are pixel values with the camera's curve taken off), the largest patch first"""
    idx = np.round(idx).astype(np.int32)
    rows = []
    for i, n in enumerate(WORN):
        m = shrink((idx == i + 1) & (a > 0.98))
        if m.sum() >= 40:
            rows.append((int(m.sum()), n, np.median(cg[m], 0), np.median(real[m], 0),
                         np.percentile(cg[m].mean(1), 95), np.percentile(real[m].mean(1), 95)))
    print('PROBE frame %d: material, pixels, render, clip, clip over render, brightest 5%% render and clip, worn by' % F)
    for cnt, n, x, y, hx, hy in sorted(rows, key=lambda r: -r[0]):
        print('PROBE  %-18s %6d  %-22s %-22s %-20s %.2f %.2f  %s' % (n, cnt, np.round(x, 3), np.round(y, 3), np.round(y / np.maximum(x, 1e-3), 2), hx, hy,
                                                                    ' '.join(sorted(USE.get(n, ()))[:6])), flush=True)
    np.savez_compressed(os.path.join(OUT, 'probe_%04d.npz' % F), idx=idx.astype(np.int16), names=np.array(WORN), a=a.astype(np.float16),
                        render=cg.astype(np.float16), clip=real.astype(np.float16))


def shoulder(v, t=0.88):
    """highlights roll off as a camera's do: pixel values above t bend over and never pass 1"""
    return np.where(v <= t, v, t + (1 - t) * (1 - np.exp(-(np.maximum(v, t) - t) / (1 - t))))


def unshoulder(v, t=0.88):
    """the way back, so that a filmed pixel taken apart and put together again is the same pixel"""
    return np.where(v <= t, v, t - (1 - t) * np.log(np.maximum(1 - (np.clip(v, t, 1) - t) / (1 - t), 1e-3)))


def cube(p):
    n, rows = 0, []
    for ln in open(p):
        w = ln.split()
        if not w or w[0].startswith('#'):
            continue
        if w[0] == 'LUT_3D_SIZE':
            n = int(w[1])
        elif len(w) == 3 and w[0][0] in '-.0123456789':
            rows.append([float(v) for v in w])
    return np.array(rows, np.float32).reshape(n, n, n, 3)           # [blue, green, red]: red runs fastest in the file


def graded(t, im):
    if t is None:
        return im
    n = t.shape[0]
    x = np.clip(im, 0, 1) * (n - 1)
    i = np.minimum(x.astype(np.int32), n - 2)
    f = x - i
    r, g, b = i[..., 0], i[..., 1], i[..., 2]
    fr, fg, fb = f[..., 0:1], f[..., 1:2], f[..., 2:3]
    c00 = t[b, g, r] * (1 - fr) + t[b, g, r + 1] * fr
    c01 = t[b, g + 1, r] * (1 - fr) + t[b, g + 1, r + 1] * fr
    c10 = t[b + 1, g, r] * (1 - fr) + t[b + 1, g, r + 1] * fr
    c11 = t[b + 1, g + 1, r] * (1 - fr) + t[b + 1, g + 1, r + 1] * fr
    return (c00 * (1 - fg) + c01 * fg) * (1 - fb) + (c10 * (1 - fg) + c11 * fg) * fb


LUT = cube(path(kv['lut'])) if kv.get('lut') else None


# ---------------------------------------------------------------- the table, the sun, the room

box = M['clean_box']                                  # X0, Y0, X1, Y1 of the clean picture of the table, millimetres
cs = M['clean_scale'] / 2.0                           # the table's colour is made at half the picture's size
clean = cam_x(np.clip(load(M['clean'], (int(round((box[2] - box[0]) * cs)), int(round((box[3] - box[1]) * cs)))), 0, 1))
if M.get('shade'):                                    # shade over sun on the real wood as light, red green blue
    RHO = cam_x(np.array(M['shade']['core_bgr'][::-1]) ** (1 / GAMMA)) / cam_x(np.array(M['shade']['ring_bgr'][::-1]) ** (1 / GAMMA))
else:                                                 # an older match.json has only the ratio after the solver's power: put it on the table's middle level
    mid = unshoulder(cam_v(np.median(clean.reshape(-1, 3), 0)))
    RHO = cam_x(mid * np.array(M['shadow_bgr'][::-1]) ** (1 / GAMMA)) / cam_x(mid)
ROOM = LOOK.get('room', {})
OPEN = float(kv.get('open', ROOM.get('open', 0.88)))  # how much of the room's light the shade beside the board still gets: measured in the render (probe=1)
WIN = [float(v) for v in kv['window'].split(',')] if kv.get('window') else ROOM.get('window')
sky = np.array([float(v) for v in kv['sky'].split(',')] if kv.get('sky') else RHO * NORM / (OPEN - RHO))
albedo = np.clip(clean / (EXPO * (NORM + sky)), 0.005, 0.95).astype(np.float32)      # the clean picture shows the wood in sun and room light together
wood = np.median(albedo.reshape(-1, 3), 0)
print('match: camera gain %s; a white table in the sun shows %.3f; shade over sun on the wood, as light %s; wood colour %s'
      % (np.round(EXPO, 3), NORM, np.round(RHO, 4), np.round(wood, 3)), flush=True)
if LEVEL0 and LV:
    print('match: the clip\'s light against the look\'s frame (level %.3f): %s' % (LEVEL0, ', '.join(
        'frame %d %.2f' % (F, level(K0 + F)) for F in sorted({1, NF // 4, NF // 2, 3 * NF // 4, NF}))), flush=True)
os.makedirs(OUT, exist_ok=True)
ab = oiio.ImageBuf(oiio.ImageSpec(albedo.shape[1], albedo.shape[0], 3, oiio.HALF))
ab.set_pixels(oiio.ROI(0, albedo.shape[1], 0, albedo.shape[0]), np.ascontiguousarray(albedo))
if not ab.write(os.path.join(OUT, 'table.exr')):
    raise SystemExit('match: cannot write the table colour: %s' % ab.geterror())


def quad(name, x0, y0, x1, y1, drop=0.0):
    me = bpy.data.meshes.new(name)
    cs = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    me.from_pydata([tuple(scene((x, y, table_z(x, y, drop)))) for x, y in cs], [], [(0, 1, 2, 3)])
    uv = me.uv_layers.new(name='uv')
    for i, (u, v) in enumerate(((0, 0), (1, 0), (1, 1), (0, 1))):
        uv.data[i].uv = (u, v)
    o = bpy.data.objects.new(name, me)
    S.collection.objects.link(o)
    return o


tm = bpy.data.materials.new('table')
tm.use_nodes = True
nt = tm.node_tree
nt.nodes.clear()
n_out, n_d, n_tex = nt.nodes.new('ShaderNodeOutputMaterial'), nt.nodes.new('ShaderNodeBsdfDiffuse'), nt.nodes.new('ShaderNodeTexImage')
n_tex.image = bpy.data.images.load(os.path.join(OUT, 'table.exr'))
n_tex.image.colorspace_settings.name = 'Non-Color'  # the numbers are the wood's colour already
n_tex.extension = 'EXTEND'
nt.links.new(n_tex.outputs['Color'], n_d.inputs['Color'])
nt.links.new(n_d.outputs['BSDF'], n_out.inputs['Surface'])
table = quad('table', *box)
table.data.materials.append(tm)
table.is_shadow_catcher = not STUDIO
far = quad('table_far', box[0] - 3000, box[1] - 3000, box[2] + 3000, box[3] + 3000, drop=0.3)   # the rest of the table: seen by the parts, not by the camera
far.data.materials.append(K.mat('wood', [float(v) for v in wood], 0.6)[0])
far.visible_camera = False
if STUDIO:
    # the floor the camera sees, a hair above the table and seen by the camera alone: the sun, the room and the parts'
    # shadows fall on it as on anything, but what lights and mirrors in the board is still the wood under it
    table.visible_camera = False
    FLOOR = [float(v) for v in kv.get('floor', '0.105,0.105,0.11').split(',')]
    POOL = float(kv.get('pool', 170.0))
    floor = quad('floor', box[0] - 3000, box[1] - 3000, box[2] + 3000, box[3] + 3000, drop=-0.02)
    floor.visible_diffuse = floor.visible_glossy = floor.visible_transmission = floor.visible_shadow = False
    fm = bpy.data.materials.new('floor')
    fm.use_nodes = True
    fn = fm.node_tree
    fn.nodes.clear()
    f_out, f_d, f_geo, f_dist, f_col = (fn.nodes.new(n) for n in ('ShaderNodeOutputMaterial', 'ShaderNodeBsdfDiffuse', 'ShaderNodeNewGeometry',
                                                                  'ShaderNodeVectorMath', 'ShaderNodeVectorMath'))
    f_dist.operation, f_col.operation = 'DISTANCE', 'SCALE'
    f_dist.inputs[1].default_value = tuple(scene((MID[0], MID[1], table_z(MID[0], MID[1]))))
    fn.links.new(f_geo.outputs['Position'], f_dist.inputs[0])
    last = f_dist.outputs['Value']
    for op, v in (('DIVIDE', POOL / 1000.0), ('POWER', 2.0), ('MULTIPLY', -1.0), ('EXPONENT', None)):   # exp(-(r / pool)^2)
        f_m = fn.nodes.new('ShaderNodeMath')
        f_m.operation = op
        fn.links.new(last, f_m.inputs[0])
        if v is not None:
            f_m.inputs[1].default_value = v
        last = f_m.outputs['Value']
    f_col.inputs[0].default_value = tuple(FLOOR)
    fn.links.new(last, f_col.inputs['Scale'])
    fn.links.new(f_col.outputs['Vector'], f_d.inputs['Color'])
    fn.links.new(f_d.outputs['BSDF'], f_out.inputs['Surface'])
    floor.data.materials.append(fm)
    print('match: studio: a floor of %s under the board, fading over %.0f mm' % (np.round(FLOOR, 3), POOL), flush=True)

sd = bpy.data.lights.new('sun', 'SUN')
sd.energy, sd.angle = SUN, math.radians(float(kv.get('sun_angle', 0.53)))
so = bpy.data.objects.new('sun', sd)
S.collection.objects.link(so)
so.rotation_euler = Vector(LIGHT).to_track_quat('-Z', 'Y').to_euler()

wd = bpy.data.worlds.new('room')
S.world = wd
wd.use_nodes = True
wn = wd.node_tree
wn.nodes['Background'].inputs[0].default_value = tuple(float(v) for v in sky) + (1,)
wn.nodes['Background'].inputs[1].default_value = 1.0
if WIN and WIN[0] > 0:                                # the window: a bright patch of the room where the sun comes from, the rest dimmer
    share, el, inner, outer = WIN[0], math.radians(WIN[1]), math.radians(WIN[2]), math.radians(WIN[3])
    up = TN if TN[2] > 0 else -TN
    hz = -LIGHT - (-LIGHT @ up) * up
    hz /= np.linalg.norm(hz)
    axis = hz * math.cos(el) + up * math.sin(el)
    rng = np.random.default_rng(1)                    # the patch's share of what an even room puts on the table: its mean over
    u1, u2 = rng.random(400000), rng.random(400000)   # directions drawn as a matt table takes light (more from overhead)
    e1 = np.cross(up, [1.0, 0.0, 0.0])
    e1 /= np.linalg.norm(e1)
    e2 = np.cross(up, e1)
    d = (np.sqrt(u1) * np.cos(2 * math.pi * u2))[:, None] * e1 + (np.sqrt(u1) * np.sin(2 * math.pi * u2))[:, None] * e2 + np.sqrt(1 - u1)[:, None] * up
    x = np.clip((d @ axis - math.cos(outer)) / (math.cos(inner) - math.cos(outer)), 0, 1)
    wmean = float((x * x * (3 - 2 * x)).mean())
    base, amp = 1.0 - share, share / max(wmean, 1e-4)  # so the open table gets the same room light as from an even room
    n_tc, n_dot, n_map = wn.nodes.new('ShaderNodeTexCoord'), wn.nodes.new('ShaderNodeVectorMath'), wn.nodes.new('ShaderNodeMapRange')
    n_dot.operation = 'DOT_PRODUCT'
    n_dot.inputs[1].default_value = tuple(float(v) for v in axis)
    n_map.interpolation_type = 'SMOOTHSTEP'
    for i, v in ((1, math.cos(outer)), (2, math.cos(inner)), (3, base), (4, base + amp)):
        n_map.inputs[i].default_value = v
    wn.links.new(n_tc.outputs['Generated'], n_dot.inputs[0])       # for the world this is the direction looked along
    wn.links.new(n_dot.outputs['Value'], n_map.inputs[0])
    wn.links.new(n_map.outputs[0], wn.nodes['Background'].inputs[1])
    print('match: window towards %s: %.2f of the table\'s room light; the room shows %.2f of an even room\'s brightness, the window %.2f'
          % (np.round(axis, 3), share, base, base + amp), flush=True)
print('match: sun %.2f along %s; room light %s; open %.3f' % (SUN, np.round(LIGHT, 3), np.round(sky, 4), OPEN), flush=True)

cam, cd = K.camera(50, float(kv.get('fstop', 16)))
cd.dof.use_dof = bool(kv.get('fstop'))               # the clip's own softness is added afterwards (sigma): a lens blur only when asked
cd.sensor_fit, cd.sensor_width = 'HORIZONTAL', 36.0
cd.clip_start, cd.clip_end = 0.02, 20.0
cd.shift_x = -(M['centre'][0] - (W - 1) / 2.0) / W
cd.shift_y = (M['centre'][1] - (H - 1) / 2.0) / W
blur = float(kv.get('blur', 0.5 if FALL else 0))
if blur:
    S.render.use_motion_blur = True
    S.render.motion_blur_shutter = blur


def pose(F):
    """the clip's camera for shot frame F. Set by hand, not keyed: the clip's own softness is added afterwards (sigma),
    so the camera's travel must not blur the render a second time"""
    r = FR[K0 + F]
    R, t = np.array(r['R']).reshape(3, 3), np.array(r['t'])
    Rc = R.T @ np.diag([1.0, -1.0, -1.0])               # OpenCV looks along +z with y down, Blender along -z with y up
    C = -R.T @ t / 1000.0 + ORG
    m = Matrix.Identity(4)
    for i in range(3):
        for j in range(3):
            m[i][j] = Rc[i, j]
        m[i][3] = C[i]
    cam.matrix_world = m
    cd.lens = r['f'] * 36.0 / W
    cd.dof.focus_distance = float((R @ MID + t)[2]) / 1000.0


def seen(X, F):
    """solver millimetres -> pixels of the render, for shot frame F"""
    r = FR[K0 + F]
    p = np.asarray(X, float) @ np.array(r['R']).reshape(3, 3).T + np.array(r['t'])
    u = r['f'] * p[:, 0] / p[:, 2] + M['centre'][0]
    v = r['f'] * p[:, 1] / p[:, 2] + M['centre'][1]
    return np.c_[u, v] * (RW / W)


def on_table(F, px):
    """where the lines of sight of render pixels px (n by 2) meet the table for shot frame F, solver millimetres"""
    r = FR[K0 + F]
    R, t = np.array(r['R']).reshape(3, 3), np.array(r['t'])
    uv = (np.asarray(px, float) + 0.5) * (W / RW) - 0.5
    d = np.c_[(uv[:, 0] - M['centre'][0]) / r['f'], (uv[:, 1] - M['centre'][1]) / r['f'], np.ones(len(uv))] @ R
    C = -R.T @ t
    s = (TD - C @ TN) / (d @ TN)
    if (s <= 0).any():
        raise SystemExit('match: frame %d looks over the table\'s horizon: the line of light needs the table behind every pixel' % F)
    return C + d * s[:, None]


# ---------------------------------------------------------------- the line of light

if SW:
    SWA, SWB = int(SW[0]), int(SW[1])
    turn = math.radians(SW[2]) if len(SW) > 2 else 0.0
    UPRIGHT = bool(kv.get('upright'))                               # the sheet stands upright on the table (a tall box: see case=)
    SN = np.cross(LIGHT, [math.sin(turn), math.cos(turn), 0.0])     # the sheet of light holds the sun's direction and this line on the table
    if UPRIGHT:
        SN[2] = 0.0
    SN /= SN[0]                                                     # so SN @ X is where along the board's X the sheet through X meets the board's top edge line
    SD = 1.0 if LIGHT[0] >= 0 else -1.0                             # it travels with the light, away from the sun
    L_SIG, L_HALO, L_TAIL = (float(v) for v in kv.get('line', '0.7,8,30').split(','))          # millimetres: the line itself, the glow round it, the settling behind it
    G_CORE, G_HALO, G_TAIL, G_ADD, G_BLOOM = (float(v) for v in kv.get('glow', '2.2,0.5,0.45,0.2,0.5').split(','))
    EASE, SHUT = float(kv.get('ease', 0.42)), float(kv.get('shutter', 0.5))
    corners = np.array([[0, 0], [RW - 1, 0], [RW - 1, RH - 1], [0, RH - 1]], float)
    qs = np.concatenate([SD * (on_table(F, corners) @ SN) for F in range(SWA, SWB)])
    if CASE:
        qs = np.concatenate([qs, SD * (cpts @ SN)])
    tall = max(0.0, max((o.matrix_world @ Vector(c)).z for o in parts + CASE if o.type == 'MESH' for c in o.bound_box) - ORG[2]) * 1000.0
    lean = SD * SN[2] * tall                                        # a part's top meets the sheet this much later (or sooner) than the table under it
    QA, QB = float(qs.min()) + min(0.0, lean) - 2.0, float(qs.max()) + max(0.0, lean) + 2.0
    QM = float(SD * (MID @ SN))
    c1, a_, b_ = EASE * (QB - QA), 0.0, 1.0                         # slowest at the board's middle (EASE of its mean speed), fast at the picture's edges:
    for _ in range(60):                                             # a cubic through both edges with its flat point over the board's middle
        UM = (a_ + b_) / 2
        c3 = (QB - QA) * (1 - EASE) / ((1 - UM) ** 3 + UM ** 3)
        if c1 * UM + c3 * UM ** 3 < QM - QA:
            a_ = UM
        else:
            b_ = UM

    def line_at(F):
        """where the line is at (fractional) shot frame F, and how strong: nothing before frame A - 1 or after B"""
        u = min(1.0, max(0.0, (F - (SWA - 1)) / (SWB - (SWA - 1))))
        e = min(1.0, u / 0.1) * min(1.0, (1 - u) / 0.15)
        return QM + c1 * (u - UM) + c3 * (u - UM) ** 3, e * e * (3 - 2 * e)

    HIT = (SWA - 1) + UM * (SWB - (SWA - 1))
    EVENTS['hits'].append(round(HIT, 2))
    WHITE = EXPO * (NORM + sky)                                     # what a white card in this light shows: the line's own colour
    WHITE = (WHITE / WHITE.max()).astype(np.float32)
    print('match: line of light: frames %d to %d, from %.0f to %.0f mm along the board (the board\'s middle, %.0f mm, at frame %.1f, %.1f mm a frame there)'
          % (SWA, SWB - 1, QA, QB, QM, HIT, c1 / (SWB - (SWA - 1))), flush=True)


def window(d, reach):
    """1 at the line, 0 from `reach` millimetres away on, smoothly: so the light ends, and what it has left is untouched"""
    x = np.clip(1 - np.abs(d) / reach, 0, 1)
    return x * x * (3 - 2 * x)


def sweep(F, cg, real, P):
    """the picture while the line of light is in it: the render ahead of the line, the filmed frame behind it"""
    yy, xx = np.mgrid[0:RH, 0:RW]
    T = on_table(F, np.c_[xx.ravel(), yy.ravel()]).reshape(RH, RW, 3)
    got = np.abs(P).sum(-1) > 0                                     # the render writes no place where it met nothing
    X = np.where(got[..., None], (P.astype(np.float64) - ORG) * 1000.0, T)
    if F == SWA:                                                    # the render's places and the camera's lines of sight must tell the same floor
        flat = got & (np.abs(X @ TN - TD) < 0.2)
        print('match: frame %d: the render\'s Position pass and the camera agree on the table within %.2f mm (median, %d pixels)'
              % (F, float(np.median(np.linalg.norm((X - T)[flat], axis=1))) if flat.any() else -1, int(flat.sum())), flush=True)
    q = (SD * (X @ SN)).astype(np.float32)                          # the light falls on what the pixel shows: over a part it bends as a shadow's edge does
    qt = q if UPRIGHT else (SD * (T @ SN)).astype(np.float32)       # the picture turns over by the table behind it: a part standing in front of filmed
    m, core, halo, tail = (np.zeros((RH, RW), np.float32) for _ in range(4))     # table is filmed too, never a render laid over a photograph
    sub = np.linspace(-SHUT / 2, SHUT / 2, 9)                       # while the shutter is open the line travels: it smears as anything moving does
    if kv.get('probe'):
        q0 = line_at(F)[0]
        print('PROBE frame %d: %d pixels of parts the light has not reached stand before table it has passed' % (F, int(((q > q0) & (qt <= q0) & got).sum())), flush=True)
    for s in sub:
        q0, e = line_at(F + s)
        d = q - q0
        x = np.clip(0.5 - (qt - q0) / 2.0, 0, 1)                    # filmed behind the line, render ahead, a millimetre either side to turn over
        m += x * x * (3 - 2 * x)
        core += e * np.exp(-d * d / (2 * L_SIG * L_SIG))
        halo += e * np.exp(-np.abs(d) / L_HALO) * window(d, 5 * L_HALO)
        tail += e * np.where(d < 0, np.exp(np.minimum(d, 0) / L_TAIL), 0) * window(d, 4 * L_TAIL)
    m, core, halo, tail = (v / len(sub) for v in (m, core, halo, tail))
    there = cam_x(unshoulder(real))
    base = cam_x(unshoulder(cg))
    base = base + (there - base) * m[..., None]
    gain = G_CORE * core + G_HALO * halo + G_TAIL * tail
    low = np.clip((1.5 - X[..., 2]) / 1.2, 0, 1)                    # the table and the board's face: the line is drawn on them. A part standing
    low = (low * low * (3 - 2 * low)).astype(np.float32)            # on the board is only lit by it (white laid over a black part turns it to milk)
    if UPRIGHT:
        low = np.ones_like(low)                                     # an upright sheet is drawn on all it meets
    lit = base * (1 + gain[..., None]) + (G_ADD * core * low)[..., None] * WHITE     # light on what is there, and a little of the light itself
    if G_BLOOM:                                                     # the lens: what is this bright spills a little round itself
        lit = lit + G_BLOOM * soften(np.maximum(lit - base, 0), 9.0 * RW / 1920)
    out = shoulder(cam_v(lit))
    same = (m >= 1) & (np.abs(lit - base).max(-1) < 1e-5)
    return np.where(same[..., None], real, out)


# ---------------------------------------------------------------- the fall

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


def clear_height(o, last, top=0.9, step=0.005):
    """metres above its seat at which a part, and the shadow it throws on the table, have left the picture: one step above
    the last height at which either shows in any frame from 1 to `last`. A part let go from there comes into the picture
    over its edge; one let go lower would appear in mid-air, or its shadow would. The part tumbles, so a ball round it
    stands in for it; its shadow is that ball's, drawn out along the low sun, with 12 mm more for the soft edge"""
    pts = np.array([ob.matrix_world @ Vector(c) for ob in [o] + list(o.children_recursive) if ob.type == 'MESH' for c in ob.bound_box])
    if not len(pts):
        return 0.0
    a, b = (pts.min(0) - ORG) * 1000.0, (pts.max(0) - ORG) * 1000.0
    r = float(np.linalg.norm(b - a)) / 2
    hs = np.arange(0.0, top, step)
    P = (a + b)[None] / 2 + np.outer(hs * 1000.0, [0.0, 0.0, 1.0])
    Sh = P + ((TD - P @ TN) / (LIGHT @ TN))[:, None] * LIGHT[None]
    bad = np.zeros(len(hs), bool)
    cx, cy = M['centre']
    for F in range(1, last + 1):
        fr = FR[K0 + F]
        R, t, f = np.array(fr['R']).reshape(3, 3), np.array(fr['t']), fr['f']
        # the picture is a pyramid with the lens at its point: its four sides, as planes through the lens facing inwards
        sides = np.array([[f, 0, cx], [-f, 0, W - 1 - cx], [0, f, cy], [0, -f, H - 1 - cy]], float)
        sides /= np.linalg.norm(sides, axis=1)[:, None]
        for X, rad in ((P, r), (Sh, r / max(0.2, float(M['cos_sun'])) + 12.0)):
            bad |= (((X @ R.T + t) @ sides.T) > -rad).all(1)        # the ball reaches inside all four
    k = np.flatnonzero(bad)
    return float(hs[k[-1]] + step) if len(k) else 0.0


if FALL:
    random.seed(4)
    LA, LB = (float(v) for v in kv.get('land', '15,%d' % (NF - 50)).split(','))
    POW, HMIN, OVER, REST = float(kv.get('pow', 0.85)), float(kv.get('h0', 0.04)), float(kv.get('over', 0.05)), 0.12
    SL = [float(v) for v in kv.get('slow', '7,2.2').split(',')]
    refs = sorted(REFS, key=lambda o: (o.matrix_world.translation.x - lo.x) + 0.5 * (hi.y - o.matrix_world.translation.y))
    n = len(refs)
    EVENTS['refs'] = n
    HS, AIR = [], 0
    for i, o in enumerate(refs):
        x = i / max(1, n - 1)
        G = 9.81 / (SL[0] + (SL[1] - SL[0]) * x) ** 2
        land = LA + x ** POW * (LB - LA)
        # let go just above where it, and its shadow, come into the picture (`over` more, so it comes in already moving);
        # the early ones are let go before frame 1: the shot opens on parts in the air
        H0 = max(HMIN, clear_height(o, int(math.ceil(land))) + OVER)
        T0 = math.sqrt(2 * H0 / G)
        f0 = land - T0 * 30
        HS.append(H0)
        AIR += f0 < 1
        EVENTS['lands'].append(round(land, 2))
        o.rotation_mode = 'QUATERNION'
        z0, q0 = o.location.z, o.rotation_quaternion.copy()
        tilt = Euler((random.uniform(-.5, .5), random.uniform(-.5, .5), random.uniform(-.3, .3)))
        fa = max(1, int(math.floor(f0)))
        if fa > 1:
            for ob in [o] + list(o.children_recursive):
                ob.hide_render = True
                ob.keyframe_insert('hide_render', frame=1)
                ob.hide_render = False
                ob.keyframe_insert('hide_render', frame=fa)
        for f in range(fa - 1, NF + 1):
            h = bounce(max(0.0, (f - f0) / 30), G, T0, H0, REST)
            k = min(1.0, h / 0.03)
            o.location.z = z0 + h
            o.keyframe_insert('location', index=2, frame=f)
            o.rotation_quaternion = Euler((tilt.x * k, tilt.y * k, tilt.z * k)).to_quaternion() @ q0
            o.keyframe_insert('rotation_quaternion', frame=f)
            if h == 0.0 and f > land + 12:
                break
    print('match: %d parts fall; let go from %.0f to %.0f mm up (half of them under %.0f); %d already in the air at frame 1'
          % (n, min(HS) * 1000, max(HS) * 1000, float(np.median(HS)) * 1000, AIR), flush=True)

if CASE:
    def rig(name, objs):
        e = bpy.data.objects.new(name, None)
        S.collection.objects.link(e)
        e.location = scene((MID[0], MID[1], 0.0))
        bpy.context.view_layer.update()
        for o in objs:
            o.parent = e
            o.matrix_parent_inverse = e.matrix_world.inverted()
        return e

    LA, LB = (float(v) for v in kv.get('land', '16,36').split(','))
    G = 9.81 / float(kv.get('slow', '2.5').split(',')[0]) ** 2
    HMIN, OVER = float(kv.get('h0', 0.04)), float(kv.get('over', 0.05))
    for name, objs, land, tilt in (('board_rig', [o for o in board + parts if o.parent is None], LA, (0.10, -0.06, 0.0)),
                                   ('lid_rig', CASE[1:], LB, (-0.08, 0.05, 0.0))):
        e = rig(name, objs)
        H0 = max(HMIN, clear_height(e, int(math.ceil(land))) + OVER)    # from above the picture, as the parts are
        T0 = math.sqrt(2 * H0 / G)
        f0 = land - T0 * 30
        fa = max(1, int(math.floor(f0)))
        if fa > 1:
            for ob in list(e.children_recursive):
                ob.hide_render = True
                ob.keyframe_insert('hide_render', frame=1)
                ob.hide_render = False
                ob.keyframe_insert('hide_render', frame=fa)
        e.rotation_mode = 'XYZ'
        z0 = e.location.z
        for f in range(max(0, fa - 1), NF + 1):
            h = bounce(max(0.0, (f - f0) / 30), G, T0, H0, 0.10)
            k = min(1.0, h / 0.05)
            e.location.z = z0 + h
            e.keyframe_insert('location', index=2, frame=f)
            e.rotation_euler = (tilt[0] * k, tilt[1] * k, tilt[2] * k)
            e.keyframe_insert('rotation_euler', frame=f)
            if h == 0.0 and f > land + 12:
                break
        EVENTS['hits'].append(round(land, 2))
        print('match: %s is let go %.0f mm up at frame %.1f, lands on frame %.1f at %.2f m/s' % (name, H0 * 1000, f0, land, G * T0), flush=True)
    EVENTS['hits'].sort()

# ---------------------------------------------------------------- render, then put the picture together

os.makedirs(os.path.join(OUT, 'exr'), exist_ok=True)
json.dump(EVENTS, open(os.path.join(OUT, 'events.json'), 'w'))     # the score lands its ticks on these frames


def exr(F):
    return os.path.join(OUT, 'exr', '%04d.exr' % F)


def render(F):
    S.frame_set(F)
    pose(F)
    tmp = os.path.join(OUT, 'exr', 'tmp_%04d.exr' % F)
    S.render.filepath = tmp
    bpy.ops.render.render(write_still=True)
    os.replace(tmp, exr(F))


def filmed(k):
    """the clip's frame k"""
    for e in ('png', 'jpg'):
        p = os.path.join(M['real'], '%05d.%s' % (k, e))
        if os.path.exists(p):
            return load(p, (RW, RH))
    raise SystemExit('match: no filmed frame %05d (.png or .jpg) in %s' % (k, M['real']))


def compose(F):
    k = K0 + F
    r = FR[k]
    if SW:                                                # None while the line of light is in the picture
        w = 0.0 if F < SWA else 1.0 if F >= SWB else None
    else:
        u = (F - MIX[0]) / max(1, MIX[1] - MIX[0])
        w = 0.0 if u <= 0 else 1.0 if u >= 1 else u * u * (3 - 2 * u)
    pic = cg = P = None
    if w != 1:
        fg, a0, sc0, idx, P = layers(exr(F))
        s = r.get('sigma', 0.0) * RW / W
        fg, a = soften(fg, s), soften(a0, s)[..., None]
        # all of it as light the camera takes, then the camera's curve once
        lv = level(k)                                     # the sun's own strength on this frame: on the board as it is on the table
        if STUDIO:                                        # the floor is in the render; past its edge there is nothing
            light = fg * EXPO * lv
        else:                                             # the plate is the clean table at this frame's level already
            sc = soften(np.clip(sc0, 0, 4), s)
            plate = cam_x(unshoulder(load(os.path.join(M['plates'], '%05d.png' % k), (RW, RH))))
            light = fg * EXPO * lv + plate * sc * (1 - a)
        cg = pic = shoulder(cam_v(light))
        if FIX is not None:
            cg = pic = np.clip(cg @ FIX.T, 0, 1)
        if kv.get('probe') and STUDIO and idx is not None and w is None:      # in the studio only the parts can be held against the clip,
            swatches(F, cam_x(cg), a[..., 0], idx, cam_x(filmed(k)))          # and only on a frame that has both: one the line crosses
        if kv.get('probe') and not STUDIO:
            real = cam_x(filmed(k))
            mine = cam_x(cg)
            g = np.mgrid[112:158:1.0, -100:45:1.0].reshape(2, -1).T      # the table beside the board, where the real shadows were measured
            p = np.round(seen(np.c_[g, table_z(g[:, 0], g[:, 1])], F)).astype(int)
            p = p[(p[:, 0] >= 0) & (p[:, 0] < RW) & (p[:, 1] >= 0) & (p[:, 1] < RH)]
            p = p[a0[p[:, 1], p[:, 0]] < 0.02]
            v = sc0[p[:, 1], p[:, 0]]
            dark, lit = p[v[:, 1] < 0.25], p[v[:, 1] > 0.9]
            print('PROBE frame %d: table beside the board, %d pixels in shade, %d in sun; shade over sun in the render\'s shadow picture %s, on the real wood (all frames) %s'
                  % (F, len(dark), len(lit), np.round(np.median(v[v[:, 1] < 0.25], 0), 4) if len(dark) else None, np.round(RHO, 4)), flush=True)
            if len(dark):
                got = OPEN * float(np.mean(np.median(v[v[:, 1] < 0.25], 0) / RHO))
                print('PROBE   the shade gets %.3f of the room light the open table gets; open= is %.3f%s'
                      % (got, OPEN, '' if abs(got / OPEN - 1) < 0.04 else ': run again with open=%.3f' % got), flush=True)
            for name, q in (('shade', dark), ('sun', lit)):
                if len(q):
                    x, y = np.median(mine[q[:, 1], q[:, 0]], 0), np.median(real[q[:, 1], q[:, 0]], 0)
                    print('PROBE   this frame, light in the %s: render %s clip %s clip over render %s' % (name, np.round(x, 4), np.round(y, 4), np.round(y / np.maximum(x, 1e-4), 2)), flush=True)
            print('PROBE render light before the camera: 50%% %s 99%% %s max %.2f' % (np.round(np.percentile(fg[a0 > 0.98], 50, axis=0), 3),
                                                                                    np.round(np.percentile(fg[a0 > 0.98], 99, axis=0), 3), float(fg.max())), flush=True)
            if idx is not None:
                swatches(F, mine, a[..., 0], idx, real)
    if w != 0 or kv.get('side'):
        real = filmed(k)
        if w is None:
            pic = sweep(F, cg, real, P)
        elif w > 0:
            pic = real if pic is None else pic * (1 - w) + real * w
    if kv.get('side') and cg is not None:                # the render beside the filmed frame, for the eye
        os.makedirs(os.path.join(OUT, 'side'), exist_ok=True)
        save(os.path.join(OUT, 'side', '%04d.png' % F), graded(LUT, np.clip(np.concatenate([cg, real], 1), 0, 1)))
        if P is not None:                                 # how far from the camera each pixel's place is (mm; 0 where the render met nothing):
            R, t = np.array(r['R']).reshape(3, 3), np.array(r['t'])     # the lens's softness is measured against it
            z = ((P.astype(np.float64) - ORG) * 1000.0) @ R[2] + t[2]
            np.save(os.path.join(OUT, 'side', '%04d_z.npy' % F), np.where(np.abs(P).sum(-1) > 0, z, 0).astype(np.float32))
    save(os.path.join(OUT, '%04d.png' % F), graded(LUT, np.clip(pic, 0, 1)), K.SIZES[Q])


if kv.get('stills'):
    todo = [int(v) for v in kv['stills'].split(',')]
elif kv.get('span'):
    a0, b0 = (int(v) for v in kv['span'].split(','))
    todo = list(range(a0, b0 + 1))
else:
    todo = list(range(1, NF + 1))
for F in todo:
    if os.path.exists(os.path.join(OUT, '%04d.png' % F)) and not kv.get('comp') and not kv.get('stills'):
        continue
    if F <= LAST and not os.path.exists(exr(F)):
        render(F)
    compose(F)
    print('match: frame %d' % F, flush=True)
print('match: done', flush=True)
