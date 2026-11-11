---
name: video
description: Make a demo video, highlight reel or GIF of a web app, a terminal or a 3D scene, in code, smooth and frame-exact. Use when asked for a demo video, a highlight reel, a product GIF, or when a screen recording looks janky.
---

# Making a video

Don't screen-record. A recording stutters whenever the box is busy, and nobody can re-run it after one fix. Write
the film as a script instead. The kit runs the page on a virtual clock and takes one frame per 1/30 s of page
time, so every animation, timer, scroll and typed key lands on exact frames. Camera moves, the cursor and click
rings are drawn over the frames afterwards. The same script always makes the same film.

## The loop

1. `video new DIR` writes a starter `DIR/film.mjs`. Point it at a throwaway server holding made-up data, never at
   a real account. Write three to five beats with one idea each.
2. `heavy timeout 1800 video render DIR/film.mjs OUT/` films, encodes each beat and stitches the beats into the
   MP4. The first render runs `video check` first. A render fails if any word on the deny list appears on screen.
3. `video sheet OUT/film.mp4 OUT/sheet.png 16`, then **look at the sheet**. Most bugs only show up here: a list
   that never scrolled, an empty panel, the camera on the wrong thing.
4. `video stutters OUT/film.mp4` must report 0 stutters. Jerks are fast or popping motion. A jerk is fine where
   content is meant to cut (a page switch, a message arriving); `--allow A-B` skips those spans.
5. `video export IN.mp4 DIR` makes site, X, LinkedIn and vertical (1080x1920) copies from the master.
   `video mp4 IN OUT.mp4` makes the web MP4 (H.264, faststart). `video gif IN OUT.gif --max 3` steps the width
   down from 960 px until the GIF fits under 3 MB.
6. Iterate on timings in the script, never by trimming the video.

The pace and the full director API are in `kit/KIT.md`; read it before your first film. Briefly: about 20 s in
total; the thing working within 2 s; one camera move a beat (1.5-2x, 0.4-0.7 s); hold a result at least 0.8 s
(`d.show`); type at about 30 keys a second.

## Finish (what makes it look professional, not just smooth)

Learned from reworking a launch reel that looked amateur for these reasons; each is now fixed in the kit:
- **Size the page to the film.** Caption strip height is `CAPTION.height`; film the page at `1080 - CAPTION.height` high so the final frame is exactly 1920x1080 (or 2560x1440). A page filmed at full height plus a strip gets shrunk and letterboxed later: narrow, off-centre, soft.
- **Render at 1440p:** `VIDEO_OUT_SCALE=1.3333` (frames are captured at 2x, so this is real detail); `2` for 4K. `VIDEO_CRF` (default 14). Encode once: stitch is the master; make web copies from it with `video mp4` / `web-encode.sh`, never re-encode a master twice.
- **Caption:** a dark strip in the app's own colour, Inter Medium, left-aligned with the app's margin, no accent mark. One short line.
- **Camera:** don't push in so far that the app's logo or the edge of a table is cropped; <=1.05x on full-screen app views, tighter zooms only onto one component.
- **Badges** (e.g. a "replayed 300x" pill) go in free header space, never over rows.
- **Cuts:** `stitch(clips, {fade: 0.25})` crossfades between app views; hard cuts only inside one view.
- A typical run: `BEATS=a,b,c NAME=x.mp4 VIDEO_OUT_SCALE=1.3333 node reel.mjs OUT`, where `reel.mjs` is your film script.

## What makes it smooth (learned the hard way)

- **Put film-only polish in an init script, not in the app.** Make new items ease in
  (`animation: in .4s cubic-bezier(.16,1,.3,1)` from opacity 0 and translateY 12px) instead of popping. For a
  list that jumps to its end, wrap `Element.prototype.scrollTop`'s setter so it glides there over about 500 ms.
  The hive-stars demo film is a worked example with both.
- **Drive your own motion with `setTimeout`.** The film's clock runs timers exactly. requestAnimationFrame
  callbacks may not fire while the clock is paused.
- **Look up the page's timeline.** If the app replies on timers (canned replies at 0.7 s, 1.8 s, and so on), size
  each beat's `hold` to them, so that a beat ends just after the thing it shows.
- **`zoom` and viewport units.** The director's `zoom: 1.5` films a 1280x720 layout at 1920x1080. Chrome doesn't
  divide `vh`/`dvh`/`vw` by root zoom, so the kit rewrites those units in same-origin stylesheets. Without that, a
  `calc(100dvh - x)` layout is 1.5x too tall and its scroller never scrolls. Cross-origin CSS isn't rewritten, so
  serve the page yourself.
- **Apps that patch `Date`.** The kit reads the clock through its own saved `Date`, so a page that wraps `Date`
  (a time skew, a fake "now") can't make `pauseAt` go backwards.
- **The deny list:** host name, user, git name and email, real project names. Fake data only.

## 3D shots (Blender)

`video blender SHOT.py OUT/ [--quality preview|final]` renders a shot script on the CPU. Run it under your job limiter (`heavy` on H2),
and run `--quality preview` first, because a final render takes minutes per second of film. The helpers (easing,
camera with depth of field, light rig, a PCB from KiCad, a schematic that draws itself, GDS extrusion, a UI plane,
node graphs, a spring camera, cached rigid-body and cloth physics, bloom) are in
`kit/blender/README.md`. `--frames A-B` renders part of a shot, `VIDEO_THREADS=N` caps its threads. Encode the frames with the kit's `encodeFrames` or ffmpeg, then cut them in with
`stitch` (`endFade` crossfades into the end card only, the rest stay hard cuts).

## Terminals

`kit/term.mjs` records a real tmux/bash session in a sandbox with a made-up home and host, then replays it with
xterm.js on the film clock. See `kit/KIT.md`.
