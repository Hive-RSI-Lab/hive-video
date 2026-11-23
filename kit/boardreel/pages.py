"""The research the design read, as paper: the first pages of each datasheet, each fitted on a sheet as a printer
fits it (whole, centred, never stretched), with the vendor logo taken off the front page (a logo on screen reads as
an advert). Frames for shots/pages.py.

    python3 pages.py OUT/ SOURCE ... [--pages 3] [--max 30] [--cache DIR]

A SOURCE is a PDF, a folder of PDFs or page PNGs, or a notes file (.md/.txt): every https link ending in .pdf
in it is fetched, once, into DIR (default OUT/pdf/; reel.py keeps it beside OUT, so a changed rule here re-makes
the pages without fetching anything again). Only what the design actually cited belongs here: point it at the
project's datasheet notes, not at a search.
Writes OUT/<part>-p<N>.jpg at 850x1100 and OUT/index.json {pages: [{file, part}], parts}.
"""
import argparse
import glob
import json
import os
import re
import subprocess
import sys

import numpy as np
from PIL import Image

W, H = 850, 1100
LOGOS = [(0, 0, 290, 105), (W - 290, 0, W, 105)]   # where vendors put their logo on a first page (TI: right)
BAND = 165                                          # the top of a first page: logos and shop buttons sit in it


def marks(ink, rx=8, ry=2):
    """the groups of ink that belong together (the letters of a line, a logo with its lettering): ink less than
    2*rx apart sideways, 2*ry up and down, is one mark. A label for every pixel (0: none) and the number of marks."""
    fat = ink.copy()
    for d in range(1, rx + 1):
        fat[:, d:] |= ink[:, :-d]
        fat[:, :-d] |= ink[:, d:]
    wide = fat.copy()
    for d in range(1, ry + 1):
        fat[d:] |= wide[:-d]
        fat[:-d] |= wide[d:]
    h, w = fat.shape
    lab = np.zeros((h, w), np.int32)
    n = 0
    for y0, x0 in zip(*np.nonzero(fat)):
        if lab[y0, x0]:
            continue
        n += 1
        lab[y0, x0] = n
        todo = [(y0, x0)]
        while todo:
            y, x = todo.pop()
            for yy, xx in ((y - 1, x), (y + 1, x), (y, x - 1), (y, x + 1)):
                if 0 <= yy < h and 0 <= xx < w and fat[yy, xx] and not lab[yy, xx]:
                    lab[yy, xx] = n
                    todo.append((yy, xx))
    return lab, n


def clear_header(im, front=True):
    """white out what reads as an advert at the top of a page: whole marks, never half of one (fixed boxes cut a
    title's ascenders off and left half a part number).
    On a front page a mark goes if most of its ink lies in a logo corner, or if it is small and has colour in it on
    a page that is otherwise black and white (a logo outside the corners, a shop button); else it stays whole. A mark
    too big to be a logo or a line (a banner, a drawing) is only cut at the corners.
    On a later page only a small mark with colour in a corner goes (the logo in the running header): the text may
    begin right under it there, and a line of that is not a logo."""
    a = np.asarray(im.convert('RGB')).copy()
    top = a[:BAND].astype(np.int16)
    sat = top.max(2) - top.min(2)
    plain = ((a.max(2).astype(np.int16) - a.min(2)) > 60).mean() < 0.004
    ink = (top.min(2) < 225) | (sat > 25)
    lab, n = marks(ink)
    corner = np.zeros(ink.shape, bool)
    for x0, y0, x1, y1 in LOGOS:
        corner[y0:y1 + 1, x0:x1 + 1] = True
    gone = corner.copy() if front else np.zeros(ink.shape, bool)
    small = LOGOS[0][2] - LOGOS[0][0]
    for k in range(1, n + 1):
        m = lab == k
        ys, xs = np.nonzero(m.any(1))[0], np.nonzero(m.any(0))[0]
        if ys[-1] >= BAND - 1 or ys[-1] - ys[0] >= 90:
            continue
        mine = m & ink
        cornered = (mine & corner).sum() > 0.5 * mine.sum()
        logo = (sat[m] > 60).sum() >= 12 and xs[-1] - xs[0] <= small
        if (cornered or (plain and logo)) if front else (cornered and logo):
            gone |= m
        else:
            gone &= ~m
    a[:BAND][gone] = 255
    return Image.fromarray(a)


