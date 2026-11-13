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
from common import INK, AMBER, PAPER, LIGHT, layer_colour, layer_head, layer_order  # noqa: E402
import kicad  # noqa: E402
from kicad import sexpr, kids, nums, layer_of, layers_of, place, arc_points  # noqa: E402

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
    o = ap.parse_args(argv)
    if o.mode == 'replay':
        print('state starts:', replay(o.board, o.timeline, o.out, o.frames, o.width, o.first, o.last, hold=o.hold))
    else:
        L, n = trace(o.board, o.timeline, o.out, o.frames, o.event, o.width, o.rev)
        print('%d frames; longest trace %.1f mm, %d traces' % (o.frames, L, n))


if __name__ == '__main__':
    main()
