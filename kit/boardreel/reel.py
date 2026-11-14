"""A board reel from a board project, in one command: the design's own files in, a scored film out.

    python3 reel.py build  reel.json [--final]     prep, render, cut, score, check (each step skips what is done)
    python3 reel.py prep   reel.json               3D models, case parts, datasheet pages, routing history, drawings
    python3 reel.py render reel.json [--final] [--only NAME,...]
    python3 reel.py cut    reel.json [--final]     the cut, then its score (a re-timed cut is always re-scored)
    python3 reel.py check  reel.json [--final]

reel.json (see kit/KIT.md for a whole one): `source` (the board project, read only), `board`, `sheet`,
`enclosure`, `research` (paths in the source), `prompt` (the request as written, in the film folder), `title`,
`drawings` (frame sequences made from the design: prompt, schematic, layout replay/trace), `shots` (film order:
Blender shots and `slot` lines for real footage) and optionally `build` (scratch; default ./build), `film`
(where the finished film goes), `allow` (stutter spans to skip), `length` [min, max] seconds,
`heights` (a part-heights file in the source, the enclosure tool's format: sizes the stand-in block drawn for
any part the design has no 3D model for), `spp` {quality: samples} for every shot that sets none (a 1440p final at the board shots' 160 takes a day; 48 to 64
with the denoiser costs a third of that).

A shot line: {name, section, shot: paper|pages|board, frames, args, use, hold, xfade}. In args, `@NAME` is the
folder of drawing NAME, or of a prep output (`@real` models, `@case` enclosure, `@pages` datasheets); `@NAME/x` a
file or folder inside it. Every Blender run and every drawing goes through $REEL_RUN (default `heavy timeout 3600`
when `heavy` is on the PATH), so a render cannot take the machine's memory. A shot whose args change is rendered
again from scratch; one whose args did not resumes where it stopped.
"""
import argparse
import glob
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import common as K  # noqa: E402
import cut as CUT  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(HERE))          # the module
SHOTS = {'paper': 'paper.py', 'pages': 'pages.py', 'board': 'board.py'}
PREP = ('real', 'case', 'pages', 'timeline')


def say(*a):
    print('reel:', *a, flush=True)


def wrap():
    w = os.environ.get('REEL_RUN')
    if w is not None:
        return shlex.split(w)
    return ['heavy', 'timeout', '3600'] if shutil.which('heavy') else []


def run(cmd, **kw):
    say(' '.join(shlex.quote(str(c)) for c in cmd[:6]) + (' ...' if len(cmd) > 6 else ''))
    r = subprocess.run(wrap() + [str(c) for c in cmd], **kw)
    if r.returncode:
        raise SystemExit('reel: failed (%d): %s' % (r.returncode, ' '.join(map(str, cmd[:4]))))


def tool(name):
    """a program: $NAME (BLENDER, KICAD_CLI), the module's own Blender cache (for blender), or the PATH"""
    env = os.environ.get(name.upper().replace('-', '_'))
    if env:
        return env
    if name == 'blender':   # the official build first: a distro Blender often has no OptiX/CUDA and renders on the CPU
        c = sorted(glob.glob(os.path.expanduser('~/.cache/hive-video/blender-*/blender')))
        if c:
            return c[-1]
    w = shutil.which(name)
    if w:
        return w
    raise SystemExit('reel: %s not found; set $%s' % (name, name.upper().replace('-', '_')))


def fresh(d, spec):
    """make d hold output for spec: kept if spec is unchanged, emptied if not. True if already complete."""
    tag = hashlib.sha1(json.dumps(spec, sort_keys=True).encode()).hexdigest()[:12]
    stamp = os.path.join(d, '.spec')
    if os.path.isdir(d) and (not os.path.exists(stamp) or open(stamp).read() != tag):
        shutil.rmtree(d)
    os.makedirs(d, exist_ok=True)
    open(stamp, 'w').write(tag)
    return os.path.exists(os.path.join(d, '.done'))


def code(*files):
    """a short hash of kit source files: a part of every spec, so a changed tool or shot script redraws what it made
    (the second film's new palette did not reach drawings that were already made)"""
    h = hashlib.sha1()
    for f in files:
        h.update(open(os.path.join(HERE, f), 'rb').read())
    return h.hexdigest()[:12]


def deps(cfg, args):
    """the .spec of every build folder a shot's args point into, so a re-made input re-renders the shot"""
    b, out = os.path.abspath(K.build_dir(cfg)), []
    for a in args:
        v = os.path.abspath(a.split('=', 1)[-1]) if '=' in a else ''
        while v.startswith(b + os.sep):
            if os.path.exists(os.path.join(v, '.spec')):
                out.append(open(os.path.join(v, '.spec')).read())
                break
            v = os.path.dirname(v)
    return out


def done(d):
    open(os.path.join(d, '.done'), 'w').write('')


# ---- prep: everything the shots draw from, once ------------------------------------------------------------------

