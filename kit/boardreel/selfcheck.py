#!/usr/bin/env python3
"""The board reel kit's own cases, on the tiny board and sheet in fixture/ (no kicad-cli, build123d or Blender
needed; kit/blender/selfcheck.py runs them with its own).

    python3 selfcheck.py

Each case is one of the rules the first board reel paid for, checked on the tool that keeps it."""
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
FIX = os.path.join(HERE, 'fixture')
sys.path.insert(0, HERE)
RESULTS = []


def check(name, ok, got=''):
    RESULTS.append(bool(ok))
    print('%s %s%s' % ('ok  ' if ok else 'FAIL', name, '' if ok else '  (got %r)' % (got,)), flush=True)


def cfg_in(tmp, **kw):
    """a reel.json in tmp over the fixture board, built into tmp/build"""
    c = dict(source=FIX, board='tiny.kicad_pcb', sheet='tiny.kicad_sch', title='A small board', build=os.path.join(tmp, 'build'),
             shots=[], drawings={})
    c.update(kw)
    p = os.path.join(tmp, 'reel.json')
    json.dump(c, open(p, 'w'))
    import common as K
    return K.load(p)


def drawing_cases(tmp):
    import common as K
    import schematic
    import checks
    out = os.path.join(tmp, 'build', 'drawings', 'S')
    m = schematic.render(os.path.join(FIX, 'tiny.kicad_sch'), out, 12, crop=(40, 35, 90, 65), width=400)
    check('R1 a schematic crop adds ink on every frame, first to last (no blank opening, no still ending)',
          len(m['new']) == 12 and min(m['new']) > 0, m['new'])
    check('R1b the drawing is the crop\'s own shape and draws on paper', abs(m['aspect'] - 30 / 50) < 0.02 and
          len([f for f in os.listdir(out) if f.endswith('.png')]) == 12, m['aspect'])
    c = cfg_in(tmp, drawings={'S': {'tool': 'schematic'}}, shots=[
        dict(name='good', shot='paper', frames=12, args='seq=@S'),
        dict(name='slow', shot='paper', frames=12, args='seq=@S rate=0.5'),
        dict(name='held', shot='paper', frames=12, args='seq=@S seqn=8')])
    res = {n: ok for n, ok, _ in checks.drawing(c)}
    check('R2 the drawing check passes a shot that draws every frame and fails one that repeats or runs out of ink',
          res == {'good': True, 'slow': False, 'held': False}, res)
    check('R2b the check and the render share one frame map (seq_frame): ramp ends on the last drawing frame',
          K.seq_frame(1, 30, 0, 50, ramp=1.5) == 0 and K.seq_frame(30, 30, 0, 50, ramp=1.5) == 49 and K.seq_frame(5, 30, 10) == 14,
          [K.seq_frame(f, 30, 0, 50, ramp=1.5) for f in (1, 30)])


def layout_cases(tmp):
    import history
    import layout
    import common as K
    b = os.path.join(tmp, 'b')
    os.makedirs(os.path.join(b, 'a'))
    shutil.copy(os.path.join(FIX, 'tiny.kicad_pcb'), b)
    shutil.copy(os.path.join(FIX, 'saves', 'a', 'tiny.kicad_pcb'), os.path.join(b, 'a'))
    os.utime(os.path.join(b, 'a', 'tiny.kicad_pcb'), (1e9, 1e9))
    os.utime(os.path.join(b, 'tiny.kicad_pcb'), (1e9 + 60, 1e9 + 60))
    tl = history.build(os.path.join(b, 'tiny.kicad_pcb'), also=[os.path.join(b, 'a', '*.kicad_pcb')])
    st = tl['states']
    check('R3 the routing history: the early save first, then the later one adds three tracks and a via',
          len(st) == 2 and st[0]['segs'] == 1 and len(st[1]['added']) == 3 and len(st[1]['vias_added']) == 1, [(e['segs'], len(e['added'])) for e in st])
    tp = os.path.join(tmp, 'timeline.json')
    json.dump(tl, open(tp, 'w'))
    out = os.path.join(tmp, 'lay')
    layout.replay(os.path.join(b, 'tiny.kicad_pcb'), tp, out, 20, width=400)
    s = json.load(open(os.path.join(out, 'starts.json')))
    check('R4 the replay draws every state in order and leaves one sheet a copper layer for the pulled-apart stack',
          s['starts'] == sorted(s['starts']) and len(s['starts']) == 2 and sorted(s['layers']) == ['B.Cu', 'F.Cu']
          and all(os.path.exists(os.path.join(out, 'layers', L + '.png')) for L in s['layers']), s)
    light = [sum(K.layer_colour(L, i)) / 3 for i, L in enumerate(['F.Cu', 'B.Cu', 'In1.Cu', 'In2.Cu'])]
    cols = {tuple(K.layer_colour(L, i)) for i, L in enumerate(['F.Cu', 'B.Cu', 'In1.Cu', 'In2.Cu'])}
    check('R4b light ink look: each copper layer its own pastel (lighter than the ink, each its own hue)',
          len(cols) == 4 and min(light) > 130, sorted(cols))


