#!/usr/bin/env python3
"""kicad.py — a KiCad board for Blender with no KiCad installed: its bare board drawn as two images and its parts'
3D bodies placed where the footprints put them, for scene.board_from_images and scene.board_parts.

    python3 kicad.py BOARD.kicad_pcb OUTDIR [--models DIR] [--px-per-mm 32]

writes OUTDIR/top.png (seen from above), OUTDIR/bottom.png (seen from below, so mirrored) and OUTDIR/parts.json:
{'size': [w, h] mm, 'holes': [[x, y, drill]] mm from the board's top-left corner, 'meshes': {model: [[rgba,
metal, verts, faces] per VRML shape]}, 'parts': [{'ref', 'model', 'x', 'y', 'rot', 'side', 'offset', 'rotate',
'scale'}]}. The images are mask over copper (zones, tracks, vias a shade lighter), bare pads in gold, holes and
silkscreen (lines, shapes and text). A footprint's model is found by its file name in --models (default: the
board's lib/*.3dshapes beside kicad/), .wrl first, since VRML is what this reads; a model it cannot find is
reported on stderr and left out. Board edge and holes come from Edge.Cuts and the footprints' NPTH pads; a slotted
(oval) drill is drawn as its slot, and an NPTH slot goes into 'holes' as a round hole as wide as the slot.
With --synth a footprint with no model, or whose model can't be found, gets a plain body instead: a box (a cylinder for a can) as big as
its courtyard, F.Fab outline or pads, its height and finish guessed from the footprint's name (SYNTH). Mounting holes, test points, fiducials
and solder jumpers get none. Needs Pillow for the images; the parsing is plain Python."""
import glob
import json
import math
import os
import re
import sys

MASK, COPPER, PAD, SILK, HOLE = (16, 48, 26, 255), (30, 84, 42, 255), (214, 176, 96, 255), (236, 236, 228, 255), (8, 8, 8, 255)
FONT = '/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed.ttf'
WRL_MM = 2.54                     # a KiCad VRML unit is 0.1 inch
SKIP = re.compile(r'TestPoint|Fiducial|MountingHole|SolderJumper|NetTie|Logo', re.I)
BLACK, TAN, METAL, CERAMIC = [.05, .05, .055, 1.], [.62, .5, .3, 1.], [.78, .78, .8, 1.], [.86, .84, .78, 1.]
# footprint or model name -> (height mm, colour, metal, round). First match wins.
SYNTH = [(r'USB_A', 14.0, METAL, True, False), (r'USB_C', 3.3, METAL, True, False), (r'microSD', 1.9, METAL, True, False),
         (r'M\.2|2199230', 4.2, BLACK, False, False), (r'JST|PinHeader|S2B-PH', 6.0, CERAMIC, False, False),
         (r'CP_Elec', 7.7, METAL, True, True), (r'Spacer', 2.0, METAL, True, False), (r'Module|MGM240', 2.2, METAL, True, False),
         (r'IHLP', 3.0, BLACK, False, False), (r'XEL|XFL', 2.0, BLACK, False, False), (r'SW_|Switch', 2.5, BLACK, False, False),
         (r'OSD|BGA', 1.3, BLACK, False, False), (r'Crystal|SiT', .8, METAL, True, False), (r'MMICT', 1.0, METAL, True, False),
         (r'^C_', 1.2, TAN, False, False), (r'^L_', .8, BLACK, False, False), (r'^R_', .4, BLACK, False, False),
         (r'LED', .6, CERAMIC, False, False), (r'.', .9, BLACK, False, False)]


def sexpr(text):
    """the s-expression text as nested lists of strings (quoted ones unquoted)"""
    stack, cur = [], []
    for m in re.finditer(r'\(|\)|"((?:\\.|[^"\\])*)"|[^\s()]+', text):
        t = m.group(0)
        if t == '(':
            stack.append(cur)
            cur = []
        elif t == ')':
            done, cur = cur, stack.pop()
            cur.append(done)
        else:
            cur.append(m.group(1).replace('\\"', '"') if m.group(1) is not None else t)
    return cur[0]


