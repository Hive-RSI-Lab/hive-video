"""The enclosure for the case shot: each printed part as an STL where it sits when assembled, in the enclosure
frame (mm, origin at the board's lower-left, z 0 the board's bottom face), plus the board.json that says where
that frame is on the KiCad board.

    python3 case.py ENCLOSURE_DIR OUT/

Print STLs are usually laid flat for printing, so they are no use here. If ENCLOSURE_DIR has an assembly STEP
(enclosure.step: one named product per part, as the mech module writes it) the parts are cut out of it in place;
this needs build123d (pass --python for one that has it, e.g. mech's venv). Without a STEP, STLs already in
place (base.stl, lid.stl, btn_*.stl) are copied. Exit 1 if neither, or if the assembly's board is not where
board.json says.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys

SPLIT = r'''
import sys, json
from build123d import import_step, export_stl
src, out = sys.argv[1], sys.argv[2]
res = {}
for s in import_step(src).children or []:      # one labelled solid a part, already in place
    bb = s.bounding_box()
    res[s.label] = [bb.min.X, bb.min.Y, bb.min.Z, bb.max.X, bb.max.Y, bb.max.Z]
    if s.label != 'board':
        export_stl(s, out + '/' + s.label + '.stl', tolerance=0.02, angular_tolerance=0.15)
print(json.dumps(res))
'''


def from_step(step, out, python):
    r = subprocess.run([python, '-c', SPLIT, step, out], capture_output=True, text=True)
    if r.returncode:
        sys.exit('case.py: could not split %s:\n%s' % (step, r.stderr[-1500:]))
    return json.loads(r.stdout.strip().splitlines()[-1])


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('enclosure')
    ap.add_argument('out')
    ap.add_argument('--python', default=sys.executable)
    o = ap.parse_args(argv)
    os.makedirs(o.out, exist_ok=True)
    spec = os.path.join(o.enclosure, 'board.json')
    if not os.path.exists(spec):
        sys.exit('case.py: %s has no board.json (where the enclosure frame sits on the board)' % o.enclosure)
    shutil.copy(spec, os.path.join(o.out, 'board.json'))
    b = json.load(open(spec))
    step = os.path.join(o.enclosure, 'enclosure.step')
    if os.path.exists(step):
        boxes = from_step(step, o.out, o.python)
        for n, bb in sorted(boxes.items()):
            print('%-10s %s' % (n, ' '.join('%7.1f' % v for v in bb)))
        if 'board' in boxes and b.get('size'):
            bb = boxes['board']
            off = max(abs(bb[0]), abs(bb[1]), abs(bb[3] - b['size'][0]), abs(bb[4] - b['size'][1]))
            if off > 1.0:
                sys.exit('case.py: the assembly\'s board is %.1f mm from where board.json puts it' % off)
    else:
        for f in os.listdir(o.enclosure):
            if f.endswith('.stl') and (f in ('base.stl', 'lid.stl') or f.startswith('btn_')):
                shutil.copy(os.path.join(o.enclosure, f), o.out)
    if not os.path.exists(os.path.join(o.out, 'base.stl')):
        sys.exit('case.py: no base.stl came out of %s' % o.enclosure)


if __name__ == '__main__':
    main()
