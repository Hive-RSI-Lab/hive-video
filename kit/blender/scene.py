"""scene.py — the bpy half of the demo-video Blender helpers: a shot script builds its scene from these and nothing else.

A shot is a Python script run by `blender -b --factory-startup --python SHOT.py`; no .blend is ever saved or shipped.
It builds the scene and sets the frame range and output, and stops there: whoever runs it renders (`video blender`,
which runs shot_main below with --render on the CPU). Text a viewer must read is never rendered
here; track() writes where each labelled thing lands on screen, frame by frame, so the compositor can set it.

    reset(res, fps, frames)             an empty scene: no default cube, light or camera
    render_settings(quality, ...)       Cycles; preview (box CPU) or final (GPU) samples, motion blur, PNG RGBA out
    studio_rig(target, size)            soft key, fill and rim area lights and a dim world, aimed at target
    backdrop(color, size)               a seamless curved sweep behind and under the subject
    camera(lens, fstop, focus)          a camera with depth of field on a focus object
    bake(obj, fn, f0, f1)               keys obj on every frame from fn(frame) -> {'location': ..., ...}, linear
    board_from_images(top, bottom, size_mm, holes, ...)
                                        a PCB slab: the top and bottom renders as its faces, real drilled holes
    board_parts(parts, board)           its components as 3D bodies, from kicad.py's parts.json (KiCad's VRML models)
                                        (both take finish='gloss', the default, or 'satin': see FINISH)
    mount(pitch, ...)                   an aluminium plate with four standoffs on a pitch x pitch square
    gds_extrude(doc, stack, colors)     one mesh per GDS layer, every polygon a prism, from gds2json's JSON
    ui_plane(image, rect, cam, res)     an unlit plane showing a UI frame (or a numbered sequence), placed so it
                                        covers exactly the pixel rect it had in the 2D film
    node_graph(trees, blocks)           the agent map: trees of nodes on edges, named surface blocks, message arcs
    track(cam, points, f0, f1)          {frame: {name: [x, y, visible]}} in output pixels, y down
    shot_main(build)                    the shot script's entry: build(), then --track FILE and --render DIR if given

Units: one Blender unit is whatever the shot says; boards are built in millimetres x scale (default 0.01, 1 m = 100 mm).
"""
import json
import math
import os
import sys

import bpy
import mathutils

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kit  # noqa: E402

QUALITY = {  # samples, resolution percentage
    'preview': (16, 50),
    'final': (256, 100),
}

# How a board and its parts take the light. 'gloss' is a lacquered look: a clear coat on the mask, shiny plastic.
# 'satin' is a PCB as a studio photographs it: a satin mask with no coat, matte epoxy and ceramic, and only metal
# (pads, pins, shields, plated holes) metallic, so a highlight spreads soft instead of sitting on the board as glare.
# The pads are found in the board image by colour (kicad.py draws them gold: red well above blue, which mask, copper
# and silkscreen never are). spec is the dielectric's Specular IOR Level (Blender's default 0.5).
FINISH = {
    'gloss': dict(mask_rough=0.32, coat=0.25, coat_rough=0.08, pads=False, spec=0.5,
                  plating_rough=0.25, metal_rough=0.28, light_rough=0.42, dark_rough=0.55, part_coat=0.15),
    'satin': dict(mask_rough=0.55, coat=0.0, coat_rough=0.3, pads=True, pad_rough=0.38, spec=0.35,
                  plating_rough=0.4, metal_rough=0.4, light_rough=0.58, dark_rough=0.68, part_coat=0.0),
}


def _finish(finish):
    if finish not in FINISH:
        raise ValueError('finish is %s, not %r' % (' or '.join(FINISH), finish))
    return FINISH[finish]


def _pads_metal(m, f):
    """the pads in m's board image turn metal: metallic where red stands well above blue, its own roughness there"""
    nt = m.node_tree
    p = nt.nodes['Principled BSDF']
    t = next(n for n in nt.nodes if n.type == 'TEX_IMAGE')
    sep = nt.nodes.new('ShaderNodeSeparateColor')
    nt.links.new(t.outputs['Color'], sep.inputs['Color'])
    d = nt.nodes.new('ShaderNodeMath')
    d.operation = 'SUBTRACT'
    nt.links.new(sep.outputs['Red'], d.inputs[0])
    nt.links.new(sep.outputs['Blue'], d.inputs[1])
    r = nt.nodes.new('ShaderNodeMapRange')               # linear red - blue: pads 0.56, silkscreen 0.06, mask about 0
    r.clamp = True
    r.inputs['From Min'].default_value, r.inputs['From Max'].default_value = 0.15, 0.40
    nt.links.new(d.outputs['Value'], r.inputs['Value'])
    nt.links.new(r.outputs['Result'], p.inputs['Metallic'])
    rr = nt.nodes.new('ShaderNodeMapRange')
    rr.clamp = True
    rr.inputs['To Min'].default_value, rr.inputs['To Max'].default_value = f['mask_rough'], f['pad_rough']
    nt.links.new(r.outputs['Result'], rr.inputs['Value'])
    nt.links.new(rr.outputs['Result'], p.inputs['Roughness'])


