"""The board reel's rules, checked on the film itself: the lessons the first film paid for, so the next one cannot
quietly break them. `reel.py check` (and `build`) runs them; exit 1 if any fails.

    python3 checks.py reel.json [--final]

  drawing     every paper shot on a schematic drawing adds ink on every frame it uses, first to last (a cut that
              opens or closes on a still drawing reads as a stall)
  models      every footprint has exactly one visible 3D model (two draw the part doubled); none is reported
  drops       in each fall shot the drops speed up: the gaps between landings in its last third are shorter than in
              its first
  smooth      `video stutters` on the film (the film's own cuts skipped): no frozen frames inside a move, no flash
              frames; sharp moments are listed with their times to look at, not failed
  words       what the film says on screen (title, status, credit, labels) names no model, gives no count, claims
              nothing works, and is not hype
  score       the score was made from this cut's marks (re-time, re-score)
  length      the film is inside reel.json's `length` [min, max] seconds, default 45 to 70
"""
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import common as K  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(HERE))
BANNED = [
    (r'\b(claude|opus|sonnet|haiku|fable|gpt|gemini|llm|ai-designed|ai designed)\b', 'names a model'),
    (r'\b\d+\s*(parts|components|tracks|traces|vias|nets|pads|footprints|hours|agents|runs)\b', 'gives a count'),
    (r'(?<!not )(?<!not yet )\b(works|working|tested|proven|verified|guaranteed|flawless|perfect)\b', 'claims it works'),
    (r'\b(revolution\w*|game.?chang\w*|magic\w*|incredible|amazing|insane|stunning|blazing|unleash\w*|next.?level)\b', 'hype'),
]


def kv(args):
    return dict(w.split('=', 1) for w in args.split() if '=' in w)


def drawing(cfg):
    """[(shot, ok, detail)] for every paper shot whose seq= is a schematic drawing"""
    out = []
    for line in cfg['shots']:
        if line.get('shot') != 'paper':
            continue
        a = kv(line.get('args', ''))
        m = re.match(r'@([\w-]+)$', a.get('seq', ''))
        d = cfg.get('drawings', {}).get(m.group(1)) if m else None
        if not d or d['tool'] != 'schematic':
            continue
        new = json.load(open(os.path.join(K.build_dir(cfg), 'drawings', m.group(1), 'new.json')))['new']
        nf = int(line['frames'])
        first, last = line.get('use', [1, nf])
        sq = dict(seq0=int(a.get('seq0', 0)), seqn=int(a.get('seqn', len(new))), rate=float(a.get('rate', 1)), ramp=float(a.get('ramp', 0)))
        sq['seqn'] = min(sq['seqn'], len(new))
        still = []
        prev = K.seq_frame(first - 1, nf, **sq) if first > 1 else sq['seq0'] - 1
        for f in range(first, last + 1):
            k = K.seq_frame(f, nf, **sq)
            if sum(new[max(0, prev + 1):k + 1]) == 0:
                still.append(f)
            prev = k
        out.append((line['name'], not still, 'still on frames %s' % _spans(still) if still else 'ink on all %d frames' % (last - first + 1)))
    return out


def _spans(fs):
    if not fs:
        return ''
    out, a = [], fs[0]
    for x, y in zip(fs, fs[1:] + [None]):
        if y != x + 1:
            out.append('%d' % a if a == x else '%d-%d' % (a, x))
            a = y
    return ','.join(out[:6]) + (' ...' if len(out) > 6 else '')


def drops(cfg, quality):
    out = []
    for line in cfg['shots']:
        if line.get('shot') != 'board' or 'fall' not in line.get('args', '').split():
            continue
        ev = os.path.join(K.build_dir(cfg), quality, 'shots', line['name'], 'events.json')
        lands = sorted(set(json.load(open(ev))['lands'])) if os.path.exists(ev) else []
        if len(lands) < 6:
            out.append((line['name'], False, '%d landings: too few to read as a pour' % len(lands)))
            continue
        gaps = [b - a for a, b in zip(lands, lands[1:])]
        n = len(gaps) // 3
        early, late = sum(gaps[:n]) / n, sum(gaps[-n:]) / n
        out.append((line['name'], late < early, 'gap %.1f -> %.1f frames' % (early, late)))
    return out


