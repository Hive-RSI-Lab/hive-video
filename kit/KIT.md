
# Demo video

A film is a script, not a recording session. You seed fake data, start a throwaway server or workspace, and write
the moves; the kit films them frame by frame and encodes each beat as a clip, the clips cut together into one MP4.
The page runs on a virtual clock that moves one frame at a time (30 fps, or 60 with `fps: 60`), so every CSS
animation, transition, rAF loop, timer, scroll and typed key moves exactly one frame's worth a frame, and the film
comes out the same however loaded the box is; a loaded box only makes the render slower. Each frame is captured at
2x, and the camera, the cursor and the click ring are drawn over it afterwards, so a zoom has real detail and the
cursor moves on every frame. Nothing real may be in frame: every beat checks the visible text against a list of denied words
(the host name, the user, the git identity, real project names) and fails when one shows.

## The pace

- About 20 s a film and never over 30 (`checkLength` fails a longer one; `DEMO_LONG=1` lets one through on purpose).
- Three to five beats, each one idea, cut hard into the next (`stitch` with no fade). Crossfade only into an end card.
- Show the thing working in the first 2 s. No title card up front.
- Hold a result at least 0.8 s (`d.show()`, which refuses less). That is a floor for a result, not the pace: the
  moves between results are quick, a cursor move 0.2-0.5 s, typing about 30 keys a second.
- One camera move a beat, zoom 1.5-2.2x (`d.camera`), eased in and out over 0.4-0.7 s. Zoom onto the result, not
  onto the cursor's travel. A swoop between two far places is `dip: 0.3`.
- Captions are optional. When the pictures say it, leave them out; when a beat needs one, keep it to one short line.
- 1920x1080 H.264, yuv420p, faststart, 30 fps (60 with `fps: 60`). A page laid out for 1280x720 is filmed at a
  1920x1080 viewport with `zoom: 1.5`.

## Files

- `film.mjs`: `director(page, {frames, deny, zoom, fps = 30, scale = 2})`, made before the page's first `goto` so
  its clock is in before the page's scripts, gives `beat`, `moveTo`, `click`, `type`, `press`, `scrollTo`, `drag`,
  `camera`, `show`, `hold`, `wait`, `cut`/`roll` (take a slow stretch out), `stop`, `beats()`. Film time passes only
  inside those calls and the kit's `sleep`, one captured frame per 1/fps; outside a beat they run in real time.
  - A page call that takes page time (typing inside the page, a terminal replay, an animation you await) goes
    through `await d.wait(page.evaluate(...))`, which films until it settles. Awaited bare, the clock would sit
    still; after 1.5 s the kit runs it anyway and warns at the beat's end, and that stretch's length then depends
    on the box.
  - `beat()` takes no frame until the first call that takes time, so `d.camera(view, {ms: 0})` right after it is in
    force from the beat's first frame. `camera` never moves the page, so boxes, the cursor and clicks stay in the
    same pixels whatever it does.
  - The cursor moves like a hand: slow off, quick in the middle, settling, along a slight arc, and a far reach takes
    longer than a near one (`reachMs`). `page.mouse.down()` from the script also spreads the click ring.
  - Then `await encodeClip` per beat: a compositor page draws each frame with the camera, cursor and ring, and
    ffmpeg encodes that image sequence once at `-framerate`, near lossless, with the caption strip when there is
    one. `stitch` is the one final encode. Also `encodeFrames` (stills with their own durations, resampled onto
    exact frames), `checkLength`, `toGif` and `contactSheet`.
- `camera.mjs`: the camera's maths (`cameraAt`, `viewFor`), pure, shared by the director, the selfcheck and the
  composition: the centre eases along a line, the scale in log space, `dip` pulls back mid-move.
- `term.mjs`: `recordTerminal({out, home, user, host, bins, script, deny})` runs tmux and bash for real in a
  bubblewrap sandbox: your made-up home at /home/<user>, a made-up host name, a passwd that knows only that user, a
  clean environment. The script types (`run`, `type`, `keys`), splits panes (`split`) and drops `mark`s. Then
  `terminalPage(cast, {dir, width, height, font})` writes a page that replays it with xterm.js; in it
  `player.seek(mark)`, `player.play(from, to, {speed, idle})` and `player.rect(mark, pane)` for the camera.
- `record.py`: the pty recorder behind `recordTerminal` (asciicast v2, with marks).
- `deps.mjs`: playwright-core and @xterm/xterm (`PINS`), installed once into ~/.cache/hive-video (VIDEO_CACHE)
  (`DEMO_NODE_MODULES` to use another node_modules), and the Chromium in ~/.cache/ms-playwright (`CHROME` to name
  another), which films the page and composites the frames.
