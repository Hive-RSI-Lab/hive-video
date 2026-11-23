"""The board's layout drawn as the design went, from history.py's timeline, as numbered frames for a paper shot.

    python3 layout.py replay BOARD.kicad_pcb TIMELINE.json OUT/ --frames N [--width 4000] [--from I] [--to J]
    python3 layout.py trace  BOARD.kicad_pcb TIMELINE.json OUT/ --frames N --event I [--rev] [--width 4000]

replay: every saved state in turn. New tracks go down in dark ink and settle to their layer's pastel; tracks a
        re-route rips up show once in amber and fade. Also writes OUT/layers/<layer>.png (the last state's tracks,
        one transparent sheet a layer, for the pulled-apart stack) and OUT/starts.json (the frame each state starts).
trace:  one state drawn track by track: every trace it added grows from one end to the other, so the eye can
        follow one. --rev runs the longest the other way and starts the shorter ones late, so all finish on the
        last frame. Writes OUT/track.json: where the head of the longest trace is on the sheet, in metres from the
        sheet centre, for a camera to follow (paper.py --track).

Both draw on BOARD's outline, pads and silk in a quiet grey (the base), so the copper is what moves.
"""
import argparse
import heapq
import json
import math
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import INK, AMBER, PAPER, LIGHT, layer_colour, layer_head, layer_order, font  # noqa: E402
import kicad  # noqa: E402
from kicad import sexpr, kids, kid, nums, layer_of, layers_of, place, arc_points  # noqa: E402

PLANE_W = 0.594
VIA = (150, 150, 146)


class Sheet:
    def __init__(self, sh, width):
        self.ox, self.oy, self.sw, self.shh = sh['x0'], sh['y0'], sh['w'], sh['h']
        self.W, self.H = width, round(width * sh['h'] / sh['w'])
        self.S = width / sh['w']

    def P(self, x, y):
        return ((x - self.ox) * self.S, (y - self.oy) * self.S)

    def metres(self, x, y):
        """a board point on the paper plane, metres from its centre, y up"""
        return [((x - self.ox) / self.sw - 0.5) * PLANE_W, (0.5 - (y - self.oy) / self.shh) * PLANE_W * self.shh / self.sw]


def base(board, sh):
    """white paper; board edge in grey ink, pads and silk light"""
    from PIL import Image, ImageDraw
    pcb = sexpr(open(board, encoding='utf-8').read())
    c = kicad.Canvas((sh.ox, sh.oy, sh.ox + sh.sw, sh.oy + sh.shh), sh.S, False)
    c.img = Image.new('RGBA', (sh.W, sh.H), PAPER + (255,))
    c.d = ImageDraw.Draw(c.img)
    silk = (214, 214, 210, 255)
    old = kicad.SILK
    kicad.SILK = silk
    try:
        for fp in kids(pcb, 'footprint'):
            at = nums(fp, 'at')
            at = at + [0.0] * (3 - len(at))
            kicad._graphics(c, fp, 'F', at)
        kicad._graphics(c, pcb, 'F')
    finally:
        kicad.SILK = old
    for fp in kids(pcb, 'footprint'):
        at = nums(fp, 'at')
        at = at + [0.0] * (3 - len(at))
        for pad in kids(fp, 'pad'):
            ls = layers_of(pad)
            if pad[2] != 'np_thru_hole' and ('F.Cu' in ls or '*.Cu' in ls or 'B.Cu' in ls):
                c.poly(kicad._pad_poly(pad, at), LIGHT + (255,))
    edge = (96, 96, 92, 255)
    for g in pcb:
        if isinstance(g, list) and g and g[0] in ('gr_line', 'gr_arc', 'gr_rect', 'gr_circle') and layer_of(g) == 'Edge.Cuts':
            if g[0] == 'gr_line':
                c.line([nums(g, 'start'), nums(g, 'end')], 0.25, edge)
            elif g[0] == 'gr_arc':
                c.line(arc_points(nums(g, 'start'), nums(g, 'mid'), nums(g, 'end')), 0.25, edge)
            elif g[0] == 'gr_rect':
                (x0, y0), (x1, y1) = nums(g, 'start'), nums(g, 'end')
                c.line([(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)], 0.25, edge)
            else:
                (cx, cy), (ex, ey) = nums(g, 'center'), nums(g, 'end')
                r = math.hypot(ex - cx, ey - cy)
                c.line([(cx + r * math.cos(a * math.pi / 24), cy + r * math.sin(a * math.pi / 24)) for a in range(49)], 0.25, edge)
    return c.img.convert('RGB')


def _seg(d, sh, s, col, wmin=2):
    w = max(int(round(s[4] * sh.S)), wmin)
    a, b = sh.P(s[0], s[1]), sh.P(s[2], s[3])
    d.line([a, b], fill=col, width=w)
    if w > 3:
        r = w / 2
        for p in (a, b):
            d.ellipse([p[0] - r, p[1] - r, p[0] + r, p[1] + r], fill=col)


def _via(d, sh, v, col):
    x, y = sh.P(v[0], v[1])
    r = max(1.5, v[2] * sh.S / 2)
    d.ellipse([x - r, y - r, x + r, y + r], fill=col)


def _copper(d, sh, segs, vias, layers):
    for i, L in enumerate(layers):
        col = layer_colour(L, i)
        for s in segs:
            if s[5] == L:
                _seg(d, sh, s, col)
    for v in vias:
        _via(d, sh, v, VIA)


def _state_before(states, i):
    cur, vias = [], []
    for e in states[:i]:
        rem, vrem = set(map(tuple, e['removed'])), set(map(tuple, e['vias_removed']))
        cur = [s for s in cur if tuple(s) not in rem] + e['added']
        vias = [v for v in vias if tuple(v) not in vrem] + e['vias_added']
    return cur, vias


