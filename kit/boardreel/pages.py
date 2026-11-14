"""The research the design read, as paper: the first pages of each datasheet, shrunk for texture, with the vendor
logo corner blanked (a logo on screen reads as an advert). Frames for shots/pages.py.

    python3 pages.py OUT/ SOURCE ... [--pages 3] [--max 30]

A SOURCE is a PDF, a folder of PDFs or page PNGs, or a notes file (.md/.txt): every https link ending in .pdf
in it is fetched (to OUT/pdf/, once). Only what the design actually cited belongs here: point it at the
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

from PIL import Image, ImageDraw

W, H = 850, 1100
LOGOS = [(0, 0, 290, 105), (W - 290, 0, W, 105)]   # where vendors put their logo on a first page (TI: right)


def pdfs_of(src, out):
    if os.path.isdir(src):
        return sorted(glob.glob(os.path.join(src, '*.pdf'))) + sorted(glob.glob(os.path.join(src, '*.png')))
    if src.lower().endswith('.pdf') or src.lower().endswith('.png'):
        return [src]
    found = []
    cache = os.path.join(out, 'pdf')
    os.makedirs(cache, exist_ok=True)
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


def prep(out, sources, pages=3, cap=30):
    os.makedirs(out, exist_ok=True)
    index = []
    for src in sources:
        for f in pdfs_of(src, out):
            part = part_name(f)
            if f.lower().endswith('.png'):
                imgs = [f]
            else:
                tmp = os.path.join(out, 'pdf', part)
                subprocess.run(['pdftoppm', '-r', '100', '-png', '-f', '1', '-l', str(pages), f, tmp], check=True)
                imgs = sorted(glob.glob(tmp + '-*.png'))
            for k, p in enumerate(imgs[:pages]):
                im = Image.open(p).convert('RGB').resize((W, H), Image.LANCZOS)
                if k == 0:
                    for box in LOGOS:
                        ImageDraw.Draw(im).rectangle(box, fill='white')
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
    o = ap.parse_args(argv)
    idx = prep(o.out, o.sources, o.pages, o.max)
    print('pages: %d pages from %d parts -> %s' % (len(idx), len({e['part'] for e in idx}), o.out))
    if not idx:
        sys.exit(1)


if __name__ == '__main__':
    main()
