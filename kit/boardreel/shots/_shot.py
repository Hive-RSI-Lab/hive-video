"""What every board-reel Blender shot shares: key=value arguments, the render settings for a quality, the pale
ground and soft studio light, and a resumable render. Runs inside Blender only.

    blender -b -P shots/paper.py -- OUTDIR key=value ... quality=preview|final [stills=1,40]
"""
import math
import os
import sys

import bpy
from mathutils import Vector

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from common import ease, move, match_size, match_soft  # noqa: E402,F401  plain maths the shots share with checks.py and
#                                                         selfcheck.py, which cannot run Blender: a shot reads them as K.name

SIZES = {'preview': (1280, 720), 'final': (2560, 1440)}
SAMPLES = {'preview': 40, 'final': 64}


def args():
    """(positional, {key: value}) from the words after `--`"""
    a = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
    pos = [w for w in a if '=' not in w]
    kv = dict(w.split('=', 1) for w in a if '=' in w)
    return pos, kv


def setup(kv, frames, samples=None):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    S = bpy.context.scene
    q = kv.get('quality', 'preview')
    S.render.engine = 'CYCLES'
    S.cycles.device = 'CPU'
    if kv.get('device', os.environ.get('REEL_DEVICE', 'gpu')) in ('gpu', 'optix', 'cuda'):   # GPU first (OptiX, then CUDA), the CPU when the build sees no card; device=cpu to force it
        pr = bpy.context.preferences.addons['cycles'].preferences
        for kind in ('OPTIX', 'CUDA'):
            try:
                pr.compute_device_type = kind
                pr.get_devices()
                if any(d.type == kind for d in pr.devices):
                    for d in pr.devices:
                        d.use = d.type == kind
                    S.cycles.device = 'GPU'
                    print('shot: rendering on', kind, flush=True)
                    break
            except TypeError:
                continue
    S.cycles.samples = int(kv.get('spp', samples or SAMPLES[q]))
    S.cycles.use_denoising = True
    S.render.use_persistent_data = kv.get('persist', os.environ.get('REEL_PERSIST', '0')) == '1'   # off: a kept scene copy cost ~1.5 GB of RAM a frame-run, and memguard kills the biggest job in a stall
    S.render.resolution_x, S.render.resolution_y = SIZES[q]
    S.render.resolution_percentage = 100
    S.view_settings.view_transform = 'AgX'
    S.view_settings.look = 'AgX - Medium High Contrast'
    S.render.image_settings.file_format = 'PNG'
    S.frame_start, S.frame_end, S.render.fps = 1, frames, 30
    return S


def mat(name, col, rough, metal=0.0):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    b = bsdf(m)
    b.inputs['Base Color'].default_value = tuple(col)[:3] + (1,)
    b.inputs['Roughness'].default_value = rough
    b.inputs['Metallic'].default_value = metal
    return m, b


def bsdf(m):
    return next((n for n in m.node_tree.nodes if n.type == 'BSDF_PRINCIPLED'), None) if m and m.use_nodes else None