def reset(res=(1920, 1080), fps=30, frames=(1, 90)):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    s = bpy.context.scene
    s.render.resolution_x, s.render.resolution_y = res
    s.render.fps = fps
    s.frame_start, s.frame_end = frames
    s.frame_set(frames[0])
    bpy.context.preferences.edit.keyframe_new_interpolation_type = 'LINEAR'
    return s


def render_settings(quality='preview', transparent=True, motion_blur=True, shutter=0.5, view='AgX', out=None):
    """view: 'AgX' for objects lit by the rig; 'Standard' when a UI plane must keep its exact colours."""
    if quality not in QUALITY:
        raise ValueError('render_settings: quality is preview or final, not %r' % quality)
    s = bpy.context.scene
    samples, pct = QUALITY[quality]
    s.render.engine = 'CYCLES'
    s.cycles.samples = samples
    s.cycles.use_adaptive_sampling = True
    # Ubuntu's Blender is built without a denoiser (the enum is empty); the laptop's official build has OIDN
    have = [i.identifier for i in s.cycles.bl_rna.properties['denoiser'].enum_items]
    s.cycles.use_denoising = 'OPENIMAGEDENOISE' in have
    if s.cycles.use_denoising:
        s.cycles.denoiser = 'OPENIMAGEDENOISE'
    s.cycles.max_bounces = 8
    s.cycles.sample_clamp_indirect = 4.0   # glossy metal at low samples throws fireflies
    s.cycles.blur_glossy = 1.0
    s.render.resolution_percentage = pct
    s.render.film_transparent = transparent
    s.render.use_motion_blur = motion_blur
    s.render.motion_blur_shutter = shutter
    s.view_settings.view_transform = view
    s.view_settings.look = 'None'
    s.render.image_settings.file_format = 'PNG'
    s.render.image_settings.color_mode = 'RGBA'
    s.render.image_settings.color_depth = '8'
    s['quality'] = quality
    if out:
        s.render.filepath = os.path.join(out, '####')
    return s


def _mat(name, color=(0.8, 0.8, 0.8, 1), metallic=0.0, rough=0.5, coat=0.0, emit=None, strength=0.0):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    p = m.node_tree.nodes['Principled BSDF']
    p.inputs['Base Color'].default_value = color
    p.inputs['Metallic'].default_value = metallic
    p.inputs['Roughness'].default_value = rough
    p.inputs['Coat Weight'].default_value = coat
    if emit:
        p.inputs['Emission Color'].default_value = emit
        p.inputs['Emission Strength'].default_value = strength
    return m


def _aim(obj, target):
    d = mathutils.Vector(target) - obj.location
    obj.rotation_euler = d.to_track_quat('-Z', 'Y').to_euler()


def _area(name, loc, target, size, energy, color=(1, 1, 1)):
    ld = bpy.data.lights.new(name, 'AREA')
    ld.shape = 'RECTANGLE'
    ld.size, ld.size_y = size
    ld.energy = energy
    ld.color = color
    o = bpy.data.objects.new(name, ld)
    bpy.context.collection.objects.link(o)
    o.location = loc
    _aim(o, target)
    return o


def studio_rig(target=(0, 0, 0), size=1.0, key=600.0, world=0.03):
    """Three soft area lights scaled to a subject about `size` across, and a near-black world for soft fill."""
    t = mathutils.Vector(target)
    k = size
    lights = [
        _area('key', t + mathutils.Vector((-2.2, -2.0, 3.0)) * k, t, (2.5 * k, 1.6 * k), key * k * k, (1.0, 0.97, 0.93)),
        _area('fill', t + mathutils.Vector((2.6, -1.4, 1.2)) * k, t, (2.0 * k, 2.0 * k), key * 0.25 * k * k, (0.9, 0.95, 1.0)),
        _area('rim', t + mathutils.Vector((0.8, 2.6, 1.8)) * k, t, (3.0 * k, 0.4 * k), key * 0.9 * k * k, (0.85, 0.92, 1.0)),
    ]
    w = bpy.data.worlds.new('world')
    w.use_nodes = True
    w.node_tree.nodes['Background'].inputs['Color'].default_value = (world, world, world * 1.1, 1)
    bpy.context.scene.world = w
    return lights


