#!/usr/bin/env python3
"""The board reel kit's own cases, on the tiny board and sheet in fixture/ (no kicad-cli, build123d or Blender
needed; kit/blender/selfcheck.py runs them with its own).

    python3 selfcheck.py

Each case is one of the rules the first board reel paid for, checked on the tool that keeps it."""
import json
import os
import re
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
    c = cfg_in(tmp, drawings={'S': {'tool': 'schematic'}}, shots=[
        dict(name='far', shot='paper', frames=12, args='seq=@S cam=0,0,0.20,0,50:0,0,0.12,0,50 lens=50'),
        dict(name='near', shot='paper', frames=12, args='seq=@S cam=0,0,0.20,0,50:0,0,0.03,0,50 lens=50'),
        dict(name='part', shot='paper', frames=6, args='seq=@S cam=0,0,0.20,0,50:0,0,0.03,0,50 lens=50 of=12 at=0 ease=even'),
        dict(name='tiles', shot='paper', frames=12, args='tiles=@S cam=0,0,0.01,0,50:0,0,0.01,0,50')])
    res = {n: (ok, d) for n, ok, d in checks.sharp(c)}
    # a 400 px drawing on the 0.594 m sheet, 50 mm lens: at 0.12 m the final's 2560 px see 0.0864 m of it, 58 px
    check('R2c sharp: a drawing the final would show soft fails with the width that fixes it; the same move cut '
          'short of the close end passes; tiles are not judged',
          sorted(res) == ['far', 'near', 'part'] and not res['far'][0] and '"width": 18000' in res['far'][1]
          and not res['near'][0] and '176.00 final px' in res['near'][1] and abs(K.move([0, 0, 0.20, 0, 50], [0, 0, 0.03, 0, 50], 5 / 11, 'even')[2]
                                                                                 - 0.20 * (0.03 / 0.20) ** (5 / 11)) < 1e-9, res)
    wide = os.path.join(tmp, 'build', 'drawings', 'W')
    os.makedirs(wide)
    from PIL import Image
    Image.new('L', (20000, 8), 255).save(os.path.join(wide, '00000.png'))
    c = cfg_in(tmp, drawings={'W': {'tool': 'schematic'}}, shots=[dict(name='ok', shot='paper', frames=12, args='seq=@W cam=0,0,0.20,0,50:0,0,0.12,0,50')])
    res = checks.sharp(c)
    check('R2d sharp: with the pixels the closest frame needs the shot passes', len(res) == 1 and res[0][1] and res[0][2].startswith('0.88 final px'), res)
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
    check('R5 3D models are counted per footprint: a doubled part is found',
          m == {'R1': 1, 'J1': 2}, m)
    check('R5c a bare mounting hole (no model, no soldered pad) is not listed as a part needing a stand-in block',
          'H1' not in m, m)


