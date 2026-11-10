"""draw.py — things that draw themselves on and things that really fall, for a Blender shot. Needs bpy.

    draw_on(name, ...)                  a material that appears where frame >= the mesh's `t` attribute, glowing as it lands
    text_on(name, image, t0, t1, ...)   the same for a text plane: image R = coverage, G = (appear frame - t0) / (t1 - t0)
    prisms(segs, mat, name)             one mesh of raised strokes: segs = (ax, ay, bx, by, ta, tb, width, height, z)
    rigid_sim(objs, f0, f1, cache=...)  Bullet rigid bodies, stepped once and baked to keys on every frame
    cloth_sim(objs, f0, f1, dir=...)    Blender cloth, stepped once and written to PC2 files, played by a Mesh Cache
    boost(mats, keys)                   a flare: keyed factors on the emission of finished materials, keys = (frame, factor)
    bloom(...)                          the render's compositor: a bloom from the bright HDR parts of the frame

A sim is run once and stored (cache=FILE or dir=DIR), so a preview and the final are the same take, a frame range can be
rendered by itself, and the kit's rule that every move is baked holds for physics too.
"""
import json
import math
import os

import bpy
import mathutils
import numpy as np


def _frame_value(nt):
    v = nt.nodes.new('ShaderNodeValue')
    d = v.outputs[0].driver_add('default_value').driver
    d.type = 'SCRIPTED'
    d.expression = 'frame'
    return v


def _math(nt, op, a, b=None):
    n = nt.nodes.new('ShaderNodeMath')
    n.operation = op
    for i, x in enumerate((a, b)):
        if x is None:
            continue
        if isinstance(x, (int, float)):
            n.inputs[i].default_value = x
        else:
            nt.links.new(x, n.inputs[i])
    return n.outputs[0]


def _reveal(nt, when, shader, hot, power, tau, rest=0.0, rest_color=None):
    """shader shows from frame `when`; returns the output. A hot glow on `shader` decays with time constant tau."""
    now = _frame_value(nt)
    age = _math(nt, 'SUBTRACT', now.outputs[0], when)
    vis = _math(nt, 'GREATER_THAN', age, 0.0)
    heat = _math(nt, 'MULTIPLY', _math(nt, 'EXPONENT', _math(nt, 'MULTIPLY', age, -1.0 / tau)), vis)
    shader.inputs['Emission Color'].default_value = (*hot, 1)
    nt.links.new(_math(nt, 'ADD', _math(nt, 'MULTIPLY', heat, power), _math(nt, 'MULTIPLY', vis, rest)), shader.inputs['Emission Strength'])
    tr = nt.nodes.new('ShaderNodeBsdfTransparent')
    mix = nt.nodes.new('ShaderNodeMixShader')
    nt.links.new(vis, mix.inputs[0])
    nt.links.new(tr.outputs[0], mix.inputs[1])
    nt.links.new(shader.outputs[0], mix.inputs[2])
    return mix


def _new(name):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    nt.nodes.clear()
    out = nt.nodes.new('ShaderNodeOutputMaterial')
    return m, nt, out


def draw_on(name, color=(0.8, 0.8, 0.8), metallic=0.0, rough=0.4, hot=(1, 0.3, 0.1), power=40.0, tau=8.0, attr='t', rest=0.0):
    """rest: emission that stays once the glow has decayed, in the hot colour, so a drawn line never goes black."""
    m, nt, out = _new(name)
    a = nt.nodes.new('ShaderNodeAttribute')
    a.attribute_type = 'GEOMETRY'
    a.attribute_name = attr
    p = nt.nodes.new('ShaderNodeBsdfPrincipled')
    p.inputs['Base Color'].default_value = (*color, 1)
    p.inputs['Metallic'].default_value = metallic
    p.inputs['Roughness'].default_value = rough
    nt.links.new(_reveal(nt, a.outputs['Fac'], p, hot, power, tau, rest).outputs[0], out.inputs[0])
    return m