def backdrop(color=(0.0045, 0.0055, 0.0075, 1), size=6.0, rough=0.35):
    """A sweep: a floor that curves up into a back wall, so the horizon never shows. Default is the film's #0B0D10."""
    bpy.ops.mesh.primitive_plane_add(size=1)
    o = bpy.context.object
    o.name = 'backdrop'
    me = o.data
    import bmesh
    bm = bmesh.new()
    n, r = 16, size * 0.25
    prof = [(-size, 0.0)] + [(r * math.sin(a), r - r * math.cos(a)) for a in [i / n * math.pi / 2 for i in range(n + 1)]]
    prof = [(y, z) for y, z in prof] + [(r, size)]
    rows = []
    for x in (-size, size):
        rows.append([bm.verts.new((x, y + size * 0.5, z)) for y, z in prof])
    for i in range(len(prof) - 1):
        bm.faces.new((rows[0][i], rows[1][i], rows[1][i + 1], rows[0][i + 1]))
    bm.to_mesh(me)
    bm.free()
    for p in me.polygons:
        p.use_smooth = True
    me.materials.append(_mat('backdrop', color, rough=rough))
    return o


def camera(lens=50.0, fstop=2.8, focus=None, name='cam'):
    cd = bpy.data.cameras.new(name)
    cd.lens = lens
    cd.sensor_width = 36.0
    cd.sensor_fit = 'HORIZONTAL'
    cd.clip_start, cd.clip_end = 0.01, 500
    if focus is not None:
        cd.dof.use_dof = True
        cd.dof.aperture_fstop = fstop
        cd.dof.focus_object = focus
    o = bpy.data.objects.new(name, cd)
    bpy.context.collection.objects.link(o)
    bpy.context.scene.camera = o
    return o


def empty(name, loc=(0, 0, 0)):
    o = bpy.data.objects.new(name, None)
    bpy.context.collection.objects.link(o)
    o.location = loc
    return o


def bake(obj, fn, f0, f1):
    """fn(frame) -> {'location': (x,y,z), 'rotation_euler': (..), 'scale': (..), 'color': (r,g,b,a), 'aim': target,
    'data.lens': v, ...}. Keys every frame, so motion blur and a preview match the curve exactly."""
    for f in range(f0, f1 + 1):
        for path, v in fn(f).items():
            if path == 'aim':
                _aim(obj, v)
                obj.keyframe_insert('rotation_euler', frame=f)
            elif path.startswith('data.'):
                head, _, last = path[5:].rpartition('.')
                setattr(obj.data.path_resolve(head) if head else obj.data, last, v)
                obj.data.keyframe_insert(path[5:], frame=f)
            else:
                setattr(obj, path, v)
                obj.keyframe_insert(path, frame=f)


def _apply(obj, mod):
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.modifier_apply(modifier=mod.name)


def _image_bbox(img, thresh=0.04):
    import numpy as np
    w, h = img.size
    px = np.empty(w * h * 4, dtype=np.float32)
    img.pixels.foreach_get(px)
    px = px.reshape(h, w, 4)
    lum = px[..., :3].max(axis=2) * px[..., 3]
    ys, xs = np.nonzero(lum > thresh)
    if not len(xs):
        return 0, 0, w, h
    # Blender's pixel rows run bottom-up; return (x0, y0, x1, y1) top-down, as an image viewer counts
    return int(xs.min()), int(h - 1 - ys.max()), int(xs.max()) + 1, int(h - ys.min())


def _img_mat(name, path, alpha=True, rough=0.32, coat=0.5):
    img = bpy.data.images.load(path, check_existing=True)
    m = _mat(name, rough=rough, coat=coat)
    nt = m.node_tree
    t = nt.nodes.new('ShaderNodeTexImage')
    t.image = img
    t.interpolation = 'Cubic'
    p = nt.nodes['Principled BSDF']
    nt.links.new(t.outputs['Color'], p.inputs['Base Color'])
    if alpha:
        nt.links.new(t.outputs['Alpha'], p.inputs['Alpha'])
    return m, img


