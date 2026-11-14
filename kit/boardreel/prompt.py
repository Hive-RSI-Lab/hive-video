"""The request, typed: the person's real prompt drawn in ink on a sheet, the newest ink amber, the phrases that
became requirements underlined as they are typed. Frames for paper.py's seq= input.

    python3 prompt.py PROMPT.txt OUT/ --frames 60 [--hold 45] [--phrase 'TEXT' ...] [--label 'THE REQUEST, AS WRITTEN']

PROMPT.txt is the prompt exactly as written (wrapped to the sheet here; blank lines kept). Phrases must appear in it
verbatim; one that does not is an error, since an underline under nothing reads as a mistake. Writes %05d.png at
4000x2800: --frames typing frames, then --hold still frames.
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


def frames(text, out, nf, hold=45, phrases=(), label='THE REQUEST, AS WRITTEN', number='01'):
    flat = ' '.join(text.split())
    for p in phrases:
        if ' '.join(p.split()) not in flat:
            raise SystemExit('prompt.py: phrase not in the prompt: %r' % p)
    f = K.font('medium', SIZE)
    lines = wrap(text, f, W - 2 * X0)
    if Y0 + LEAD * len(lines) > H - 200:
        raise SystemExit('prompt.py: %d lines do not fit the sheet; trim the prompt to the part that matters' % len(lines))
    os.makedirs(out, exist_ok=True)
    cov = Image.new('L', (W, H))
    d = ImageDraw.Draw(cov)
    order = np.full((H, W), 9e9, np.float32)     # typing position (in characters) at which each pixel appears
    n = 0
    for i, line in enumerate(lines):
        base = Y0 + i * LEAD
        d.text((X0, base), line, font=f, fill=255, anchor='ls')
        xs = [X0 + f.getlength(line[:j]) for j in range(len(line) + 1)]
        for j in range(len(line)):
            a, b = int(round(xs[j])), int(round(xs[j + 1]))
            order[base - 80:base + 26, a:b] = n + j + 1
        for p in phrases:                          # a phrase may break across lines: underline each piece
            for piece in _pieces(p, line):
                k = line.find(piece)
                a, b = int(xs[k]), int(xs[k + len(piece)])
                y = base + 16
                d.rectangle((a, y, b, y + 3), fill=255)
                order[y - 1:y + 5, a:b] = n + k + len(piece) + 2 + 10 * (np.arange(a, b) - a) / max(1, b - a)
        n += len(line)
    total = max(1, n)
    static = Image.new('L', (W, H))
    s = ImageDraw.Draw(static)
    mono = K.font('label', 40)
    if label:
        s.text((X0, 400), number, font=mono, fill=255, anchor='ls')
        s.text((X0 + 110, 400), label.upper(), font=mono, fill=150, anchor='ls')
        s.rectangle((X0, 440, W - X0, 441), fill=110)
    C = np.asarray(cov, np.float32) / 255
    ST = np.asarray(static, np.float32)[..., None] / 255
    ink, amb, wh = (np.array(c, np.float32) for c in (K.INK, K.AMBER, K.PAPER))
    base_img = (wh * (1 - ST) + ink * ST).clip(0, 255).astype(np.uint8) * np.ones((H, W, 3), np.uint8)
    ys, xs_ = np.nonzero(C > 0)
    cv = C[ys, xs_][:, None]
    od = order[ys, xs_]
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
    o = ap.parse_args(argv)
    n = frames(open(o.prompt).read(), o.out, o.frames, o.hold, o.phrase, o.label)
    print('prompt: %d lines, %d frames -> %s' % (n, o.frames + o.hold, o.out))


if __name__ == '__main__':
    main()