def replay(board, timeline, out, frames, width=4000, first=0, last=None, wipe=6.0, fade=8, hold=0):
    from PIL import Image, ImageDraw
    tl = json.load(open(timeline))
    sh = Sheet(tl['sheet'], width)
    states = tl['states']
    last = len(states) - 1 if last is None else last
    layers = layer_order({s[5] for e in states for s in e['added']})
    os.makedirs(os.path.join(out, 'layers'), exist_ok=True)
    b0 = base(board, sh)
    cur, vias = _state_before(states, first)
    run = states[first:last + 1]

    def weight(e):
        n = len(e['added']) + len(e['vias_added'])
        if n:
            return 1 + math.sqrt(n)
        return wipe if e['removed'] else 0.2
    wts = [weight(e) for e in run]
    tot = sum(wts)
    nfs = [max(1, round(frames * w / tot)) for w in wts]
    nfs[-1] += frames - sum(nfs)            # exactly `frames` frames
    if nfs[-1] < 1:
        raise SystemExit('too few frames for %d states' % len(run))
    f, starts, new = 0, [], []
    for e, n in zip(run, nfs):
        starts.append(f)
        rem, vrem = set(map(tuple, e['removed'])), set(map(tuple, e['vias_removed']))
        gone = [s for s in cur if tuple(s) in rem]
        cur = [s for s in cur if tuple(s) not in rem]
        vias = [v for v in vias if tuple(v) not in vrem]
        img = b0.copy()
        _copper(ImageDraw.Draw(img), sh, cur, vias, layers)
        add, vadd = e['added'], e['vias_added']
        for k in range(n):
            fr = img.copy()
            d = ImageDraw.Draw(fr)
            if gone and k < fade:              # the ripped-up copper shows in amber and fades out, not blinks off
                for s in gone:
                    _seg(d, sh, s, AMBER, 3)
                fr = Image.blend(img, fr, 1 - (k / fade) ** 2)
                d = ImageDraw.Draw(fr)
            a0, a = int(len(add) * k / n), int(len(add) * (k + 1) / n)
            v0, va = int(len(vadd) * k / n), int(len(vadd) * (k + 1) / n)
            _copper(d, sh, add[:a0], vadd[:v0], layers)
            for s in add[a0:a]:
                _seg(d, sh, s, layer_head(s[5], layers.index(s[5]) if s[5] in layers else 0), 4)
            for v in vadd[v0:va]:
                _via(d, sh, v, INK)
            new.append(a - a0 + va - v0 + (len(gone) if k < fade else 0))
            fr.save(os.path.join(out, '%05d.png' % f), compress_level=1)
            f += 1
        cur, vias = cur + add, vias + vadd
    fin = b0.copy()
    _copper(ImageDraw.Draw(fin), sh, cur, vias, layers)
    for k in range(hold):
        fin.save(os.path.join(out, '%05d.png' % f), compress_level=1)
        f += 1
    fin.save(os.path.join(out, 'final.png'), compress_level=1)
    for i, L in enumerate(layers):
        ss = [s for s in cur if s[5] == L]
        col = layer_colour(L, i)
        im = Image.new('RGBA', (sh.W, sh.H), col + (0,))
        d = ImageDraw.Draw(im)
        for s in ss:
            _seg(d, sh, s, col + (255,))
        im.save(os.path.join(out, 'layers', '%s.png' % L), compress_level=1)
    b0.save(os.path.join(out, 'layers', 'base.png'), compress_level=1)
    json.dump(dict(starts=starts, names=[e['name'] for e in run], layers=layers, new=new, aspect=sh.H / sh.W), open(os.path.join(out, 'starts.json'), 'w'))
    return starts


def trace(board, timeline, out, frames, event, width=4000, rev=False, head=3.0):
    from PIL import ImageDraw
    tl = json.load(open(timeline))
    sh = Sheet(tl['sheet'], width)
    states = tl['states']
    layers = layer_order({s[5] for e in states for s in e['added']})
    os.makedirs(out, exist_ok=True)
    cur, vias = _state_before(states, event)
    e = states[event]
    rem = set(map(tuple, e['removed']))
    cur = [s for s in cur if tuple(s) not in rem]
    add = e['added']
    if not add:
        raise SystemExit('state %d adds no tracks' % event)
    img = base(board, sh)
    _copper(ImageDraw.Draw(img), sh, cur, vias, layers)

    def key(x, y):
        return (round(x, 3), round(y, 3))
    adj = defaultdict(list)
    for s in add:
        a, b = key(s[0], s[1]), key(s[2], s[3])
        ln = math.hypot(s[2] - s[0], s[3] - s[1])
        adj[a].append((b, ln))
        adj[b].append((a, ln))
    seen, comps = set(), []
    for n0 in list(adj):
        if n0 in seen:
            continue
        st, c = [n0], []
        while st:
            n = st.pop()
            if n in seen:
                continue
            seen.add(n)
            c.append(n)
            st += [m for m, _ in adj[n]]
        comps.append(c)

    def dij(src):
        D, h = {src: 0}, [(0, src)]
        while h:
            dd, n = heapq.heappop(h)
            if dd > D[n]:
                continue
            for m, ln in adj[n]:
                if dd + ln < D.get(m, 1e9):
                    D[m] = dd + ln
                    heapq.heappush(h, (dd + ln, m))
        return D

    def ends(c):        # a trace's two ends: the furthest node from any node, then the furthest from that
        a = max(dij(c[0]).items(), key=lambda kv: kv[1])[0]
        Da = dij(a)
        b = max(Da.items(), key=lambda kv: kv[1])[0]
        return a, b, Da[b]
    info = sorted((ends(c) for c in comps), key=lambda t: -t[2])
    A0, B0, LMAX = info[0]
    if rev:
        A0, B0 = B0, A0
    DIST, lead = {}, None
    for a, b, L in info:   # every trace starts from its end nearer the longest one's start, so a bus runs one way
        if math.dist(b, A0) < math.dist(a, A0):
            a, b = b, a
        Da = dij(a)
        if rev:
            Da = {n: v + LMAX - L for n, v in Da.items()}
        DIST.update(Da)
        if lead is None:
            lead = (Da, a, b)
    Da, a, b = lead
    path = [b]
    while path[-1] != a:
        n = path[-1]
        path.append(min((m for m, ln in adj[n] if abs(Da[m] + ln - Da[n]) < 1e-6), key=lambda m: Da[m]))
    path = path[::-1]

    def tip(D):
        for p, q in zip(path, path[1:]):
            if Da[q] >= D:
                t = (D - Da[p]) / max(1e-9, Da[q] - Da[p])
                return (p[0] + (q[0] - p[0]) * t, p[1] + (q[1] - p[1]) * t)
        return path[-1]
    track = []
    for k in range(frames):
        u = k / max(1, frames - 1)
        D = 1.5 + (LMAX + head - 1.5) * (0.55 * u + 0.45 * u * u)   # moving on the first frame, gathering speed
        fr = img.copy()
        d = ImageDraw.Draw(fr)
        for ink in (False, True):
            for i, L in enumerate(layers):
                for s in add:
                    if s[5] != L:
                        continue
                    p, q = (s[0], s[1]), (s[2], s[3])
                    dp, dq = DIST[key(*p)], DIST[key(*q)]
                    if dp > dq:
                        p, q, dp, dq = q, p, dq, dp
                    ln = math.hypot(q[0] - p[0], q[1] - p[1]) or 1e-9
                    if ink:
                        lo, hi = max(dp, D - head), min(dp + ln, D)
                    else:
                        lo, hi = dp, min(dp + ln, D - head if D < LMAX + head - 1e-6 else D)
                    if hi <= lo:
                        continue
                    f = lambda x, p=p, q=q, dp=dp, ln=ln: (p[0] + (q[0] - p[0]) * (x - dp) / ln, p[1] + (q[1] - p[1]) * (x - dp) / ln)  # noqa: E731
                    pa, pb = f(lo), f(hi)
                    _seg(d, sh, (pa[0], pa[1], pb[0], pb[1], s[4], L), layer_head(L, i) if ink else layer_colour(L, i), 4 if ink else 2)
        fr.save(os.path.join(out, '%05d.png' % k), compress_level=1)
        track.append(sh.metres(*tip(min(D, LMAX))))
    json.dump(track, open(os.path.join(out, 'track.json'), 'w'))
    return LMAX, len(info)


