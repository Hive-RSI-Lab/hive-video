"""The board's real routing history: every distinct saved state of a .kicad_pcb, oldest first, as a timeline of
what each save added and removed.

    python3 history.py BOARD.kicad_pcb OUT.json [--also 'GLOB' ...] [--since REV]

States come from the file's git history (`git log --follow`) and from any other saved copies you name with --also
(snapshot folders, autosaves): sorted by time, identical saves dropped. Nothing is written to the source tree.

OUT.json: {sheet: {x0, y0, w, h}, states: [{i, name, time, segs, vias, added, removed, vias_added,
vias_removed, moved}]} with every track as [x0, y0, x1, y1, width, layer] in mm (arcs as short straight runs).
`layout.py` replays it. A state that adds nothing and removes a lot is a rip-up; one that only moves parts is a
placement pass.
"""
import argparse
import glob
import hashlib
import json
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: E402,F401  (puts kit/blender on the path)
from kicad import sexpr, kids, kid, nums, layer_of, arc_points, outline  # noqa: E402

ASPECT = 0.7      # a layout sheet is 0.594 m wide and 0.7 as tall, like the paper shot's plane


def parse(text):
    """(segs, vias, footprints {ref: (x, y, rot)}) of one saved board"""
    pcb = sexpr(text)
    segs = set()
    for s in kids(pcb, 'segment'):
        a, b = nums(s, 'start'), nums(s, 'end')
        segs.add((round(a[0], 4), round(a[1], 4), round(b[0], 4), round(b[1], 4), nums(s, 'width')[0], layer_of(s)))
    for s in kids(pcb, 'arc'):
        pts = arc_points(nums(s, 'start'), nums(s, 'mid'), nums(s, 'end'), 8)
        for a, b in zip(pts, pts[1:]):
            segs.add((round(a[0], 4), round(a[1], 4), round(b[0], 4), round(b[1], 4), nums(s, 'width')[0], layer_of(s)))
    vias = set()
    for v in kids(pcb, 'via'):
        p = nums(v, 'at')
        vias.add((round(p[0], 4), round(p[1], 4), nums(v, 'size')[0]))
    fps = {}
    for fp in kids(pcb, 'footprint'):
        ref = next((g[2] for g in kids(fp, 'property') if g[1] == 'Reference'), None)
        ref = ref or next((t[2] for t in kids(fp, 'fp_text') if t[1] == 'reference'), None)
        at = nums(fp, 'at') or [0, 0]
        if ref:
            fps[ref] = (at[0], at[1], at[2] if len(at) > 2 else 0.0)
    try:
        box = outline(pcb)
    except ValueError:
        box = None
    return segs, vias, fps, box


def git_states(path, since=None):
    """[(unix time, name, text)] for each commit that touched path"""
    d, f = os.path.split(os.path.abspath(path))
    try:
        top = subprocess.check_output(['git', '-C', d, 'rev-parse', '--show-toplevel'], text=True, stderr=subprocess.DEVNULL).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return []
    rng = ['%s..HEAD' % since] if since else []
    log = subprocess.check_output(['git', '-C', top, 'log', '--follow', '--name-only', '--format=@%H %ct %s'] + rng + ['--', os.path.relpath(path, top)], text=True)
    out, cur = [], None
    for line in log.splitlines():
        if line.startswith('@'):
            h, t, subj = (line[1:].split(' ', 2) + [''])[:3]
            cur = (h, int(t), subj)
        elif line.strip() and cur:
            try:
                text = subprocess.check_output(['git', '-C', top, 'show', '%s:%s' % (cur[0], line.strip())], text=True, stderr=subprocess.DEVNULL)
            except subprocess.CalledProcessError:
                continue
            out.append((cur[1], cur[0][:7] + ' ' + cur[2][:60], text))
            cur = None
    return out


def build(path, also=(), since=None):
    found = git_states(path, since)
    for g in also:
        for p in glob.glob(os.path.expanduser(g), recursive=True):
            found.append((os.path.getmtime(p), os.path.basename(os.path.dirname(p)) + '/' + os.path.basename(p), open(p, errors='replace').read()))
    now = open(path, errors='replace').read()
    if not any(text == now for _, _, text in found):   # the board as it is now is always the last state
        found.append((os.path.getmtime(path), os.path.basename(path), now))
    found.sort(key=lambda s: s[0])
    seen, prev, states, box = set(), None, [], None
    for t, name, text in found:
        h = hashlib.md5(text.encode()).hexdigest()
        if h in seen:
            continue
        seen.add(h)
        segs, vias, fps, b = parse(text)
        box = b or box
        e = dict(i=len(states), name=name, time=time.strftime('%Y-%m-%d %H:%M', time.gmtime(t)), segs=len(segs), vias=len(vias))
        if prev:
            e.update(added=sorted(segs - prev[0]), removed=sorted(prev[0] - segs), vias_added=sorted(vias - prev[1]),
                     vias_removed=sorted(prev[1] - vias), moved={r: [prev[2][r], fps[r]] for r in fps if r in prev[2] and prev[2][r] != fps[r]})
        else:
            e.update(added=sorted(segs), removed=[], vias_added=sorted(vias), vias_removed=[], moved={})
        if prev and not (e['added'] or e['removed'] or e['vias_added'] or e['vias_removed'] or e['moved']):
            continue                     # a save that changed only text, zones or settings
        states.append(e)
        prev = (segs, vias, fps)
    return dict(sheet=sheet(box or (0, 0, 100, 70)), states=states)


def sheet(box, margin=0.09):
    """the paper around the board: the board centred, a margin all round, ASPECT tall"""
    x0, y0, x1, y1 = box
    bw, bh = x1 - x0, y1 - y0
    m = margin * max(bw, bh)
    w = max(bw + 2 * m, (bh + 2 * m) / ASPECT)
    h = w * ASPECT
    return dict(x0=x0 - (w - bw) / 2, y0=y0 - (h - bh) / 2, w=w, h=h, board=list(box))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('board')
    ap.add_argument('out')
    ap.add_argument('--also', action='append', default=[])
    ap.add_argument('--since')
    o = ap.parse_args(argv)
    tl = build(o.board, o.also, o.since)
    os.makedirs(os.path.dirname(os.path.abspath(o.out)), exist_ok=True)
    json.dump(tl, open(o.out, 'w'))
    for e in tl['states']:
        print('%2d %s  tracks %5d (+%d -%d)  vias %4d  moved %3d  %s' % (e['i'], e['time'], e['segs'], len(e['added']), len(e['removed']), e['vias'], len(e['moved']), e['name']))


if __name__ == '__main__':
    main()