def models(pcb_path):
    """{reference: visible 3D models} for every footprint on the board. One each: a footprint with two draws its part
    doubled (the first film's connector), one with none leaves a hole in the drop."""
    from kicad import sexpr, kids, hidden, _ref   # noqa: E402  (kit/blender, put on the path by common)
    pcb = sexpr(open(pcb_path).read())
    out = {}
    for fp in kids(pcb, 'footprint'):
        ref = _ref(fp)
        if not ref or ref.startswith('#') or any('board_only' in a for a in kids(fp, 'attr')):   # holes, logos
            continue
        out[ref] = sum(1 for m in kids(fp, 'model') if not hidden(m))
    return out


def prep(cfg):
    b = K.build_dir(cfg)
    board = K.src(cfg, cfg['board'])
    real = os.path.join(b, 'real')
    heights = K.src(cfg, cfg['heights']) if cfg.get('heights') else None
    if not fresh(real, [board, os.path.getmtime(board), heights, heights and os.path.getmtime(heights), code('standin.py')]):
        cli = tool('kicad-cli')
        common = ['--subst-models', '--force']
        run([cli, 'pcb', 'export', 'glb', '--no-components', '--include-tracks', '--include-pads', '--include-zones',
             '--include-silkscreen', '--include-soldermask', '--cut-vias-in-body', *common, '-o', os.path.join(real, 'board.glb'), board])
        import standin   # every part shows: a model-less footprint gets a block of its own size
        say('stand-in bodies:', ' '.join(standin.make(board, real, heights)) or 'none needed')
        run([cli, 'pcb', 'export', 'glb', '--no-board-body', *common, '-o', os.path.join(real, 'parts.glb'),
             os.path.join(real, 'standin.kicad_pcb')])
        done(real)
    if cfg.get('enclosure'):
        case = os.path.join(b, 'case')
        enc = K.src(cfg, cfg['enclosure'])
        if not fresh(case, [enc]):
            py = cfg.get('cad_python') or os.environ.get('CAD_PYTHON') or sys.executable
            run([sys.executable, os.path.join(HERE, 'case.py'), enc, case, '--python', os.path.expanduser(py)])
            done(case)
    if cfg.get('research'):
        pages = os.path.join(b, 'pages')
        srcs = [K.src(cfg, r) for r in cfg['research']]
        if not fresh(pages, [srcs, cfg.get('pages', 3)]):
            run([sys.executable, os.path.join(HERE, 'pages.py'), pages, *srcs, '--pages', cfg.get('pages', 3)])
            done(pages)
    tl = os.path.join(b, 'timeline')
    if not fresh(tl, [board, os.path.getmtime(board), cfg.get('also', [])]):
        run([sys.executable, os.path.join(HERE, 'history.py'), board, os.path.join(tl, 'timeline.json'),
             *sum((['--also', a] for a in cfg.get('also', [])), [])])
        done(tl)
    for name, d in cfg.get('drawings', {}).items():
        drawing(cfg, name, d)


def drawing(cfg, name, d):
    out = os.path.join(K.build_dir(cfg), 'drawings', name)
    tool_py = d['tool'].split()[0] + '.py' if d['tool'] in ('prompt', 'schematic') else 'layout.py'
    if fresh(out, [d, code(tool_py, 'common.py')]):
        return
    t, py = d['tool'], [sys.executable, os.path.join(HERE, d['tool'].split()[0] + '.py')]
    opt = lambda k, flag=None: ['--' + (flag or k), str(d[k])] if k in d else []   # noqa: E731
    if t == 'prompt':
        run(py + [K.film(cfg, cfg['prompt']), out, *opt('frames'), *opt('hold'), *opt('label'),
                  *sum((['--phrase', p] for p in d.get('phrases', [])), [])])
    elif t == 'schematic':
        crop = d.get('crop')
        run(py + [K.src(cfg, d.get('sheet', cfg['sheet'])), out, *opt('frames'), *opt('width'), *opt('t'), *opt('pow'),
                  *opt('order'), *opt('bold'), *(['--crop', ','.join(map(str, crop))] if crop else [])])
    elif t in ('layout', 'trace'):
        tl = os.path.join(K.build_dir(cfg), 'timeline', 'timeline.json')
        run(py[:1] + [os.path.join(HERE, 'layout.py'), 'replay' if t == 'layout' else 'trace', K.src(cfg, cfg['board']), tl, out,
                      *opt('frames'), *opt('width'), *opt('from'), *opt('to'), *opt('hold'), *opt('event'),
                      *(['--rev'] if d.get('rev') else [])])
    else:
        raise SystemExit('reel: drawing %s: unknown tool %r' % (name, t))
    done(out)


# ---- render: each Blender shot, resumable ------------------------------------------------------------------------

