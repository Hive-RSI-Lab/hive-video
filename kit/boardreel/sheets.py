"""Many schematic sheets on the table at once, each drawing itself in: the frames for shots/paper.py's tiles=.

    python3 sheets.py SPEC.json OUT --frames N [--bold B] [--fade F] [--jobs J]

SPEC.json: {"scale": metres on the table per metre of sheet (0.5), "px": tile pixels per sheet millimetre (3.364,
an A0 sheet 4000 across), "sheets": [{"sheet": FILE.kicad_sch, "plot": FULL.pdf, "bare": BARE.pdf, "page": N (else
the plot's page that names the file), "at": [x, y] the sheet's centre on the table in metres, "t": "a,b" the part
of its drawing the shot's frames span (below 0 the sheet is still empty, above 1 it is finished: "-0.4,1.6" starts
late and ends early), "order": as schematic.py's}]}. reel.py writes that file for a `sheets` drawing.

"one": true writes them all onto one big sheet instead: of each only what it draws (no page frame, no title block,
`pad` mm of paper around its ink, or its own "crop": [x0, y0, x1, y1] in sheet mm), set in rows ("row": 1, 2 ...
top to bottom, left to right as listed), every row as wide as the widest, `gap` mm between and `margin` mm of bare
paper around them all. "at" is not used.

"paper": [w, h] (mm) puts each on a sheet of its own instead, every sheet that size: of each only what it draws
(as "one"), scaled to fit its sheet inside `margin` mm of bare paper all round and centred, as a printer fits a
page to its paper. The sheets lie in rows of `cols` (4) in the order listed, top row first, `gap` mm apart, the
group's middle at 0, 0. A drawing scaled down a lot wants its own "bold" to read as dark as the rest. "at" is not
used. A sheet's own "px" overrides the spec's: more for one the camera comes close to, so it stays sharp there
(its "bold" is in its own pixels, so a sheet with more px needs more bold for the same line).

Writes OUT/p1 .. pN (one frame sequence a sheet, every one the same pixels per millimetre unless a sheet sets its
own "px"; for "paper" the whole sheet, `px` pixels per paper mm), OUT/layout.json (where
each lies and how big; for "one" {"sheet": the big sheet, "tiles": [...]}) and OUT/new.json (new ink a frame, all
sheets together, for the check).
"""
import argparse
import json
import os
import sys
from concurrent.futures import ProcessPoolExecutor

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import schematic  # noqa: E402


def ink_box(pdf, page, size, tmp, pad):
    """the box (sheet mm) around all a plot's page draws, with pad mm of paper, kept on the page"""
    a = schematic.plot_ink(pdf, page, (0.0, 0.0) + tuple(size), round(2 * size[0]), tmp)
    ys, xs = np.nonzero(a > 0.1)
    if not len(xs):
        return (0.0, 0.0) + tuple(size)
    k = size[0] / a.shape[1]
    return (max(0.0, xs.min() * k - pad), max(0.0, ys.min() * k - pad),
            min(size[0], (xs.max() + 1) * k + pad), min(size[1], (ys.max() + 1) * k + pad))