def smooth(out):
    """('smooth', ok, detail) from `video stutters` output: frozen frames inside a move and flash frames fail; sharp
    moments (a part falling past the lens, a lid shutting) are listed to look at, not failed: the first film passed
    review with 22 of them"""
    num = lambda k: int((re.search(r'^%s: (\d+)' % k, out, re.M) or [0, -1])[1])   # noqa: E731
    st, js, fl = num('stutters'), num('jerks'), num('flash frames')
    sharp = re.findall(r'^\s+([\d.]+(?:-[\d.]+)? s \w+)$', out, re.M)
    ok = st == 0 and fl == 0
    return ('smooth', ok, 'stutters %d, flash frames %d, sharp moments %d%s' % (
        st, fl, max(js, 0), (' (look at: %s)' % ', '.join(sharp[:8])) if sharp else ''))


def cut_spans(marks):
    """the film's own hard cuts, a frame either side, as stutter spans to skip: two paper shots cut together differ
    too little for the detector to see a cut, so it reads them as a jump inside a move"""
    fps = marks['fps']
    return ['%.3f-%.3f' % ((s['start'] * fps - 1) / fps, (s['start'] * fps + 1) / fps)
            for s in marks['shots'][1:]]


def words(cfg):
    import cut
    said = [cfg.get('title', ''), cut.status(cfg), cfg.get('credit', '')]
    said += [d.get('label', '') for d in cfg.get('drawings', {}).values()]
    said += re.findall(r'(?:label|caption)=(\S+)', ' '.join(l.get('args', '') for l in cfg['shots']))
    bad = []
    for s in filter(None, said):
        for rx, why in BANNED:
            if re.search(rx, s, re.I):
                bad.append('%r %s' % (s, why))
    return bad


def run(cfg, quality):
    import reel
    p = reel.paths(cfg, quality)
    res = [('drawing ' + n, ok, d) for n, ok, d in drawing(cfg)]
    m = reel.models(K.src(cfg, cfg['board']))
    two = sorted(r for r, n in m.items() if n > 1)
    none = sorted(r for r, n in m.items() if n == 0)
    res.append(('models', not two, ('doubled: %s' % ' '.join(two) if two else 'one each') + ('; no model: %s' % ' '.join(none) if none else '')))
    res += [('drops ' + n, ok, d) for n, ok, d in drops(cfg, quality)]
    if os.path.exists(p['film']):
        spans = list(cfg.get('allow', [])) + cut_spans(json.load(open(p['marks'])))
        allow = ['--allow', ','.join(spans)] if spans else []
        r = subprocess.run(['node', os.path.join(ROOT, 'bin', 'video.mjs'), 'stutters', p['film'], *allow], capture_output=True, text=True)
        res.append(smooth(r.stdout + r.stderr))
        stamp = json.load(open(p['stamp'])) if os.path.exists(p['stamp']) else {}
        same = stamp.get('marks') == hashlib.sha1(open(p['marks'], 'rb').read()).hexdigest()
        res.append(('score', same, 'made from this cut' if same else 'made from another cut: run reel.py cut'))
        secs = json.load(open(p['marks']))['seconds']
        lo, hi = cfg.get('length', [45, 70])
        res.append(('length', lo <= secs <= hi, '%.1f s (%g to %g)' % (secs, lo, hi)))
    else:
        res.append(('film', False, 'no %s: run reel.py cut' % p['film']))
    w = words(cfg)
    res.append(('words', not w, '; '.join(w) or 'clean'))
    return res


def report(res):
    for name, ok, detail in res:
        print('%s %-22s %s' % ('ok  ' if ok else 'FAIL', name, detail))
    return sum(1 for _, ok, _ in res if not ok)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('reel')
    ap.add_argument('--final', action='store_true')
    o = ap.parse_args(argv)
    sys.exit(1 if report(run(K.load(o.reel), 'final' if o.final else 'preview')) else 0)


if __name__ == '__main__':
    main()
