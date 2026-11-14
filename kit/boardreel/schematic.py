"""A KiCad schematic drawn in, stroke by stroke, as a numbered image sequence for a paper shot.

    python3 schematic.py SHEET.kicad_sch OUT/ --frames 60 [--crop X0,Y0,X1,Y1] [--width 4000] [--t A,B] [--pow P]
                         [--order in:FX,FY | out:FX,FY | sweep:FX0,FY0:FX1,FY1] [--fade F] [--bold N]

Drawn from the file itself (schem.py), so it needs no KiCad. Each part is wiped in left to right, then the wires it
starts grow along their real path. The newest ink is amber and settles to ink.

  --crop     the part of the sheet to draw, in sheet millimetres (y down). A big sheet (A2 and up) is too small to
             read whole, so draw it as close-ups. Only the parts and wires that touch the crop are timed, so the
             crop is drawing on every frame.
  --t A,B    this shot draws from A to B of its own drawing (0..1): a shot can open on a half-drawn sheet.
  --pow P    the drawing gathers speed (P > 1) or brakes (P < 1).
  --order    where drawing starts, in fractions of the crop (0,0 top left): closing in on a point, spreading out
             from it, or sweeping along a line. Default: KiCad's order, read across the sheet.

Writes OUT/00000.png ... (one a frame; a paper shot holds the last one) and OUT/new.json: {ink, new[], aspect,
crop}. new[f] is how many ink pixels appear on frame f. `checks.py` fails a shot where any frame from the first to
the last adds none: every schematic cut must show drawing in progress, start to end (the first film's lesson).
"""
import argparse
import json
import math
import os
import sys

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import INK, AMBER, PAPER, font  # noqa: E402
import schem  # noqa: E402

Image.MAX_IMAGE_PIXELS = None
SS = 2                      # supersampling: draw at 2x, box down for smooth lines
WIDTH = {'wire': 0.30, 'body': 0.25, 'pin': 0.18, 'dot': 0.30}   # mm
T0, T1 = 0.0, 0.98         # the share of the drawing given over to strokes


def _bbox(pts):
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    return min(xs), min(ys), max(xs), max(ys)


def plan(doc, crop=None, order=None):
    """time every stroke and text in the crop: [(kind, item, t_start, t_end, prog)] where prog maps a point to 0..1
    within its group. Returns (items, groups_used)."""
    by = {}
    for s in doc['strokes']:
        by.setdefault(s['group'], {'s': [], 't': []})['s'].append(s)
    for t in doc['texts']:
        by.setdefault(t['group'], {'s': [], 't': []})['t'].append(t)
    G = {g['id']: g for g in doc['groups']}
    x0, y0, x1, y1 = crop or (0, 0) + tuple(doc['size'])
    m = 2.0

    def inside(p):
        return x0 - m <= p[0] <= x1 + m and y0 - m <= p[1] <= y1 + m

    used = []
    for gid, b in by.items():
        pts = [p for s in b['s'] for p in s['pts']] + [(t['x'], t['y']) for t in b['t']]
        if pts and any(inside(p) for p in pts):
            used.append((gid, _bbox(pts)))
    rank = {int(k): v for k, v in doc.get('order', {}).items()}
    used.sort(key=lambda g: rank.get(g[0], 0))
    if order:
        kind, *pt = order.split(':')
        W, H = x1 - x0, y1 - y0

        def at(s):
            fx, fy = map(float, s.split(','))
            return x0 + fx * W, y0 + fy * H

        def centre(g):
            bx = g[1]
            return (bx[0] + bx[2]) / 2, (bx[1] + bx[3]) / 2
        a = at(pt[0])
        if kind == 'sweep':
            b = at(pt[1])
            used.sort(key=lambda g: (centre(g)[0] - a[0]) * (b[0] - a[0]) + (centre(g)[1] - a[1]) * (b[1] - a[1]))
        else:
            used.sort(key=lambda g: math.hypot(centre(g)[0] - a[0], centre(g)[1] - a[1]), reverse=(kind == 'in'))
        # a net goes straight after the first part it touches, as a person draws: re-thread nets behind symbols
        syms = [g for g in used if G.get(g[0], {}).get('kind') != 'net']
        nets = [g for g in used if G.get(g[0], {}).get('kind') == 'net']
        if syms and nets:
            out, left = [], list(nets)
            for s in syms:
                out.append(s)
                bx = s[1]
                near = [n for n in left if n[1][0] <= bx[2] + 1 and n[1][2] >= bx[0] - 1 and n[1][1] <= bx[3] + 1 and n[1][3] >= bx[1] - 1]
                for n in near:
                    out.append(n)
                    left.remove(n)
            used = out + left

    def weight(g):
        kind = G.get(g[0], {}).get('kind', 'net')
        bx = g[1]
        if kind == 'net':
            return 1.0
        return 2.0 + 0.25 * ((bx[2] - bx[0]) + (bx[3] - bx[1])) / 2
    tot = sum(weight(g) for g in used) or 1.0
    acc, items = T0, []
    for g in used:
        dur = (T1 - T0) * weight(g) / tot
        gid, bx = g
        b = by[gid]
        if G.get(gid, {}).get('kind') == 'net':      # wires grow along their length, one after another
            L = [sum(math.dist(a, c) for a, c in zip(s['pts'], s['pts'][1:])) for s in b['s']]
            tl, run = sum(L) or 1.0, 0.0
            for s, l in zip(b['s'], L):
                items.append(('line', s, acc + dur * run / tl, acc + dur * (run + l) / tl))
                run += l
            for t in b['t']:
                items.append(('text', t, acc + dur * 0.9, acc + dur))
        else:                                           # a part is wiped in left to right
            wx = max(1e-3, bx[2] - bx[0])
            for s in b['s']:
                sx = _bbox(s['pts'])
                items.append(('wipe', s, acc + dur * (sx[0] - bx[0]) / wx, acc + dur * (sx[2] - bx[0]) / wx))
            for t in b['t']:
                u = min(1, max(0, (t['x'] - bx[0]) / wx))
                items.append(('text', t, acc + dur * u, acc + dur * u))
        acc += dur
    return items, [g[0] for g in used]