# ---- ink: the same history as a plot ----------------------------------------------------------------------------
# --ink 1 draws replay and trace as KiCad-plot line art for a paper shot: black ink on white paper, every part's
# outline and name, the two copper sides in two dense pen inks, and the ratsnest: a thin straight air wire between
# pads of one net that the copper drawn so far does not join. Every saved state is read whole from git (its parts,
# nets and pours), so what appears, moves and is still unrouted is that state's own. Nothing here is made up: the
# only choice is the order inside one state, which is the board file's own (net by net), each trace end to end.

BLACK = (20, 20, 18)
PENS = {'F.Cu': (186, 22, 28), 'B.Cu': (14, 58, 156)}
AIRW = (44, 44, 42)
_FONTS = {}


def _snap(text):
    """one saved board as plain lists: parts in file order with pads and nets, tracks, vias, filled pours, edge"""
    pcb = sexpr(text)
    codes = {n[1]: n[2] for n in kids(pcb, 'net') if len(n) > 2}
    netof = lambda g: codes.get((kid(g, 'net') or [None])[-1], (kid(g, 'net') or [None])[-1])   # noqa: E731
    parts = {}
    for fp in kids(pcb, 'footprint'):
        at = nums(fp, 'at') or [0.0, 0.0]
        at = at + [0.0] * (3 - len(at))
        box = None
        for g in kids(fp, 'fp_rect'):
            if (layer_of(g) or '').endswith('.Fab'):
                (x0, y0), (x1, y1) = nums(g, 'start'), nums(g, 'end')
                box = (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))
                break
        if not box and any((layer_of(g) or '').endswith(('.CrtYd', '.Fab')) for k in ('fp_line', 'fp_rect', 'fp_poly') for g in kids(fp, k)):
            box = kicad._fp_box(fp)        # a part that draws no body (a mounting hole: one round pad) gets no outline
        pads = []
        for pad in kids(fp, 'pad'):
            cu = [n for n in layers_of(pad) if n.endswith('.Cu')]
            if not cu:
                continue
            poly = kicad._pad_poly(pad, at)
            xs, ys = [q[0] for q in poly], [q[1] for q in poly]
            p = nums(pad, 'at')
            np_ = pad[2] == 'np_thru_hole'
            hole = kicad._pad_poly(pad, at, kicad._drill(pad), 'oval') if kid(pad, 'drill') else None
            pads.append(dict(poly=poly, box=(min(xs), min(ys), max(xs), max(ys)), c=place(at, p[0], p[1]), cu=cu,
                             net=None if np_ else netof(pad), hole=hole, np=np_))
        name = None
        for g in kids(fp, 'property'):
            if g[1] == 'Reference' and not kicad.hidden(g) and not kicad.hidden(kid(g, 'effects') or []):
                p = nums(g, 'at')
                size = nums(kid(kid(g, 'effects') or [], 'font') or [], 'size', [1, 1])[1]
                name = (place(at, p[0], p[1]), p[2] if len(p) > 2 else 0.0, size)
        ref = kicad._ref(fp)
        parts[ref] = dict(
            ref=ref, value=next((g[2] for g in kids(fp, 'property') if g[1] == 'Value'), ''), at=tuple(at), pads=pads, name=name,
            corners=[place(at, x, y) for x, y in ((box[0], box[1]), (box[2], box[1]), (box[2], box[3]), (box[0], box[3]))] if box else [])
    segs = []
    for s in kids(pcb, 'segment'):
        a, b = nums(s, 'start'), nums(s, 'end')
        segs.append((round(a[0], 4), round(a[1], 4), round(b[0], 4), round(b[1], 4), nums(s, 'width')[0], layer_of(s), netof(s)))
    for s in kids(pcb, 'arc'):
        pts = arc_points(nums(s, 'start'), nums(s, 'mid'), nums(s, 'end'), 8)
        for a, b in zip(pts, pts[1:]):
            segs.append((round(a[0], 4), round(a[1], 4), round(b[0], 4), round(b[1], 4), nums(s, 'width')[0], layer_of(s), netof(s)))
    vias = []
    for v in kids(pcb, 'via'):
        p = nums(v, 'at')
        vias.append((round(p[0], 4), round(p[1], 4), nums(v, 'size')[0], (nums(v, 'drill') or [0.3])[0], netof(v)))
    fills = []
    for z in kids(pcb, 'zone'):
        for g in kids(z, 'filled_polygon'):
            pts = [(float(xy[1]), float(xy[2])) for xy in kids(kid(g, 'pts') or [], 'xy')]
            if len(pts) >= 3:
                fills.append((layer_of(g), netof(z), pts))
    edge = []
    for g in pcb:
        if isinstance(g, list) and g and g[0] in ('gr_line', 'gr_arc', 'gr_rect', 'gr_circle') and layer_of(g) == 'Edge.Cuts':
            if g[0] == 'gr_line':
                edge.append([nums(g, 'start'), nums(g, 'end')])
            elif g[0] == 'gr_arc':
                edge.append(arc_points(nums(g, 'start'), nums(g, 'mid'), nums(g, 'end')))
            elif g[0] == 'gr_rect':
                (x0, y0), (x1, y1) = nums(g, 'start'), nums(g, 'end')
                edge.append([(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)])
            else:
                (cx, cy), (ex, ey) = nums(g, 'center'), nums(g, 'end')
                r = math.hypot(ex - cx, ey - cy)
                edge.append([(cx + r * math.cos(a * math.pi / 24), cy + r * math.sin(a * math.pi / 24)) for a in range(49)])
    texts = []
    for g in kids(pcb, 'gr_text'):
        if layer_of(g) == 'F.SilkS' and not kicad.hidden(g) and not kicad.hidden(kid(g, 'effects') or []) and not g[1].startswith('${'):
            p = nums(g, 'at')
            texts.append((g[1], (p[0], p[1]), p[2] if len(p) > 2 else 0.0, nums(kid(kid(g, 'effects') or [], 'font') or [], 'size', [1, 1])[1]))
    pts = [q for pl in edge for q in pl]
    org = (round(min(q[0] for q in pts), 3), round(min(q[1] for q in pts), 3)) if pts else None
    return dict(parts=parts, segs=segs, vias=vias, fills=fills, edge=edge, texts=texts, org=org)


def _stroke(d, pts, w, col):
    """a pen line through pts (px) with round ends and corners"""
    w = max(1, int(round(w)))
    d.line(pts, fill=col, width=w)
    if w > 2:
        r = w / 2
        for x, y in pts:
            d.ellipse([x - r, y - r, x + r, y + r], fill=col)


