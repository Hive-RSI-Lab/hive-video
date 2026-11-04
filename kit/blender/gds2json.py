#!/usr/bin/env python3
"""gds2json.py — flatten a GDS's top cell into the JSON scene.gds_extrude reads, because Blender's Python has no gdstk.

    python gds2json.py IN.gds OUT.json [LAYER/DT ...]

Run it with a Python that has gdstk (the demo-video kit keeps one in ~/.cache/demo-video/py). With no layers named,
every layer goes in. OUT is {"cell", "unit_um", "bbox": [x0, y0, x1, y1], "layers": {"34/0": [[x, y, x, y, ...]]}},
coordinates in microns, rounded to 1 nm."""
import json
import sys


def dump(src, out, keep=()):
    import gdstk
    lib = gdstk.read_gds(src)
    cell = lib.top_level()[0]
    (x0, y0), (x1, y1) = cell.bounding_box()
    scale = lib.unit / 1e-6
    layers = {}
    for p in cell.get_polygons():
        key = '%d/%d' % (p.layer, p.datatype)
        if keep and key not in keep:
            continue
        layers.setdefault(key, []).append([round(v * scale, 3) for xy in p.points for v in xy])
    doc = {'cell': cell.name, 'unit_um': 1.0, 'bbox': [x0 * scale, y0 * scale, x1 * scale, y1 * scale], 'layers': layers}
    with open(out, 'w') as f:
        json.dump(doc, f, separators=(',', ':'))
    return doc


if __name__ == '__main__':
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    d = dump(sys.argv[1], sys.argv[2], tuple(sys.argv[3:]))
    print('%s: %s' % (d['cell'], ', '.join('%s %d' % (k, len(v)) for k, v in sorted(d['layers'].items()))))