def board_from_images(top, bottom, size_mm=(78.0, 78.0), holes=(), drill=3.2, thick=1.6, scale=0.01, name='board',
                      crop=None, edge=(0.035, 0.09, 0.04, 1), finish='gloss'):
    """A PCB slab whose top and bottom faces are the board's own renders. crop is the board's (x0, y0, x1, y1) in the
    top image, found from its non-black pixels when not given; the bottom image is taken as seen from below (mirrored
    left to right). holes are (x, y) in mm from the board's top-left corner, as KiCad gives them, drilled through
    `drill` wide, or (x, y, d) each with its own drill, as kicad.py's parts.json lists them. finish is a FINISH."""
    f = _finish(finish)
    W, H = size_mm
    holes = [(h[0], h[1], h[2] if len(h) > 2 else drill) for h in holes]
    bpy.ops.mesh.primitive_cube_add(size=1)
    o = bpy.context.object
    o.name = name
    o.scale = (W * scale, H * scale, thick * scale)
    bpy.ops.object.transform_apply(scale=True)
    for i, (hx, hy, hd) in enumerate(holes):
        bpy.ops.mesh.primitive_cylinder_add(vertices=48, radius=hd / 2 * scale, depth=thick * scale * 4,
                                            location=((hx - W / 2) * scale, (H / 2 - hy) * scale, 0))
        c = bpy.context.object
        b = o.modifiers.new('hole%d' % i, 'BOOLEAN')
        b.operation, b.solver, b.object = 'DIFFERENCE', 'EXACT', c
        _apply(o, b)
        bpy.data.objects.remove(c)
    # opaque solder mask: the images' alpha stays unlinked and nothing transmits, so the far side never shows through,
    # and the finish says how much the mask shines and whether its pads are metal
    mt, img_t = _img_mat(name + '-top', top, alpha=False, rough=f['mask_rough'], coat=f['coat'])
    mb, img_b = _img_mat(name + '-bottom', bottom, alpha=False, rough=f['mask_rough'], coat=f['coat'])
    for m in (mt, mb):
        p = m.node_tree.nodes['Principled BSDF']
        p.inputs['Coat Roughness'].default_value = f['coat_rough']
        p.inputs['Specular IOR Level'].default_value = f['spec']
        p.inputs['Transmission Weight'].default_value = 0.0
        p.inputs['Subsurface Weight'].default_value = 0.0
        if f['pads']:
            _pads_metal(m, f)
    me_edge = _mat(name + '-edge', edge, rough=0.6)
    plated = _mat(name + '-plating', (0.9, 0.72, 0.45, 1), metallic=1.0, rough=f['plating_rough'])
    o.data.materials.clear()  # Blender 5.2's boolean leaves the cutter's empty slot, which would shift every index
    for m in (mt, mb, me_edge, plated):
        o.data.materials.append(m)
    x0, y0, x1, y1 = crop or _image_bbox(img_t)
    iw, ih = img_t.size
    bx0, by0, bx1, by1 = crop or _image_bbox(img_b)
    bw, bh = img_b.size
    while o.data.uv_layers:  # the cube's own UVMap would win at render time
        o.data.uv_layers.remove(o.data.uv_layers[0])
    uv = o.data.uv_layers.new(name='uv')
    hw, hh = W * scale / 2, H * scale / 2
    for p in o.data.polygons:
        n = p.normal
        on_hole = any(math.hypot(o.data.vertices[v].co.x - (hx - W / 2) * scale, o.data.vertices[v].co.y - (H / 2 - hy) * scale)
                      < hd * scale * 0.51 for v in p.vertices for hx, hy, hd in holes)
        p.material_index = 0 if n.z > 0.5 else 1 if n.z < -0.5 else 3 if on_hole else 2
        for li in p.loop_indices:
            co = o.data.vertices[o.data.loops[li].vertex_index].co
            u, v = (co.x + hw) / (2 * hw), (co.y + hh) / (2 * hh)
            if p.material_index == 1:
                u = 1 - u
                uv.data[li].uv = ((bx0 + u * (bx1 - bx0)) / bw, 1 - (by0 + (1 - v) * (by1 - by0)) / bh)
            else:
                uv.data[li].uv = ((x0 + u * (x1 - x0)) / iw, 1 - (y0 + (1 - v) * (y1 - y0)) / ih)
    return o