- `selfcheck.mjs`: `node selfcheck.mjs` checks the kit without a browser, `motion/` included (its pieces are
  rendered to markup with react-dom/server); `--film` also films a moving page (a
  moving element and the cursor must advance on every output frame, timestamps must be exact, a zoom must not pop)
  and a tiny sandboxed terminal. `director()` runs the plain selfcheck first, once per render, and refuses to film
  if it fails; nothing in it depends on the box's load.
- `motion/`: the kit for a drawn film, where the UI is drawn rather than filmed (a chat window, an app rebuilt in its own
  look, a product shot). Each frame is a pure function of its time, rendered by Remotion, so it is
  frame-exact like a filmed beat. `motion.mjs` is the maths: one easing family (`EASE.out` for entrances, `inOut`
  for moves, `snap` for a hard return), `spring` (critically damped by default, so nothing bounces),
  `typed`, `ripple`, `drift` (a hand-held sway under 0.2 px a frame), `cameraKeys`, `blurTimes` and `frameTravel`
  for motion blur, `rng` for seeded randomness. `pieces.mjs` is the React pieces built on it, made with
  `pieces(React)` so no bundler is needed to check them: `Ripple` (a touch: ring and press dot, never a cursor or a
  hand), `MessageIn` (a list item that opens its height and
  rises in, its blur gone before the still tail so it never pops), `Typed`, `Camera` (with `depth` for parallax and `driftAmp`), `MotionBlur` (n samples across a
  180-degree shutter; give n = 1 when the move is slow) and `Crossfade` (each side its own stacking context, so a
  z-index inside the outgoing shot never paints over the incoming one). `render.mjs` renders it: `renderFilm`
  (lossless PNG frames, one H.264 yuv420p encode, faststart), `renderStills`, and `frameCost`, which times a
  stretch so you can pick 30 or 60 fps from what the box can do now. `measure.mjs` makes "no stutter" a number:
  `frameDiffs(mp4)` and `stutters(diffs)`, the frames that froze in the middle of a move. `flashFrames(diffs)` finds a single frame whose
  brightness jumps away and straight back, like one black frame. `sound.mjs` is the film's
  sound effects, synthesized, so no recording and no licence: `mix(cues, {dur})` places its voices (a tap, a key,
  typing, a message, a whoosh for a camera move, a rise into a 3D shot, a chord for the end) on their times, and
  `master` brings the mix to -16 LUFS under -1.5 dBTP (`lufs`, `tp`) and muxes it in as AAC, copying the video, then
  measures the AAC and encodes again until the AAC itself is in range. `score.mjs` is the
  background score and the mixing tools: notes rendered by a synthesized felt piano, pad and sub, a convolution room
  (`reverb`), a sidechain (`duck`), EQ, fades and `toLoudness`. `AUDIO.md` says how to score a film (the music carries
  it, a few soft touches under it) and how to mix and master it. Remotion and React are
  `MOTION_PINS` in `deps.mjs`, installed into the same cache on first use.
- `web-encode.sh`: the web copies of a finished film. `web-encode.sh mp4 IN OUT [CRF]` is a small H.264 for a page's
  video (CRF 24 by default, faststart), and `web-encode.sh gif IN OUT WIDTH FPS COLOURS [SS T]` a GIF with one palette
  and no dithering, which keeps a UI's flat colours clean; `web-encode.sh selfcheck` checks both.
- Every H.264 encode here (the beat clips, the stitched film, the web MP4) is libx264 on the CPU.

## How to make one

1. Write the story in beats: what the viewer should see working, one idea each, 3-5 beats.
2. Make the fake world: seed data, a throwaway server on a free port, or a home directory for the terminal. Made-up
   people, domains and projects only.
3. Build the denied list from the real machine at run time (host, user, git name and e-mail, real project names), so
   no real value is ever written into the script.
4. Film: a 1920x1080 context, `director`, one `beat` per idea, `show()` on each result, `camera` onto it.
5. Encode, stitch, `checkLength`, and make a `contactSheet`. Look at the sheet before you call it done: it shows
   the pace, the framing and anything in frame that should not be.

## Blender shots