def _write(im, s, cx, cy, cap, angle, col, plate=None):
    """s centred on (cx, cy) px in the film's label font, capitals cap px tall, turned angle degrees and kept
    upright; plate: a paper box under it, so a name inside a part reads over that part's pads"""
    from PIL import Image, ImageDraw
    px = max(7, int(round(cap / 0.72)))
    f = _FONTS.get(px) or _FONTS.setdefault(px, font('label', px))
    l, t, r, b = f.getbbox(s)
    m = max(2, px // 4) if plate else 2
    t_ = Image.new('RGBA', (r - l + 2 * m, b - t + 2 * m), (tuple(plate) + (255,)) if plate else (tuple(col) + (0,)))
    ImageDraw.Draw(t_).text((m - l, m - t), s, font=f, fill=tuple(col) + (255,))
    a = angle % 360
    if 90 < a <= 270:
        a -= 180
    a %= 360
    if abs(a - 90) < 0.5:
        t_ = t_.transpose(Image.ROTATE_90)
    elif abs(a - 270) < 0.5:
        t_ = t_.transpose(Image.ROTATE_270)
    elif a > 0.5:
        t_ = t_.rotate(a, expand=True, resample=Image.BICUBIC)
    x, y = int(round(cx - t_.width / 2)), int(round(cy - t_.height / 2))
    x0, y0 = max(0, -x), max(0, -y)
    x1, y1 = min(t_.width, im.width - x), min(t_.height, im.height - y)
    if x1 > x0 and y1 > y0:
        im.alpha_composite(t_.crop((x0, y0, x1, y1)), (x + x0, y + y0))


def _name(im, sh, p):
    """a part's name: inside its outline when that can hold it (its value under it when there is room), else where
    the board itself has the part's reference text"""
    if not p['ref']:
        return
    xs, ys = [c[0] for c in p['corners']] or [0], [c[1] for c in p['corners']] or [0]
    bw, bh = max(xs) - min(xs), max(ys) - min(ys)
    cx, cy = (max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2
    L, T = max(bw, bh), min(bw, bh)
    ref, val = p['ref'], p['value']
    if T >= 2.6:
        h = min(0.34 * T, 0.8 * L / (0.84 * len(ref)), 2.6)
        hv = min(0.55 * h, 0.9 * L / (0.84 * max(1, len(val)))) if val and val != ref and T >= 4.5 else 0
        hv = hv if hv >= 0.5 else 0
        ang = 0 if bw >= bh else 90
        B = h + (0.55 * h + hv if hv else 0)
        for s, hh, off in ((ref, h, -B / 2 + h / 2), (val, hv, B / 2 - hv / 2)):
            if hh:
                x, y = (cx, cy + off) if ang == 0 else (cx + off, cy)
                _write(im, s, *sh.P(x, y), hh * sh.S, ang, BLACK, PAPER)
    elif p['name']:
        (x, y), ang, size = p['name']
        _write(im, ref, *sh.P(x, y), min(1.2, max(0.8, size)) * sh.S, ang, BLACK)


ALL = ('edge', 'outline', 'pads', 'names')


def _parts(sh, snap, pen, refs=None, what=ALL, im=None):
    """the parts on a clear sheet (RGBA): the board edge, each part's outline, pads, holes and name. refs: only
    these parts, drawn onto im when given. what: 'edge', 'outline', 'pads' (holes paper white; with 'clear', cut
    through), 'holes' (the drills alone, as rings), 'names'"""
    from PIL import Image, ImageDraw
    K = BLACK + (255,)
    wl = max(2.0, 0.14 * sh.S * pen)
    new = im is None
    if new:
        im = Image.new('RGBA', (sh.W, sh.H), BLACK + (0,))
    d = ImageDraw.Draw(im)
    if new and 'edge' in what:
        for pl in snap['edge']:
            _stroke(d, [sh.P(*q) for q in pl], 0.32 * sh.S * pen, K)
    todo = [snap['parts'][r] for r in (snap['parts'] if refs is None else refs) if r in snap['parts']]
    for p in todo:
        real = any(not pad['np'] for pad in p['pads'])
        if 'outline' in what and p['corners'] and real:
            q = [sh.P(*c) for c in p['corners']]
            _stroke(d, q + q[:1], wl, K)
        for pad in p['pads']:
            if 'pads' in what and not pad['np']:
                d.polygon([sh.P(*c) for c in pad['poly']], fill=K)
            if pad['hole'] and ('pads' in what or 'holes' in what):
                h = [sh.P(*c) for c in pad['hole']]
                if 'pads' in what:
                    d.polygon(h, fill=PAPER + ((0,) if 'clear' in what else (255,)))
                if pad['np'] or 'holes' in what:
                    _stroke(d, h + h[:1], wl, K)
    if 'names' in what:
        for p in todo:
            if any(not pad['np'] for pad in p['pads']):
                _name(im, sh, p)
        if new:                                # the board's own silkscreen notes, but not one that lies under a part's name
            named = [(min(c[0] for c in p['corners']), min(c[1] for c in p['corners']), max(c[0] for c in p['corners']), max(c[1] for c in p['corners']))    # any part's, also one that is still to arrive: its mark must not sit alone on the bare sheet
                     for p in snap['parts'].values() if p['corners'] and any(not pad['np'] for pad in p['pads'])]
            named = [b for b in named if min(b[2] - b[0], b[3] - b[1]) >= 2.6]
            for s, (x, y), ang, size in snap['texts']:
                if not any(b[0] <= x <= b[2] and b[1] <= y <= b[3] for b in named):
                    _write(im, s, *sh.P(x, y), size * sh.S, ang, BLACK)
    return im


def _near(x, y, s, r):
    """is (x, y) within r of track s"""
    dx, dy = s[2] - s[0], s[3] - s[1]
    q = dx * dx + dy * dy
    t = 0.0 if q < 1e-12 else min(1.0, max(0.0, ((x - s[0]) * dx + (y - s[1]) * dy) / q))
    return math.hypot(x - s[0] - t * dx, y - s[1] - t * dy) <= r + 0.005


def _inside(poly, pts):
    """which of pts (M, 2) lie in the polygon poly (N, 2), even-odd; numpy arrays"""
    import numpy as np
    out = np.zeros(len(pts), bool)
    x0, y0 = poly[:, 0][None, :], poly[:, 1][None, :]
    x1, y1 = np.roll(poly[:, 0], -1)[None, :], np.roll(poly[:, 1], -1)[None, :]
    dy = np.where(y1 == y0, 1e-9, y1 - y0)
    for i in range(0, len(pts), 200):
        x, y = pts[i:i + 200, 0][:, None], pts[i:i + 200, 1][:, None]
        out[i:i + 200] = (((y0 > y) != (y1 > y)) & (x < (x1 - x0) * (y - y0) / dy + x0)).sum(1) % 2 == 1
    return out


def _airwires(pads, segs, vias, fills=()):
    """One net's air wires: its pads, the tracks and vias drawn so far (and, once the pours are drawn, the filled
    areas [(layer, points array)]) are joined where they touch; a shortest tree of straight pad-to-pad lines
    then joins the groups that are left, as a layout program's ratsnest does."""
    n = len(pads)
    if n < 2:
        return []
    S0, V0 = n, n + len(segs)
    F0 = V0 + len(vias)
    par = list(range(F0 + len(fills)))

    def find(i):
        while par[i] != i:
            par[i] = par[par[i]]
            i = par[i]
        return i

    def join(i, j):
        i, j = find(i), find(j)
        if i != j:
            par[i] = j

    def inbox(b, x, y):
        return b[0] - 0.02 <= x <= b[2] + 0.02 and b[1] - 0.02 <= y <= b[3] + 0.02

    def crosses(b, s):                     # a track that runs over a pad joins it, wherever its ends are
        t0, t1 = 0.0, 1.0
        for p, d, lo, hi in ((s[0], s[2] - s[0], b[0] - 0.02, b[2] + 0.02), (s[1], s[3] - s[1], b[1] - 0.02, b[3] + 0.02)):
            if abs(d) < 1e-12:
                if not lo <= p <= hi:
                    return False
            else:
                a, c = sorted(((lo - p) / d, (hi - p) / d))
                t0, t1 = max(t0, a), min(t1, c)
        return t0 <= t1
    for i, s in enumerate(segs):
        for j, p in enumerate(pads):
            if (s[5] in p['cu'] or '*.Cu' in p['cu']) and crosses(p['box'], s):
                join(S0 + i, j)
        for k in range(i):
            t = segs[k]
            if t[5] == s[5] and (_near(s[0], s[1], t, t[4] / 2) or _near(s[2], s[3], t, t[4] / 2)
                                 or _near(t[0], t[1], s, s[4] / 2) or _near(t[2], t[3], s, s[4] / 2)):
                join(S0 + i, S0 + k)
    for i, v in enumerate(vias):
        for j, p in enumerate(pads):
            if inbox(p['box'], v[0], v[1]):
                join(V0 + i, j)
        for k, s in enumerate(segs):
            if _near(v[0], v[1], s, v[2] / 2):
                join(V0 + i, S0 + k)
    if fills:
        import numpy as np
        pts, who, lay = [], [], []
        for j, p in enumerate(pads):       # a pad touches a pour at its middle or just inside one of its four sides
            b, (cx, cy) = p['box'], p['c']
            for q in ((cx, cy), (b[0] + 0.05, cy), (b[2] - 0.05, cy), (cx, b[1] + 0.05), (cx, b[3] - 0.05)):
                pts.append(q), who.append(j), lay.append(p['cu'])
        for i, s in enumerate(segs):
            for q in ((s[0], s[1]), (s[2], s[3])):
                pts.append(q), who.append(S0 + i), lay.append([s[5]])
        for i, v in enumerate(vias):
            pts.append((v[0], v[1])), who.append(V0 + i), lay.append(['*.Cu'])
        arr = np.array(pts, float)
        for k, (L, poly) in enumerate(fills):
            for i in np.nonzero(_inside(poly, arr))[0]:
                if L in lay[i] or '*.Cu' in lay[i]:
                    join(F0 + k, who[i])
    if len({find(j) for j in range(n)}) < 2:
        return []
    out = []
    for dd, a, b in sorted((math.dist(pads[a]['c'], pads[b]['c']), a, b) for a in range(n) for b in range(a) if find(a) != find(b)):
        ra, rb = find(a), find(b)
        if ra != rb:
            par[ra] = rb
            out.append((pads[a]['c'], pads[b]['c']))
    return out


class _Rats:
    """a state's air wires as its copper lands; only the nets whose copper changed are worked out again"""

    def __init__(self, snap, refs=None):
        self.pads = defaultdict(list)
        for ref, p in snap['parts'].items():
            if refs is None or ref in refs:
                for pad in p['pads']:
                    if pad['net']:
                        self.pads[pad['net']].append(pad)
        self.wires, self.sig = {}, {}

    def update(self, segs, vias, fills=None):
        bs, bv = defaultdict(list), defaultdict(list)
        for s in segs:
            bs[s[6]].append(s)
        for v in vias:
            bv[v[4]].append(v)
        for net, pads in self.pads.items():
            sig = (hash(tuple(bs[net])), hash(tuple(bv[net])), fills is not None)
            if self.sig.get(net) != sig:
                self.sig[net] = sig
                self.wires[net] = _airwires(pads, bs[net], bv[net], (fills or {}).get(net, ()))
        return [w for ws in self.wires.values() for w in ws]


def _dij(adj, src):
    D, h = {src: 0.0}, [(0.0, src)]
    while h:
        dd, n = heapq.heappop(h)
        if dd > D[n]:
            continue
        for m, ln in adj[n]:
            if dd + ln < D.get(m, 1e18):
                D[m] = dd + ln
                heapq.heappush(h, (dd + ln, m))
    return D


def _key(x, y):
    return (round(x, 3), round(y, 3))


def _runs(add):
    """the tracks one state added, net by net in the file's order: {net: [tracks, D, L, adj, a, b]}; D is each
    track end's distance along its own trace from the end it grows from, L the net's longest trace, a -> b its ends"""
    by = defaultdict(list)
    for s in add:
        by[s[6]].append(s)
    out = {}
    for net, ss in by.items():
        adj = defaultdict(list)
        for s in ss:
            a, b = _key(s[0], s[1]), _key(s[2], s[3])
            ln = math.hypot(s[2] - s[0], s[3] - s[1])
            adj[a].append((b, ln))
            adj[b].append((a, ln))
        D, best = {}, (-1.0, None, None)
        for n0 in list(adj):
            if n0 in D:
                continue
            d0 = _dij(adj, n0)
            a = max(d0, key=d0.get)
            da = _dij(adj, a)
            b = max(da, key=da.get)
            D.update(da)
            if da[b] > best[0]:
                best = (da[b], a, b)
        out[net] = [ss, D, max(best[0], 1e-6), adj, best[1], best[2]]
    return out


def _timed(runs, t0, dur, vadd, rem, vrem):
    """when each change of a state happens, in state time: ([(u0, u1, track, from its far end)], [(u, via)],
    [(u, track ripped up)], [(u, via ripped up)]). A net's old copper goes as its new copper starts; a via lands
    as its trace reaches it, a via on no new trace in its turn in the file."""
    segs, vias = [], []
    for net, (ss, D, L, adj, a, b) in runs.items():
        for s in ss:
            da, db = D[_key(s[0], s[1])], D[_key(s[2], s[3])]
            lo = min(da, db)
            hi = max(lo + 1e-6, min(L, lo + math.hypot(s[2] - s[0], s[3] - s[1])))
            segs.append((t0[net] + dur[net] * lo / L, t0[net] + dur[net] * hi / L, s, db < da))
    free = sum(1 for v in vadd if not (v[4] in runs and _key(v[0], v[1]) in runs[v[4]][1]))
    i = 0
    for v in vadd:
        r, k = runs.get(v[4]), _key(v[0], v[1])
        if r and k in r[1]:
            vias.append((t0[v[4]] + dur[v[4]] * r[1][k] / r[2], v))
        else:
            i += 1
            vias.append((i / free, v))
    return segs, vias, [(t0.get(s[6], 0.0), s) for s in rem], [(t0.get(v[4], 0.0), v) for v in vrem]


def _plan(add, vadd, rem, vrem):
    """a whole state: its nets one after another in file order, overlapping, a long trace taking longer"""
    runs = _runs(add)
    order = list(runs)
    K = len(order)
    Ls = sorted(r[2] for r in runs.values())
    ref = Ls[int(0.85 * (K - 1))] if K else 1.0
    t0, dur = {}, {}
    for k, net in enumerate(order):
        dur[net] = 1.0 if K == 1 else min(0.4, max(0.1, 0.4 * runs[net][2] / ref))
        t0[net] = k / max(1, K - 1) * (1 - dur[net])
    return _timed(runs, t0, dur, vadd, rem, vrem), {net: t0[net] + dur[net] for net in order}


def _at(plan, cur, vias, u):
    """the copper at state time u: (tracks down, [(track, a, b)] growing, vias down)"""
    segs, vs, gone, vgone = plan
    off = {s for t, s in gone if u > t}
    voff = {v for t, v in vgone if u > t}
    down = [s for s in cur if s not in off]
    grow = []
    for u0, u1, s, flip in segs:
        if u >= u1 - 1e-9:
            down.append(s)
        elif u > u0:
            k = (u - u0) / (u1 - u0)
            a, b = ((s[2], s[3]), (s[0], s[1])) if flip else ((s[0], s[1]), (s[2], s[3]))
            grow.append((s, a, (a[0] + (b[0] - a[0]) * k, a[1] + (b[1] - a[1]) * k)))
    return down, grow, [v for v in vias if v not in voff] + [v for t, v in vs if u >= t - 1e-9]


def _hatch(sh, snap, pen):
    """each copper side's pour as pen hatching, {layer: bool array}: slanted lines 3 mm apart (one way on the
    front, the other on the back) clipped to that state's real filled areas, each area with its edge drawn. Wide
    apart and fine, so the traces stay the darkest thing on the sheet"""
    import numpy as np
    from PIL import Image, ImageDraw, ImageFilter
    out = {}
    pitch, wd = max(10, round(4.24 * sh.S)), max(2, round(0.17 * sh.S * pen))   # measured along a row: 3 mm between the slanted lines
    x, y = np.arange(sh.W, dtype=np.int32)[None, :], np.arange(sh.H, dtype=np.int32)[:, None]
    for L in sorted({f[0] for f in snap['fills']}):
        m = Image.new('L', (sh.W, sh.H), 0)
        d = ImageDraw.Draw(m)
        for lay, net, pts in snap['fills']:
            if lay == L:
                d.polygon([sh.P(*q) for q in pts], fill=255)
        k = max(1, round(0.07 * sh.S * pen))
        rim = np.asarray(m) != np.asarray(m.filter(ImageFilter.MinFilter(2 * k + 1)))
        out[L] = (np.asarray(m) > 0) & ((((x + y) if L == 'F.Cu' else (x - y)) % pitch) < wd) | rim
    return out


def _sweep(sh):
    """the order a pour is hatched in, 0..1 over the sheet: left to right, the front leaning"""
    import numpy as np
    x, y = np.arange(sh.W, dtype=np.float32)[None, :], np.arange(sh.H, dtype=np.float32)[:, None]
    return (x + 0.4 * y) / (sh.W + 0.4 * sh.H)


def _compose(sh, pen, down, grow, vias, wires, over, pour=()):
    """one frame: paper, pours, back copper, front copper, vias, air wires, then the parts sheet on top"""
    from PIL import Image, ImageDraw
    fr = Image.new('RGB', (sh.W, sh.H), PAPER)
    for col, mask in pour:
        fr.paste(col, mask=mask)
    d = ImageDraw.Draw(fr)
    _copper_ink(d, sh, down, grow, vias, pen)
    wa = max(2.0, 0.15 * sh.S * pen)
    for a, b in wires:
        _stroke(d, [sh.P(*a), sh.P(*b)], wa, AIRW)
    if over is not None:
        fr.paste(over, mask=over)
    return fr


def _copper_ink(d, sh, down, grow, vias, pen, only=None, clear=False):
    wmin = 0.2 * pen
    for top in (False, True):
        for s in down:
            if (s[5] == 'F.Cu') == top and (only is None or s[5] == only):
                _stroke(d, [sh.P(s[0], s[1]), sh.P(s[2], s[3])], max(s[4], wmin) * sh.S, PENS.get(s[5], BLACK) + ((255,) if clear else ()))
        for s, a, b in grow:
            if (s[5] == 'F.Cu') == top and (only is None or s[5] == only):
                _stroke(d, [sh.P(*a), sh.P(*b)], max(s[4], wmin) * sh.S, PENS.get(s[5], BLACK) + ((255,) if clear else ()))
    for v in vias:
        x, y = sh.P(v[0], v[1])
        r = max(3.0, v[2] * sh.S / 2)
        h = max(1.2, min(v[3] * sh.S / 2, 0.6 * r))
        d.ellipse([x - r, y - r, x + r, y + r], fill=BLACK + ((255,) if clear else ()))
        d.ellipse([x - h, y - h, x + h, y + h], fill=PAPER + ((0,) if clear else ()))


def _saved(board, timeline):
    """(timeline, snapshot(i)): each state's whole board, from git by the state's name, else the board as it is"""
    import history
    tl = json.load(open(timeline))
    texts = {name: text for _, name, text in history.git_states(board)}
    now = open(board, encoding='utf-8').read()
    got = {}

    def snap(i):
        if i not in got:
            got[i] = _snap(texts.get(tl['states'][i]['name'], now))
        return got[i]
    return tl, snap


def _before(snap, i):
    """the copper already down when state i starts: the state before's, if it is drawn on the same origin"""
    if i > 0 and snap(i - 1)['org'] == snap(i)['org']:
        return list(snap(i - 1)['segs']), list(snap(i - 1)['vias'])
    return [], []


def ink(board, timeline, out, frames, width=4000, first=0, last=None, place_n=0, pour=0, hold=0, pen=1.0, lead=0, stack=1.0):
    """replay as line art. place_n frames: the parts of state `first` arrive in the order of place-ops.json beside
    the board (else the file's), each with its air wires. Then the states first..last, each net's old copper
    going and its new copper growing, air wires going as copper joins their pads. pour frames: the last state's
    pours hatched in, the air wires they join going with them. hold frames: the finished sheet. lead: the frames
    the first state gets (else every state its share by how much it adds). Writes NNNNN.png, final.png,
    starts.json and layers/ (base.png, B.Cu, F.Cu and parts on clear sheets, order.json); stack: how much heavier
    the pen on those sheets is, which the camera sees from further off."""
    import numpy as np
    from PIL import Image, ImageDraw
    tl, snap = _saved(board, timeline)
    sh = Sheet(tl['sheet'], width)
    states = tl['states']
    last = len(states) - 1 if last is None else last
    os.makedirs(os.path.join(out, 'layers'), exist_ok=True)
    f = 0
    info = dict(place=[0, place_n], aspect=sh.H / sh.W)

    def save(fr):
        nonlocal f
        fr.save(os.path.join(out, '%05d.png' % f), compress_level=1)
        f += 1
    s0 = snap(first)
    cur, vias = _before(snap, first)
    if place_n:                                   # placement: nothing routed yet
        ops = os.path.join(os.path.dirname(os.path.abspath(board)), 'place-ops.json')
        order = []
        if os.path.exists(ops):
            j = json.load(open(ops))
            order = [o['ref'] for o in (j.get('ops', []) if isinstance(j, dict) else j) if isinstance(o, dict) and o.get('ref') in s0['parts']]
        order = list(dict.fromkeys(order))
        there = [r for r in s0['parts'] if r not in order] if order else []    # what the placement file does not place (mounting holes) is there from the start
        order = order or list(s0['parts'])
        over = _parts(sh, s0, pen, refs=there)
        done = 0
        for k in range(place_n):
            m = round(len(order) * (k + 1) / place_n)
            _parts(sh, s0, pen, refs=order[done:m], im=over)
            done = m
            rats = _Rats(s0, set(there) | set(order[:m]))
            save(_compose(sh, pen, cur, [], vias, rats.update(cur, vias), over))
    run = list(range(first, last + 1))
    nroute = frames - place_n - pour - hold
    starts, names, landed = [], [], {}
    wires = []
    over = None
    if nroute > 0:
        def weight(i):
            e = states[i]
            n = len(e['added']) + len(e['vias_added'])
            return 1 + math.sqrt(n) if n else (2.0 if e['removed'] or e['vias_removed'] or e['moved'] else 0.5)
        wts = [weight(i) for i in run]
        if lead and len(run) > 1:                 # the first routing drawn at length, the later states sharing the rest
            lead = max(1, min(lead, nroute - (len(run) - 1)))
            nfs = [lead] + [max(1, round((nroute - lead) * w / sum(wts[1:]))) for w in wts[1:]]
            nfs[1 + nfs[1:].index(max(nfs[1:]))] += nroute - sum(nfs)
        else:
            nfs = [max(1, round(nroute * w / sum(wts))) for w in wts]
            nfs[nfs.index(max(nfs))] += nroute - sum(nfs)
        if min(nfs) < 1:
            raise SystemExit('too few frames for %d states' % len(run))
        for i, n in zip(run, nfs):
            starts.append(f)
            names.append(states[i]['name'])
            s = snap(i)
            over = _parts(sh, s, pen)
            now, vnow = set(s['segs']), set(s['vias'])
            was, vwas = set(cur), set(vias)
            plan, ends = _plan([x for x in s['segs'] if x not in was], [v for v in s['vias'] if v not in vwas],
                               [x for x in cur if x not in now], [v for v in vias if v not in vnow])
            if i == first:
                landed = {net: f + int(math.ceil(u * n)) - 1 for net, u in ends.items()}
            rats = _Rats(s)
            for k in range(n):
                down, grow, vdown = _at(plan, cur, vias, (k + 1) / n)
                wires = rats.update(down, vdown)
                save(_compose(sh, pen, down, grow, vdown, wires, over))
            cur, vias = list(s['segs']), list(s['vias'])
    s = snap(last)
    if over is None or nroute <= 0:
        over = _parts(sh, s, pen)
        if not place_n:
            cur, vias = list(s['segs']), list(s['vias'])
        wires = _Rats(s).update(cur, vias)
    hat = _hatch(sh, s, pen) if (pour or hold) and s['fills'] else {}
    info.update(states=starts, names=names, landed=landed, pour=f, air_before_pour=len(wires))
    if hat:
        byn = defaultdict(list)
        for L, net, pts in s['fills']:
            byn[net].append((L, np.array(pts, float)))
        left = set(_Rats(s).update(cur, vias, byn))                 # what even the pours leave unjoined stays drawn
        info.update(air_after_pour=len(left))
        c = _sweep(sh)
        cv = lambda p: (sh.P(*p)[0] + 0.4 * sh.P(*p)[1]) / (sh.W + 0.4 * sh.H)   # noqa: E731
        Ls = sorted(hat, key=lambda L: L != 'F.Cu')                # the front first, the back a quarter behind
        for k in range(pour):
            u = (k + 1) / pour
            fronts = [1.02 * min(1.0, u * (1.0 + 0.25 * j) / 1.0) if j == 0 else 1.02 * max(0.0, (u * 1.25 - 0.25)) for j in range(len(Ls))]
            masks = [(PENS.get(L, BLACK), Image.fromarray(((hat[L] & (c < fr_)) * np.uint8(255)))) for L, fr_ in zip(Ls, fronts)]
            back = min(fronts)
            ws = [w for w in wires if w in left or max(cv(w[0]), cv(w[1])) > back]
            save(_compose(sh, pen, cur, [], vias, ws, over, masks[::-1]))
        wires = [w for w in wires if w in left] if pour else wires
    full = [(PENS.get(L, BLACK), Image.fromarray(hat[L] * np.uint8(255))) for L in sorted(hat, key=lambda L: L == 'F.Cu')] if pour else []
    fin = _compose(sh, pen, cur, [], vias, wires, over, full)
    info.update(hold=f)
    for k in range(hold):
        save(fin)
    fin.save(os.path.join(out, 'final.png'), compress_level=1)
    order = []                                    # the pulled-apart stack: bare board, back copper, front copper with the pads, parts and names
    sp = pen * stack
    hs = _hatch(sh, s, sp) if hat and pour and stack != 1 else hat
    for L in ['B.Cu', 'F.Cu']:
        im = Image.new('RGBA', (sh.W, sh.H), PENS[L] + (0,))
        if L in hs and pour:
            im.paste(PENS[L] + (255,), mask=Image.fromarray(hs[L] * np.uint8(255)))
        _copper_ink(ImageDraw.Draw(im), sh, cur, [], vias, sp, only=L, clear=True)
        if L == 'F.Cu':
            im.alpha_composite(_parts(sh, s, pen, what=('pads', 'clear')))
        im.save(os.path.join(out, 'layers', '%s.png' % L), compress_level=1)
        order.append(L)
    _parts(sh, s, sp, what=('outline', 'names')).save(os.path.join(out, 'layers', 'parts.png'), compress_level=1)
    order.append('parts')
    b0 = Image.new('RGB', (sh.W, sh.H), PAPER)
    hl = _parts(sh, s, sp, what=('edge', 'holes'))
    b0.paste(hl, mask=hl)
    b0.save(os.path.join(out, 'layers', 'base.png'), compress_level=1)
    json.dump(order, open(os.path.join(out, 'layers', 'order.json'), 'w'))
    info.update(frames=f)
    json.dump(info, open(os.path.join(out, 'starts.json'), 'w'))
    return info


def inktrace(board, timeline, out, frames, event, net=None, width=4000, crop=None, pen=1.0, rev=False, land=0.88, lag=0.09):
    """trace as line art: state `event` at the moment net `net` is routed (default: its longest). The nets before
    it in the file are down, the ones after it still air wires; its trace grows end to end and lands at `land`
    of the shot, its air wire going as the copper joins its pads, and the next nets in the file set out one
    after another, `lag` apart, at the same pen speed. crop: draw only the net's surroundings, this many mm round
    it, so a close shot is sharp. Writes NNNNN.png, track.json (the head of the trace, for paper.py track=) and
    info.json (the net, its parts, its length)."""
    tl, snap = _saved(board, timeline)
    s = snap(event)
    cur, vias = _before(snap, event)
    now, vnow, was, vwas = set(s['segs']), set(s['vias']), set(cur), set(vias)
    add = [x for x in s['segs'] if x not in was]
    if not add:
        raise SystemExit('state %d adds no tracks' % event)
    runs = _runs(add)
    order = list(runs)
    net = net or max(runs, key=lambda n: runs[n][2])
    if net not in runs:
        raise SystemExit('state %d adds no track of net %s; it adds: %s' % (event, net, ' '.join(order)))
    ss, D, L, adj, a, b = runs[net]
    if rev:
        D.update(_dij(adj, b))
        a, b = b, a
    k0 = order.index(net)
    t0, dur = {n: -1.0 for n in order[:k0]}, {n: 0.5 for n in order}
    t0[net], dur[net] = 0.0, land
    for j, n in enumerate(order[k0 + 1:], 1):
        t0[n] = lag * j if lag * j < 1 else 2.0
        dur[n] = max(0.06, land * runs[n][2] / L)
    plan = _timed(runs, t0, dur, [v for v in s['vias'] if v not in vwas], [x for x in cur if x not in now], [v for v in vias if v not in vnow])
    sheet = tl['sheet']
    if crop:
        xs, ys = [v for x in ss for v in (x[0], x[2])], [v for x in ss for v in (x[1], x[3])]
        asp = sheet['h'] / sheet['w']
        w = max(max(xs) - min(xs) + 2 * crop, (max(ys) - min(ys) + 2 * crop) / asp)
        sheet = dict(x0=(max(xs) + min(xs)) / 2 - w / 2, y0=(max(ys) + min(ys)) / 2 - w * asp / 2, w=w, h=w * asp)
    sh = Sheet(sheet, width)
    os.makedirs(out, exist_ok=True)
    over = _parts(sh, s, pen)
    rats = _Rats(s)
    path = [b]
    while path[-1] != a:
        n = path[-1]
        path.append(min((m for m, ln in adj[n] if abs(D[m] + ln - D[n]) < 1e-6), key=lambda m: D[m]))
    path = path[::-1]

    def tip(dd):
        for p, q in zip(path, path[1:]):
            if D[q] >= dd:
                t = (dd - D[p]) / max(1e-9, D[q] - D[p])
                return (p[0] + (q[0] - p[0]) * t, p[1] + (q[1] - p[1]) * t)
        return path[-1]
    track, air = [], []
    for k in range(frames):
        u = (k + 1) / frames
        down, grow, vdown = _at(plan, cur, vias, u)
        wires = rats.update(down, vdown)
        air.append(len(rats.wires.get(net, [])))
        _compose(sh, pen, down, grow, vdown, wires, over).save(os.path.join(out, '%05d.png' % k), compress_level=1)
        track.append(sh.metres(*tip(L * min(1.0, u / land))))
    json.dump(track, open(os.path.join(out, 'track.json'), 'w'))
    ends = sorted({r for r, p in s['parts'].items() for pad in p['pads'] if pad['net'] == net})
    info = dict(net=net, parts=ends, length=round(L, 2), tracks=len(ss), air=air, sheet=sheet, nets_before=k0, nets_after=len(order) - k0 - 1)
    json.dump(info, open(os.path.join(out, 'info.json'), 'w'))
    return info


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('mode', choices=['replay', 'trace'])
    ap.add_argument('board')
    ap.add_argument('timeline')
    ap.add_argument('out')
    ap.add_argument('--frames', type=int, required=True)
    ap.add_argument('--width', type=int, default=4000)
    ap.add_argument('--from', dest='first', type=int, default=0)
    ap.add_argument('--to', dest='last', type=int)
    ap.add_argument('--hold', type=int, default=0)
    ap.add_argument('--event', type=int)
    ap.add_argument('--rev', action='store_true')
    ap.add_argument('--ink', type=int, default=0, help='1: line art with part names and air wires (see ink, inktrace)')
    ap.add_argument('--place', type=int, default=0, help='ink replay: frames of placement before the routing')
    ap.add_argument('--pour', type=int, default=0, help='ink replay: frames of pour hatching after the routing')
    ap.add_argument('--pen', type=float, default=1.0, help='ink: line weight')
    ap.add_argument('--lead', type=int, default=0, help='ink replay: frames the first state gets (else its share by size)')
    ap.add_argument('--stack', type=float, default=1.0, help='ink replay: the pen on the layer sheets, times --pen')
    ap.add_argument('--net', help='ink trace: the net to follow')
    ap.add_argument('--crop', type=float, help='ink trace: draw only this many mm round the net')
    o = ap.parse_args(argv)
    if o.ink and o.mode == 'replay':
        i = ink(o.board, o.timeline, o.out, o.frames, o.width, o.first, o.last, o.place, o.pour, o.hold, o.pen, o.lead, o.stack)
        print('ink: %d frames; states start %s; pour %s hold %s; air wires %s before the pour, %s after' % (
            i['frames'], i['states'], i['pour'], i['hold'], i.get('air_before_pour'), i.get('air_after_pour')))
    elif o.ink:
        i = inktrace(o.board, o.timeline, o.out, o.frames, o.event, o.net, o.width, o.crop, o.pen, o.rev)
        print('ink: %d frames; net %s between %s, %.1f mm in %d tracks; its air wires by frame %s' % (
            o.frames, i['net'], ' '.join(i['parts']), i['length'], i['tracks'], i['air']))
    elif o.mode == 'replay':
        print('state starts:', replay(o.board, o.timeline, o.out, o.frames, o.width, o.first, o.last, hold=o.hold))
    else:
        L, n = trace(o.board, o.timeline, o.out, o.frames, o.event, o.width, o.rev)
        print('%d frames; longest trace %.1f mm, %d traces' % (o.frames, L, n))


if __name__ == '__main__':
    main()