def kids(node, key):
    return [n for n in node if isinstance(n, list) and n and n[0] == key]


def kid(node, key):
    k = kids(node, key)
    return k[0] if k else None


def nums(node, key, default=None):
    k = kid(node, key)
    return [float(v) for v in k[1:] if not isinstance(v, list)] if k else default


def layer_of(node):
    k = kid(node, 'layer')
    return k[1] if k else None


def layers_of(node):
    k = kid(node, 'layers')
    return k[1:] if k else []


def hidden(node):
    return any(n == ['hide', 'yes'] or n == 'hide' for n in node)


def place(at, x, y):
    """footprint-local (x, y) -> board, KiCad's y-down coordinates; at = (X, Y, rot degrees, counter-clockwise)"""
    X, Y = at[0], at[1]
    r = math.radians(at[2] if len(at) > 2 else 0)
    return X + x * math.cos(r) + y * math.sin(r), Y - x * math.sin(r) + y * math.cos(r)


def arc_points(s, m, e, n=24):
    """the arc through start, mid and end as n+1 points"""
    ax, ay = s
    bx, by = m
    cx, cy = e
    d = 2 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
    if abs(d) < 1e-12:
        return [s, e]
    ux = ((ax * ax + ay * ay) * (by - cy) + (bx * bx + by * by) * (cy - ay) + (cx * cx + cy * cy) * (ay - by)) / d
    uy = ((ax * ax + ay * ay) * (cx - bx) + (bx * bx + by * by) * (ax - cx) + (cx * cx + cy * cy) * (bx - ax)) / d
    rad = math.hypot(ax - ux, ay - uy)
    a0, am, a1 = (math.atan2(p[1] - uy, p[0] - ux) for p in (s, m, e))
    sweep = (a1 - a0) % (2 * math.pi)
    if (am - a0) % (2 * math.pi) > sweep:   # the mid point says it runs the other way round
        sweep -= 2 * math.pi
    return [(ux + rad * math.cos(a0 + sweep * i / n), uy + rad * math.sin(a0 + sweep * i / n)) for i in range(n + 1)]


def outline(pcb):
    """the board's (x0, y0, x1, y1) in mm, from Edge.Cuts"""
    xs, ys = [], []
    for g in pcb:
        if isinstance(g, list) and g and g[0] in ('gr_line', 'gr_arc', 'gr_rect') and layer_of(g) == 'Edge.Cuts':
            for k in ('start', 'mid', 'end'):
                p = nums(g, k)
                if p:
                    xs.append(p[0])
                    ys.append(p[1])
    if not xs:
        raise ValueError('no Edge.Cuts outline')
    return min(xs), min(ys), max(xs), max(ys)


def parse_wrl(path):
    """a KiCad VRML file -> [[rgba, metal, verts (mm), faces]] per shape"""
    text = open(path, encoding='utf-8', errors='replace').read()
    shapes = []
    for chunk in text.split('Shape')[1:]:
        dc = re.search(r'diffuseColor\s+([-\d.eE]+)\s+([-\d.eE]+)\s+([-\d.eE]+)', chunk)
        sc = re.search(r'specularColor\s+([-\d.eE]+)\s+([-\d.eE]+)\s+([-\d.eE]+)', chunk)
        tr = re.search(r'transparency\s+([-\d.eE]+)', chunk)
        pt = re.search(r'point\s*\[([^\]]*)\]', chunk)
        ix = re.search(r'coordIndex\s*\[([^\]]*)\]', chunk)
        if not (pt and ix):
            continue
        v = [float(x) for x in re.split(r'[\s,]+', pt.group(1).strip()) if x]
        verts = [[round(v[i] * WRL_MM, 5), round(v[i + 1] * WRL_MM, 5), round(v[i + 2] * WRL_MM, 5)] for i in range(0, len(v) - 2, 3)]
        faces, f = [], []
        for x in re.split(r'[\s,]+', ix.group(1).strip()):
            if not x:
                continue
            if int(x) < 0:
                if len(f) >= 3:
                    faces.append(f)
                f = []
            else:
                f.append(int(x))
        if len(f) >= 3:
            faces.append(f)
        rgb = [float(c) for c in dc.groups()] if dc else [0.6, 0.6, 0.6]
        spec = [float(c) for c in sc.groups()] if sc else [0, 0, 0]
        # a grey with a bright highlight is a metal pin or tab; everything else is plastic, ceramic or epoxy
        metal = max(rgb) - min(rgb) < 0.08 and sum(spec) / 3 > 0.45 and sum(rgb) / 3 > 0.45
        shapes.append([rgb + [1.0 - (float(tr.group(1)) if tr else 0.0)], bool(metal), verts, faces])
    return shapes


