"""kit.py — the numbers half of the demo-video Blender helpers. No bpy, so plain python3 can test it.

scene.py (the bpy half) calls these; a shot script may too. Everything here is deterministic: the same arguments
give the same frames, so a preview on the box and a final on the laptop are the same film.

    ease(t, kind)                       0..1 -> 0..1; kinds: linear in out inout snap (hard ease out, no overshoot)
    track(points, f)                    a value (number or tuple) at frame f from [(frame, value, kind), ...]
    plane_for_pixels(rect, res, lens, sensor, depth)
                                        the camera-space centre and size of a plane that covers exactly the pixel rect
                                        (x, y, w, h) of a res=(W, H) frame, at that depth in front of the camera
    hole_pitch(holes)                   the side of the square four holes sit on, and how far they are from square
    fits_mount(holes, pitch, tol)       whether four holes land on a pitch x pitch square within tol (same units)
    tree_layout(roots, ...)             nodes of a forest of small trees on a grid (the agent map), in pixels
    traffic(n, t0, t1, every, seed)     message events between trees: [(t, a, b)] with a != b
    gds_stack(layers, stack)            z and thickness for each GDS layer to extrude, in the order given
"""
import math
import random

KINDS = ('linear', 'in', 'out', 'inout', 'snap')


def ease(t, kind='inout'):
    t = max(0.0, min(1.0, float(t)))
    if kind == 'linear':
        return t
    if kind == 'in':
        return t ** 3
    if kind == 'out':
        return 1 - (1 - t) ** 3
    if kind == 'inout':
        return 4 * t ** 3 if t < 0.5 else 1 - (-2 * t + 2) ** 3 / 2
    if kind == 'snap':
        return 1 - (1 - t) ** 5
    raise ValueError('ease: unknown kind %r (have %s)' % (kind, ', '.join(KINDS)))


def _mix(a, b, k):
    if isinstance(a, (tuple, list)):
        return tuple(x + (y - x) * k for x, y in zip(a, b))
    return a + (b - a) * k


def track(points, f):
    """points: [(frame, value, kind)], frames ascending; kind is the easing INTO that point. Holds outside the range."""
    if not points:
        raise ValueError('track: no points')
    if f <= points[0][0]:
        return points[0][1]
    for (f0, v0, _), (f1, v1, kind) in zip(points, points[1:]):
        if f <= f1:
            return _mix(v0, v1, ease((f - f0) / float(f1 - f0) if f1 > f0 else 1.0, kind))
    return points[-1][1]


def plane_for_pixels(rect, res, lens=50.0, sensor=36.0, depth=10.0):
    """Horizontal sensor fit (Blender's AUTO with W >= H). Returns ((cx, cy), (w, h)) in camera space, +y up."""
    x, y, w, h = rect
    W, H = res
    vis_w = depth * sensor / lens
    vis_h = vis_w * H / W
    cx = ((x + w / 2.0) / W - 0.5) * vis_w
    cy = (0.5 - (y + h / 2.0) / H) * vis_h
    return (cx, cy), (w / W * vis_w, h / H * vis_h)


def hole_pitch(holes):
    """holes: four (x, y). Returns (mean side, worst deviation of any side or diagonal from a square of that side)."""
    if len(holes) != 4:
        raise ValueError('hole_pitch: want four holes, got %d' % len(holes))
    d = sorted(math.dist(a, b) for i, a in enumerate(holes) for b in holes[i + 1:])
    sides, diags = d[:4], d[4:]
    s = sum(sides) / 4.0
    dev = max([abs(v - s) for v in sides] + [abs(v - s * math.sqrt(2)) for v in diags])
    return s, dev


def fits_mount(holes, pitch, tol=0.2):
    s, dev = hole_pitch(holes)
    return abs(s - pitch) <= tol and dev <= tol


def tree_layout(roots, cols=6, pitch=182, x0=178, row_y=(34, 334), node=(84, 34), gap=4, seed=11, roles=None):
    """roots: [(name, n)]. Node 0 of each tree is its planner and spans two columns; the rest pair up below it.
    Returns trees [{name, row, x0, y0, cx, nodes:[{x, y, w, h, role, phase, period}]}] in pixels, +y down."""
    roles = roles or (lambda name, j, r: 'planner' if j == 0 else ('worker' if r < 0.55 else 'helper' if r < 0.8 else 'reviewer'))
    rnd = random.Random(seed)
    pw, ph = node
    cw = 2 * pw + gap
    trees = []
    for k, (name, n) in enumerate(roots):
        col, row = k % cols, k // cols
        tx, ty = x0 + col * pitch, row_y[min(row, len(row_y) - 1)]
        nodes = []
        for j in range(n):
            r = rnd.random()
            x = tx if j == 0 else tx + ((j - 1) % 2) * (pw + gap)
            y = ty + 24 if j == 0 else ty + 68 + ((j - 1) // 2) * 40
            nodes.append({'x': x, 'y': y, 'w': cw if j == 0 else pw, 'h': ph, 'role': roles(name, j, r),
                          'phase': rnd.random(), 'period': 0.7 + rnd.random() * 0.35})
        trees.append({'name': name, 'row': row, 'x0': tx, 'y0': ty, 'cx': tx + cw / 2.0, 'nodes': nodes})
    return trees


def traffic(n, t0, t1, every, seed=5):
    rnd = random.Random(seed)
    out, t = [], t0
    while t < t1:
        a = rnd.randrange(n)
        b = rnd.randrange(n - 1)
        out.append((round(t, 4), a, b + (b >= a)))
        t += every
    return out


def gds_stack(layers, stack):
    """layers: the keys a GDS dump has ('34/0', ...). stack: [(key, thickness, gap_below)]; a key the dump lacks is
    skipped and takes no height. Returns [(key, z0, thickness)] bottom first."""
    out, z = [], 0.0
    for key, thick, gap in stack:
        if key not in layers:
            continue
        z += gap
        out.append((key, z, thick))
        z += thick
    return out
