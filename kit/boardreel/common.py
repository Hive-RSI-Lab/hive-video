"""Shared pieces of the board-reel kit: the look (ink, amber, one pastel per copper layer), fonts, easing,
the reel.json config, and the size each quality renders at. Plain Python; Pillow and numpy only where drawn.

The look is a lesson, not a taste: the first board film went dark and glowing for 20 cuts and read as a game
trailer. Light paper, dark ink, the newest ink amber, and a soft pastel for each copper layer read as drawings
a person made, which is what they are.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
BLENDER = os.path.join(os.path.dirname(HERE), 'blender')
if BLENDER not in sys.path:
    sys.path.insert(0, BLENDER)

INK = (26, 26, 24)             # finished ink
AMBER = (214, 134, 20)         # ink as it lands; fades to INK
PAPER = (255, 255, 255)        # drawing paper (Blender multiplies it down to a warm off-white)
LIGHT = (176, 176, 172)        # outline, pads and silk under a layout replay: there, but quiet
# one pastel a copper layer, drawn bottom first so the top layer reads on top
COPPER = {
    'F.Cu': (238, 164, 150), 'In1.Cu': (234, 204, 140), 'In2.Cu': (156, 206, 178),
    'In3.Cu': (190, 178, 230), 'In4.Cu': (232, 178, 210), 'B.Cu': (154, 190, 234),
}
ORDER = ['B.Cu', 'In6.Cu', 'In5.Cu', 'In4.Cu', 'In3.Cu', 'In2.Cu', 'In1.Cu', 'F.Cu']
SPARE = [(160, 210, 216), (222, 196, 156)]

# end card colours
CARD_PAPER, CARD_INK, CARD_INK2 = (238, 237, 232), (21, 23, 26), (75, 78, 83)

SIZES = {'preview': (1280, 720), 'final': (2560, 1440)}
FPS = 30

FONTS = {
    'display': ['/usr/share/fonts/opentype/inter/InterDisplay-SemiBold.otf', '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'],
    'body': ['/usr/share/fonts/opentype/inter/Inter-Regular.otf', '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'],
    'medium': ['/usr/share/fonts/opentype/inter/Inter-Medium.otf', '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'],
    'mono': ['/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf', '/usr/share/fonts/truetype/noto/NotoSansMono-Regular.ttf'],
    'label': ['/usr/share/fonts/truetype/noto/NotoSansMono-Regular.ttf', '/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf'],
}


def font(kind, size):
    from PIL import ImageFont
    for p in FONTS[kind]:
        if os.path.exists(p):
            return ImageFont.truetype(p, int(size))
    return ImageFont.load_default(size=int(size))


def layer_colour(name, i=0):
    return COPPER.get(name, SPARE[i % len(SPARE)])


def layer_head(name, i=0):
    """a copper layer's colour while its trace is being laid: the same hue, deeper (black there reads as a layer of its own)"""
    return tuple(int(c * 0.62) for c in layer_colour(name, i))


def layer_order(names):
    """copper layers bottom first"""
    return sorted(names, key=lambda n: ORDER.index(n) if n in ORDER else -1)


def smooth(u):
    u = min(1.0, max(0.0, u))
    return u * u * (3 - 2 * u)


def ease(u, kind='steady'):
    """in: gathers speed; out: brakes to rest; steady: mostly linear, so a cut lands on a camera already moving"""
    u = min(1.0, max(0.0, u))
    if kind == 'in':
        return u ** 2.2
    if kind == 'out':
        return 1 - (1 - u) ** 3
    return 0.6 * u + 0.4 * smooth(u)


def load(path):
    """reel.json, with every relative path made absolute against the file's folder (film) or `source` (design)"""
    cfg = json.load(open(path))
    cfg['_dir'] = os.path.dirname(os.path.abspath(path))
    cfg['_src'] = os.path.normpath(os.path.join(cfg['_dir'], cfg.get('source', '.')))
    return cfg


def src(cfg, rel):
    return rel if os.path.isabs(rel) else os.path.join(cfg['_src'], rel)


def film(cfg, rel):
    return rel if os.path.isabs(rel) else os.path.join(cfg['_dir'], rel)


def build_dir(cfg):
    d = os.path.expandvars(cfg.get('build', os.path.join(cfg['_dir'], 'build')))
    os.makedirs(d, exist_ok=True)
    return d


def save(img, path):
    img.save(path, compress_level=1)


def seq_frame(f, nf, seq0=0, seqn=10 ** 6, rate=1.0, ramp=0.0):
    """the drawing frame (0-based file index) a paper shot shows on its frame f (1-based). Shared by shots/paper.py
    and checks.py, so the check sees exactly what the render shows."""
    if ramp:   # the drawing speeds up (ramp>1) or slows (ramp<1) through the shot
        k = seq0 + int((seqn - 1 - seq0) * ((f - 1) / max(1, nf - 1)) ** ramp)
    else:
        k = seq0 + int((f - 1) * rate)
    return min(seqn - 1, k)
