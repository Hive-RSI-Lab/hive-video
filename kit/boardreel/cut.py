"""The cut: rendered shots, then any real footage, then the end card, into one silent MP4 with its marks and a
contact sheet. reel.py runs it; the score is laid on afterwards from the marks (score.mjs), never typed by hand.

    python3 cut.py reel.json [--final] [--out FILM.mp4] [--sheet SHEET.jpg]

The shot list is reel.json's `shots`, in film order. A shot line takes frames `use` [first, last] of its render
(default all), holds the last picture `hold` frames with a slow push-in (a held picture never sits still), and may
dissolve in over `xfade` frames. A `slot` line is a place for real footage: it takes every picture and clip in its
folder, in name order, and is left out cleanly while the folder is empty. The end card's status line follows the
slots: no photos, "design files only / not yet built"; photos, "built"; testing footage, "on the bench". It never
says the hardware works.

Writes FILM.mp4 (silent), FILM.marks.json (where every shot starts, every part lands, every hit falls) and the
contact sheet.
"""
import argparse
import glob
import json
import os
import subprocess
import sys

from PIL import Image, ImageDraw

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as K  # noqa: E402

PICS = ('.jpg', '.jpeg', '.png', '.webp')
CLIPS = ('.mp4', '.mov', '.m4v', '.mkv', '.webm')
END_FRAMES = 75
STATUS = {'none': 'DESIGN FILES ONLY  /  NOT YET BUILT', 'photos': 'BUILT  /  NOT YET TESTED',
          'testing': 'BUILT  /  ON THE BENCH'}


def ease_out(u):
    u = max(0., min(1., u))
    return 1 - (1 - u) ** 3


def zoom(im, z, anchor=(0.5, 0.5)):
    W, H = im.size
    cw, ch = W / z, H / z
    x0, y0 = (W - cw) * anchor[0], (H - ch) * anchor[1]
    return im.resize((W, H), Image.BICUBIC, box=(x0, y0, x0 + cw, y0 + ch))