def text_on(name, image, t0, t1, color=(0.8, 0.82, 0.86), glow=0.6, hot=(1, 0.3, 0.1), power=12.0, tau=8.0):
    m, nt, out = _new(name)
    tx = nt.nodes.new('ShaderNodeTexImage')
    tx.image = bpy.data.images.load(image, check_existing=True)
    tx.image.colorspace_settings.name = 'Non-Color'
    tx.extension = 'CLIP'
    sep = nt.nodes.new('ShaderNodeSeparateColor')
    nt.links.new(tx.outputs[0], sep.inputs[0])
    when = _math(nt, 'ADD', _math(nt, 'MULTIPLY', sep.outputs[1], t1 - t0), t0)
    p = nt.nodes.new('ShaderNodeBsdfPrincipled')
    p.inputs['Base Color'].default_value = (*color, 1)
    p.inputs['Roughness'].default_value = 0.6
    p.inputs['Specular IOR Level'].default_value = 0.0
    show = _reveal(nt, when, p, hot, power, tau)
    # keep some light of its own, so type stays readable on a dark table
    lift = nt.nodes.new('ShaderNodeEmission')
    lift.inputs['Color'].default_value = (*color, 1)
    lift.inputs['Strength'].default_value = glow
    add = nt.nodes.new('ShaderNodeAddShader')
    nt.links.new(show.outputs[0], add.inputs[0])
    gate = _math(nt, 'GREATER_THAN', _math(nt, 'SUBTRACT', _frame_value(nt).outputs[0], when), 0.0)
    cov = _math(nt, 'MULTIPLY', sep.outputs[0], gate)
    mix0 = nt.nodes.new('ShaderNodeMixShader')
    nt.links.new(gate, mix0.inputs[0])
    nt.links.new(nt.nodes.new('ShaderNodeBsdfTransparent').outputs[0], mix0.inputs[1])
    nt.links.new(lift.outputs[0], mix0.inputs[2])
    nt.links.new(mix0.outputs[0], add.inputs[1])
    # coverage cuts the whole thing out of the plane
    cut = nt.nodes.new('ShaderNodeMixShader')
    nt.links.new(cov, cut.inputs[0])
    nt.links.new(nt.nodes.new('ShaderNodeBsdfTransparent').outputs[0], cut.inputs[1])
    nt.links.new(add.outputs[0], cut.inputs[2])
    nt.links.new(cut.outputs[0], out.inputs[0])
    return m


def boost(mats, keys):
    """multiply the emission of each material by a keyed factor, for one flare across a whole shot"""
    for m in mats:
        nt = m.node_tree
        v = nt.nodes.new('ShaderNodeValue')
        for f, k in keys:
            v.outputs[0].default_value = k
            v.outputs[0].keyframe_insert('default_value', frame=f)
        for n in list(nt.nodes):
            sock = {'BSDF_PRINCIPLED': 'Emission Strength', 'EMISSION': 'Strength'}.get(n.type)
            if not sock:
                continue
            i = n.inputs[sock]
            x = _math(nt, 'MULTIPLY', i.links[0].from_socket if i.links else i.default_value, v.outputs[0])
            nt.links.new(x, i)


