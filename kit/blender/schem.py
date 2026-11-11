"""schem.py — a KiCad schematic as drawable geometry, with no KiCad installed and no bpy.

    python3 schem.py SHEET.kicad_sch OUT.json

OUT.json: {size: [w, h], strokes: [{pts: [[x, y], ...], kind, group}], texts: [{s, x, y, size, rot, kind, group}],
groups: [{id, kind, ref, x, y}], order: {group: 0..1}}, in millimetres with y DOWN as on the sheet.

Every stroke and text belongs to a group: one placed symbol, or one connected run of wire. order gives each group its
place in the drawing order: symbols sweep across the sheet, and each net is drawn after the first symbol it touches, so
a film can draw a schematic the way a person would, part then its wires.
"""
import json
import math
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from kicad import sexpr, kids, kid  # noqa: E402

PAPER = {'A5': (210, 148), 'A4': (297, 210), 'A3': (420, 297), 'A2': (594, 420), 'A1': (841, 594), 'A0': (1189, 841)}


def _nums(node):
    return [float(v) for v in node[1:] if isinstance(v, str) and re.fullmatch(r'-?[\d.]+', v)]


def _xy(node):
    return [_nums(p)[:2] for p in kids(node, 'xy')]


def _text(v):
    return v[1:-1] if v.startswith('"') else v


def _hidden(node):
    eff = kid(node, 'effects')
    return bool(eff and any(c == 'hide' or (isinstance(c, list) and c[0] == 'hide' and c[1:] == ['yes']) for c in eff))


def _size(node, d=1.27):
    f = kid(kid(node, 'effects') or [], 'font') if kid(node, 'effects') else None
    s = kid(f, 'size') if f else None
    return _nums(s)[0] if s else d


def _arc(s, m, e, n=12):
    ax, ay, bx, by, cx, cy = *s, *m, *e
    d = 2 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
    if abs(d) < 1e-9:
        return [s, e]
    a2, b2, c2 = ax * ax + ay * ay, bx * bx + by * by, cx * cx + cy * cy
    ux = (a2 * (by - cy) + b2 * (cy - ay) + c2 * (ay - by)) / d
    uy = (a2 * (cx - bx) + b2 * (ax - cx) + c2 * (bx - ax)) / d
    r = math.hypot(ax - ux, ay - uy)
    t0, t1, t2 = (math.atan2(p[1] - uy, p[0] - ux) for p in (s, m, e))
    tw = 2 * math.pi
    d1 = (t1 - t0) % tw
    d2 = (t2 - t0) % tw
    sweep = d2 if d1 <= d2 else d2 - tw
    return [[ux + r * math.cos(t0 + sweep * i / n), uy + r * math.sin(t0 + sweep * i / n)] for i in range(n + 1)]


def _graphics(unit):
    """a library symbol unit's drawing, in symbol space (y up): strokes and pins"""
    out, pins = [], []
    for c in unit[1:]:
        if not isinstance(c, list):
            continue
        if c[0] == 'polyline':
            out.append(_xy(kid(c, 'pts')))
        elif c[0] == 'rectangle':
            (x0, y0), (x1, y1) = _nums(kid(c, 'start'))[:2], _nums(kid(c, 'end'))[:2]
            out.append([[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]])
        elif c[0] == 'circle':
            x, y = _nums(kid(c, 'center'))[:2]
            r = _nums(kid(c, 'radius'))[0]
            out.append([[x + r * math.cos(2 * math.pi * i / 20), y + r * math.sin(2 * math.pi * i / 20)] for i in range(21)])
        elif c[0] == 'arc':
            out.append(_arc(_nums(kid(c, 'start'))[:2], _nums(kid(c, 'mid'))[:2], _nums(kid(c, 'end'))[:2]))
        elif c[0] == 'pin':
            at = _nums(kid(c, 'at'))
            ln = _nums(kid(c, 'length'))[0]
            a = math.radians(at[2] if len(at) > 2 else 0)
            name = kid(c, 'name')
            num = kid(c, 'number')
            pins.append(dict(x=at[0], y=at[1], x1=at[0] + ln * math.cos(a), y1=at[1] + ln * math.sin(a),
                             name=_text(name[1]) if name else '', num=_text(num[1]) if num else ''))
    return out, pins


def _library(root):
    lib = {}
    for sym in kids(kid(root, 'lib_symbols'), 'symbol'):
        name = _text(sym[1])
        units = {}
        for u in kids(sym, 'symbol'):
            m = re.search(r'_(\d+)_(\d+)"?$', u[1])
            n = int(m.group(1)) if m else 0
            s, p = _graphics(u)
            units.setdefault(n, ([], []))
            units[n][0].extend(s)
            units[n][1].extend(p)
        lib[name] = units
    return lib


def _place(p, at, mirror):
    x, y = p
    if mirror == 'x':
        y = -y
    elif mirror == 'y':
        x = -x
    a = math.radians(at[2] if len(at) > 2 else 0)
    return [round(at[0] + x * math.cos(a) - y * math.sin(a), 3) * 1.0, round(at[1] - (x * math.sin(a) + y * math.cos(a)), 3)]