def _font(px):
    from PIL import ImageFont
    return ImageFont.truetype(FONT, max(4, int(px)))


class Canvas:
    """one side's image; mm -> px through the board origin, mirrored left to right for the bottom"""

    def __init__(self, box, ppm, mirror):
        from PIL import Image, ImageDraw
        self.x0, self.y0, x1, y1 = box
        self.w, self.ppm, self.mirror = x1 - self.x0, ppm, mirror
        self.img = Image.new('RGBA', (round(self.w * ppm), round((y1 - self.y0) * ppm)), MASK)
        self.d = ImageDraw.Draw(self.img)

    def P(self, x, y):
        u = (x - self.x0) * self.ppm
        return (self.w * self.ppm - u if self.mirror else u, (y - self.y0) * self.ppm)

    def line(self, pts, width, col):
        q = [self.P(*p) for p in pts]
        wpx = max(1, round(width * self.ppm))
        self.d.line(q, fill=col, width=wpx)
        r = width * self.ppm / 2
        for x, y in q:
            self.d.ellipse((x - r, y - r, x + r, y + r), fill=col)

    def poly(self, pts, col):
        if len(pts) >= 3:
            self.d.polygon([self.P(*p) for p in pts], fill=col)

    def disc(self, x, y, dia, col):
        cx, cy = self.P(x, y)
        r = dia * self.ppm / 2
        self.d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=col)

    def text(self, s, x, y, size, angle, col, mirror=False):
        from PIL import Image, ImageDraw
        f = _font(size * self.ppm / 0.72)
        l, t, r, b = f.getbbox(s)
        im = Image.new('RGBA', (r - l + 4, b - t + 4), (0, 0, 0, 0))
        ImageDraw.Draw(im).text((2 - l, 2 - t), s, font=f, fill=col)
        if mirror != self.mirror:
            im = im.transpose(Image.FLIP_LEFT_RIGHT)
        im = im.rotate(-angle if self.mirror else angle, expand=True, resample=Image.BICUBIC)
        cx, cy = self.P(x, y)
        self.img.alpha_composite(im, (int(cx - im.width / 2), int(cy - im.height / 2)))


def _drill(pad):
    """a pad's drill as (w, h) in mm: KiCad writes (drill D) for a round hole and (drill oval W H) for a slot"""
    d = kid(pad, 'drill')
    if d[1] == 'oval':
        w = float(d[2])
        return w, float(d[3]) if len(d) > 3 and not isinstance(d[3], list) else w
    return float(d[1]), float(d[1])