def prisms(segs, mat, name='strokes'):
    """segs: an array of rows (ax, ay, bx, by, ta, tb, width, height, z). Each is a bar with a tapered top and square
    ends pushed out by half its width, so polylines close their corners. Attribute `t` runs from ta to tb along it."""
    a = np.asarray(segs, dtype=float)
    n = len(a)
    d = a[:, 2:4] - a[:, 0:2]
    ln = np.maximum(np.hypot(d[:, 0], d[:, 1]), 1e-6)
    ux, uy = d[:, 0] / ln, d[:, 1] / ln
    px, py = -uy, ux
    w, h, z = a[:, 6] / 2, a[:, 7], a[:, 8]
    A = a[:, 0:2] - np.c_[ux * w, uy * w]
    B = a[:, 2:4] + np.c_[ux * w, uy * w]
    v = np.zeros((n * 8, 3))
    for k, (P, s, top) in enumerate(((A, 1, 0), (A, -1, 0), (A, -0.7, 1), (A, 0.7, 1), (B, 1, 0), (B, -1, 0), (B, -0.7, 1), (B, 0.7, 1))):
        v[k::8, 0] = P[:, 0] + px * w * s
        v[k::8, 1] = P[:, 1] + py * w * s
        v[k::8, 2] = z + h * top
    t = np.empty(n * 8)
    t[0::8], t[1::8], t[2::8], t[3::8] = a[:, 4], a[:, 4], a[:, 4], a[:, 4]
    t[4::8], t[5::8], t[6::8], t[7::8] = a[:, 5], a[:, 5], a[:, 5], a[:, 5]
    quads = np.array([[0, 4, 7, 3], [3, 7, 6, 2], [2, 6, 5, 1], [1, 2, 3, 0], [4, 5, 6, 7]])
    base = np.arange(n)[:, None, None] * 8
    faces = (quads[None] + base).reshape(-1, 4)
    me = bpy.data.meshes.new(name)
    me.vertices.add(len(v))
    me.vertices.foreach_set('co', v.ravel())
    me.loops.add(faces.size)
    me.loops.foreach_set('vertex_index', faces.ravel())
    me.polygons.add(len(faces))
    me.polygons.foreach_set('loop_start', np.arange(0, faces.size, 4))
    me.update(calc_edges=True)
    att = me.attributes.new('t', 'FLOAT', 'POINT')
    att.data.foreach_set('value', t)
    me.materials.append(mat)
    o = bpy.data.objects.new(name, me)
    bpy.context.collection.objects.link(o)
    return o


def _key_all(objs, track):
    # keys from before the sim stay: a lift keyed by the shot hands over to the fall at the sim's first frame
    for o in objs:
        o.rotation_mode = 'QUATERNION'
        for f, (p, q) in sorted(track[o.name].items(), key=lambda kv: int(kv[0])):
            o.location, o.rotation_quaternion = p, q
            o.keyframe_insert('location', frame=int(f))
            o.keyframe_insert('rotation_quaternion', frame=int(f))


def rigid_sim(objs, f0, f1, cache=None, passive=(), gravity=-9.81, substeps=20, setup=None):
    """objs get active rigid bodies from each one's starting transform, passive are colliders. setup(obj) may set
    obj.rigid_body fields (mass, friction, restitution, collision_shape) and a starting velocity by a brief kinematic
    key. Each object's whole fall is stored in cache (JSON) and keyed; with the cache present nothing is simulated."""
    if cache and os.path.exists(cache):
        _key_all(objs, json.load(open(cache)))
        return
    s = bpy.context.scene
    s.frame_set(f0)
    if s.rigidbody_world is None:
        bpy.ops.rigidbody.world_add()
    w = s.rigidbody_world
    w.substeps_per_frame, w.solver_iterations = substeps, 40
    w.point_cache.frame_start, w.point_cache.frame_end = f0, f1
    s.gravity = (0, 0, gravity)
    if w.collection is None:
        w.collection = bpy.data.collections.new('rb')
    for o, kind in [(o, 'ACTIVE') for o in objs] + [(o, 'PASSIVE') for o in passive]:
        w.collection.objects.link(o)
        bpy.context.view_layer.objects.active = o
        o.select_set(True)
        bpy.ops.rigidbody.object_add(type=kind)
        o.select_set(False)
        if setup:
            setup(o)
    track = {o.name: {} for o in objs}
    for f in range(f0, f1 + 1):
        s.frame_set(f)
        for o in objs:
            loc, rot, _ = o.matrix_world.decompose()
            track[o.name][f] = [[round(v, 6) for v in loc], [round(v, 6) for v in rot]]
    for o in objs + list(passive):
        w.collection.objects.unlink(o)
        bpy.context.view_layer.objects.active = o
        o.select_set(True)
        bpy.ops.rigidbody.object_remove()
        o.select_set(False)
    bpy.ops.rigidbody.world_remove()
    s.frame_set(f0)
    if cache:
        os.makedirs(os.path.dirname(os.path.abspath(cache)), exist_ok=True)
        json.dump(track, open(cache, 'w'), separators=(',', ':'))
    _key_all(objs, track)