def standin_cases(tmp):
    import standin
    b = os.path.join(tmp, 'si', 'board.kicad_pcb')
    os.makedirs(os.path.dirname(b), exist_ok=True)
    text = open(os.path.join(FIX, 'tiny.kicad_pcb')).read().rstrip().rstrip(')') + """
  (footprint "x:IND-SMD_L8.0-W8.0_X" (layer "F.Cu") (at 20 8)
    (property "Reference" "L1" (at 0 -2 0) (layer "F.SilkS"))
    (pad "1" smd rect (at -3 0) (size 2 3) (layers "F.Cu" "F.Mask"))
    (pad "2" smd rect (at 3 0) (size 2 3) (layers "F.Cu" "F.Mask")))
  (footprint "x:Logo" (layer "F.Cu") (at 30 5) (attr board_only exclude_from_pos_files exclude_from_bom)
    (property "Reference" "G1" (at 0 -2 0) (layer "F.SilkS"))
    (pad "1" smd rect (at 0 0) (size 1 1) (layers "F.Cu")))
)
"""
    open(b, 'w').write(text)
    hj = os.path.join(tmp, 'si', 'heights.json')
    json.dump({'IND-SMD_L8.0-W8.0_X': {'above': 5.2}}, open(hj, 'w'))
    out = os.path.join(tmp, 'si', 'out')
    refs = standin.make(b, out, hj)
    w = open(os.path.join(out, 'standin', 'L1.wrl')).read()
    pts = [tuple(float(v) * 2.54 for v in l.strip(' ,]').split()) for l in w.split('point [')[1].split(']')[0].strip().split('\n')]
    size = tuple(round(max(p[i] for p in pts) - min(p[i] for p in pts), 2) for i in range(3))
    pcb = open(os.path.join(out, 'standin.kicad_pcb')).read()
    check('R5b a part with no 3D model gets a stand-in block sized from its footprint name and the heights file; '
          'modelled parts, holes and board-only art get none',
          refs == ['L1'] and size == (8.0, 8.0, 5.2) and pcb.count('/standin/L1.wrl') == 1, (refs, size))
    import reel
    m = reel.models(b)
    check('R5d a soldered part with no model is listed for a stand-in; board-only art and a bare hole are not',
          m.get('L1') == 0 and 'G1' not in m and 'H1' not in m, m)
    d = os.path.join(tmp, 'paths', 'proj')
    os.makedirs(d, exist_ok=True)
    pb = os.path.join(d, 'p.kicad_pcb')
    open(pb, 'w').write('(kicad_pcb\n  (footprint "x:A" (layer "F.Cu") (at 1 1)\n    (property "Reference" "U1")\n'
                        '    (pad "1" smd rect (at 0 0) (size 1 1) (layers "F.Cu"))\n'
                        '    (model "models/a.step") (model "${KIPRJMOD}/b.wrl") (model "${LIB3D}/c.step")\n'
                        '    (model "${KICAD9_3DMODEL_DIR}/R.wrl") (model "/abs/d.wrl") (model "kicad-embed://e.step")\n'
                        '    (model "${NEST}/f.step") (model "$(KIPRJMOD)/g.wrl"))\n'
                        '  (footprint "x:Fid" (layer "F.Cu") (at 5 5) (attr smd exclude_from_bom)\n'
                        '    (property "Reference" "FID1")\n    (pad "1" smd circle (at 0 0) (size 1 1) (layers "F.Cu")))\n)\n')
    json.dump({'text_variables': {'LIB3D': '../lib3d', 'NEST': '${KIPRJMOD}/../nest'}}, open(os.path.join(d, 'p.kicad_pro'), 'w'))
    standin.make(pb, os.path.join(tmp, 'paths', 'out'))
    got = re.findall(r'\(model "([^"]+)"', open(os.path.join(tmp, 'paths', 'out', 'standin.kicad_pcb')).read())
    want = [os.path.join(d, 'models/a.step'), os.path.join(d, 'b.wrl'), os.path.join(tmp, 'paths', 'lib3d', 'c.step'),
            '${KICAD9_3DMODEL_DIR}/R.wrl', '/abs/d.wrl', 'kicad-embed://e.step', os.path.join(tmp, 'paths', 'nest', 'f.step'),
            os.path.join(d, 'g.wrl')]
    check('R5e the copied board resolves from OUTDIR: relative, ${KIPRJMOD} and project-variable model paths are made '
          'absolute (a variable inside a variable, $(X) too); KiCad\'s own variables, absolute paths and embedded models kept',
          got == want, got)
    m = reel.models(pb)
    check('R5f a fiducial (an smd pad, off the BOM, no model) is not listed for a stand-in block', m == {'U1': 8}, m)
    q = os.path.join(tmp, 'paths', 'my "q" dir')
    os.makedirs(q, exist_ok=True)
    open(os.path.join(q, 'b.kicad_pcb'), 'w').write('(kicad_pcb\n  (footprint "x:A" (layer "F.Cu") (at 1 1)\n'
                                                     '    (property "Reference" "U1")\n    (model "m.wrl"))\n)\n')
    standin.make(os.path.join(q, 'b.kicad_pcb'), os.path.join(tmp, 'paths', 'out2'))
    from kicad import sexpr, kids
    fp = kids(sexpr(open(os.path.join(tmp, 'paths', 'out2', 'standin.kicad_pcb')).read()), 'footprint')[0]
    got = kids(fp, 'model')[0][1]
    check('R5g a quote in the board\'s folder name is escaped in the copy, which still parses to the real path',
          got == os.path.join(q, 'm.wrl'), got)


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
        cfg_in(tmp, title='A board', status='Tested and working'), cfg_in(tmp, title='An incredible board'),
        cfg_in(tmp, title='A board', end=dict(by='Proven by 12 agents'))]
    good = cfg_in(tmp, title='A hi-fi receiver', credit='A. Person',
                  end=dict(title='A receiver', by='Designed and developed by the Hive', links=['hivelab.ca'], status=False))
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
          'NOT YET BUILT' in s0 and s1.startswith('BUILT') and len(fr) == 90 and fr[0][1].size == (320, 180)
          and fr[0][0].endswith('01.jpg')
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
                        dict(name='c', section='layout', start=5, frames=24), dict(name='c2', section='layout', start=5.8, frames=36),
                        dict(name='d', section='case', start=7, frames=150)])
    mp = os.path.join(tmp, 'm.json')
    json.dump(marks, open(mp, 'w'))
    js = ("import {notes, sections} from %s; const m = JSON.parse(require_('%s'));"
          "const n = notes(m).notes; const at = (i, t) => n.some((x) => x.inst === i && Math.abs(x.at - t) < 1e-6);"
          "console.log(JSON.stringify({secs: sections(m).map((s) => s.name), cut3: at('impact', 3) && at('riser', 3 - 1.5),"
          "cut5: at('snare', 5) && at('impact', 5), quick: at('impact', 5.8) && !at('snare', 5.8), snares: n.filter((x) => x.inst === 'snare').length,"
          "case7: at('impact', 7), hit10: at('crash', 10), lands: [6.1, 6.12, 6.3].filter((t) => at('hat', t)).length}))"
          % (json.dumps('file://' + os.path.join(HERE, 'score.mjs')), mp)).replace(' MOD ', ' % ')
    js = "import { readFileSync as require_ } from 'node:fs';" + js
    r = subprocess.run([node, '--input-type=module', '-e', js], capture_output=True, text=True)
    got = json.loads(r.stdout) if r.returncode == 0 else r.stderr[-400:]
    check('R10 the score comes from the marks: a hit and riser on each section cut, an impact and a snare on a cut inside one, a crash on each hit',
          isinstance(got, dict) and got['secs'] == ['open', 'layout', 'case'] and got['cut3'] and got['cut5'] and got['case7'] and got['hit10'], got)
    check('R10c a cut that comes less than 1.5 s after a snare keeps its impact and gets no snare of its own',
          isinstance(got, dict) and got['quick'] and got['snares'] == 1, got)
    check('R10b landings tick, thinned so two within 70 ms are one', isinstance(got, dict) and got['lands'] == 2, got)
    # a spoken line: half a second of a 220 Hz tone stands in for the take
    import math
    import struct
    import wave
    wav = os.path.join(tmp, 'line.wav')
    with wave.open(wav, 'wb') as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(24000)
        w.writeframes(b''.join(struct.pack('<h', int(12000 * math.sin(2 * math.pi * 220 * i / 24000))) for i in range(12000)))
    js = ("import { readFileSync } from 'node:fs'; import { voice } from %s; import { RATE } from %s;"
          "const m = JSON.parse(readFileSync('%s')); m.voice = { file: '%s', at: 10 };"
          "const v = voice(m); const rms = (b, t0, t1) => { let s = 0; for (let i = Math.round(t0 * RATE); i < Math.round(t1 * RATE); i++) s += b.L[i] * b.L[i] + b.R[i] * b.R[i]; return Math.sqrt(s / (2 * (t1 - t0) * RATE)); };"
          "let late = ''; try { voice({ ...m, voice: { file: m.voice.file, at: 11.6 } }); } catch (e) { late = e.message; }"
          "let none = ''; try { voice({ ...m, voice: { file: m.voice.file + '.no', at: 10 } }); } catch (e) { none = e.message; }"
          "console.log(JSON.stringify({ n: v.bus.L.length, before: rms(v.bus, 0, 10), said: rms(v.bus, 10, 10.5), middle: v.dry.L.every((x, i) => x === v.dry.R[i]), late, none }))"
          % (json.dumps('file://' + os.path.join(HERE, 'score.mjs')), json.dumps('file://' + os.path.join(HERE, '..', 'motion', 'sound.mjs')), mp, wav))
    r = subprocess.run([node, '--input-type=module', '-e', js], capture_output=True, text=True)
    got = json.loads(r.stdout) if r.returncode == 0 else r.stderr[-400:]
    check('R10d a line said over the end card: in the mix from its second and not before, the same on both sides',
          isinstance(got, dict) and got['n'] == 12 * 48000 and got['before'] < 1e-9 and got['said'] > 0.02 and got['middle'], got)
    check('R10e a line that would run into the end of the film, or a take that cannot be read, stops the score and says why',
          isinstance(got, dict) and 'before the film ends' in got['late'] and 'cannot read the voice' in got['none'], got)
    track_cases(tmp, node, mp)