A shot that is modelled rather than filmed (a product turning, a logo, a 3D scene) is a Blender scene script: Python
that builds the whole scene from an empty file at render time, so it needs no .blend and renders the same under any
Blender version. `video blender SHOT.py OUT/ [--quality preview|final] [--frames A-B]` runs it in the local
Blender through `heavy`, on the GPU first (OptiX, then CUDA; the CPU only when the build sees no card or the
frame does not fit; `VIDEO_DEVICE=cpu` forces it). It picks the official build in ~/.cache/hive-video before a distro
Blender, because Ubuntu's Blender has no GPU support. Set the engine, samples, resolution and file format in the
script. Try it with `video blender blender/test-scene.py $TMPDIR/frames --raw`: two 320x180 frames.
See `blender/README.md` for the helpers and `scene.shot_main`.

## Needs

Node 18+, ffmpeg, python3, and for terminals tmux and bwrap. The first run installs the node modules (network once).

## Finish settings (Nov 2026)

- `CAPTION` (dark strip, Inter Medium) and `OUT_K` are exported from `film.mjs`. `VIDEO_OUT_SCALE` (default 1) scales
  the output: 1.3333 gives 2560x1440, 2 gives 4K. `VIDEO_CRF` sets the final encode (default 14, libx264 slow).
- Film the page at `1080 - CAPTION.height` so the strip fills the frame exactly.
- `video export IN DIR` writes the site, x, linkedin and vertical copies.

## Board reels

A board reel is a 45 to 70 s film of a circuit board being made, from the design's own files: the request typed,
the datasheets read, the schematic drawn stroke by stroke, the layout replayed from its history, the parts falling
onto the board, the case closing, an end card. `kit/boardreel/` makes one from a single `reel.json`:

    python3 kit/boardreel/reel.py build reel.json            # 720p preview: prep, render, cut, score, check
    python3 kit/boardreel/reel.py build reel.json --final    # one 1440p final when the preview is right

Each step skips what is done; a shot or drawing whose args, inputs or kit code change is made again, the rest
resume (a fix to a shot script re-renders the shots that use it, so a preview never shows stale frames). Every Blender run and
drawing goes through `heavy timeout 3600` (or `$REEL_RUN`). Needs Blender, kicad-cli (`$KICAD_CLI`), ffmpeg, node,
and for the case shot build123d (`cad_python`).

**reel.json.** `source` is the board project (read only; every design path is inside it), `board` and `sheet` the
KiCad files, `enclosure` a folder of case STEP/STL parts, `research` datasheet PDFs or a datasheets.md list, `prompt`
the request as written. `drawings` are frame sequences made from the design: `prompt` (the request typed, its
`phrases` marked), `schematic` (a `crop` of the sheet in mils, drawn in an `order`: `in:FX,FY`, `out:FX,FY` or
`sweep:FX0,FY0:FX1,FY1`), `layout` (the routing replayed from git history plus `also` save folders) and `trace` (the
longest new trace followed). A drawing is 4000 pixels across unless it says more: `"scale": 3.5` on the prompt (the
same sheet, 14000 across), `"width": 8000` on a schematic (with `"bold"` doubled too: it is in the drawing's own
pixels), a layout or a trace. Give a drawing the pixels its closest shot needs, once, for the preview and the final
alike: the check `sharp` names the number. `shots` are the film in order: `paper` (a drawing on a desk, `seq=@NAME seq0= seqn=
ramp=`), `pages` (`pages=@pages`: each datasheet page whole on its sheet, the front pages dealt first, every title left
uncovered), `board` (`fall real=@real` for the parts drop, `real=@real case=@case` for the case), `match` (below),
each with `frames`, `section`, and optionally `use` [first, last] (only those frames are rendered),
`hold`, `xfade`. A `{"slot": "real photos",
"dir": "assets/real/photos"}` line is a place for real footage: left out while the folder is empty, filled on the
next `reel.py cut` once files land. `spp` ({"final": 48}) sets the samples for every shot that names none: the board shots' own 160 at
1440p takes about a day, 48 with the denoiser a third of that. A board shot with a shallow focus (a long lens, a low
`fstop`) shows grain in the soft parts at 48: give it `spp=96` and a deep `fstop` (22 for a long lens close in) in its args; the denoiser
already runs with albedo and normal passes and the accurate prefilter. At 1440p 96 still shows grain in the blurred
parts: a final wants `spp=192 noise=0.004` on the board shots (about 130 s a frame on 20 cores, twice 96). A shot
longer than one run's time cap resumes by itself from the frames on disk. Shots render on the GPU first (OptiX,
then CUDA) with the official Blender build in ~/.cache/hive-video, which reel.py now picks before a distro Blender
(Ubuntu's has no GPU support); a frame that took 130 s on 20 CPU cores took about 30 s on an RTX 5060 Ti, in about
1.2 GB of card memory. `device=cpu` in a shot's args, or `REEL_DEVICE=cpu`, forces the CPU. `heights` is the enclosure tool's
heights.json: the stand-in bodies take their heights from it, and a library model that is the wrong size for its part
(a 7.7 mm can for a 13 mm capacitor) is given the part's real height, its straight wall made longer and not the whole
model stretched (`shots/_shot.py`, `heights`). `projects/hifi-reel/reel.json` on H2 is a whole one.

**A render that ends in the filmed board.** A `match` shot (`shots/match.py`, its header is the manual) stands the
design's board in a filmed clip. The clip is solved beforehand into a match file (`match=@match/NAME.json`: a camera
for every frame, the table's plane, the way the sunlight travels, the wood's colour in sun and shade, the filmed
frames' folder); the solve is the film's own work, and `projects/hifi-reel/match/` on H2 is one for a board on a table
and one for a closed case. The render then has the clip's lens and light, goes through the clip's grade (`lut=`), and
`sweep=A,B` sends a line of the clip's own sunlight across the picture, the render ahead of it and the filmed frame
behind it, so the cut out of the shot is the take itself. `studio=1` stands the render on a dark floor that fades to
black, not on the filmed table: parts fall in a void and the line turns it into the room (it reads as a render becoming
real, not as a drawing laid over a photograph). A studio render is alone in the picture until the clip shows, so it
is made at the film's size even when the clip is smaller (a 1080p take in a 1440p film: the filmed frames are enlarged
to it, the render is not rendered small and enlarged), and it takes the clip's softness on only over the 12 frames
before the line starts. On the filmed table the render is never larger than the clip. `fall` drops the parts, `case=@case upright=1` stands the printed case
round the board and shuts it, `look=@film/FILE.json` names the finishes CAD colours cannot give, `probe=1` prints the
render's light beside the clip's for tuning them. A shot line's own `spp` ({"final": 192}) replaces the film's for
that shot. In args `@film` is the folder reel.json is in and `@NAME` any folder the film keeps in its build (`@match`,
`@graded`); a file an arg names is part of the shot's stamp by its size and time, so a new solve renders the shot again.
A folder of frames the film made itself (no `.spec` in it: a drawn sheet, a screen capture) is in the stamp by its
count of files, their total size and the newest one's time, so a sheet drawn again larger for the final renders its
shot again and is not skipped as done.
A match file names its filmed frames and its clean table by full path: keep what the solve made in the film's folder,
not in scratch (a scratch folder nothing has touched for a day is swept, and the shot then dies on a missing file just
before a final), and write beside it how to put the scratch frames back.