def drop(o, land, lift, tilt=(0.0, 0.0, 0.0), spin=(0.0, 0.0, 0.0), scatter=(0.0, 0.0), f0=1, tail=30, g=9.81, e=0.26):
    """Hang o above where it is now, then let it fall under gravity so it hits home exactly on frame land, bounces at
    restitution e and settles flat. A worked-out fall, no solver: a part this small jumps about in Bullet and a solver can't
    be told when to land. Keys o in its parent's space, so a part riding a moving board stays on it. lift is the height it
    falls, tilt (radians) how far it hangs off true, spin how fast that changes a frame, scatter how far off to the side
    it hangs in xy. Returns the frame it lets go."""
    loc, q = o.location.copy(), o.rotation_quaternion.copy()
    o.rotation_mode = 'QUATERNION'
    fall = 30 * math.sqrt(2 * lift / g)
    r = land - fall
    tq = lambda f: q @ mathutils.Euler(tuple(t + w * (f - f0) for t, w in zip(tilt, spin))).to_quaternion()  # noqa: E731
    z, v, hit = 0.0, g * fall / 30 * e, tq(land)
    for f in range(f0, land + tail + 1):
        if f < r:
            h, u, rot = lift * (1 - .06 * (r - f) / max(1.0, r - f0)), 0.0, tq(f)
        elif f <= land:
            h, u, rot = lift - .5 * g * ((f - r) / 30) ** 2, (f - r) / (land - r), tq(f)
        else:
            for _ in range(8):
                v -= g / 30 / 8
                z += v / 30 / 8
                if z <= 0:
                    z, v = 0.0, -v * e if abs(v) > .15 else 0.0
            h, u, rot = z, 1.0, hit.slerp(q, 1 - math.exp(-(f - land) / 3))
        k = 1 - u * u * (3 - 2 * u)
        o.location = (loc.x + scatter[0] * k, loc.y + scatter[1] * k, loc.z + max(0.0, h))
        o.rotation_quaternion = rot
        o.keyframe_insert('location', frame=f)
        o.keyframe_insert('rotation_quaternion', frame=f)
    return r


def _write_pc2(path, frames, fps_start):
    a = np.asarray(frames, dtype='<f4')
    with open(path, 'wb') as f:
        f.write(b'POINTCACHE2\0')
        np.array([1, a.shape[1]], '<i4').tofile(f)
        np.array([float(fps_start), 1.0], '<f4').tofile(f)
        np.array([a.shape[0]], '<i4').tofile(f)
        a.tofile(f)


def _play_pc2(o, path, f0):
    m = o.modifiers.new('sim', 'MESH_CACHE')
    m.cache_format, m.filepath = 'PC2', path
    m.frame_start = f0
    m.time_mode, m.play_mode = 'FRAME', 'SCENE'
    m.deform_mode = 'OVERWRITE'
    m.interpolation = 'LINEAR'
    m.forward_axis, m.up_axis = 'POS_Y', 'POS_Z'
    o.cycles.use_motion_blur = True
    o.cycles.use_deform_motion = True