def parse(path):
    root = sexpr(open(path, encoding='utf-8').read())
    paper = kid(root, 'paper')
    size = PAPER.get(_text(paper[1]), (420, 297))
    lib = _library(root)
    strokes, texts, groups, ends = [], [], [], {}
    for sym in kids(root, 'symbol'):
        lid = _text(kid(sym, 'lib_id')[1])
        at = _nums(kid(sym, 'at'))
        mi = kid(sym, 'mirror')
        mirror = mi[1] if mi else None
        unit = int(_nums(kid(sym, 'unit'))[0]) if kid(sym, 'unit') else 1
        short = lid.split(':')[-1]
        spec = lib.get(lid) or lib.get(short)
        if not spec:
            continue
        props = {_text(p[1]): p for p in kids(sym, 'property')}
        ref = _text(props['Reference'][2]) if 'Reference' in props else ''
        gid = len(groups)
        power = ref.startswith('#')
        groups.append(dict(id=gid, kind='power' if power else 'symbol', ref=ref, x=at[0], y=at[1]))
        for n in (0, unit):
            for line in spec.get(n, ([], []))[0]:
                strokes.append(dict(pts=[_place(p, at, mirror) for p in line], kind='body', group=gid))
            for pin in spec.get(n, ([], []))[1]:
                a, b = _place((pin['x'], pin['y']), at, mirror), _place((pin['x1'], pin['y1']), at, mirror)
                strokes.append(dict(pts=[a, b], kind='pin', group=gid))
                ends.setdefault(tuple(a), gid)
        for key in ('Reference', 'Value'):
            p = props.get(key)
            if p is None or _hidden(p):
                continue
            pa = _nums(kid(p, 'at'))
            texts.append(dict(s=_text(p[2]), x=pa[0], y=pa[1], size=_size(p), rot=0, kind=key.lower(), group=gid))
    # a hierarchical sheet box, on the top sheet: a rectangle and its name
    for sh in kids(root, 'sheet'):
        (x, y), (w, h) = _nums(kid(sh, 'at'))[:2], _nums(kid(sh, 'size'))[:2]
        gid = len(groups)
        groups.append(dict(id=gid, kind='symbol', ref='', x=x, y=y))
        strokes.append(dict(pts=[[x, y], [x + w, y], [x + w, y + h], [x, y + h], [x, y]], kind='body', group=gid))
        for p in kids(sh, 'property'):
            if _text(p[1]) in ('Sheetname', 'Sheet name'):
                texts.append(dict(s=_text(p[2]), x=x + 1, y=y + h / 2, size=2.5, rot=0, kind='value', group=gid))
    # wires: a connected run of wire is one group
    wires = [_xy(kid(w, 'pts')) for w in kids(root, 'wire')]
    parent = list(range(len(wires)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    at = {}
    for i, w in enumerate(wires):
        for p in w:
            k = (round(p[0], 2), round(p[1], 2))
            if k in at:
                parent[find(i)] = find(at[k])
            else:
                at[k] = i
    runs = {}
    for i, w in enumerate(wires):
        runs.setdefault(find(i), []).append(w)
    run_gid = {}
    for r, ws in runs.items():
        gid = len(groups)
        xs = [p[0] for w in ws for p in w]
        ys = [p[1] for w in ws for p in w]
        groups.append(dict(id=gid, kind='net', ref='', x=sum(xs) / len(xs), y=sum(ys) / len(ys)))
        run_gid[r] = gid
        for w in ws:
            strokes.append(dict(pts=w, kind='wire', group=gid))
    # first symbol a net touches, for the order
    touch = {}
    for r, ws in runs.items():
        for w in ws:
            for p in w:
                g = ends.get((round(p[0], 3), round(p[1], 3)))
                if g is not None:
                    touch[run_gid[r]] = min(touch.get(run_gid[r], 1 << 30), g)
    for j in kids(root, 'junction'):
        x, y = _nums(kid(j, 'at'))[:2]
        k = (round(x, 2), round(y, 2))
        if k in at:
            g = run_gid[find(at[k])]
            strokes.append(dict(pts=[[x + .45 * math.cos(2 * math.pi * i / 10), y + .45 * math.sin(2 * math.pi * i / 10)]
                                     for i in range(11)], kind='dot', group=g))
    for kind in ('label', 'global_label', 'hierarchical_label'):
        for lb in kids(root, kind):
            a = _nums(kid(lb, 'at'))
            k = (round(a[0], 2), round(a[1], 2))
            g = run_gid[find(at[k])] if k in at else None
            if g is None:
                g = len(groups)
                groups.append(dict(id=g, kind='net', ref='', x=a[0], y=a[1]))
            texts.append(dict(s=_text(lb[1]), x=a[0], y=a[1], size=_size(lb), rot=a[2] if len(a) > 2 else 0, kind='label', group=g))
    # drawing order: symbols sweep left to right, each followed by the nets it starts
    syms = sorted((g for g in groups if g['kind'] != 'net'), key=lambda g: (g['x'] + 0.3 * g['y']))
    seq = []
    placed = set()
    for g in syms:
        seq.append(g['id'])
        for n, s in touch.items():
            if s == g['id'] and n not in placed:
                placed.add(n)
                seq.append(n)
    for g in groups:
        if g['kind'] == 'net' and g['id'] not in placed:
            seq.append(g['id'])
    n = max(1, len(seq) - 1)
    order = {str(g): i / n for i, g in enumerate(seq)}
    return dict(size=size, strokes=strokes, texts=texts, groups=groups, order=order)


if __name__ == '__main__':
    doc = parse(sys.argv[1])
    json.dump(doc, open(sys.argv[2], 'w'), separators=(',', ':'))
    print('%s: %d strokes, %d texts, %d groups, %s mm' % (os.path.basename(sys.argv[1]), len(doc['strokes']), len(doc['texts']), len(doc['groups']), doc['size']))
