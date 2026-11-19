"""The cut: rendered shots, then any real footage, then the end card, into one silent MP4 with its marks and a
contact sheet. reel.py runs it; the score is laid on afterwards from the marks (score.mjs), never typed by hand.

    python3 cut.py reel.json [--final] [--out FILM.mp4] [--sheet SHEET.jpg]

The shot list is reel.json's `shots`, in film order. A shot line takes frames `use` [first, last] of its render
(default all), holds the last picture `hold` frames with a slow push-in (a held picture never sits still), and may
dissolve in over `xfade` frames. A `slot` line is a place for real footage: it takes every picture and clip in its
folder (beside reel.json, or `@name` in the build), in name order, and is left out cleanly while the folder is
empty. A clip plays its first `max` seconds (default 6). The end card's status line follows the
slots: no photos, "design files only / not yet built"; photos, "built"; testing footage, "on the bench". It never
says the hardware works. reel.json's `end` changes the card's words (see end_card) and `credit` puts a name in the
lower right of every frame.

Writes FILM.mp4 (silent), FILM.marks.json (where every shot starts, every part lands, every hit falls) and the
contact sheet.
"""
import argparse
import glob
import json
import os
import subprocess
import sys

from PIL import Image, ImageDraw, ImageFilter, ImageStat

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as K  # noqa: E402

PICS = ('.jpg', '.jpeg', '.png', '.webp')
CLIPS = ('.mp4', '.mov', '.m4v', '.mkv', '.webm')
END_FRAMES = 75
# the film says what its colours are (BT.709 matrix and primaries, sRGB curve, video range): untagged, a player guesses
TAGS = ['-colorspace', 'bt709', '-color_primaries', 'bt709', '-color_trc', 'iec61966-2-1', '-color_range', 'tv']
# the credit's ink: the picture's levels under it at which it turns light and dark; frames to turn; a jump in that
# level read as a cut; how dark the shade behind the light ink is
CREDIT_SWITCH, CREDIT_FADE, CREDIT_JUMP, CREDIT_SHADE = (120, 165), 8, 45, 0.5
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
    """`dir` is beside reel.json (or absolute); `@name/...` is a folder in the build, e.g. footage the film graded"""
    d = line['dir']
    d = os.path.join(K.build_dir(cfg), d[1:]) if d.startswith('@') else K.film(cfg, d)
    fs = sorted(glob.glob(os.path.join(d, '*')))
    return [f for f in fs if f.lower().endswith(PICS + CLIPS)]


def matrix(f):
    """a camera clip with no colour tag is read as BT.709 when it is HD (ffmpeg alone would guess BT.601: a green cast)"""
    r = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_entries', 'stream=height,color_space',
                        '-of', 'csv=p=0', f], capture_output=True, text=True).stdout.strip().split(',')
    untagged = len(r) < 2 or r[1] in ('', 'unknown')
    return ':in_color_matrix=bt709' if untagged and r[0].isdigit() and int(r[0]) >= 720 else ''


def slot_frames(cfg, line, size):
    """real footage as (file, frame): each picture `each` seconds (default 3) with a slow push-in; each clip up to
    `max` seconds"""
    W, H = size
    each, cap = float(line.get('each', 3)), float(line.get('max', 6))
    for f in slot_files(cfg, line):
        if f.lower().endswith(PICS):
            base = fit(Image.open(f).convert('RGB'), size)
            n = int(round(each * K.FPS))
            for i in range(n):
                yield f, zoom(base, 1 + 0.04 * (i / max(1, n - 1)) ** 1.2)
        else:
            p = subprocess.Popen(['ffmpeg', '-loglevel', 'error', '-i', f, '-t', str(cap), '-vf',
                                  'fps=%d,scale=%d:%d:force_original_aspect_ratio=increase:flags=lanczos%s,crop=%d:%d'
                                  % (K.FPS, W, H, matrix(f), W, H),
                                  '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-'], stdout=subprocess.PIPE)
            while True:
                b = p.stdout.read(W * H * 3)
                if len(b) < W * H * 3:
                    break
                yield f, Image.frombytes('RGB', (W, H), b)
            p.wait()