def _pad_poly(pad, at, size=None, shape=None):
    """a pad's outline on the board, as points (rect, roundrect, trapezoid and custom drawn as their bounding rect);
    size and shape stand in for the pad's own, so its slot is drawn turned and placed the same way"""
    p = nums(pad, 'at')
    w, h = size or nums(pad, 'size', [0, 0])[:2]
    shape = shape or (pad[3] if len(pad) > 3 else 'rect')
    cx, cy = place(at, p[0], p[1])
    r = math.radians(p[2] if len(p) > 2 else 0)
    if shape in ('circle', 'oval'):
        rr = min(w, h) / 2           # an oval as a stadium: two half circles joined along the long side
        dx, dy = (w / 2 - rr, 0) if w >= h else (0, h / 2 - rr)
        a0 = -math.pi / 2 if w >= h else 0.0
        pts = []
        for s in (1, -1):
            for i in range(17):
                a = a0 + math.pi * i / 16 + (0 if s > 0 else math.pi)
                pts.append((s * dx + rr * math.cos(a), s * dy + rr * math.sin(a)))
    else:
        pts = [(-w / 2, -h / 2), (w / 2, -h / 2), (w / 2, h / 2), (-w / 2, h / 2)]
    return [(cx + x * math.cos(r) + y * math.sin(r), cy - x * math.sin(r) + y * math.cos(r)) for x, y in pts]


def _graphics(c, node, side, at=None):
    """draw node's silkscreen children (lines, rects, circles, arcs, polys) on side 'F' or 'B'"""
    T = (lambda x, y: place(at, x, y)) if at else (lambda x, y: (x, y))
    pre = 'fp_' if at else 'gr_'
    for g in node:
        if not (isinstance(g, list) and g and g[0].startswith(pre)) or layer_of(g) != side + '.SilkS':
            continue
        k = g[0][3:]
        st = kid(g, 'stroke')
        wd = nums(st, 'width', [0.12])[0] if st else 0.12
        fill = kid(g, 'fill')
        solid = fill is not None and fill[1] in ('solid', 'yes')
        if k == 'line':
            c.line([T(*nums(g, 'start')), T(*nums(g, 'end'))], wd, SILK)
        elif k == 'rect':
            (x0, y0), (x1, y1) = nums(g, 'start'), nums(g, 'end')
            pts = [T(x0, y0), T(x1, y0), T(x1, y1), T(x0, y1)]
            c.poly(pts, SILK) if solid else c.line(pts + pts[:1], wd, SILK)
        elif k == 'circle':
            (cx, cy), (ex, ey) = nums(g, 'center'), nums(g, 'end')
            rr = math.hypot(ex - cx, ey - cy)
            pts = [T(cx + rr * math.cos(a * math.pi / 24), cy + rr * math.sin(a * math.pi / 24)) for a in range(49)]
            c.poly(pts, SILK) if solid else c.line(pts, wd, SILK)
        elif k == 'arc':
            c.line([T(*p) for p in arc_points(nums(g, 'start'), nums(g, 'mid'), nums(g, 'end'))], wd, SILK)
        elif k == 'poly':
            pts = [T(*[float(v) for v in xy[1:3]]) for xy in kids(kid(g, 'pts'), 'xy')]
            c.poly(pts, SILK) if solid else c.line(pts + pts[:1], wd, SILK)


def _texts(c, node, side, at=None):
    for g in node:
        if not (isinstance(g, list) and g and g[0] in ('property', 'fp_text', 'gr_text')):
            continue
        if layer_of(g) != side + '.SilkS' or hidden(g) or hidden(kid(g, 'effects') or []):
            continue
        s = g[2] if g[0] in ('property', 'fp_text') else g[1]
        if s.startswith('${'):
            continue
        p = nums(g, 'at')
        x, y = place(at, p[0], p[1]) if at else (p[0], p[1])
        size = nums(kid(kid(g, 'effects') or [], 'font') or [], 'size', [1, 1])[1]
        c.text(s, x, y, size, p[2] if len(p) > 2 else 0, SILK, mirror=side == 'B')


def _ref(fp):
    for pr in kids(fp, 'property'):
        if pr[1] == 'Reference':
            return pr[2]
    return next((t[2] for t in kids(fp, 'fp_text') if t[1] == 'reference'), '')