def fit(im, size):
    """a photo near the film's shape fills the frame; anything else (a plot, a portrait photo) sits whole on paper"""
    W, H = size
    r = (im.width / im.height) / (W / H)
    if 0.85 < r < 1.18:
        s = max(W / im.width, H / im.height)
        im = im.resize((round(im.width * s), round(im.height * s)), Image.LANCZOS)
        x, y = (im.width - W) // 2, (im.height - H) // 2
        return im.crop((x, y, x + W, y + H))
    s = min(W * 0.86 / im.width, H * 0.86 / im.height)
    im = im.resize((round(im.width * s), round(im.height * s)), Image.LANCZOS)
    out = Image.new('RGB', (W, H), K.CARD_PAPER)
    out.paste(im, ((W - im.width) // 2, (H - im.height) // 2))
    return out


def slot_files(cfg, line):
    d = K.film(cfg, line['dir'])
    fs = sorted(glob.glob(os.path.join(d, '*')))
    return [f for f in fs if f.lower().endswith(PICS + CLIPS)]


def slot_frames(cfg, line, size):
    """real footage: each picture `each` seconds (default 3) with a slow push-in; each clip up to `max` seconds"""
    W, H = size
    each, cap = float(line.get('each', 3)), float(line.get('max', 6))
    for f in slot_files(cfg, line):
        if f.lower().endswith(PICS):
            base = fit(Image.open(f).convert('RGB'), size)
            n = int(round(each * K.FPS))
            for i in range(n):
                yield zoom(base, 1 + 0.04 * (i / max(1, n - 1)) ** 1.2)
        else:
            p = subprocess.Popen(['ffmpeg', '-loglevel', 'error', '-i', f, '-t', str(cap), '-vf',
                                  'fps=%d,scale=%d:%d:force_original_aspect_ratio=increase,crop=%d:%d' % (K.FPS, W, H, W, H),
                                  '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-'], stdout=subprocess.PIPE)
            while True:
                b = p.stdout.read(W * H * 3)
                if len(b) < W * H * 3:
                    break
                yield Image.frombytes('RGB', (W, H), b)
            p.wait()


def status(cfg):
    if cfg.get('status'):
        return cfg['status']
    filled = {line['slot'] for line in cfg['shots'] if 'slot' in line and slot_files(cfg, line)}
    kinds = {line.get('kind', 'testing' if 'test' in line['slot'] else 'photos') for line in cfg['shots']
             if 'slot' in line and line['slot'] in filled}
    return STATUS['testing'] if 'testing' in kinds else STATUS['photos'] if kinds else STATUS['none']


def end_card(cfg, size, i):
    """title, a rule and the status, then who made it; each part slides up on its own delay, the card drifts in"""
    W, H = size
    s = W / 1920
    im = Image.new('RGB', (W, H), K.CARD_PAPER)
    lay = Image.new('RGBA', (W, H), (0, 0, 0, 0))

    def put(delay, draw):
        k = ease_out((i - delay) / 16)
        if k <= 0:
            return
        p = Image.new('RGBA', (W, H), (0, 0, 0, 0))
        draw(ImageDraw.Draw(p), k)
        if k < 1:
            p.putalpha(p.getchannel('A').point(lambda v: int(v * k)))
        lay.alpha_composite(p, (0, int(round(28 * s * (1 - k)))))
    x = 96 * s

    def title(d, k):
        f, xx = K.font('display', 104 * s), x
        for ch in cfg.get('title', 'A board'):
            d.text((xx, 560 * s), ch, font=f, fill=K.CARD_INK + (255,), anchor='ls')
            xx += f.getlength(ch) - 2.1 * s

    def rule(d, k):
        d.line([(x, 610 * s), (x + 464 * s * k, 610 * s)], fill=K.CARD_INK + (255,), width=max(1, round(2 * s)))
        d.text((x, 664 * s), status(cfg), font=K.font('mono', 26 * s), fill=K.CARD_INK2 + (255,), anchor='ls')

    def made(d, k):
        fb = K.font('body', 34 * s)
        d.text((x, H - 44 * s), 'Made by the Hive', font=fb, fill=K.CARD_INK + (255,), anchor='ls')
        d.text((x + fb.getlength('Made by the Hive') + 36 * s, H - 44 * s), 'hivelab.ca', font=K.font('mono', 26 * s),
               fill=K.CARD_INK2 + (255,), anchor='ls')
    put(0, title)
    put(5, rule)
    put(10, made)
    im = im.convert('RGBA')
    im.alpha_composite(lay)
    return zoom(im.convert('RGB'), 1 + 0.08 * min(1., i / END_FRAMES), anchor=(0, 0.5))   # anchored on the left margin


def credit(cfg, im):
    """an optional credit (reel.json `credit`), small in the lower right of every frame; none by default"""
    if not cfg.get('credit'):
        return im
    W, H = im.size
    s = W / 1920
    lay = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(lay).text((W - 56 * s, H - 44 * s), cfg['credit'], font=K.font('mono', 24 * s), fill=K.CARD_INK2 + (240,), anchor='rs')
    im = im.convert('RGBA')
    im.alpha_composite(lay)
    return im.convert('RGB')


def shot_dir(cfg, name, quality):
    return os.path.join(K.build_dir(cfg), quality, 'shots', name)


def frames(cfg, quality, marks):
    size = K.SIZES[quality]
    last, n = None, 0
    for line in cfg['shots']:
        if 'slot' in line:
            start = n
            for im in slot_frames(cfg, line, size):
                yield line['slot'], im
                n += 1
            if n > start:
                marks['shots'].append(dict(name=line['slot'], section='slot', start=start / K.FPS, frames=n - start))
                last = None
            continue
        d = shot_dir(cfg, line['name'], quality)
        files = sorted(glob.glob(os.path.join(d, '[0-9]*.png')))
        if not files:
            raise SystemExit('cut: shot %s has no frames in %s; render it first (reel.py render)' % (line['name'], d))
        a, b = line.get('use', [1, len(files)])
        hold, xf = int(line.get('hold', 0)), int(line.get('xfade', 0))
        marks['shots'].append(dict(name=line['name'], section=line.get('section', line['name']), start=n / K.FPS, frames=b - a + 1 + hold))
        ev = os.path.join(d, 'events.json')
        if os.path.exists(ev):
            e = json.load(open(ev))
            for f in e.get('lands', []):
                if a <= f <= b:
                    marks['lands'].append(round((n + f - a) / K.FPS, 3))
            for f in e.get('hits', []):
                if a <= f <= b:
                    marks['hits'].append(round((n + f - a) / K.FPS, 3))
        for i in range(b - a + 1 + hold):
            f = min(b, a + i)
            p = os.path.join(d, '%04d.png' % f)
            if not os.path.exists(p):
                raise SystemExit('cut: %s missing (render not finished?)' % p)
            im = Image.open(p).convert('RGB')
            if im.size != size:
                im = im.resize(size, Image.LANCZOS)
            if i > b - a:
                im = zoom(im, 1 + 0.035 * ((i - (b - a)) / max(1, hold)) ** 1.6)
            if xf and i < xf and last is not None:
                im = Image.blend(last, im, (i + 1) / (xf + 1))
            yield line['name'], im
            last = im
            n += 1
    marks['shots'].append(dict(name='end', section='end', start=n / K.FPS, frames=END_FRAMES))
    for i in range(END_FRAMES):      # a hard cut on the beat; the card's own parts then move in
        yield 'end', end_card(cfg, size, i)


def cut(cfg, quality='preview', out=None, sheet=None):
    W, H = K.SIZES[quality]
    b = os.path.join(K.build_dir(cfg), quality)
    out = out or os.path.join(b, 'film.mp4')
    sheet = sheet or os.path.join(b, 'sheet.jpg')
    os.makedirs(os.path.dirname(out), exist_ok=True)
    tmp = out + '.part.mp4'
    ff = subprocess.Popen(['ffmpeg', '-y', '-loglevel', 'error', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', '%dx%d' % (W, H),
                           '-r', str(K.FPS), '-i', '-', '-c:v', 'libx264', '-crf', '17', '-pix_fmt', 'yuv420p',
                           '-movflags', '+faststart', tmp], stdin=subprocess.PIPE)
    marks = dict(fps=K.FPS, shots=[], lands=[], hits=[])
    keep, n = [], 0
    for name, im in frames(cfg, quality, marks):
        ff.stdin.write(credit(cfg, im).tobytes())
        if n % 45 == 22:
            keep.append(im.resize((480, 270)))
        n += 1
    ff.stdin.close()
    if ff.wait():
        raise SystemExit('cut: ffmpeg failed')
    os.replace(tmp, out)
    marks['frames'], marks['seconds'] = n, round(n / K.FPS, 3)
    json.dump(marks, open(out[:-4] + '.marks.json', 'w'), indent=1)
    cols = 6
    s = Image.new('RGB', (480 * cols, 270 * ((len(keep) + cols - 1) // cols)), K.CARD_PAPER)
    for i, im in enumerate(keep):
        s.paste(im, (480 * (i % cols), 270 * (i // cols)))
    s.save(sheet, quality=86)
    return out, marks


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('reel')
    ap.add_argument('--final', action='store_true')
    ap.add_argument('--out')
    ap.add_argument('--sheet')
    o = ap.parse_args(argv)
    out, marks = cut(K.load(o.reel), 'final' if o.final else 'preview', o.out, o.sheet)
    print('cut: %s  %d frames, %.1f s  %s' % (out, marks['frames'], marks['seconds'],
                                              ' '.join('%s@%.1f' % (s['name'], s['start']) for s in marks['shots'])))


if __name__ == '__main__':
    main()