def fit(im):
    """the page on the sheet: whole, centred, in its own proportions. An A4 page on this sheet loses a little width
    and a drawing in landscape lies across the middle (stretched to the sheet it was half as wide as drawn)."""
    k = min(W / im.width, H / im.height)
    w, h = max(1, round(im.width * k)), max(1, round(im.height * k))
    sheet = Image.new('RGB', (W, H), (255, 255, 255))
    sheet.paste(im.resize((w, h), Image.LANCZOS), ((W - w) // 2, (H - h) // 2))
    return sheet


def pdfs_of(src, cache):
    if os.path.isdir(src):
        return sorted(glob.glob(os.path.join(src, '*.pdf'))) + sorted(glob.glob(os.path.join(src, '*.png')))
    if src.lower().endswith('.pdf') or src.lower().endswith('.png'):
        return [src]
    found = []
    for url in dict.fromkeys(re.findall(r'https?://[^\s|)>\]]+?\.pdf', open(src, errors='replace').read())):
        dst = os.path.join(cache, os.path.basename(url))
        if not os.path.exists(dst):
            r = subprocess.run(['curl', '-sfL', '--max-time', '60', '-A', 'Mozilla/5.0', '-o', dst + '.part', url])
            ok = r.returncode == 0 and os.path.exists(dst + '.part') and open(dst + '.part', 'rb').read(5) == b'%PDF-'
            if not ok:
                print('pages: could not fetch %s; skipped' % url, file=sys.stderr)
                if os.path.exists(dst + '.part'):
                    os.remove(dst + '.part')
                continue
            os.rename(dst + '.part', dst)
        found.append(dst)
    return found


def part_name(path):
    n = os.path.splitext(os.path.basename(path))[0]
    return re.sub(r'(_datasheet|-datasheet|_ds)$', '', n, flags=re.I)


def prep(out, sources, pages=3, cap=30, cache=None):
    cache = cache or os.path.join(out, 'pdf')
    os.makedirs(out, exist_ok=True)
    os.makedirs(cache, exist_ok=True)      # also for a folder of PDFs as source: their page images are made here
    index = []
    for src in sources:
        for f in pdfs_of(src, cache):
            part = part_name(f)
            if f.lower().endswith('.png'):
                imgs = [f]
            else:
                tmp = os.path.join(cache, part)
                subprocess.run(['pdftoppm', '-r', '100', '-png', '-f', '1', '-l', str(pages), f, tmp], check=True)
                imgs = sorted(glob.glob(tmp + '-*.png'))
            for k, p in enumerate(imgs[:pages]):
                im = fit(Image.open(p).convert('RGB'))
                im = clear_header(im, front=k == 0)
                name = '%s-p%d.jpg' % (part, k + 1)
                im.save(os.path.join(out, name), quality=86)
                index.append(dict(file=name, part=part))
                if p != f:
                    os.remove(p)
    # spread the cap over the parts: first pages of everyone before second pages of anyone
    index.sort(key=lambda e: (int(e['file'].rsplit('-p', 1)[1][:-4]), e['part']))
    index = index[:cap]
    json.dump(dict(pages=index, parts=len({e['part'] for e in index})), open(os.path.join(out, 'index.json'), 'w'), indent=1)
    return index


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('out')
    ap.add_argument('sources', nargs='+')
    ap.add_argument('--pages', type=int, default=3)
    ap.add_argument('--max', type=int, default=30)
    ap.add_argument('--cache', help='where fetched PDFs are kept (default OUT/pdf)')
    o = ap.parse_args(argv)
    idx = prep(o.out, o.sources, o.pages, o.max, o.cache)
    print('pages: %d pages from %d parts -> %s' % (len(idx), len({e['part'] for e in idx}), o.out))
    if not idx:
        sys.exit(1)


if __name__ == '__main__':
    main()