def net_pads(pcb, ref, net):
    """where part ref's pads on net are, [(x, y)] in board mm"""
    out = []
    for fp in kids(pcb, 'footprint'):
        if _ref(fp) != ref:
            continue
        at = nums(fp, 'at') + [0.0]
        for pad in kids(fp, 'pad'):
            n = kid(pad, 'net')
            if n and n[-1] == net:
                out.append(tuple(place(at[:3], *nums(pad, 'at')[:2])))
    return out


def net_path(pcb, net, a, b, tol=0.02):
    """The copper a signal really runs on from part a to part b: [(x0, y0, x1, y1, width)] in board mm, in order, and True; through vias, whichever
    layer. If the net isn't routed all the way, the straight airwire and False, so a film can show the path and say which it was."""
    pa, pb = net_pads(pcb, a, net), net_pads(pcb, b, net)
    if not pa or not pb:
        raise ValueError('%s has no pad of %s on %s or %s' % (net, net, a, b))
    key = lambda p: (round(p[0] / tol), round(p[1] / tol))  # noqa: E731
    graph, width = {}, {}
    for s in kids(pcb, 'segment'):
        if kid(s, 'net')[-1] != net:
            continue
        u, v = tuple(nums(s, 'start')), tuple(nums(s, 'end'))
        graph.setdefault(key(u), []).append((key(v), v, nums(s, 'width')[0]))
        graph.setdefault(key(v), []).append((key(u), u, nums(s, 'width')[0]))
    near = lambda p: min(graph, key=lambda k: math.dist((k[0] * tol, k[1] * tol), p), default=None)  # noqa: E731
    for src in pa:
        k0 = near(src)
        if k0 is None or math.dist((k0[0] * tol, k0[1] * tol), src) > 1.0:
            continue
        prev, todo = {k0: None}, [k0]
        for k in todo:
            for n, p, w in graph[k]:
                if n not in prev:
                    prev[n] = (k, p, w)
                    todo.append(n)
        for dst in pb:
            k1 = min(prev, key=lambda k: math.dist((k[0] * tol, k[1] * tol), dst))
            if math.dist((k1[0] * tol, k1[1] * tol), dst) > 1.0:
                continue
            path, k = [], k1
            while prev[k]:
                pk, p, w = prev[k]
                path.append(((pk[0] * tol, pk[1] * tol), p, w))
                k = pk
            return [(u[0], u[1], v[0], v[1], w) for u, v, w in reversed(path)], True
    best = min(((u, v) for u in pa for v in pb), key=lambda c: math.dist(*c))
    return [(best[0][0], best[0][1], best[1][0], best[1][1], 0.2)], False


def _fp_box(fp):
    """a footprint's body outline in its own frame, (x0, y0, x1, y1) mm: its courtyard, else its Fab outline, else its pads"""
    for layer in ('F.CrtYd', 'B.CrtYd', 'F.Fab', 'B.Fab'):
        pts = []
        for k in ('fp_line', 'fp_rect'):
            for g in kids(fp, k):
                if layer_of(g) == layer:
                    pts += [nums(g, 'start'), nums(g, 'end')]
        for g in kids(fp, 'fp_poly'):
            if layer_of(g) == layer:
                pts += [[float(xy[1]), float(xy[2])] for xy in kids(kid(g, 'pts'), 'xy')]
        if pts:
            xs, ys = [p[0] for p in pts], [p[1] for p in pts]
            return min(xs), min(ys), max(xs), max(ys)
    pts = [nums(p, 'at')[:2] for p in kids(fp, 'pad')]
    if not pts:
        return None
    w = max(max(nums(p, 'size')[:2]) for p in kids(fp, 'pad')) / 2
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    return min(xs) - w, min(ys) - w, max(xs) + w, max(ys) + w