**Pace.** A reel is watched once and paused when someone wants to look: a shot is over when its point is made, 1 to
1.5 s for a drawing, 2 s for a drop. The settings that cut the waiting out of a shot, not the content:
- `ease=fast` on a paper or phone shot: the camera is at twice its mean speed on the first frame and at half of it on
  the last, so the shot opens inside the move and the cut out still lands on a moving camera. The default (mostly
  steady) and `in`/`out` start or end at rest, which reads as a pause on either side of every cut.
- `ease=even` on a paper, pages or phone shot: the picture moves at one speed from the first frame to the last, so
  neither side of a cut slows down. The angles turn steadily, the distance changes by the same factor every frame
  and the target slides in step with it (`_shot.move`): a pull-back at a steady rate in metres crawls on screen by
  its end, because the sheet is smaller there. `fast` still ends at half speed, and several `fast` shots in a row
  read as a slowdown before every cut; use `even` for a run of short shots and keep the eased kinds for a shot that
  stands alone. With `track=` the camera runs along the tracked path at one speed to the shot's last frame
  (`paper.follow`), and does not wait where the drawing pauses. `pages` picks its pull-back for `even` by itself.
  Measure it, do not judge it by eye: the mean frame-to-frame change over a shot's last quarter should not be far
  below its first quarter's.
- `of=N at=K` on two paper shots in a row with the same `cam=` and `ease=`: one camera move N frames long carried
  across the cut (the second shot has `at=` the first one's length). With `from=PNG fade=8` on the second (a `still=`
  shot) the sheet shows the first shot's last drawing on its first frame and turns into the still over 8 frames.
- match shots: frame F of the shot is frame `k0` + F of the clip, so a larger `k0` and fewer `frames` leave less of the
  filmed take after the reveal; `land=A,B` are the frames the first and the last part land on, `slow=` how many times
  slower than life they fall, `drop=A,B` (the case) the millimetres the board and the lid are let go from, so a short
  shot opens on a board that is already falling. `sweep=A,B` goes right after the last landing. `crisp=1` leaves the
  render as sharp as it was rendered, for one that meets the clip only in the line of light.