def cloth_sim(objs, f0, f1, dir, setup=None, colliders=None):
    """objs (grid meshes, vertices in world space) fall as cloth; colliders(obj) -> objects that one collides with
    (each page can have a floor of its own, to lie on a pile without paying for page-on-page collisions).
    The result is one .pc2 per object in dir, played by a Mesh Cache modifier; if the files exist nothing is simulated."""
    os.makedirs(dir, exist_ok=True)
    paths = {o.name: os.path.join(dir, bpy.path.clean_name(o.name) + '.pc2') for o in objs}
    if all(os.path.exists(p) for p in paths.values()):
        for o in objs:
            _play_pc2(o, paths[o.name], f0)
        return
    s = bpy.context.scene
    mods = []
    for o in objs:
        c = o.modifiers.new('cloth', 'CLOTH')
        c.settings.quality = 8
        c.settings.mass = 0.08
        c.settings.tension_stiffness, c.settings.compression_stiffness = 40, 40
        c.settings.shear_stiffness, c.settings.bending_stiffness = 20, 4
        c.settings.air_damping = 2.0
        c.point_cache.frame_start, c.point_cache.frame_end = f0, f1
        c.collision_settings.use_collision = True
        c.collision_settings.distance_min = 0.002
        if colliders:
            col = bpy.data.collections.new('col_' + o.name)
            for k in colliders(o):
                col.objects.link(k)
            c.collision_settings.collection = col
        if setup:
            setup(o, c)
        mods.append(c)
    store = {o.name: [] for o in objs}
    for f in range(f0, f1 + 1):
        s.frame_set(f)
        dg = bpy.context.evaluated_depsgraph_get()
        for o in objs:
            me = o.evaluated_get(dg).to_mesh()
            a = np.empty(len(me.vertices) * 3)
            me.vertices.foreach_get('co', a)
            store[o.name].append(a.reshape(-1, 3).copy())
            o.evaluated_get(dg).to_mesh_clear()
    for o, c in zip(objs, mods):
        o.modifiers.remove(c)
        _write_pc2(paths[o.name], store[o.name], f0)
        _play_pc2(o, paths[o.name], f0)
    s.frame_set(f0)


def bloom(threshold=1.0, strength=0.6, size=0.55, vignette=0.0):
    """A compositor that adds a bloom from the HDR frame. For a finished frame, not a transparent plate to composite."""
    s = bpy.context.scene
    nt = bpy.data.node_groups.new('finish', 'CompositorNodeTree')
    s.compositing_node_group = nt
    s.render.use_compositing = True
    rl = nt.nodes.new('CompositorNodeRLayers')
    g = nt.nodes.new('CompositorNodeGlare')
    nt.links.new(rl.outputs['Image'], g.inputs[0])
    want = {'Type': 'Bloom', 'Glare Type': 'Bloom', 'Quality': 'High', 'Threshold': threshold, 'Highlights Threshold': threshold,
            'Strength': strength, 'Size': size}
    for i in g.inputs:
        if i.name in want and hasattr(i, 'default_value'):
            try:
                i.default_value = want[i.name]
            except (TypeError, ValueError):
                pass
    nt.interface.new_socket('Image', in_out='OUTPUT', socket_type='NodeSocketColor')
    out = nt.nodes.new('NodeGroupOutput')
    nt.links.new(g.outputs[0], out.inputs[0])
    return nt


def clear_lens(objs, f0, f1, near=.15):
    """hide any object, for just those frames, while it comes within `near` plus its own size of the camera: a falling part that crosses
    the lens fills a frame with black, and nobody misses a part for the frame it would have covered everything. Call it last, after the
    objects and the camera are animated. Returns how many frames were hidden."""
    scene = bpy.context.scene
    was, hidden = scene.frame_current, 0
    sizes = [(o, max(o.dimensions) / 2) for o in objs]
    for f in range(f0, f1 + 1):
        scene.frame_set(f)
        eye = scene.camera.matrix_world.translation
        for o, r in sizes:
            if (o.matrix_world.translation - eye).length < near + r:
                o.hide_render = True
                o.keyframe_insert('hide_render', frame=f)
                o.hide_render = False
                o.keyframe_insert('hide_render', frame=f + 1)
                hidden += 1
    scene.frame_set(was)
    return hidden