def _synth_mesh(w, d, h, rgba, metal, cyl):
    """a body w x d x h mm standing on z=0, centred, as a parse_wrl shape; cyl makes it a 24-sided can"""
    if cyl:
        n, r = 24, min(w, d) / 2
        v = [[r * math.cos(2 * math.pi * i / n), r * math.sin(2 * math.pi * i / n), z] for z in (0, h) for i in range(n)]
        f = [[(i + 1) % n, i, n + i, n + (i + 1) % n] for i in range(n)] + [list(range(n))[::-1], [n + i for i in range(n)]]
        return [[rgba, metal, [[round(c, 5) for c in p] for p in v], f]]
    x, y = w / 2, d / 2
    v = [[-x, -y, 0], [x, -y, 0], [x, y, 0], [-x, y, 0], [-x, -y, h], [x, -y, h], [x, y, h], [-x, y, h]]
    return [[rgba, metal, v, [[3, 2, 1, 0], [4, 5, 6, 7], [0, 1, 5, 4], [1, 2, 6, 5], [2, 3, 7, 6], [3, 0, 4, 7]]]]


def board(path, models=None, ppm=32, synth=False):
    """parse the board -> (images {'top', 'bottom'} or None without Pillow, parts.json's dict)"""
    pcb = sexpr(open(path, encoding='utf-8').read())
    box = outline(pcb)
    x0, y0, x1, y1 = box
    if models is None:
        models = glob.glob(os.path.join(os.path.dirname(os.path.abspath(path)), '..', 'lib', '*.3dshapes'))
    elif isinstance(models, str):
        models = [models]
    fps = kids(pcb, 'footprint')
    holes, parts, meshes = [], [], {}
    for fp in fps:
        at = nums(fp, 'at')
        at = at + [0.0] * (3 - len(at))
        side = 'B' if layer_of(fp) == 'B.Cu' else 'F'
        ref = next((g[2] for g in kids(fp, 'property') if g[1] == 'Reference'), '?')
        for pad in kids(fp, 'pad'):
            if pad[2] == 'np_thru_hole':
                q = place(at, *nums(pad, 'at')[:2])
                holes.append([round(q[0] - x0, 4), round(q[1] - y0, 4), min(_drill(pad))])
        placed = False
        for m in kids(fp, 'model'):
            if hidden(m):
                continue
            stem = os.path.splitext(os.path.basename(m[1]))[0]
            found = next((f for d in models for f in (os.path.join(d, stem + '.wrl'), os.path.join(d, stem + '.WRL')) if os.path.exists(f)), None)
            if not found:
                print('kicad.py: %s: no %s.wrl in %s' % (ref, stem, models), file=sys.stderr)
                continue
            if stem not in meshes:
                meshes[stem] = parse_wrl(found)
            v3 = lambda k, d: [float(x) for x in (kid(kid(m, k) or [], 'xyz') or ['', d, d, d])[1:4]]  # noqa: E731
            parts.append({'ref': ref, 'model': stem, 'x': round(at[0] - x0, 4), 'y': round(at[1] - y0, 4), 'rot': at[2],
                          'side': side, 'offset': v3('offset', 0), 'rotate': v3('rotate', 0), 'scale': v3('scale', 1)})
            placed = True
        fpname = fp[1] if isinstance(fp[1], str) else ''
        if synth and not placed and not SKIP.search(fpname):
            b = _fp_box(fp)
            if b and b[2] - b[0] > 0 and b[3] - b[1] > 0:
                name = fpname.split(':')[-1]
                modelnames = [os.path.splitext(os.path.basename(m[1]))[0] for m in kids(fp, 'model')]
                h, col, metal, cyl = next((t[1:] for t in SYNTH if any(re.search(t[0], n) for n in modelnames + [name])), SYNTH[-1][1:])
                w, d = max(.2, b[2] - b[0] - .5), max(.2, b[3] - b[1] - .5)   # the courtyard is about .25 mm outside the body
                key = 'synth-%.2fx%.2fx%.2f-%s%s' % (w, d, h, '%02x%02x%02x' % tuple(int(c * 255) for c in col[:3]), 'c' if cyl else '')
                meshes.setdefault(key, _synth_mesh(w, d, h, col, metal, cyl))
                # the box is centred on the outline; a model's offset is in KiCad's model axes, y up
                parts.append({'ref': ref, 'model': key, 'x': round(at[0] - x0, 4), 'y': round(at[1] - y0, 4), 'rot': at[2], 'side': side,
                              'offset': [round((b[0] + b[2]) / 2, 4), round(-(b[1] + b[3]) / 2, 4), 0.0], 'rotate': [0.0, 0.0, 0.0], 'scale': [1.0, 1.0, 1.0]})
    data = {'size': [round(x1 - x0, 4), round(y1 - y0, 4)], 'holes': holes, 'meshes': meshes, 'parts': parts}
    try:
        import PIL  # noqa: F401
    except ImportError:
        return None, data
    imgs = {}
    for name, side, mirror in (('top', 'F', False), ('bottom', 'B', True)):
        c = Canvas(box, ppm, mirror)
        cu = side + '.Cu'
        for z in kids(pcb, 'zone'):
            for fpoly in kids(z, 'filled_polygon'):
                if layer_of(fpoly) == cu:
                    c.poly([(float(xy[1]), float(xy[2])) for xy in kids(kid(fpoly, 'pts'), 'xy')], COPPER)
        for s in kids(pcb, 'segment'):
            if layer_of(s) == cu:
                c.line([nums(s, 'start'), nums(s, 'end')], nums(s, 'width')[0], COPPER)
        for s in kids(pcb, 'arc'):
            if layer_of(s) == cu:
                c.line(arc_points(nums(s, 'start'), nums(s, 'mid'), nums(s, 'end')), nums(s, 'width')[0], COPPER)
        for v in kids(pcb, 'via'):
            p = nums(v, 'at')
            c.disc(p[0], p[1], nums(v, 'size')[0], COPPER)
            c.disc(p[0], p[1], nums(v, 'drill')[0], (10, 26, 14, 255))
        for fp in fps:
            at = nums(fp, 'at')
            at = at + [0.0] * (3 - len(at))
            for pad in kids(fp, 'pad'):
                ls = layers_of(pad)
                if pad[2] != 'np_thru_hole' and (cu in ls or '*.Cu' in ls):
                    c.poly(_pad_poly(pad, at), PAD)
                if pad[2] in ('thru_hole', 'np_thru_hole') and kid(pad, 'drill'):
                    w, h = _drill(pad)
                    if w == h:
                        q = place(at, *nums(pad, 'at')[:2])
                        c.disc(q[0], q[1], w, HOLE)
                    else:
                        c.poly(_pad_poly(pad, at, (w, h), 'oval'), HOLE)
            _graphics(c, fp, side, at)
            _texts(c, fp, side, at)
        _graphics(c, pcb, side)
        _texts(c, pcb, side)
        imgs[name] = c.img
    return imgs, data


def main(argv):
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('pcb')
    ap.add_argument('out')
    ap.add_argument('--models')
    ap.add_argument('--px-per-mm', type=float, default=32)
    ap.add_argument('--synth', action='store_true', help='give a footprint with no usable model a plain body')
    a = ap.parse_args(argv)
    imgs, data = board(a.pcb, a.models, a.px_per_mm, a.synth)
    if imgs is None:
        print('kicad.py: the images need Pillow', file=sys.stderr)
        return 1
    os.makedirs(a.out, exist_ok=True)
    for k, im in imgs.items():
        im.save(os.path.join(a.out, k + '.png'))
    with open(os.path.join(a.out, 'parts.json'), 'w') as f:
        json.dump(data, f, separators=(',', ':'))
    print('%s: %d parts, %d models, %d holes, %.1f x %.1f mm' % (a.out, len(data['parts']), len(data['meshes']),
                                                                   len(data['holes']), *data['size']))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
