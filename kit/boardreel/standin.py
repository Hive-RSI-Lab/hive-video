"""Stand-in bodies for parts the design has no 3D model for, so every part shows in the board shots (the second
film's inductors were missing until the person asked where they were).

    python3 standin.py BOARD.kicad_pcb OUTDIR [--heights heights.json]

Writes OUTDIR/standin.kicad_pcb (the board, with ${KIPRJMOD} made absolute and a model added to each model-less
part) and OUTDIR/standin/REF.wrl, a dark moulded block with a chamfered top. Its footprint is the L and W in the
footprint's name (IND-SMD_L8.0-W8.0_...), else the F.Fab outline, else the courtyard less 0.5 mm a side. Its height
is the footprint's `above` in the heights file (by footprint name after 'lib:', the enclosure tool's format; a
plain number also works), else -H in the name, else 1 mm. Board-only footprints (mounting holes, logos) and ones
without a soldered pad get none. Prints the references it stood in for.
"""
import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: E402,F401  (puts kit/blender on the path)
from kicad import sexpr, kids, hidden, _ref  # noqa: E402

MM = 1 / 2.54   # KiCad VRML units are 0.1 inch


def blocks(text):
    """(start, end) of each top-level `(footprint ...)` in the board text"""
    i = 0
    while True:
        i = text.find('(footprint "', i)
        if i < 0:
            return
        depth, j, q = 0, i, False
        while j < len(text):
            c = text[j]
            if c == '"' and text[j - 1] != '\\':
                q = not q
            elif not q and c == '(':
                depth += 1
            elif not q and c == ')':
                depth -= 1
                if depth == 0:
                    break
            j += 1
        yield i, j
        i = j


def _box(fp, layer):
    xs, ys = [], []
    for k in ('fp_line', 'fp_rect', 'fp_poly'):
        for g in kids(fp, k):
            if not any(l[1] == layer for l in kids(g, 'layer')):
                continue
            for p in kids(g, 'start') + kids(g, 'end'):
                xs.append(float(p[1]))
                ys.append(float(p[2]))
            for pts in kids(g, 'pts'):
                for p in kids(pts, 'xy'):
                    xs.append(float(p[1]))
                    ys.append(float(p[2]))
    return (min(xs), min(ys), max(xs), max(ys)) if xs else None


def body(fp, heights):
    """(cx, cy, w, l, h) mm in the footprint's frame, KiCad's y down; None if the part needs no stand-in"""
    if any('board_only' in a or 'exclude_from_bom' in a for a in kids(fp, 'attr')):
        return None
    if not [p for p in kids(fp, 'pad') if p[2] in ('smd', 'thru_hole')]:
        return None
    name = fp[1].split(':')[-1]
    m = re.search(r'L([\d.]+)-W([\d.]+)', name)
    top = 'F' if any(l[1].startswith('F.') for l in kids(fp, 'layer')) else 'B'
    if m:
        cx = cy = 0.0
        w, l = float(m.group(1)), float(m.group(2))
    else:
        b = _box(fp, top + '.Fab')
        pad = 0.0
        if not b:
            b, pad = _box(fp, top + '.CrtYd'), 0.5
        if not b:
            return None
        cx, cy = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
        w, l = b[2] - b[0] - 2 * pad, b[3] - b[1] - 2 * pad
    hv = heights.get(name)
    if isinstance(hv, dict):
        hv = hv.get('above')
    if hv is None:
        mh = re.search(r'-H([\d.]+)', name)
        hv = float(mh.group(1)) if mh else 1.0
    return cx, cy, max(w, 0.3), max(l, 0.3), float(hv)


def wrl(cx, cy, w, l, h):
    """a block w x l x h mm with a 6% chamfer round its top, centred on (cx, -cy), in KiCad VRML"""
    c = min(w, l, h) * 0.06 + 0.05
    x0, x1, y0, y1 = cx - w / 2, cx + w / 2, -cy - l / 2, -cy + l / 2
    ring = lambda a, z: [(x0 + a, y0 + a, z), (x1 - a, y0 + a, z), (x1 - a, y1 - a, z), (x0 + a, y1 - a, z)]  # noqa: E731
    pts = ring(0, 0) + ring(0, h - c) + ring(c, h)
    faces = [[0, 3, 2, 1], [8, 9, 10, 11]]
    for r0, r1 in ((0, 4), (4, 8)):
        for i in range(4):
            j = (i + 1) % 4
            faces.append([r0 + i, r0 + j, r1 + j, r1 + i])
    pt = ',\n'.join('%.4f %.4f %.4f' % (x * MM, y * MM, z * MM) for x, y, z in pts)
    ix = ', '.join('%s,-1' % ','.join(map(str, f)) for f in faces)
    return ('#VRML V2.0 utf8\n# stand-in body: the design has no 3D model for this part\n'
            'Shape {\n appearance Appearance { material Material { diffuseColor 0.12 0.12 0.13 '
            'specularColor 0.2 0.2 0.2 shininess 0.3 } }\n'
            ' geometry IndexedFaceSet { ccw TRUE solid FALSE\n  coord Coordinate { point [\n%s ] }\n'
            '  coordIndex [ %s ] }\n}\n' % (pt, ix))


def make(board, out, heights=None):
    text = open(board).read().replace('${KIPRJMOD}', os.path.dirname(os.path.abspath(board)))
    hs = json.load(open(heights)) if heights else {}
    os.makedirs(os.path.join(out, 'standin'), exist_ok=True)
    parts, refs, last = [], [], 0
    for a, b in blocks(text):
        fp = sexpr(text[a:b + 1])
        if [m for m in kids(fp, 'model') if not hidden(m)]:
            continue
        bd = body(fp, hs)
        ref = _ref(fp)
        if not bd or not ref:
            continue
        f = os.path.join(os.path.abspath(out), 'standin', re.sub(r'\W', '_', ref) + '.wrl')
        open(f, 'w').write(wrl(*bd))
        parts += [text[last:b], '\n    (model "%s" (offset (xyz 0 0 0)) (scale (xyz 1 1 1)) (rotate (xyz 0 0 0)))\n  ' % f]
        last = b
        refs.append(ref)
    parts.append(text[last:])
    open(os.path.join(out, 'standin.kicad_pcb'), 'w').write(''.join(parts))
    return refs


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('board')
    ap.add_argument('out')
    ap.add_argument('--heights')
    o = ap.parse_args(argv)
    print(' '.join(make(o.board, o.out, o.heights)) or '(none)')


if __name__ == '__main__':
    main()
