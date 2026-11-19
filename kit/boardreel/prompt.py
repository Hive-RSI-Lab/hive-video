"""The request, typed: the person's real prompt drawn in ink on a sheet, the newest ink amber, the phrases that
became requirements underlined as they are typed. Frames for paper.py's seq= input.

    python3 prompt.py PROMPT.txt OUT/ --frames 60 [--hold 45] [--phrase 'TEXT' ...] [--label 'THE REQUEST, AS WRITTEN']
                      [--scale 1]

PROMPT.txt is the prompt exactly as written (wrapped to the sheet here; blank lines kept). Phrases must appear in it
verbatim; one that does not is an error, since an underline under nothing reads as a mistake. Writes %05d.png at
4000x2800 times --scale: --frames typing frames, then --hold still frames.

--scale draws the same sheet with more pixels (same words on the same lines, same timing): a camera that comes
close to the type needs about one sheet pixel for each screen pixel, or the letters look soft. A sheet is 0.594 m
wide on the table; a 50 mm lens at distance d sees 0.72 d of it, so a 2560-wide frame at d = 0.15 m wants
2560 / (0.72 * 0.15 / 0.594) = 14000 pixels across: --scale 3.5.
"""
import argparse
import os
import sys

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as K  # noqa: E402

W, H = 4000, 2800
SIZE, LEAD, X0, Y0 = 72, 118, 560, 660


def wrap(text, f, width):
    out = []
    for para in text.strip('\n').split('\n'):
        line = ''
        for word in para.split(' '):
            t = (line + ' ' + word) if line else word
            if line and f.getlength(t) > width:
                out.append(line)
                line = word
            else:
                line = t
        out.append(line)
    return out


def frames(text, out, nf, hold=45, phrases=(), label='THE REQUEST, AS WRITTEN', number='01', scale=1.0):
    flat = ' '.join(text.split())
    for p in phrases:
        if ' '.join(p.split()) not in flat:
            raise SystemExit('prompt.py: phrase not in the prompt: %r' % p)
    z = float(scale)
    px = lambda v: int(round(v * z))  # noqa: E731     every size below is in pixels of the 4000-wide sheet
    w, h = px(W), px(H)
    lines = wrap(text, K.font('medium', SIZE), W - 2 * X0)   # wrapped at the sheet's own size: a scale moves no word
    if Y0 + LEAD * len(lines) > H - 200:
        raise SystemExit('prompt.py: %d lines do not fit the sheet; trim the prompt to the part that matters' % len(lines))
    f = K.font('medium', px(SIZE))
    os.makedirs(out, exist_ok=True)
    cov = Image.new('L', (w, h))
    d = ImageDraw.Draw(cov)
    order = np.full((h, w), 9e9, np.float32)     # typing position (in characters) at which each pixel appears
    n = 0
    for i, line in enumerate(lines):
        base = px(Y0 + i * LEAD)
        d.text((px(X0), base), line, font=f, fill=255, anchor='ls')
        xs = [px(X0) + f.getlength(line[:j]) for j in range(len(line) + 1)]
        for j in range(len(line)):
            a, b = int(round(xs[j])), int(round(xs[j + 1]))
            order[base - px(80):base + px(26), a:b] = n + j + 1
        for p in phrases:                          # a phrase may break across lines: underline each piece
            for piece in _pieces(p, line):
                k = line.find(piece)
                a, b = int(xs[k]), int(xs[k + len(piece)])
                y = base + px(16)
                d.rectangle((a, y, b, y + px(3)), fill=255)
                order[y - 1:y + px(3) + 2, a:b] = n + k + len(piece) + 2 + 10 * (np.arange(a, b) - a) / max(1, b - a)
        n += len(line)
    total = max(1, n)
    static = Image.new('L', (w, h))
    s = ImageDraw.Draw(static)
    mono = K.font('label', px(40))
    if label:
        s.text((px(X0), px(400)), number, font=mono, fill=255, anchor='ls')
        s.text((px(X0) + px(110), px(400)), label.upper(), font=mono, fill=150, anchor='ls')
        s.rectangle((px(X0), px(440), w - px(X0), px(440) + max(1, px(1))), fill=110)
    ink, amb, wh = (np.array(c, np.float32) for c in (K.INK, K.AMBER, K.PAPER))
    # only the inked pixels are kept as arrays: a sheet at --scale 4 is 180 million pixels
    base_img = np.empty((h, w, 3), np.uint8)
    base_img[:] = wh.clip(0, 255).astype(np.uint8)
    sy, sx = np.nonzero(np.asarray(static))
    st = np.asarray(static)[sy, sx].astype(np.float32)[:, None] / 255
    base_img[sy, sx] = (wh * (1 - st) + ink * st).clip(0, 255).astype(np.uint8)
    del static, s, sy, sx, st
    cu = np.asarray(cov)
    ys, xs_ = np.nonzero(cu)
    cv = cu[ys, xs_].astype(np.float32)[:, None] / 255
    od = order[ys, xs_]
    del order, cu, cov, d
    od = np.where(od > 8e9, 0, od)                 # antialias fringe outside every cell: shows with its neighbour
    fade = total / nf * 14                         # ink stays amber for about 14 frames
    for fr in range(nf + hold):
        t = min(1.0, fr / max(1, nf - 1)) * (total + 14) if fr < nf else total + 14 + (fr - nf) * total / nf
        vis = (od <= t).astype(np.float32)
        hot = np.clip(1 - (t - od) / fade, 0, 1) * vis
        a = cv * vis[:, None]
        col = ink + (amb - ink) * hot[:, None]
        img = base_img.copy()
        img[ys, xs_] = (wh * (1 - a) + col * a).clip(0, 255).astype(np.uint8)
        K.save(Image.fromarray(img), os.path.join(out, '%05d.png' % fr))
    return len(lines)


def _pieces(phrase, line):
    """the parts of phrase that sit on this line (whole, or a head/tail split by the wrap)"""
    if phrase in line:
        return [phrase]
    words = phrase.split(' ')
    for k in range(len(words) - 1, 0, -1):
        head, tail = ' '.join(words[:k]), ' '.join(words[k:])
        if line.endswith(head):
            return [head]
        if line.startswith(tail):
            return [tail]
    return []


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('prompt')
    ap.add_argument('out')
    ap.add_argument('--frames', type=int, default=60)
    ap.add_argument('--hold', type=int, default=45)
    ap.add_argument('--phrase', action='append', default=[])
    ap.add_argument('--label', default='THE REQUEST, AS WRITTEN')
    ap.add_argument('--scale', type=float, default=1.0, help='draw the sheet with this many times the pixels across')
    o = ap.parse_args(argv)
    n = frames(open(o.prompt).read(), o.out, o.frames, o.hold, o.phrase, o.label, scale=o.scale)
    print('prompt: %d lines, %d frames -> %s' % (n, o.frames + o.hold, o.out))


if __name__ == '__main__':
    main()
