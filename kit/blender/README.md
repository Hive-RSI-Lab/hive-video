# Blender helpers for demo films

3D shots for a demo film, built by Python scripts that `blender -b` runs. Nobody makes or ships a .blend file. A shot
script builds its scene from these helpers and stops there. Whoever runs it renders: `video blender SHOT.py OUT/` runs the shot in
local Blender on the CPU through `heavy` (assume no GPU).

| File | What it holds |
|---|---|
| `kit.py` | The numbers, with no bpy: easing, keyed tracks, the plane that covers a pixel rect, hole-pitch checks, the agent-map layout, traffic events, the GDS layer stack. Plain `python3` can test it. |
| `scene.py` | The bpy builders: empty scene, render settings, studio light rig, backdrop sweep, camera with depth of field, per-frame baking, a PCB from its two images, its parts as 3D bodies, a mount with standoffs, GDS extrusion, a UI plane, the node graph (trees of nodes on edges, named surface blocks, and curves to send message dashes along), screen-space tracking, and `shot_main`. |
| `kicad.py` | A KiCad board with no KiCad installed: `python3 kicad.py BOARD.kicad_pcb OUT/` draws its bare board (mask, copper, pads, silkscreen and text) as `top.png` and `bottom.png` and writes `parts.json`, every footprint's VRML model with its place and transform, for `board_from_images` plus `board_parts`. Needs Pillow; the parsing is plain Python. |
| `gds2json.py` | Flattens a GDS into the JSON `gds_extrude` reads. Run it with the kit's gdstk venv (`~/.cache/demo-video/py/bin/python`), because Blender's Python has no gdstk. |
| `selfcheck.py` | `python3 selfcheck.py` runs the kit cases, then the scene cases inside `blender -b`. |

## Writing a shot

```
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import scene, kit

def build(quality):
    scene.reset(res=(1920, 1080), fps=30, frames=(1, 120))
    scene.render_settings(quality, transparent=True)
    ...                       # objects, scene.bake(obj, fn, 1, 120) for every move
    return cam, points, meta  # optional: what --track writes

scene.shot_main(build)
```

A shot imports `kit.py` and `scene.py` from beside it, or from `VIDEO_BLENDER` (`video blender` puts this directory on
`PYTHONPATH`), so a shot can live in its project's tree.

- **Preview:** `video blender shot.py OUT/` (that is `blender -b --factory-startup --python shot.py -- --quality preview --render OUT/` under `heavy`). That
  writes `OUT/0001.png`, `OUT/0002.png`... at half size with 16 samples. Ubuntu's Blender has no denoiser, so a
  preview is grainy, and Cycles at 1080p takes minutes a frame here.
- **Final:** `video blender shot.py OUT/ --quality final` (or a file named `quality` beside the shot). Final is 256
  samples at full size, which on a CPU is far too slow for 1080p: lower the samples in the shot, render
  smaller, or use a stylised look (flat or emission materials, few bounces). Measure one frame first.
- **Labels:** `-- --track labels.json` writes every tracked point's screen position, frame by frame, with the
  `meta` the shot returned. Blender never renders text a viewer must read. The compositor sets it from this file.

## Rules these helpers keep

- **Every move is baked per frame** from `kit.track`, so a preview and a final are the same film, and motion blur
  follows the same curve.
- **Honest geometry.** `board_from_images` drills the holes where the PCB file puts them. `kit.fits_mount` says
  whether they land on a mount, and a shot should assert it rather than scale the board until they do.
  `board_parts` puts each component's own KiCad model where its footprint is, so a populated board is the real
  one rather than a picture of it. `gds_extrude` builds every polygon of the layers it is given and stretches only the height.
- **UI planes are unlit** and placed with `kit.plane_for_pixels`, so the frame where the 3D shot starts matches the
  2D film's frame pixel for pixel. Render those shots with `view='Standard'`, because AgX shifts UI colours.
  `ui_plane(..., crop=True, fixed=True, edge=0.03)` makes a window that stands in the world for the camera to orbit:
  it takes the whole 2D frame (2x for a sharp face-on start), shows only the window's rect with its alpha, and has a
  thin slab behind it so it reads as a line edge-on. The hero film's signature shot is built that way.
