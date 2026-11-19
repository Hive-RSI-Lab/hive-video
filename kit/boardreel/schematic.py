"""A KiCad schematic drawn in, stroke by stroke, as a numbered image sequence for a paper shot.

    python3 schematic.py SHEET.kicad_sch OUT/ --frames 60 [--crop X0,Y0,X1,Y1] [--width 4000] [--t A,B] [--pow P]
                         [--order in:FX,FY | out:FX,FY | sweep:FX0,FY0:FX1,FY1] [--fade F] [--bold N]
                         [--plot FULL.pdf [--bare BARE.pdf] [--page N]]

Drawn from the file itself (schem.py), so it needs no KiCad. Each part is wiped in left to right, then the wires it
starts grow along their real path. The newest ink is amber and settles to ink.

  --plot     the ink is KiCad's own plot of the sheet (`kicad-cli sch export pdf --black-and-white`; needs pdftoppm):
             its lettering, pin numbers, values, frame and title block, as the designer sees them. The order and
             the timing stay this tool's: every plotted pixel appears with the stroke nearest to it. --bare is the
             same plot made with --exclude-drawing-sheet: what is in FULL and not in BARE (the frame, its zone
             marks, the title block) is on the paper from the first frame, as on a printed drawing sheet. Without
             --bare, ink further than 14 mm from every stroke is. --page: the sheet's page in a root's plot
             (default: the page whose title block names the file). --bold N then thickens the plot's lines by N
             pixels: a whole A0 sheet seen from far needs it, a close-up does not.

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
import re
import shutil
import subprocess
import sys

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFilter

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


def plot_page(pdf, sheet):
    """the page of a KiCad plot that is this sheet: the one whose title block names the file (a root's plot has a
    page for every sheet under it, and the root's own page names them all: the title block's is the last)"""
    n = int(re.search(r'Pages:\s+(\d+)', subprocess.run(['pdfinfo', pdf], capture_output=True, text=True, check=True).stdout).group(1))
    want = os.path.basename(sheet)
    for p in range(1, n + 1) if n > 1 else ():
        txt = subprocess.run(['pdftotext', '-f', str(p), '-l', str(p), '-layout', pdf, '-'], capture_output=True, text=True).stdout
        names = re.findall(r'File:\s*(\S+)', txt)
        if names and names[-1] == want:
            return p
    if n == 1:
        return 1
    raise SystemExit('schematic: no page of %s is %s' % (pdf, want))


def plot_ink(pdf, page, crop, width, tmp, bold=0.0):
    """ink alpha (0..1) of a plot's page, WIDTH px across the crop (sheet millimetres)"""
    x0, y0, x1, y1 = crop
    W, H = width * SS, round(width * (y1 - y0) / (x1 - x0)) * SS
    dpi = W * 25.4 / (x1 - x0)
    os.makedirs(tmp, exist_ok=True)
    try:
        subprocess.run(['pdftoppm', '-r', '%.5f' % dpi, '-x', str(round(x0 / 25.4 * dpi)), '-y', str(round(y0 / 25.4 * dpi)),
                        '-W', str(W), '-H', str(H), '-gray', '-png', '-singlefile', '-f', str(page), '-l', str(page),
                        pdf, os.path.join(tmp, 'p')], check=True)
        im = Image.open(os.path.join(tmp, 'p.png')).convert('L')
        im.load()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    if im.size != (W, H):                           # a crop that runs past the page: the rest is paper
        full = Image.new('L', (W, H), 255)
        full.paste(im, (0, 0))
        im = full
    im = ImageChops.invert(im)
    if bold >= 0.5:
        im = im.filter(ImageFilter.MaxFilter(2 * round(bold) + 1))
    return np.asarray(im.resize((W // SS, H // SS), Image.BOX), dtype=np.float32) / 255.0


def nearest(seed):
    """for every cell the row and column of the nearest True cell of `seed`, and how far it is in cells (jump
    flooding: each cell asks neighbours at halving distances which seed they know)"""
    H, W = seed.shape
    yy, xx = (v.astype(np.int32) for v in np.mgrid[0:H, 0:W])
    far = 2 ** 60
    sy, sx = np.where(seed, yy, -1), np.where(seed, xx, -1)
    d = np.where(seed, 0, far).astype(np.int64)
    step, steps = 1 << max(0, (max(H, W) - 1).bit_length() - 1), []
    while step >= 1:
        steps.append(step)
        step //= 2
    for step in steps + [1]:                        # a second pass at 1 mends the few cells the method misses
        for dy in (-step, 0, step):
            for dx in (-step, 0, step):
                a, b, c, e = max(0, -dy), H - max(0, dy), max(0, -dx), W - max(0, dx)
                if not (dy or dx) or a >= b or c >= e:
                    continue
                ny, nx = sy[a + dy:b + dy, c + dx:e + dx], sx[a + dy:b + dy, c + dx:e + dx]
                nd = (ny - yy[a:b, c:e]).astype(np.int64) ** 2 + (nx - xx[a:b, c:e]).astype(np.int64) ** 2
                nd[ny < 0] = far
                m = nd < d[a:b, c:e]
                d[a:b, c:e][m] = nd[m]
                ky, kx = ny[m], nx[m]
                sy[a:b, c:e][m] = ky
                sx[a:b, c:e][m] = kx
    return sy, sx, np.sqrt(d.astype(np.float64))


def runs(m, n, axis):
    """the cells of a mask that lie in a straight run of at least n cells along the axis"""
    view = np.lib.stride_tricks.sliding_window_view
    e = view(m, n, axis=axis).all(axis=-1)          # a run of n starts here
    pad = [(0, 0), (0, 0)]
    pad[axis] = (n - 1, n - 1)
    return view(np.pad(e, pad), n, axis=axis).any(axis=-1)


def spread(m, n, axis):
    """a mask grown by n cells both ways along the axis"""
    pad = [(0, 0), (0, 0)]
    pad[axis] = (n, n)
    return np.lib.stride_tricks.sliding_window_view(np.pad(m, pad), 2 * n + 1, axis=axis).any(axis=-1)


def plotted(doc, items, crop, width, out, plot, bare=None, page=None, bold=0.0):
    """the plot's ink, timed by this tool's strokes: (alpha, the time each pixel appears; 0 = on the paper already)"""
    x0, y0, x1, y1 = crop
    a = plot_ink(plot, page, crop, width, os.path.join(out, '.plot'), bold)
    wq = min(width, 1000)                           # the strokes at a coarser grain: enough to say when, and quick
    _, tq = raster(doc, items, crop, wq)
    T = np.zeros(a.shape, np.float64)
    seed = tq < 1.5
    if not seed.any():
        return a, T
    sy, sx, dist = nearest(seed)

    def grid(n, m):                                 # for each of n cells in a row, the one of m it lies in
        return np.minimum(m - 1, np.arange(n) * m // n)
    cy, cx = grid(a.shape[0], tq.shape[0])[:, None], grid(a.shape[1], tq.shape[1])[None, :]
    T = tq[sy[cy, cx], sx[cy, cx]]
    ab = plot_ink(bare, page, crop, width, os.path.join(out, '.plot'), bold) if bare else a
    # Lettering appears a word at a time. A label lies between strokes, and letter by letter its nearest one differs,
    # so it would come in pieces. What is not a straight run of 2 mm or more is lettering (and dots, arrow heads,
    # crosses): its letters are joined to their neighbours, and each such word takes the earliest time in it.
    ww = min(width, round(6.0 * (x1 - x0)))
    hh = max(1, round(ww * a.shape[0] / a.shape[1]))
    ppm = ww / (x1 - x0)
    m = np.asarray(Image.fromarray((ab * 255).astype(np.uint8)).resize((ww, hh), Image.BOX)) > 20
    n = max(3, round(2.0 * ppm))
    lines = runs(m, n, 0) | runs(m, n, 1) if min(hh, ww) > n else np.zeros_like(m)
    small = m & ~lines
    # joined along the line of writing as far as an underscore is wide (one that touches its wire counts as line),
    # and across a line the word lies over; the lines themselves keep their own times
    rl, rs = max(1, round(0.7 * ppm)), max(1, round(0.2 * ppm))
    word = spread(spread(small, rl, 1), rs, 0) | spread(spread(small, rs, 1), rl, 0)
    far = 1e9
    wy, wx = grid(hh, tq.shape[0])[:, None], grid(ww, tq.shape[1])[None, :]
    tw = np.where(small, tq[sy[wy, wx], sx[wy, wx]], far)
    for _ in range(max(2, round(30.0 * ppm))):
        pad = np.pad(tw, 1, constant_values=far)
        nt = tw.copy()
        for dy in (0, 1, 2):
            for dx in (0, 1, 2):
                np.minimum(nt, pad[dy:dy + hh, dx:dx + ww], out=nt)
        nt[~word] = far
        if np.array_equal(nt, tw):
            break
        tw = nt
    tw[lines] = far
    ts = tw[grid(a.shape[0], hh)[:, None], grid(a.shape[1], ww)[None, :]]
    T = np.where(ts < far, ts, T)
    if bare:                                        # the drawing sheet itself: frame, zone marks, title block
        T[a - ab > 0.2] = 0.0
    else:
        T[dist[cy, cx] > 14.0 * wq / (x1 - x0)] = 0.0
    return a, T


def squeeze(tv, bins=4000):
    """the drawing's time with the stretches cut out in which no ink appears (strokes outside the crop, text KiCad's
    plot hides), so that the pen never stands still for a frame"""
    h, edge = np.histogram(tv, bins=bins, range=(0.0, 1.0))
    w = np.concatenate([[0.0], np.cumsum(h > 0)])
    return np.clip(np.interp(tv, edge, w / max(1.0, w[-1])), 1e-6, 1.0)


def render(sheet, out, frames, crop=None, width=4000, t=(0.0, 1.0), pw=1.0, order=None, fade=0.012, bold=0.0, doc=None,
           plot=None, bare=None, page=None):
    doc = doc or schem.parse(sheet)
    crop = tuple(crop) if crop else (0.0, 0.0) + tuple(doc['size'])
    items, used = plan(doc, crop, order)
    os.makedirs(out, exist_ok=True)
    if plot:
        a, T = plotted(doc, items, crop, width, out, plot, bare, page or plot_page(plot, sheet), bold)
    else:
        a, T = raster(doc, items, crop, width, bold)
    ys, xs = np.nonzero(a > 0.02)
    av, tv = a[ys, xs], T[ys, xs]
    tv[tv > 1.5] = 0.0                              # ink no stroke owns (none, normally) is there from the start
    own = tv > 0
    if own.any():                                   # time runs over this crop's own strokes, so its last frame still draws
        lo, hi = tv[own].min(), tv[own].max()
        tv[own] = (tv[own] - lo) / max(1e-9, hi - lo) * (1 - 1e-6) + 1e-6
        tv[own] = squeeze(tv[own])
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
    ap.add_argument('--plot')
    ap.add_argument('--bare')
    ap.add_argument('--page', type=int)
    o = ap.parse_args(argv)
    m = render(o.sheet, o.out, o.frames, [float(v) for v in o.crop.split(',')] if o.crop else None, o.width,
               tuple(float(v) for v in o.t.split(',')), o.pow, o.order, o.fade, o.bold, plot=o.plot, bare=o.bare, page=o.page)
    print(o.frames, 'frames,', m['groups'], 'groups; fewest new ink pixels on a frame:', min(m['new'] or [0]))


if __name__ == '__main__':
    main()