def one(job):
    s, out, frames, px, bold, fade, pad = job[:7]
    paper = job[7] if len(job) > 7 else None        # (w, h, margin) mm: a sheet of its own, the drawing fitted to it
    px = float(s.get('px', px))                     # a sheet's own pixels per mm, else the spec's
    doc = schematic.schem.parse(s['sheet'])
    t = tuple(float(v) for v in str(s.get('t', '0,1')).split(','))
    crop, plot, page = None, s.get('plot'), s.get('page')
    if pad is not None:                             # one big sheet: the drawing alone, from the plot without the page's frame
        page = page or schematic.plot_page(s['plot'], s['sheet'])
        plot = s['bare']
        crop = tuple(s['crop']) if s.get('crop') else ink_box(plot, page, doc['size'], os.path.join(out, '.box'), pad)
    size = (crop[2] - crop[0], crop[3] - crop[1]) if crop else tuple(doc['size'])
    width = max(64, round(px * size[0]))
    if paper:
        k = min((paper[0] - 2 * paper[2]) / size[0], (paper[1] - 2 * paper[2]) / size[1])
        width = round(px * k * size[0])
    m = schematic.render(s['sheet'], out, frames, crop, width, t, float(s.get('pow', 1.0)),
                         s.get('order'), fade, float(s.get('bold', bold)), doc=doc, plot=plot, bare=s.get('bare'), page=page)
    if paper:                                       # each frame centred on its sheet of white paper
        from PIL import Image
        pw, ph = round(px * paper[0]), round(px * paper[1])
        for f in range(frames):
            fn = os.path.join(out, '%05d.png' % f)
            im = Image.open(fn)
            sh = Image.new('RGB', (pw, ph), schematic.PAPER)
            sh.paste(im, ((pw - im.size[0]) // 2, (ph - im.size[1]) // 2))
            sh.save(fn, compress_level=1)
        size = tuple(paper[:2])
    return size, m


def rows(spec, sizes):
    """where each drawing lies on the one big sheet (mm, centre, y up, the sheet's middle at 0, 0), and the sheet's size"""
    gap, margin = float(spec.get('gap', 44)), float(spec.get('margin', 60))
    by = {}
    for i, s in enumerate(spec['sheets']):
        by.setdefault(int(s.get('row', 1)), []).append(i)
    order = [by[k] for k in sorted(by)]
    wide = max(sum(sizes[i][0] for i in r) + gap * (len(r) - 1) for r in order)
    tall = sum(max(sizes[i][1] for i in r) for r in order) + gap * (len(order) - 1)
    at, y = {}, tall / 2
    for r in order:
        rh = max(sizes[i][1] for i in r)
        free = wide - sum(sizes[i][0] for i in r)
        g = free / (len(r) - 1) if len(r) > 1 else 0.0
        x = -wide / 2 + (free / 2 if len(r) == 1 else 0.0)
        for i in r:
            at[i] = (x + sizes[i][0] / 2, y - rh / 2)
            x += sizes[i][0] + g
        y -= rh + gap
    return at, (wide + 2 * margin, tall + 2 * margin)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('spec')
    ap.add_argument('out')
    ap.add_argument('--frames', type=int, required=True)
    ap.add_argument('--bold', type=float, default=0.0)
    ap.add_argument('--fade', type=float, default=0.012)
    ap.add_argument('--jobs', type=int, default=4)
    o = ap.parse_args(argv)
    spec = json.load(open(o.spec))
    scale, px = float(spec.get('scale', 0.5)), float(spec.get('px', 4000 / 1189))
    paper = spec.get('paper')
    pad = float(spec.get('pad', 8)) if spec.get('one') or paper else None
    paper = (float(paper[0]), float(paper[1]), float(spec.get('margin', 14))) if paper else None
    jobs = [(s, os.path.join(o.out, 'p%d' % (i + 1)), o.frames, px, o.bold, o.fade, pad, paper) for i, s in enumerate(spec['sheets'])]
    with ProcessPoolExecutor(max(1, o.jobs)) as ex:
        done = list(ex.map(one, jobs))
    k = scale / 1000
    at, big = rows(spec, [size for size, _ in done]) if spec.get('one') else ({}, None)
    if paper:                                       # a grid of same-size sheets
        cols, gap = int(spec.get('cols', 4)), float(spec.get('gap', 16))
        n = len(done)
        nr = (n + cols - 1) // cols
        for i in range(n):
            r, c = divmod(i, cols)
            at[i] = ((c - (cols - 1) / 2) * (paper[0] + gap), ((nr - 1) / 2 - r) * (paper[1] + gap))
    lay, new = [], [0] * o.frames
    for i, (s, (size, m)) in enumerate(zip(spec['sheets'], done)):
        x, y = (at[i][0] * k, at[i][1] * k) if at else s.get('at', [0, 0])
        lay.append(dict(dir='p%d' % (i + 1), x=x, y=y, w=k * size[0], h=k * size[1], sheet=os.path.basename(s['sheet']),
                        crop=m['crop']))
        new = [a + b for a, b in zip(new, m['new'])]
    if big:
        lay = dict(sheet=dict(x=0.0, y=0.0, w=k * big[0], h=k * big[1]), tiles=lay)
    json.dump(lay, open(os.path.join(o.out, 'layout.json'), 'w'), indent=1)
    json.dump(dict(new=new, frames=o.frames, sheets=len(spec['sheets'])), open(os.path.join(o.out, 'new.json'), 'w'))
    print(len(spec['sheets']), 'sheets,', o.frames, 'frames; fewest new ink pixels on a frame:', min(new or [0]))


if __name__ == '__main__':
    main()