def raster(doc, items, crop, width, bold=0):
    """ink alpha (0..1) and the time each ink pixel appears, at WIDTH px across the crop"""
    x0, y0, x1, y1 = crop
    ppm = width / (x1 - x0)
    W, H = width * SS, round(width * (y1 - y0) / (x1 - x0)) * SS
    k = ppm * SS
    BIG = 2 ** 30
    ink = Image.new('L', (W, H), 0)
    tim = Image.new('I', (W, H), BIG)
    di, dt = ImageDraw.Draw(ink), ImageDraw.Draw(tim)

    def P(p):
        return ((p[0] - x0) * k, (p[1] - y0) * k)
    pieces = []          # (t, kind, payload)
    for kind, it, ta, tb in items:
        if kind == 'text':
            pieces.append((ta, 'text', it))
            continue
        pts = it['pts']
        w = max(2, round((WIDTH.get(it['kind'], 0.25) * ppm + bold) * SS))
        L = [math.dist(a, c) for a, c in zip(pts, pts[1:])]
        tl, run = sum(L) or 1e-6, 0.0
        if kind == 'wipe':                          # time by x across the stroke
            sx = _bbox(pts)
            span = max(1e-6, sx[2] - sx[0])
        for a, c, l in zip(pts, pts[1:], L):
            n = max(1, int(l / 0.4))
            for j in range(n):
                p = [a[i] + (c[i] - a[i]) * j / n for i in (0, 1)]
                q = [a[i] + (c[i] - a[i]) * (j + 1) / n for i in (0, 1)]
                if kind == 'wipe':
                    u = ((p[0] + q[0]) / 2 - sx[0]) / span if span > 1e-5 else (run + l * j / n) / tl
                else:
                    u = (run + l * (j + 0.5) / n) / tl
                pieces.append((ta + (tb - ta) * min(1, max(0, u)), 'seg', (P(p), P(q), w, it['kind'] == 'dot')))
            run += l
    pieces.sort(key=lambda p: -p[0])               # latest first, so the earliest time wins a shared pixel
    for t, kind, pay in pieces:
        v = int(t * 1e6)
        if kind == 'seg':
            a, b, w, dot = pay
            di.line([a, b], fill=255, width=w, joint='curve')
            dt.line([a, b], fill=v, width=w)
            for e in (a, b):                       # round caps keep corners closed
                r = w / 2
                di.ellipse([e[0] - r, e[1] - r, e[0] + r, e[1] + r], fill=255)
                dt.ellipse([e[0] - r, e[1] - r, e[0] + r, e[1] + r], fill=v)
        else:
            s = pay['s']
            if not s.strip() or s.startswith('#'):
                continue
            px = max(8, int(pay.get('size', 1.27) * k * 1.25))
            f = font('mono', px)
            bb = f.getbbox(s)
            tw, th = bb[2] - bb[0] + 4, bb[3] - bb[1] + 4
            m = Image.new('L', (tw, th), 0)
            ImageDraw.Draw(m).text((2 - bb[0], 2 - bb[1]), s, font=f, fill=255)
            if pay.get('rot', 0) % 180 == 90:
                m = m.rotate(90, expand=True)
            cx, cy = P((pay['x'], pay['y']))
            rot, lift = pay.get('rot', 0) % 360, 0.4 * k
            if pay.get('kind') == 'label':       # a net label sits on its wire, text above it, from the anchor out
                if rot == 0:
                    at = (int(cx), int(cy - m.size[1] - lift))
                elif rot == 180:
                    at = (int(cx - m.size[0]), int(cy - m.size[1] - lift))
                elif rot == 90:
                    at = (int(cx - m.size[0] - lift), int(cy - m.size[1]))
                else:
                    at = (int(cx - m.size[0] - lift), int(cy))
            else:
                at = (int(cx - m.size[0] / 2), int(cy - m.size[1] / 2))
            ink.paste(255, at, m)
            tim.paste(v, at, m.point(lambda a: 255 if a > 0 else 0))
    a = np.asarray(ink.resize((W // SS, H // SS), Image.BOX), dtype=np.float32) / 255.0
    T = np.asarray(tim, dtype=np.int64).reshape(H // SS, SS, W // SS, SS).min(axis=(1, 3)).astype(np.float64) / 1e6
    a = np.clip(a * 1.15, 0, 1) ** 0.8              # a touch heavier, so thin lines hold up under a low camera
    return a, T


def render(sheet, out, frames, crop=None, width=4000, t=(0.0, 1.0), pw=1.0, order=None, fade=0.012, bold=0.0, doc=None):
    doc = doc or schem.parse(sheet)
    crop = tuple(crop) if crop else (0.0, 0.0) + tuple(doc['size'])
    items, used = plan(doc, crop, order)
    a, T = raster(doc, items, crop, width, bold)
    os.makedirs(out, exist_ok=True)
    ys, xs = np.nonzero(a > 0.02)
    av, tv = a[ys, xs], T[ys, xs]
    tv[tv > 1.5] = 0.0                              # ink no stroke owns (none, normally) is there from the start
    own = tv > 0
    if own.any():                                   # time runs over this crop's own strokes, so its last frame still draws
        lo, hi = tv[own].min(), tv[own].max()
        tv[own] = (tv[own] - lo) / max(1e-9, hi - lo) * (1 - 1e-6) + 1e-6
    tl = np.sort(tv)
    ink, amb, wh = (np.array(c, np.float32) for c in (INK, AMBER, PAPER))
    base = np.full(a.shape + (3,), 255, np.uint8)
    new, tp = [], -1.0
    TA, TB = t
    for f in range(frames):
        u = (f + 1) / frames                        # the first frame already has its first strokes: no blank paper
        tt = TA + (TB - TA) * u ** pw
        new.append(int(np.searchsorted(tl, tt, 'right') - np.searchsorted(tl, tp, 'right')))
        tp = tt
        vis = tv <= tt
        hot = np.clip(1 - (tt - tv) / fade, 0, 1) * vis
        al = np.clip(av * vis * (1 + 0.6 * hot), 0, 1)[:, None]
        col = ink + (amb - ink) * hot[:, None]
        fr = base.copy()
        fr[ys, xs] = (wh * (1 - al) + col * al).astype(np.uint8)
        Image.fromarray(fr).save(os.path.join(out, '%05d.png' % f), compress_level=1)
    meta = dict(ink=int(len(tl)), new=new, aspect=a.shape[0] / a.shape[1], crop=list(crop), groups=len(used), frames=frames)
    json.dump(meta, open(os.path.join(out, 'new.json'), 'w'))
    return meta


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('sheet')
    ap.add_argument('out')
    ap.add_argument('--frames', type=int, required=True)
    ap.add_argument('--crop')
    ap.add_argument('--width', type=int, default=4000)
    ap.add_argument('--t', default='0,1')
    ap.add_argument('--pow', type=float, default=1.0)
    ap.add_argument('--order')
    ap.add_argument('--fade', type=float, default=0.012)
    ap.add_argument('--bold', type=float, default=0.0)
    o = ap.parse_args(argv)
    m = render(o.sheet, o.out, o.frames, [float(v) for v in o.crop.split(',')] if o.crop else None, o.width,
               tuple(float(v) for v in o.t.split(',')), o.pow, o.order, o.fade, o.bold)
    print(o.frames, 'frames,', m['groups'], 'groups; fewest new ink pixels on a frame:', min(m['new'] or [0]))


if __name__ == '__main__':
    main()