def _srgb(c):
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def board_parts(parts, board, thick=1.6, scale=0.01, name='parts', finish='gloss'):
    """The board's components as real bodies: parts is kicad.py's parts.json (a dict or its path), board the slab
    board_from_images built from the same board (centred, its top face at +thick/2). One mesh per model and model
    transform, a material per VRML colour (grey with a bright highlight = metal pins), and a linked copy per part
    parented to board where its footprint puts it, turned by the footprint's angle; back-side parts hang under it.
    The model transform is KiCad's: scale, then rotate by minus the angles (x, then y, then z applied last), then
    offset in mm. finish is a FINISH. Returns the part objects."""
    f = _finish(finish)
    if isinstance(parts, str):
        with open(parts) as f:
            parts = json.load(f)
    W, H = parts['size']
    mats, data, objs = {}, {}, []

    def mat(rgba, metal):
        key = (tuple(rgba), metal)
        if key not in mats:
            c = tuple(_srgb(v) for v in rgba[:3]) + (1.0,)
            if metal:
                mats[key] = _mat('%s-metal%d' % (name, len(mats)), (0.86, 0.85, 0.82, 1), metallic=1.0, rough=f['metal_rough'])
            else:
                mats[key] = _mat('%s-mat%d' % (name, len(mats)), c, rough=f['light_rough'] if max(rgba[:3]) > 0.5 else f['dark_rough'],
                                 coat=f['part_coat'])
                mats[key].node_tree.nodes['Principled BSDF'].inputs['Specular IOR Level'].default_value = f['spec']
        return mats[key]

    for p in parts['parts']:
        key = (p['model'], tuple(p['scale']), tuple(p['rotate']), tuple(p['offset']))
        if key not in data:
            rx, ry, rz = (math.radians(-a) for a in p['rotate'])
            M = (mathutils.Matrix.Translation(p['offset']) @ mathutils.Matrix.Rotation(rz, 4, 'Z')
                 @ mathutils.Matrix.Rotation(ry, 4, 'Y') @ mathutils.Matrix.Rotation(rx, 4, 'X')
                 @ mathutils.Matrix.Diagonal(tuple(p['scale']) + (1.0,)))
            verts, faces, fm, ms = [], [], [], []
            for rgba, metal, vs, fs in parts['meshes'][p['model']]:
                m = mat(rgba, metal)
                if m not in ms:
                    ms.append(m)
                base = len(verts)
                verts += [tuple(M @ mathutils.Vector(v) * scale) for v in vs]
                faces += [[base + i for i in f] for f in fs]
                fm += [ms.index(m)] * len(fs)
            me = bpy.data.meshes.new('%s-%s-%d' % (name, p['model'], len(data)))
            me.from_pydata(verts, [], faces)
            for m in ms:
                me.materials.append(m)
            for poly, i in zip(me.polygons, fm):
                poly.material_index = i
            me.validate()
            data[key] = me
        o = bpy.data.objects.new('%s-%s' % (name, p['ref']), data[key])
        bpy.context.collection.objects.link(o)
        o.parent = board
        z = thick * scale / 2
        o.location = ((p['x'] - W / 2) * scale, (H / 2 - p['y']) * scale, z if p['side'] == 'F' else -z)
        o.rotation_euler = (0 if p['side'] == 'F' else math.pi, 0, math.radians(p['rot']))
        objs.append(o)
    return objs


def mount(pitch=60.0, plate=(100.0, 100.0, 3.0), standoff=(5.5, 6.0), drill=3.2, scale=0.01, name='mount'):
    """A bead-blasted aluminium plate with four hex standoffs on a pitch x pitch square, centred on the origin. Its top face is at
    z=0 and the standoffs rise to z=standoff[1] (mm x scale). Returns (plate, [standoffs])."""
    pw, ph, pt = plate
    bpy.ops.mesh.primitive_cube_add(size=1, location=(0, 0, -pt * scale / 2))
    p = bpy.context.object
    p.name = name
    p.scale = (pw * scale, ph * scale, pt * scale)
    bpy.ops.object.transform_apply(scale=True)
    bv = p.modifiers.new('bevel', 'BEVEL')
    bv.width, bv.segments = 0.8 * scale, 3
    p.data.materials.append(_mat('aluminium', (0.55, 0.56, 0.58, 1), metallic=0.2, rough=0.5))
    brass = _mat('brass', (0.85, 0.65, 0.32, 1), metallic=1.0, rough=0.22)
    outs = []
    h = pitch / 2
    for i, (sx, sy) in enumerate(((-h, -h), (h, -h), (-h, h), (h, h))):
        bpy.ops.mesh.primitive_cylinder_add(vertices=6, radius=standoff[0] / 2 / math.cos(math.pi / 6) * scale,
                                            depth=standoff[1] * scale, location=(sx * scale, sy * scale, standoff[1] * scale / 2))
        s = bpy.context.object
        s.name = '%s-standoff%d' % (name, i)
        s.data.materials.append(brass)
        bv = s.modifiers.new('bevel', 'BEVEL')
        bv.width, bv.segments = 0.25 * scale, 2
        outs.append(s)
    return p, outs