def model_cases(tmp):
    import reel
    m = reel.models(os.path.join(FIX, 'tiny.kicad_pcb'))
    check('R5 3D models are counted per footprint: a doubled part and a part with none are both found',
          m == {'R1': 1, 'J1': 2, 'H1': 0}, m)


def rule_cases(tmp):
    import checks
    import cut
    q = os.path.join(tmp, 'build', 'preview', 'shots')
    for name, lands in (('pour', [10, 20, 28, 34, 39, 43, 46, 48, 50, 51]), ('drip', [10, 12, 15, 19, 24, 30, 37, 45, 54, 64])):
        os.makedirs(os.path.join(q, name), exist_ok=True)
        json.dump(dict(lands=lands, hits=[], refs=[]), open(os.path.join(q, name, 'events.json'), 'w'))
    c = cfg_in(tmp, shots=[dict(name='pour', shot='board', frames=60, args='fall'), dict(name='drip', shot='board', frames=60, args='fall')])
    res = {n: ok for n, ok, _ in checks.drops(c, 'preview')}
    check('R6 falling parts must speed up drop by drop: a pour passes, a slowing drip fails', res == {'pour': True, 'drip': False}, res)
    bad = [
        cfg_in(tmp, title='Designed by Claude'), cfg_in(tmp, title='A board', credit='214 parts placed'),
        cfg_in(tmp, title='A board', status='Tested and working'), cfg_in(tmp, title='An incredible board')]
    good = cfg_in(tmp, title='A hi-fi receiver', credit='A. Person')
    check('R7 on-screen words: no model named, no count, no claim it works, no hype; a plain title passes',
          all(checks.words(c) for c in bad) and not checks.words(good), [checks.words(c) for c in bad + [good]])
    c = cfg_in(tmp, shots=[dict(slot='real photos', dir='photos'), dict(slot='real testing', dir='testing')])
    s0 = cut.status(c)
    os.makedirs(os.path.join(tmp, 'photos'))
    from PIL import Image
    Image.new('RGB', (1600, 900), (90, 120, 60)).save(os.path.join(tmp, 'photos', '01.jpg'))
    s1 = cut.status(c)
    fr = list(cut.slot_frames(c, c['shots'][0], (320, 180)))
    check('R8 slots: empty, the film says not yet built; a photo in, it says built (and never that it works)',
          'NOT YET BUILT' in s0 and s1.startswith('BUILT') and len(fr) == 90 and fr[0].size == (320, 180)
          and not checks.words(dict(c, status=s1)), (s0, s1, len(fr)))
    first, last = cut.end_card(c, (640, 360), 0), cut.end_card(c, (640, 360), cut.END_FRAMES - 1)
    ink = lambda im: sum(1 for p in im.convert('L').tobytes() if p < 120)  # noqa: E731
    src = open(os.path.join(HERE, 'cut.py')).read()
    check('R9 the end card builds in (no flash: it opens on bare paper) and says made by the hive, hivelab.ca',
          ink(first) == 0 and ink(last) > 200 and 'Made by the Hive' in src and 'hivelab.ca' in src, (ink(first), ink(last)))
    spans = checks.cut_spans(dict(fps=30, shots=[dict(start=0), dict(start=16.0), dict(start=17.5)]))
    out = 'frames: 900\nstutters: 0\njerks: 2\n  0.87-0.97 s fast\n  48.70 s jump\nflash frames: 0\n'
    ok, bad = checks.smooth(out), checks.smooth(out.replace('stutters: 0', 'stutters: 1'))
    check('R9b smooth: the film\'s own cuts are skipped; sharp moments are listed, not failed; a stutter fails',
          spans == ['15.967-16.033', '17.467-17.533'] and ok[1] and '48.70 s jump' in ok[2] and not bad[1], (spans, ok, bad))