def status(cfg):
    if cfg.get('status'):
        return cfg['status']
    filled = {line['slot'] for line in cfg['shots'] if 'slot' in line and slot_files(cfg, line)}
    kinds = {line.get('kind', 'testing' if 'test' in line['slot'] else 'photos') for line in cfg['shots']
             if 'slot' in line and line['slot'] in filled}
    return STATUS['testing'] if 'testing' in kinds else STATUS['photos'] if kinds else STATUS['none']


def end_frames(cfg):
    """how long the end card stands: reel.json's `end.frames`, else 2.5 s"""
    return int((cfg.get('end') or {}).get('frames', END_FRAMES))


def end_card(cfg, size, i):
    """title, a rule and the status, then who made it on the foot line; each part slides up on its own delay. The
    title block grows slowly from the left margin; the foot line stays still on the safe margin, level with the credit.
    reel.json's `end` may change it: `title` (default the reel's), `by` (default "Made by the Hive"), `links` (a list,
    default hivelab.ca), `frames` (how long it stands, default 75) and `status`: false leaves the status line out and
    puts `by` under the rule in its place. `voice` ({"file": a recording, "at": seconds into the card, default 0.4}) is
    a line said over the card: nothing is drawn for it, the score mixes it in (reel.py, score.mjs)"""
    W, H = size
    s = W / 1920
    e = cfg.get('end', {})
    name, by, links = e.get('title', cfg.get('title', 'A board')), e.get('by', 'Made by the Hive'), e.get('links', ['hivelab.ca'])
    says = e.get('status', True)
    lay, foot = Image.new('RGBA', (W, H), K.CARD_PAPER + (255,)), Image.new('RGBA', (W, H), (0, 0, 0, 0))

    def put(lay, delay, draw):
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
        for ch in name:
            d.text((xx, 560 * s), ch, font=f, fill=K.CARD_INK + (255,), anchor='ls')
            xx += f.getlength(ch) - 2.1 * s

    def rule(d, k):
        d.line([(x, 610 * s), (x + 464 * s * k, 610 * s)], fill=K.CARD_INK + (255,), width=max(1, round(2 * s)))
        if says:
            d.text((x, 664 * s), status(cfg), font=K.font('mono', 26 * s), fill=K.CARD_INK2 + (255,), anchor='ls')
        else:
            d.text((x, 672 * s), by, font=K.font('body', 38 * s), fill=K.CARD_INK + (255,), anchor='ls')

    def made(d, k):
        fb, fm, y, xx = K.font('body', 34 * s), K.font('mono', 26 * s), H - 62 * s, x   # the descenders sit on the 5% safe margin
        if says:
            d.text((xx, y), by, font=fb, fill=K.CARD_INK + (255,), anchor='ls')
            xx += fb.getlength(by) + 36 * s
        d.text((xx, y), '  /  '.join(links), font=fm, fill=K.CARD_INK2 + (255,), anchor='ls')
    put(lay, 0, title)
    put(lay, 5, rule)
    put(foot, 10, made)
    im = zoom(lay.convert('RGB'), 1 + 0.08 * min(1., i / end_frames(cfg)), anchor=(96 / 1920, 0.5)).convert('RGBA')   # the left margin stays put
    im.alpha_composite(foot)
    return im.convert('RGB')