def gds_extrude(doc, stack, colors, scale=0.01, z_scale=1.0, name='chip'):
    """doc: gds2json's dict. stack: kit.gds_stack's [(key, z0, thick)] in microns. colors: {key: (r,g,b,a)} — alpha
    under 1 makes that layer glassy. One object per layer, parented to an empty `name` at the chip's centre."""
    x0, y0, x1, y1 = doc['bbox']
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    root = empty(name)
    out = []
    for key, z0, th in stack:
        verts, faces = [], []
        za, zb = z0 * scale * z_scale, (z0 + th) * scale * z_scale
        for flat in doc['layers'][key]:
            pts = [((flat[i] - cx) * scale, (flat[i + 1] - cy) * scale) for i in range(0, len(flat), 2)]
            n = len(pts)
            if n < 3:
                continue
            b = len(verts)
            verts += [(x, y, za) for x, y in pts] + [(x, y, zb) for x, y in pts]
            faces.append(tuple(range(b + n - 1, b - 1, -1)))
            faces.append(tuple(range(b + n, b + 2 * n)))
            faces += [(b + i, b + (i + 1) % n, b + n + (i + 1) % n, b + n + i) for i in range(n)]
        me = bpy.data.meshes.new('%s-%s' % (name, key))
        me.from_pydata(verts, [], faces)
        me.validate()
        o = bpy.data.objects.new(me.name, me)
        bpy.context.collection.objects.link(o)
        o.parent = root
        r, g, b_, a = colors.get(key, (0.7, 0.7, 0.7, 1))
        m = _mat(me.name, (r, g, b_, 1), metallic=0.85 if a >= 1 else 0.0, rough=0.28 if a >= 1 else 0.08)
        if a < 1:
            pr = m.node_tree.nodes['Principled BSDF']
            pr.inputs['Transmission Weight'].default_value = 1 - a
        me.materials.append(m)
        out.append(o)
    return root, out


def _unlit(name, img, alpha=False):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    nt.nodes.clear()
    t = nt.nodes.new('ShaderNodeTexImage')
    t.image = img
    t.interpolation = 'Linear'
    e = nt.nodes.new('ShaderNodeEmission')
    o = nt.nodes.new('ShaderNodeOutputMaterial')
    nt.links.new(t.outputs['Color'], e.inputs['Color'])
    if alpha:  # the image's own alpha cuts the shape out, e.g. a window's rounded corners
        tr = nt.nodes.new('ShaderNodeBsdfTransparent')
        mx = nt.nodes.new('ShaderNodeMixShader')
        nt.links.new(t.outputs['Alpha'], mx.inputs['Fac'])
        nt.links.new(tr.outputs['BSDF'], mx.inputs[1])
        nt.links.new(e.outputs['Emission'], mx.inputs[2])
        nt.links.new(mx.outputs['Shader'], o.inputs['Surface'])
    else:
        nt.links.new(e.outputs['Emission'], o.inputs['Surface'])
    if img.source == 'SEQUENCE':
        t.image_user.frame_duration = 100000
        t.image_user.use_auto_refresh = True
    return m


def ui_plane(image, rect, cam, res, depth=10.0, name='ui', sequence=False, start=1, crop=False, fixed=False, edge=0.0):
    """A plane showing a UI frame, sized and placed so that, from cam where cam is now, it covers exactly the pixel
    rect (x, y, w, h) it had in a res=(W, H) 2D frame. sequence: image is the first of numbered frames, played from
    scene frame `start`. The plane's origin is its left edge's middle, so it can turn on that edge like a door.
    crop: image is the whole res-shaped frame (any multiple of res, e.g. 2x for a sharp close-up) and the plane shows
    only rect of it, its alpha cutting the shape out. fixed: the plane stays where it is in the world when the camera
    moves (otherwise it rides on the camera). edge: a dark slab this thick behind it, so seen edge-on it is a line."""
    (cx, cy), (w, h) = kit.plane_for_pixels(rect, res, cam.data.lens, cam.data.sensor_width, depth)
    img = bpy.data.images.load(image, check_existing=True)
    if sequence:
        img.source = 'SEQUENCE'
    bpy.ops.mesh.primitive_plane_add(size=1)
    o = bpy.context.object
    o.name = name
    o.data.transform(mathutils.Matrix.Translation((0.5, 0, 0)))
    o.scale = (w, h, 1)
    bpy.ops.object.transform_apply(scale=True)
    o.data.materials.append(_unlit(name, img, alpha=crop))
    if sequence:
        o.data.materials[0].node_tree.nodes['Image Texture'].image_user.frame_start = start
    if crop:
        x, y, rw, rh = rect
        W, H = res
        for d in o.data.uv_layers.active.data:
            d.uv = (x / W + d.uv.x * rw / W, 1 - (y + rh) / H + d.uv.y * rh / H)
    o.parent = cam
    o.location = (cx - w / 2, cy, -depth)
    o.rotation_euler = (0, 0, 0)
    if edge:
        sl = _rbox(name + '-edge', w, h, edge, _mat(name + '-edge', (0.03, 0.033, 0.04, 1), rough=0.4), min(edge * 0.4, h * 0.02))
        sl.parent = o
        sl.location = (w / 2, 0, -edge / 2 - 1e-4)
    if fixed:
        bpy.context.view_layer.update()
        mw = o.matrix_world.copy()
        o.parent = None
        o.matrix_world = mw
    return o