def expand(cfg, args):
    b = K.build_dir(cfg)

    def at(m):
        name, rest = m.group(1), m.group(2) or ''
        if name in cfg.get('drawings', {}):
            return os.path.join(b, 'drawings', name) + rest
        if name in PREP:
            return os.path.join(b, name) + rest
        raise SystemExit('reel: @%s is neither a drawing nor %s' % (name, ', '.join(PREP)))
    return re.sub(r'@([A-Za-z0-9_-]+)(/[^\s]*)?', at, args).split()


def render(cfg, quality, only=None):
    blender = tool('blender')
    for line in cfg['shots']:
        if 'slot' in line or (only and line['name'] not in only):
            continue
        out = CUT.shot_dir(cfg, line['name'], quality)
        args = expand(cfg, line.get('args', ''))
        spp = cfg.get('spp', {}).get(quality)
        if spp and not any(a.startswith('spp=') for a in args):
            args.append('spp=%d' % spp)
        nf = int(line['frames'])
        orb = next((int(w.split('=', 1)[1]) for w in args if w.startswith('orbit=')), 0)   # board.py renders the orbit after the frames
        a, b = line.get('use', [1, nf + orb])
        if [a, b] != [1, nf + orb]:
            args.append('span=%d,%d' % (a, b))
        if fresh(out, [line.get('shot'), nf, args, code('shots/' + SHOTS[line['shot']], 'shots/_shot.py'), deps(cfg, args)]):
            continue
        def missing():
            return [f for f in range(a, b + 1) if not os.path.exists(os.path.join(out, '%04d.png' % f))]
        cpu = 'device=cpu' in args or os.environ.get('REEL_DEVICE') == 'cpu'
        lock = os.path.expanduser('~/.cache/hive-video/gpu.lock')   # the card has room for one render: take turns, as `video blender` does
        gpu = ['flock', lock] if not cpu and shutil.which('flock') and os.path.isdir(os.path.dirname(lock)) else []
        left, stuck = None, 0
        while True:   # a long shot outlives one run's time cap, and memguard kills the biggest job in a memory stall:
            try:      # Blender skips the frames on disk, so go again; give up after 3 runs in a row that land nothing
                run(gpu + [blender, '-b', '--factory-startup', '-P', os.path.join(HERE, 'shots', SHOTS[line['shot']]), '--',
                     out, nf, *args, 'quality=' + quality], stdout=subprocess.DEVNULL if os.environ.get('REEL_QUIET') else None)
                break
            except SystemExit:
                now = len(missing())
                stuck = stuck + 1 if left is not None and now >= left else 0
                if not now:
                    break   # stopped by the time cap after the last frame it needs: that is done
                if stuck >= 3:
                    raise
                left = now
                say('%s stopped with %d frames to go; resuming%s' % (line['name'], now, ' in a minute' if stuck else ''))
                if stuck:
                    time.sleep(60)   # a stall that killed it may still be on
        miss = missing()
        if miss:
            raise SystemExit('reel: %s is missing %d of frames %d-%d' % (line['name'], len(miss), a, b))
        done(out)


# ---- cut and score -----------------------------------------------------------------------------------------------

def paths(cfg, quality):
    b = os.path.join(K.build_dir(cfg), quality)
    return dict(silent=os.path.join(b, 'silent.mp4'), marks=os.path.join(b, 'silent.marks.json'),
                film=os.path.join(b, 'film.mp4'), sheet=os.path.join(b, 'sheet.jpg'),
                stamp=os.path.join(b, 'film.score.json'))


def cut_and_score(cfg, quality):
    p = paths(cfg, quality)
    _, marks = CUT.cut(cfg, quality, p['silent'], p['sheet'])
    if cfg.get('energy'):
        marks['energy'] = cfg['energy']
        json.dump(marks, open(p['marks'], 'w'), indent=1)
    subprocess.run(['node', os.path.join(HERE, 'score.mjs'), p['silent'], p['marks'], p['film']], check=True)
    dst = cfg.get('film')
    if dst:
        dst = K.film(cfg, dst.replace('{quality}', quality))
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copyfile(p['film'], dst)
        shutil.copyfile(p['sheet'], os.path.splitext(dst)[0] + '-sheet.jpg')
        say('film: %s (%.1f s)' % (dst, marks['seconds']))
    return p


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('cmd', choices=['build', 'prep', 'render', 'cut', 'check'])
    ap.add_argument('reel')
    ap.add_argument('--final', action='store_true')
    ap.add_argument('--only')
    o = ap.parse_args(argv)
    cfg = K.load(o.reel)
    q = 'final' if o.final else 'preview'
    if o.cmd in ('build', 'prep'):
        prep(cfg)
    if o.cmd in ('build', 'render'):
        render(cfg, q, o.only.split(',') if o.only else None)
    if o.cmd in ('build', 'cut'):
        cut_and_score(cfg, q)
    if o.cmd in ('build', 'check'):
        import checks
        bad = checks.report(checks.run(cfg, q))
        sys.exit(1 if bad else 0)


if __name__ == '__main__':
    main()