def score_cases(tmp):
    node = shutil.which('node')
    if not node:
        check('R10 node is on the PATH for the score', False, 'no node')
        return
    marks = dict(fps=30, seconds=12.0, lands=[6.1, 6.12, 6.3], hits=[10.0],
                 shots=[dict(name='a', section='open', start=0, frames=90), dict(name='b', section='layout', start=3, frames=60),
                        dict(name='c', section='layout', start=5, frames=60), dict(name='d', section='case', start=7, frames=150)])
    mp = os.path.join(tmp, 'm.json')
    json.dump(marks, open(mp, 'w'))
    js = ("import {notes, sections} from %s; const m = JSON.parse(require_('%s'));"
          "const n = notes(m).notes; const at = (i, t) => n.some((x) => x.inst === i && Math.abs(x.at - t) < 1e-6);"
          "console.log(JSON.stringify({secs: sections(m).map((s) => s.name), cut3: at('impact', 3) && at('riser', 3 - 1.5),"
          "cut5: at('snare', 5), case7: at('impact', 7), hit10: at('crash', 10), lands: [6.1, 6.12, 6.3].filter((t) => at('hat', t)).length}))"
          % (json.dumps('file://' + os.path.join(HERE, 'score.mjs')), mp)).replace(' MOD ', ' % ')
    js = "import { readFileSync as require_ } from 'node:fs';" + js
    r = subprocess.run([node, '--input-type=module', '-e', js], capture_output=True, text=True)
    got = json.loads(r.stdout) if r.returncode == 0 else r.stderr[-400:]
    check('R10 the score comes from the marks: a hit and riser on each section cut, a snare on a cut inside one, a crash on each hit',
          isinstance(got, dict) and got['secs'] == ['open', 'layout', 'case'] and got['cut3'] and got['cut5'] and got['case7'] and got['hit10'], got)
    check('R10b landings tick, thinned so two within 70 ms are one', isinstance(got, dict) and got['lands'] == 2, got)


def reel_cases(tmp):
    import reel
    d = os.path.join(tmp, 'f')
    a = reel.fresh(d, ['x', 1])
    reel.done(d)
    b = reel.fresh(d, ['x', 1])
    open(os.path.join(d, '0001.png'), 'w').write('')
    c = reel.fresh(d, ['x', 2])
    check('R11 a render resumes when its args are the same and starts again when they change',
          (a, b, c) == (False, True, False) and not os.path.exists(os.path.join(d, '0001.png')), (a, b, c))
    cfg = cfg_in(tmp, drawings={'S': {'tool': 'schematic'}})
    e = reel.expand(cfg, 'seq=@S track=@S/track.json real=@real lens=50')
    check('R11b @names in shot args become the drawing and prep folders', e == [
        'seq=' + os.path.join(tmp, 'build', 'drawings', 'S'), 'track=' + os.path.join(tmp, 'build', 'drawings', 'S', 'track.json'),
        'real=' + os.path.join(tmp, 'build', 'real'), 'lens=50'], e)
    try:
        reel.expand(cfg, 'seq=@nope')
        refused = False
    except SystemExit:
        refused = True
    check('R11c an @name that is neither a drawing nor a prep output is refused', refused)


def pages_cases(tmp):
    import pages
    from PIL import Image
    src = os.path.join(tmp, 'ds')
    os.makedirs(src)
    Image.new('RGB', (850, 1100), (0, 0, 0)).save(os.path.join(src, 'chip_datasheet.png'))
    idx = pages.prep(os.path.join(tmp, 'pages'), [src])
    im = Image.open(os.path.join(tmp, 'pages', idx[0]['file']))
    check('R12 datasheet pages: the vendor logo corners of a first page are blanked, the part named from the file',
          idx[0]['part'] == 'chip' and im.getpixel((20, 20))[0] > 240 and im.getpixel((830, 20))[0] > 240 and im.getpixel((425, 600))[0] < 20,
          (idx, im.getpixel((20, 20)), im.getpixel((830, 20))))


def main():
    tmp = tempfile.mkdtemp(prefix='br-check-')
    try:
        for case in (drawing_cases, layout_cases, model_cases, rule_cases, score_cases, reel_cases, pages_cases):
            try:
                case(tmp)
            except Exception as e:   # a case that crashes is a failure with its reason, not a stopped run
                check('%s ran' % case.__name__, False, '%s: %s' % (type(e).__name__, e))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return RESULTS.count(False)


if __name__ == '__main__':
    bad = main()
    print('board reel selfcheck: %d passed, %d failed' % (len(RESULTS) - bad, bad))
    sys.exit(1 if bad else 0)