def _pulse_mat(name, base=(0.05, 0.055, 0.065, 1), rough=0.45):
    """Base plus an emission whose colour and strength come from the object's own colour (Object Info), so one
    material serves every node and each node pulses on its own keys: rgb is the glow and a dark shade of it the body,
    alpha the glow's strength / 10."""
    m = _mat(name, base, rough=rough)
    nt = m.node_tree
    p = nt.nodes['Principled BSDF']
    info = nt.nodes.new('ShaderNodeObjectInfo')
    mul = nt.nodes.new('ShaderNodeMath')
    mul.operation = 'MULTIPLY'
    mul.inputs[1].default_value = 10.0
    nt.links.new(info.outputs['Color'], p.inputs['Emission Color'])
    tint = nt.nodes.new('ShaderNodeVectorMath')  # the body takes a dark shade of the glow, so colour reads unlit too
    tint.operation = 'SCALE'
    tint.inputs['Scale'].default_value = 0.3
    nt.links.new(info.outputs['Color'], tint.inputs[0])
    nt.links.new(tint.outputs['Vector'], p.inputs['Base Color'])
    nt.links.new(info.outputs['Alpha'], mul.inputs[0])
    nt.links.new(mul.outputs['Value'], p.inputs['Emission Strength'])
    return m


def _rbox(name, w, h, d, mat, bevel):
    bpy.ops.mesh.primitive_cube_add(size=1)
    o = bpy.context.object
    o.name = name
    o.scale = (w, h, d)
    bpy.ops.object.transform_apply(scale=True)
    bv = o.modifiers.new('bevel', 'BEVEL')
    bv.width, bv.segments = bevel, 3
    o.data.materials.append(mat)
    return o


def _wire(name, pts, radius, mat):
    cd = bpy.data.curves.new(name, 'CURVE')
    cd.dimensions = '3D'
    cd.bevel_depth = radius
    cd.bevel_resolution = 2
    sp = cd.splines.new('POLY')
    sp.points.add(len(pts) - 1)
    for p, co in zip(sp.points, pts):
        p.co = (co[0], co[1], co[2], 1)
    o = bpy.data.objects.new(name, cd)
    bpy.context.collection.objects.link(o)
    o.data.materials.append(mat)
    return o


def node_graph(trees, blocks=None, px=0.01, depth=0.12, name='map'):
    """trees: [{'nodes': [{x, y, w, h}, ...]}] in pixels, +y down (kit.tree_layout makes them); node 0 is the tree's
    root and every other node hangs off it by an edge. blocks: {name: (x, y, w, h)}, the surfaces outside the trees,
    standing twice as tall as a node. Built on the XY plane of an empty `name`, one pixel = px units, +y up, nodes
    standing depth tall. Returns {'root', 'nodes': [[obj per node] per tree], 'edges': [[obj per node 1..] per tree],
    'blocks': {name: obj}, 'arc': fn}. Animate any of them by keying obj.color (rgb glow, alpha = strength / 10)."""
    root = empty(name)
    nm = _pulse_mat(name + '-node')
    lm = _pulse_mat(name + '-link', base=(0.02, 0.022, 0.026, 1), rough=0.6)
    P = lambda x, y, z=0.0: (x * px, -y * px, z)  # noqa: E731
    nodes, edges = [], []
    for k, tr in enumerate(trees):
        row, er = [], []
        for j, n in enumerate(tr['nodes']):
            o = _rbox('%s-n%02d-%d' % (name, k, j), n['w'] * px, n['h'] * px, depth, nm, min(n['h'] * px * 0.18, depth * 0.3))
            o.location = P(n['x'] + n['w'] / 2, n['y'] + n['h'] / 2, depth / 2)
            o.parent = root
            o.color = (0.3, 0.32, 0.36, 0.0)
            row.append(o)
            if j:
                pl = tr['nodes'][0]
                w = _wire('%s-e%02d-%d' % (name, k, j), [P(pl['x'] + pl['w'] / 2, pl['y'] + pl['h'], depth / 2),
                                                          P(n['x'] + n['w'] / 2, n['y'], depth / 2)], px * 0.9, lm)
                w.parent = root
                w.color = (0.3, 0.32, 0.36, 0.0)
                er.append(w)
        nodes.append(row)
        edges.append(er)
    blks = {}
    for bn, (bx, by, bw, bh) in (blocks or {}).items():
        o = _rbox('%s-b-%s' % (name, bn), bw * px, bh * px, depth * 2, nm, min(bw, bh) * px * 0.08)
        o.location = P(bx + bw / 2, by + bh / 2, depth)
        o.parent = root
        o.color = (0.3, 0.32, 0.36, 0.0)
        blks[bn] = o

    def arc(key, a, b, lift=1.0, bend=0.0, width=1.4):
        """A message line from pixel point a to pixel point b, (x, y) each: a curve bowing `bend` pixels sideways in the
        drawing (the sign picks the side) and lifting out of the plane by `lift` node depths at its middle. Key its colour to
        light it, and its data's bevel_factor_start and bevel_factor_end to send a dash along it from a to b."""
        (ax, ay), (bx, by) = a, b
        L = math.hypot(bx - ax, by - ay) or 1.0
        cx, cy = (ax + bx) / 2 + (by - ay) / L * bend, (ay + by) / 2 - (bx - ax) / L * bend
        pts = []
        for i in range(33):
            t = i / 32
            x = (1 - t) ** 2 * ax + 2 * t * (1 - t) * cx + t * t * bx
            y = (1 - t) ** 2 * ay + 2 * t * (1 - t) * cy + t * t * by
            pts.append(P(x, y, depth * (1 + 6 * lift * t * (1 - t))))
        o = _wire('%s-x-%s' % (name, key), pts, px * width, lm)
        o.parent = root
        o.color = (1.0, 0.55, 0.15, 0.0)
        return o

    return {'root': root, 'nodes': nodes, 'edges': edges, 'blocks': blks, 'arc': arc}