def track_cases(tmp, node, mp):
    # the four tracks (tracks.mjs) on one uneven film, measured by selfcheck_tracks.mjs, one process each, side by side.
    # Their line is a 1 kHz tone: 220 Hz is A, a note the tracks play, and the music under it would read as the line.
    import checks
    import math
    import struct
    import wave
    wav = os.path.join(tmp, 'line1k.wav')
    with wave.open(wav, 'wb') as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(24000)
        w.writeframes(b''.join(struct.pack('<h', int(12000 * math.sin(2 * math.pi * 1000 * i / 24000))) for i in range(12000)))
    names = ['cuts', 'steady', 'piano', 'laidback', 'cinematic']
    runs = {n: subprocess.Popen([node, os.path.join(HERE, 'selfcheck_tracks.mjs'), wav, n], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            for n in names}
    got = {}
    for n, r in runs.items():
        out, err = r.communicate()
        got[n] = json.loads(out) if r.returncode == 0 else err[-400:]
    if not all(isinstance(g, dict) for g in got.values()):
        check('R10f selfcheck_tracks.mjs measures every track', False, got)
        return
    T = {n: g for n, g in got.items() if n != 'cuts'}
    see = lambda *k: {n: {x: g[x] for x in k} for n, g in T.items()}
    check('R10f every track: the section cuts are bar lines, the eighths join end to end, no bar bent more than 6 %',
          all(g['bars'] and g['joined'] and g['bend'] <= 0.06 for g in T.values()), see('bars', 'joined', 'bend'))
    check('R10g every track: the pad starts before the first frame and never drops out',
          all(g['lead'] < 0 and not g['holes'] for g in T.values()), see('lead', 'holes'))
    check('R10h nothing marks a section cut that is not a big moment or a cut off the grid; steady marks the cut on the grid',
          all(g['unmarked'] == 0 and g['off'] == 0 for g in T.values()) and T['steady']['on'] > 0, see('unmarked', 'off', 'on'))
    check('R10i steady\'s kick is on every half bar from where the music arrives to the end card; piano and cinematic have none',
          T['steady']['beat'] and T['steady']['kicks'] > 0 and T['piano']['kicks'] == 0 and T['cinematic']['kicks'] == 0
          and all(g['kickEnd'] == 0 and g['intro'] == 0 for g in T.values()), see('kicks', 'beat', 'kickEnd', 'intro'))
    check('R10i2 no two kicks an eighth apart where a section ends in a bar of 9 eighths (steady and laidback, at full energy)',
          T['steady']['nine']['kicks'] > 0 and all(T[n]['nine']['tight'] == [] for n in ('steady', 'laidback')),
          {n: T[n]['nine'] for n in ('steady', 'laidback')})
    check('R10j without `major` the music arrives at once: no intro, notes in the first half second',
          all(g['plain']['arrive'] == 0 and g['plain']['intro'] == 0 and g['plain']['early'] > 0 for g in T.values()), see('plain'))
    check('R10k every track builds whole with and without the line; the line comes through as said; nothing sits 9 dB under the middle',
          all(g['sound']['whole'] and abs(g['sound']['line'] - 1) <= 0.05 and g['sound']['bare'] > 0.02
              and g['sound']['first'] >= -9 and g['sound']['low'] >= -9 for g in T.values()), see('sound'))
    cut = got['cuts']['sound']['jumps']
    check('R10l every track is one piece: at most 2 jumps of 4.5 dB a quarter second, fewer than the cut-by-cut score (%d)' % cut,
          got['cuts']['sound']['whole'] and all(g['sound']['jumps'] <= 2 and g['sound']['jumps'] < cut for g in T.values()),
          {n: g['sound']['jumps'] for n, g in got.items()})
    out = os.path.join(tmp, 'nope.mp4')
    r = subprocess.run([node, os.path.join(HERE, 'score.mjs'), os.path.join(tmp, 'none.mp4'), mp, out, '--track', 'nope'], capture_output=True, text=True)
    check('R10m an unknown track stops the score, says so and writes nothing',
          r.returncode == 2 and 'no track "nope"' in r.stderr and not os.path.exists(out) and not os.path.exists(os.path.join(tmp, 'nope.score.json')),
          (r.returncode, r.stderr[-200:]))
    sha = 'a' * 40
    cases = [checks.scored({}, {'marks': sha}, sha), checks.scored({}, {'marks': sha, 'track': 'cuts'}, sha),
             checks.scored({'score': 'piano'}, {'marks': sha, 'track': 'piano'}, sha), checks.scored({'score': 'piano'}, {'marks': sha}, sha),
             checks.scored({'score': 'piano'}, {'marks': sha, 'track': 'steady'}, sha), checks.scored({}, {'marks': 'b' * 40}, sha),
             checks.scored({}, {}, sha)]
    check('R10n check: the score must come from this cut\'s marks and be the track reel.json names (none: cuts)',
          [c[0] for c in cases] == [True, True, True, False, False, False, False] and 'steady' in cases[4][1] and 'another cut' in cases[5][1],
          cases)
    m = {'energy': {'a': 0.5}, 'major': ['a'], 'voice': {'file': 'v.wav', 'at': 3}}
    st = {'marks': sha, 'voice': 'c' * 40}
    more = [checks.scored({}, st, sha, m, dict(m), 'c' * 40), checks.scored({}, st, sha, m, {**m, 'energy': {'a': 0.6}}, 'c' * 40),
            checks.scored({}, st, sha, m, {**m, 'major': []}, 'c' * 40), checks.scored({}, st, sha, m, dict(m), 'd' * 40),
            checks.scored({}, {'marks': sha}, sha, m, dict(m), 'c' * 40)]
    check('R10n2 check: the marks still say what reel.json says (energy, major, voice line) and the voice take is the one mixed',
          [c[0] for c in more] == [True, False, False, False, False] and 'energy' in more[1][1] and 'major' in more[2][1]
          and 'voice take' in more[3][1] and 'voice take' in more[4][1], more)


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
    sheet = os.path.join(tmp, 'build', 'sheet')   # frames made outside prep: no .spec of their own
    os.makedirs(sheet, exist_ok=True)
    open(os.path.join(sheet, '00000.png'), 'w').write('a')
    d0 = reel.deps(cfg, ['seq=' + sheet, 'lens=50'])
    open(os.path.join(sheet, '00000.png'), 'w').write('a larger drawing')
    d1 = reel.deps(cfg, ['seq=' + sheet, 'lens=50'])
    check('R11e a folder of frames made outside prep re-renders its shot when it is made again', d0 and d0 != d1, (d0, d1))
    from PIL import Image
    tpl = os.path.join(tmp, 'tpl.png')   # a whole PNG: the resume drops a frame without its IEND end as cut off mid-write
    Image.new('RGB', (2, 2)).save(tpl)
    fake = os.path.join(tmp, 'blender')   # writes every frame, orbit too, then dies as the time cap kills it
    open(fake, 'w').write('#!/bin/sh\nwhile [ "$1" != -- ]; do shift; done; shift\n'
                          'n=$(($2 + $(echo "$@" | sed -n "s/.*orbit=\\([0-9]*\\).*/\\1/p")))\n'
                          'for f in $(seq 1 $n); do cp ' + tpl + ' $(printf "%s/%04d.png" "$1" $f); done; exit 124\n')
    os.chmod(fake, 0o755)
    cfg = cfg_in(tmp, shots=[dict(name='o', shot='board', frames=3, args='orbit=2')])
    env = {k: os.environ.get(k) for k in ('BLENDER', 'REEL_RUN', 'REEL_DEVICE', 'REEL_QUIET')}
    os.environ.update(BLENDER=fake, REEL_RUN='', REEL_DEVICE='cpu', REEL_QUIET='1')
    try:
        reel.render(cfg, 'preview')
        o = reel.CUT.shot_dir(cfg, 'o', 'preview')
        got = sorted(f for f in os.listdir(o) if f.endswith('.png')), os.path.exists(os.path.join(o, '.done'))
    except SystemExit as x:
        got = str(x)
    finally:
        for k, v in env.items():
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
    check('R11d a board shot counts its orbit frames, and a run the time cap ends after its last frame is done',
          got == (['%04d.png' % f for f in range(1, 6)], True), got)

    # a run killed with frames to go: each run lands one whole frame and leaves the next one cut off mid-write
    runs = os.path.join(tmp, 'runs')
    step = os.path.join(tmp, 'blender-step')
    open(step, 'w').write('#!/bin/sh\necho x >> ' + runs + '\nwhile [ "$1" != -- ]; do shift; done; shift\n'
                          'for f in $(seq 1 $2); do p=$(printf "%s/%04d.png" "$1" $f)\n'
                          '  if [ -f $p ] && tail -c 8 $p | grep -q IEND; then continue; fi\n'
                          '  cp ' + tpl + ' $p; q=$(printf "%s/%04d.png" "$1" $((f + 1))); head -c 20 ' + tpl + ' > $q 2>/dev/null; exit 137\n'
                          'done; exit 0\n')
    os.chmod(step, 0o755)
    stall = os.path.join(tmp, 'blender-stall')   # lands nothing, every run
    open(stall, 'w').write('#!/bin/sh\necho x >> ' + runs + '\nexit 137\n')
    os.chmod(stall, 0o755)
    import time as _time
    sleep, _time.sleep = _time.sleep, lambda s: None
    env = {k: os.environ.get(k) for k in ('BLENDER', 'REEL_RUN', 'REEL_DEVICE', 'REEL_QUIET')}
    os.environ.update(REEL_RUN='', REEL_DEVICE='cpu', REEL_QUIET='1')
    try:
        os.environ['BLENDER'] = step
        cfg = cfg_in(tmp, shots=[dict(name='r', shot='board', frames=4)])
        reel.render(cfg, 'preview')
        o = reel.CUT.shot_dir(cfg, 'r', 'preview')
        whole = [reel.whole_png(os.path.join(o, '%04d.png' % f)) for f in range(1, 5)]
        resumed = (whole, os.path.exists(os.path.join(o, '.done')))
        os.environ['BLENDER'] = stall
        open(runs, 'w').close()
        cfg = cfg_in(tmp, shots=[dict(name='s', shot='board', frames=2)])
        try:
            reel.render(cfg, 'preview')
            gave_up = 'finished'
        except SystemExit:
            gave_up = len(open(runs).read().split())
    finally:
        _time.sleep = sleep
        for k, v in env.items():
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
    check('R11f a shot killed with frames to go resumes, and draws again a frame a kill cut off mid-write',
          resumed == ([True] * 4, True), resumed)
    check('R11g a shot gives up after 3 runs in a row that land no frame', gave_up == 3, gave_up)
    bad = []
    for name in ('', '.', '../..', 'a/b'):
        try:
            cfg_in(tmp, shots=[dict(name=name, shot='board', frames=1)])
        except SystemExit:
            bad.append(name)
    check('R11h a shot named so its folder is a parent (\'\', ., ../..) is refused before anything is emptied',
          bad == ['', '.', '../..', 'a/b'], bad)


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
    # a real front page: a title that starts inside the left corner, a logo in the right one, a shop button below
    from PIL import ImageDraw
    src2 = os.path.join(tmp, 'ds2')
    os.makedirs(src2)
    pg = Image.new('RGB', (850, 1100), (255, 255, 255))
    d = ImageDraw.Draw(pg)
    for x in range(200, 650, 17):
        d.rectangle((x, 60, x + 11, 80), fill=(0, 0, 0))               # the title, letter by letter
    d.rectangle((700, 20, 800, 60), fill=(0, 0, 0))                    # the logo
    d.rectangle((400, 120, 440, 140), fill=(200, 20, 20))              # the shop button, in colour
    d.rectangle((100, 600, 750, 610), fill=(0, 0, 0))                  # the text
    pg.save(os.path.join(src2, 'amp_datasheet.png'))
    idx = pages.prep(os.path.join(tmp, 'pages2'), [src2])
    im = Image.open(os.path.join(tmp, 'pages2', idx[0]['file']))
    px = {k: im.getpixel(v)[1] for k, v in dict(title_in_corner=(205, 70), title=(545, 70), logo=(750, 40),
                                                button=(420, 130), text=(400, 605)).items()}
    check('R12 datasheet pages: a title is never cut by the logo corner; the logo and a coloured button go whole',
          px['title_in_corner'] < 60 and px['title'] < 60 and px['text'] < 60 and px['logo'] > 240 and px['button'] > 240, px)
    wide = Image.new('RGB', (2200, 1100), (255, 255, 255))             # a drawing in landscape with a round mark on it
    ImageDraw.Draw(wide).ellipse((900, 350, 1300, 750), fill=(0, 0, 0))
    src3 = os.path.join(tmp, 'ds3')
    os.makedirs(src3)
    wide.save(os.path.join(src3, 'sheet-schematic.png'))
    idx = pages.prep(os.path.join(tmp, 'pages3'), [src3])
    im = Image.open(os.path.join(tmp, 'pages3', idx[0]['file'])).convert('L')
    box = im.point(lambda v: 255 * (v < 128)).getbbox()
    check('R12b a page is fitted on the sheet in its own proportions: a circle on a landscape drawing stays round',
          im.size == (850, 1100) and box is not None and abs((box[2] - box[0]) - (box[3] - box[1])) <= 2
          and abs((box[0] + box[2]) / 2 - 425) <= 2 and abs((box[1] + box[3]) / 2 - 550) <= 2, (im.size, box))


def match_cases(tmp):
    import common as K
    got = [K.match_size(*a) for a in (((1920, 1080), 'final', True), ((1920, 1080), 'final', False), ((2560, 1440), 'final', False),
                                      ((3840, 2160), 'final', False), ((1920, 1080), 'preview', True), ((1920, 1080), 'preview', False))]
    check('R13 a studio match shot is rendered at the film\'s size, not at a smaller clip\'s and enlarged; on the filmed table never larger than the clip',
          got == [(2560, 1440), (1920, 1080), (2560, 1440), (2560, 1440), (1280, 720), (1280, 720)], got)
    soft = [K.match_soft(F, 28, True) for F in range(1, 61)]
    check('R13b a studio render takes the clip\'s softness on only where it meets the clip: none 12 frames before, all of it from the clip\'s first frame on',
          soft[0] == 0 and soft[15] == 0 and 0 < soft[21] < 1 and soft[27] == 1 and soft[59] == 1 and all(y >= x for x, y in zip(soft, soft[1:]))
          and K.match_soft(1, 28, False) == 1, [round(v, 3) for v in soft[14:29]])


def shot_cases(tmp):
    """the shot scripts run inside Blender only, so nothing here can run them: read them instead"""
    import ast
    here = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'shots')
    tree = ast.parse(open(os.path.join(here, '_shot.py')).read())
    have = set()
    for n in tree.body:
        if isinstance(n, (ast.FunctionDef, ast.ClassDef)):
            have.add(n.name)
        elif isinstance(n, (ast.Import, ast.ImportFrom)):
            have.update((a.asname or a.name).split('.')[0] for a in n.names)
        elif isinstance(n, ast.Assign):
            have.update(t.id for t in n.targets if isinstance(t, ast.Name))
    lost = []
    for f in sorted(os.listdir(here)):
        if not f.endswith('.py') or f == '_shot.py':
            continue
        t = ast.parse(open(os.path.join(here, f)).read())
        if not any(isinstance(n, ast.Import) and any(a.name == '_shot' and a.asname == 'K' for a in n.names) for n in ast.walk(t)):
            continue
        lost += ['%s: K.%s' % (f, n.attr) for n in ast.walk(t)
                 if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) and n.value.id == 'K' and n.attr not in have]
    check('R14 every K.name a shot script reads is in shots/_shot.py (a helper moved to common.py was not: the final stopped on its first shot)',
          not lost, sorted(set(lost)))


def main():
    tmp = tempfile.mkdtemp(prefix='br-check-')
    try:
        for case in (drawing_cases, layout_cases, model_cases, standin_cases, rule_cases, score_cases, reel_cases, pages_cases, match_cases, shot_cases):
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