class Credit:
    """an optional credit (reel.json `credit`), small in the lower right of every frame, on the end card's margins;
    none by default. Its ink follows the picture under it: paper on a dark picture, ink on a light one. It changes
    at once on a cut (the film's own, or one inside a clip: the picture under it jumps) and over CREDIT_FADE frames
    inside a shot, and only when the picture is well past the middle (CREDIT_SWITCH), so a corner that hovers there
    does not make it flicker. The light ink carries a soft shade of the picture's own dark, so it reads on mid tones"""

    def __init__(self, cfg):
        self.text, self.u, self.want, self.was = cfg.get('credit'), None, 0.0, None      # u: 0 the light ink, 1 the dark

    def __call__(self, im, cut=False):
        if not self.text:
            return im
        W, H = im.size
        s = W / 1920
        f, at = K.font('medium', 25 * s), (W - 96 * s, H - 62 * s)
        box = [int(round(v)) for v in ImageDraw.Draw(im).textbbox(at, self.text, font=f, anchor='rs')]
        under = ImageStat.Stat(im.crop(tuple(box)).convert('L')).mean[0]
        if self.u is None or cut or abs(under - self.was) > CREDIT_JUMP:
            self.want = self.u = 1.0 if under > sum(CREDIT_SWITCH) / 2 else 0.0
        else:
            self.want = 1.0 if under > CREDIT_SWITCH[1] else 0.0 if under < CREDIT_SWITCH[0] else self.want
            self.u += max(-1 / CREDIT_FADE, min(1 / CREDIT_FADE, self.want - self.u))
        self.was = under
        ink = tuple(int(round(a + (b - a) * self.u)) for a, b in zip(K.CARD_PAPER, K.CARD_INK2))
        m = int(round(24 * s))
        x0, y0, x1, y1 = max(0, box[0] - m), max(0, box[1] - m), min(W, box[2] + m), min(H, box[3] + m)
        word = Image.new('L', (x1 - x0, y1 - y0), 0)
        ImageDraw.Draw(word).text((at[0] - x0, at[1] - y0), self.text, font=f, fill=255, anchor='rs')
        part = im.crop((x0, y0, x1, y1))
        if self.u < 1:      # the shade: the picture darkened softly round the word, gone as the ink turns dark
            shade = word.filter(ImageFilter.GaussianBlur(7 * s)).point(lambda v: min(255, int(v * 2.2 * CREDIT_SHADE * (1 - self.u))))
            part = Image.composite(Image.new('RGB', part.size, (0, 0, 0)), part, shade)
        k = (200 + 40 * self.u) / 255
        part = Image.composite(Image.new('RGB', part.size, ink), part, word.point(lambda v: int(v * k)))
        im = im.copy()
        im.paste(part, (x0, y0))
        return im


def shot_dir(cfg, name, quality):
    return os.path.join(K.build_dir(cfg), quality, 'shots', name)


def frames(cfg, quality, marks):
    size = K.SIZES[quality]
    last, n = None, 0
    for line in cfg['shots']:
        if 'slot' in line:      # every picture and clip is a shot of its own in the marks: the score hits each cut
            cur, k = None, 0
            for f, im in slot_frames(cfg, line, size):
                if f != cur:
                    cur, k = f, k + 1
                    marks['shots'].append(dict(name=line['slot'] if k == 1 else '%s %d' % (line['slot'], k),
                                               section=line.get('section', 'slot'), slot=line['slot'],
                                               start=n / K.FPS, frames=0))
                marks['shots'][-1]['frames'] += 1
                yield line['slot'], im
                n += 1
            if cur:
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
    marks['shots'].append(dict(name='end', section='end', start=n / K.FPS, frames=end_frames(cfg)))
    for i in range(end_frames(cfg)): # a hard cut on the beat; the card's own parts then move in
        yield 'end', end_card(cfg, size, i)


def cut(cfg, quality='preview', out=None, sheet=None):
    W, H = K.SIZES[quality]
    b = os.path.join(K.build_dir(cfg), quality)
    out = out or os.path.join(b, 'film.mp4')
    sheet = sheet or os.path.join(b, 'sheet.jpg')
    os.makedirs(os.path.dirname(out), exist_ok=True)
    tmp = out + '.part.mp4'
    ff = subprocess.Popen(['ffmpeg', '-y', '-loglevel', 'error', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', '%dx%d' % (W, H),
                           '-r', str(K.FPS), '-i', '-', '-vf', 'scale=out_color_matrix=bt709:out_range=tv,format=yuv420p',
                           '-c:v', 'libx264', '-crf', '17', *TAGS, '-movflags', '+faststart', tmp], stdin=subprocess.PIPE)
    marks = dict(fps=K.FPS, shots=[], lands=[], hits=[])
    keep, n, credit, shots = [], 0, Credit(cfg), 0
    for name, im in frames(cfg, quality, marks):
        ff.stdin.write(credit(im, len(marks['shots']) != shots).tobytes())
        shots = len(marks['shots'])
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