def _hidden(eye, p, occ):
    """does the segment eye -> p pass through flat object occ (a plane: its mesh's local bounding box in x and y)?"""
    inv = occ.matrix_world.inverted()
    a, b = inv @ eye, inv @ p
    if (a.z > 0) == (b.z > 0) or a.z == b.z:
        return False
    hit = a + (b - a) * (a.z / (a.z - b.z))
    xs = [v.co.x for v in occ.data.vertices]
    ys = [v.co.y for v in occ.data.vertices]
    return min(xs) <= hit.x <= max(xs) and min(ys) <= hit.y <= max(ys)


def track(cam, points, f0, f1, occluders=()):
    """points: {name: obj or (obj, (dx, dy, dz) local offset)}. Returns {'res': [W, H], 'fps', 'frames': {f: {name:
    [x, y, visible]}}} in output pixels, y down, so a compositor can pin a label to a 3D thing. visible is 0 off
    screen, behind the camera, or behind one of `occluders` (flat objects, e.g. a window plane)."""
    from bpy_extras.object_utils import world_to_camera_view
    s = bpy.context.scene
    W = s.render.resolution_x * s.render.resolution_percentage // 100
    H = s.render.resolution_y * s.render.resolution_percentage // 100
    frames = {}
    for f in range(f0, f1 + 1):
        s.frame_set(f)
        dg = bpy.context.evaluated_depsgraph_get()
        row = {}
        for name, p in points.items():
            obj, off = (p if isinstance(p, tuple) else (p, (0, 0, 0)))
            wp = obj.evaluated_get(dg).matrix_world @ mathutils.Vector(off)
            co = world_to_camera_view(s, cam.evaluated_get(dg), wp)
            eye = cam.evaluated_get(dg).matrix_world.translation
            seen = co.z > 0 and 0 <= co.x <= 1 and 0 <= co.y <= 1 and not any(_hidden(eye, wp, o.evaluated_get(dg)) for o in occluders)
            row[name] = [round(co.x * W, 1), round((1 - co.y) * H, 1), int(seen)]
        frames[f] = row
    return {'res': [W, H], 'fps': s.render.fps, 'frames': frames}


def shot_main(build):
    """A shot's entry point. build(quality) builds the scene. After `--`: --quality preview|final (default: the
    quality file beside the shot, else final), --render DIR renders the frame range into DIR here and now,
    --frames A-B narrows it, --track FILE writes track()'s JSON for the points build() returned as
    (camera, points, meta) or (camera, points, meta, occluders), meta going in as the doc's 'meta'."""
    argv = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
    opt = dict(zip(argv[::2], argv[1::2]))
    q = opt.get('--quality')
    qf = os.path.join(os.path.dirname(os.path.abspath(sys.argv[sys.argv.index('--python') + 1])), 'quality')
    if not q and os.path.exists(qf):
        q = open(qf).read().strip()
    made = build(q or 'final')
    s = bpy.context.scene
    if '--track' in opt:
        if not made:
            sys.exit('shot_main: --track needs build() to return (camera, points, meta)')
        cam, points, meta = made[:3]
        doc = track(cam, points, s.frame_start, s.frame_end, occluders=made[3] if len(made) > 3 else ())
        doc['meta'] = meta
        with open(opt['--track'], 'w') as f:
            json.dump(doc, f, separators=(',', ':'))
    if '--frames' in opt:
        a, b = opt['--frames'].split('-')
        s.frame_start, s.frame_end = int(a), int(b)
    if '--render' in opt:
        s.render.filepath = os.path.join(opt['--render'], '####')
        bpy.ops.render.render(animation=True)