def heights(refs, top, path, quiet=False):
    """Every footprint's model at its real height above the board. path is prep's part_heights.json, {reference:
    mm}; refs are the footprints' empties, top the board's top face (scene metres). A library model is often the
    next size of the same package (a 10 x 7.7 mm can for a 10 x 13 mm capacitor), and beside the filmed part that
    shows. A model more than half a millimetre and 8 % out is corrected, and not by scaling it: what lies above its
    longest straight run moves up or down as it is, so a can gets a longer wall and keeps its base and its rim. A
    model with no straight run to speak of is stretched from the board up. Parts on the underside are left alone.
    Returns {reference: (was, now)} in mm."""
    import json
    import numpy as np
    if not path or not os.path.exists(path):
        return {}
    want, out = json.load(open(path)), {}
    for ref in refs:
        name = ref.name.split('.')[0]
        obs = [o for o in ref.children_recursive if o.type == 'MESH' and len(o.data.vertices)]
        if name not in want or not obs or abs(ref.matrix_world.translation.z - top) > 2e-4:
            continue
        cos, zs = [], []
        for o in obs:
            co = np.zeros(len(o.data.vertices) * 3, np.float64)
            o.data.vertices.foreach_get('co', co)
            mw = np.array(o.matrix_world)
            cos.append(co.reshape(-1, 3))
            zs.append((cos[-1] @ mw[2, :3] + mw[2, 3] - top) * 1000.0)
        was, now = max(z.max() for z in zs), float(want[name])
        d = now - was
        if was <= 0.05 or abs(d) <= max(0.5, 0.08 * now):
            continue
        lv = np.unique(np.round(np.concatenate([z[z > 0.05] for z in zs]), 3))
        gap = np.diff(lv)
        i = int(gap.argmax()) if len(gap) else -1
        run = i >= 0 and gap[i] >= 0.3 * was and gap[i] + d >= 0.2      # a straight run, and one that is still there after
        for o, co, z in zip(obs, cos, zs):
            if o.data.users > 1:                                        # another footprint wears the same model
                o.data = o.data.copy()
            if run:
                move = np.where(z > lv[i] + 1e-3, d, 0.0)
            else:
                move = np.maximum(z, 0.0) * (now / was - 1.0)
            up = np.linalg.inv(np.array(o.matrix_world)[:3, :3])[:, 2]  # the scene's up in the model's own frame
            co += (move / 1000.0)[:, None] * up[None, :]
            o.data.vertices.foreach_set('co', co.ravel())
            o.data.update()
        out[name] = (round(float(was), 2), now)
        if not quiet:
            print('shot: %s is %.1f mm in its model and %.1f mm in life: %s' % (
                name, was, now, 'its %.1f mm straight run made %.1f' % (gap[i], gap[i] + d) if run else 'stretched'), flush=True)
    if out:
        bpy.context.view_layer.update()
    return out


def ground(z=-0.0004, size=6, at=(0, 0)):
    """the pale grey table every shot stands on"""
    bpy.ops.mesh.primitive_plane_add(size=size, location=(at[0], at[1], z))
    o = bpy.context.object
    o.data.materials.append(mat('ground', (0.62, 0.62, 0.61), 0.5)[0])
    return o


def area(loc, size, power, tgt, color=(1, 1, 1)):
    d = bpy.data.lights.new('l', 'AREA')
    d.shape = 'RECTANGLE'
    d.size, d.size_y = size
    d.energy = power
    d.color = color
    o = bpy.data.objects.new('l', d)
    bpy.context.scene.collection.objects.link(o)
    o.location = loc
    o.rotation_euler = (Vector(tgt) - Vector(loc)).to_track_quat('-Z', 'Y').to_euler()
    return o


def world(level=0.15):
    w = bpy.data.worlds.new('w')
    bpy.context.scene.world = w
    w.use_nodes = True
    w.node_tree.nodes['Background'].inputs[0].default_value = (0.92, 0.92, 0.92, 1)
    w.node_tree.nodes['Background'].inputs[1].default_value = level


def camera(lens=50, fstop=8):
    cd = bpy.data.cameras.new('cam')
    cam = bpy.data.objects.new('cam', cd)
    bpy.context.scene.collection.objects.link(cam)
    bpy.context.scene.camera = cam
    cd.lens = lens
    cd.clip_start = 0.01
    cd.dof.use_dof = True
    cd.dof.aperture_fstop = fstop
    return cam, cd


def sph(az, el, dist):
    az, el = math.radians(az), math.radians(el)
    return Vector((math.cos(el) * math.sin(az), -math.cos(el) * math.cos(az), math.sin(el))) * dist


def aim(cam, tgt):
    cam.rotation_euler = (Vector(tgt) - cam.location).to_track_quat('-Z', 'Y').to_euler()
    cam.data.dof.focus_distance = (Vector(tgt) - cam.location).length


def render(out, kv):
    """every frame, or span=a,b of them (a re-run fills in only the frames a killed run left), or just stills=a,b"""
    S = bpy.context.scene
    stills = [int(v) for v in kv['stills'].split(',')] if kv.get('stills') else []
    os.makedirs(out, exist_ok=True)
    if stills:
        for f in stills:
            S.frame_set(f)
            S.render.filepath = os.path.join(out, '%04d.png' % f)
            bpy.ops.render.render(write_still=True)
        return
    if kv.get('span'):   # only the frames the cut uses: a shot trimmed to its middle need not pay for its ends
        S.frame_start, S.frame_end = (int(v) for v in kv['span'].split(','))
    S.render.filepath = out.rstrip('/') + '/'
    S.render.use_overwrite = False
    bpy.ops.render.render(animation=True)
