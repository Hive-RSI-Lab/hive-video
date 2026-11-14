"""What every board-reel Blender shot shares: key=value arguments, the render settings for a quality, the pale
ground and soft studio light, and a resumable render. Runs inside Blender only.

    blender -b -P shots/paper.py -- OUTDIR key=value ... quality=preview|final [stills=1,40]
"""
import math
import os
import sys

import bpy
from mathutils import Vector

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


def ease(u, kind=None):
    """in: gathers speed; out: brakes to rest; default mostly steady, so a cut lands on a camera already moving"""
    u = min(1.0, max(0.0, u))
    v = u * u * (3 - 2 * u)
    return {'in': u ** 2.2, 'out': 1 - (1 - u) ** 3}.get(kind, 0.6 * u + 0.4 * v)


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