- a drawing takes its `--frames` from the shots that show it, so a shorter shot draws faster and still ends complete;
  `"end": {"frames": 60}` sets the end card's length.
- a line said over the end card: `"end": {"voice": {"file": "voice/line.wav", "at": 0.4}}` (a recording in the film's
  folder, and the seconds into the card it starts on). The score puts it in the middle with a little of the room on
  it and the music 7 dB lower while it is said, and refuses a take that is not over 0.15 s before the film ends: start
  it sooner or give the card more `frames`. Make the take with a model on the machine, and say in the film's folder
  how it was made.
- the music: `"score": "steady"` (or `"piano"`, `"laidback"`, `"cinematic"`) picks a track from
  `boardreel/tracks.mjs` that runs through the whole film on one grid, every section cut on a bar line, so it never
  restarts at a cut. Without the key the film gets the cut-by-cut score (`score.mjs`), which restarts at every
  section and sounds like blocks on a film of many short cuts. `"major": ["sound"]` names the section where the thing
  is seen working: the music arrives there, after an intro with no beat (none: the music is there from the first
  frame). `"energy": {"open": 0.3, "layout": 1, "end": 0.25}` sets a section's energy (0 to 1; the rest keep
  `ENERGY` in `score.mjs`): a film that opens quietly and builds once says so here. To hear the same picture with
  another track, change `"score"` and run `reel.py cut`: it re-cuts from the rendered shots and re-scores, no render.
  `node boardreel/selfcheck_tracks.mjs LINE.wav TRACK` measures one track on a test film.
The check `drawing` still holds every frame to new ink, and `length` to the film's range.

**Real footage.** A slot's `dir` may be `@NAME/...` in the build too (footage the film graded and steadied itself). Each
picture and clip in a slot is a shot of its own in the marks, so the score lands on each cut (softly, with a felt
fifth, once the film has resolved). A clip plays its first `max` seconds (default 6). The film is written with its
colours named (BT.709, video range), and an HD camera clip with no colour tag is read as BT.709: ffmpeg alone would
guess BT.601 and give it a green cast.

Long finals on a busy machine: memguard kills the biggest plain `heavy` job in a memory stall, and a 1440p board run holds
about 3.5 GB of RAM, so it is often the one. A shot resumes until three runs in a row land no frame. For tier 1 work run
the Blender jobs in the spared lane with short runs, so other tier 1 jobs wait at most one: `REEL_RUN="heavy --first timeout 1200"`.
GPU runs take turns on the card through `flock ~/.cache/hive-video/gpu.lock`, the same lock `video blender` holds.

**The rules are checks, not advice.** `reel.py check` fails the film when any of these break:
- every schematic cut adds ink on every frame it shows, first to last (`drawing`);
- every paper shot's drawing has the pixels for the 1440p final where the camera comes closest: one drawing pixel
  covers at most 1.25 of the picture's at the point the camera looks at (`sharp`). It judges the final in a preview
  build too, so a soft drawing is found before the long render, and it names the `scale` or `width` that fixes it;
- every footprint has at most one visible 3D model (`models`); a soldered part with none gets a stand-in block in
  `prep` (`standin.py`: a dark moulded body, its size from the footprint name or its F.Fab outline, its height from
  `heights`), so every part falls onto the board; the check lists them so the design can get real models;
- in every drop the parts land faster and faster (`drops`);
- `video stutters` finds no frozen frame or flash (`smooth`); the film's own cuts are skipped, and sharp moments (a part falling past the lens, a lid shutting) are listed with their times to look at, not failed;
- the score was made from this cut's marks, as the track `"score"` names (none: the cut-by-cut score);
  `reel.py cut` always re-scores (`score`);
- the length is inside `length` (`length`);
- nothing on screen names a model, gives a count, claims the hardware works, or is hype (`words`).

Defaults that keep the rest: light ink on paper with one pastel per copper layer, the cut-by-cut score built from the
cut's marks (a hit on every section cut, a tick on every landing; pick a `"score"` track for a film of short cuts), and an end card that reads the title, the build status from
the slots (not yet built / built / on the bench, never "works") and "Made by the Hive  hivelab.ca". A `credit` is
config only. `python3 kit/boardreel/selfcheck.py` runs the kit's cases on the tiny board in `kit/boardreel/fixture/`.
It also reads every shot script without Blender: each `K.name` a script uses must be defined in or imported by
`shots/_shot.py` (a helper moved to `common.py` and not imported back stopped a final on its first frame). Run it
after any edit to the shot scripts and before a long render.
