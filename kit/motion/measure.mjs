/* measure.mjs (the demo-video skill) — measures a rendered film's motion, so "no stutter" is a number, not a feeling.

    import { frameDiffs, stutters } from '<skill>/motion/measure.mjs';
    const d = frameDiffs('film.mp4');            // d[i]: mean change from frame i-1 to frame i, 0..255, at 320x180 grey
    const s = stutters(d);                        // frames that froze in the middle of a move

A stutter is a frame that repeats its neighbour while the frames either side of it move: the jank a 25 fps source
resampled to 30 makes every 6th frame, or a capture that missed a frame. A hold (a run of still frames) is not one. */
import { execFileSync } from 'node:child_process';

const FFMPEG = process.env.FFMPEG || '/usr/bin/ffmpeg';

/** Per-frame change of `mp4`: d[0] = 0, d[i] = mean absolute difference of frame i from frame i-1, in grey levels. */
export function frameDiffs(mp4, { w = 320, h = 180 } = {}) {
  const raw = execFileSync(FFMPEG, ['-hide_banner', '-loglevel', 'error', '-i', mp4, '-vf', `scale=${w}:${h}:flags=area,format=gray`,
    '-f', 'rawvideo', '-'], { maxBuffer: 1 << 30 });
  const n = Math.floor(raw.length / (w * h)), d = [0];
  for (let i = 1; i < n; i++) {
    let s = 0;
    const a = (i - 1) * w * h, b = i * w * h;
    for (let k = 0; k < w * h; k++) s += Math.abs(raw[b + k] - raw[a + k]);
    d.push(s / (w * h));
  }
  return d;
}

/** Indices of frozen frames inside motion: up to `run` still frames (change <= `still`) with real motion (> `moving`)
 *  on both sides. Encoder noise sits under 0.05 grey levels a frame, so a repeated frame reads as about 0. */
export function stutters(d, { still = 0.05, moving = 0.25, run = 2 } = {}) {
  const out = [];
  for (let i = 1; i < d.length - 1; i++) {
    if (d[i] > still || d[i - 1] <= moving) continue;
    let j = i;
    while (j < d.length && d[j] <= still) j++;
    if (j - i <= run && j < d.length && d[j] > moving) for (let k = i; k < j; k++) out.push(k);
    i = j;
  }
  return out;
}

/** Uneven motion, which stutters() cannot see, as [{ i, kind }] in frame order. `jump`: inside a move (the median change of
 *  d[i-3..i+3] past `moving`), a frame whose change is over `ratio` times that median and `floor` grey levels past it:
 *  a skipped frame, a 5 Hz hitch, a 24-to-30 pulldown's double step. `fast`: `run` frames running or more that each
 *  change over `fast` grey levels, a move or a push-in too quick to read. `pop`: two hard cuts (a frame over `hard` and
 *  four times both its neighbours) within `pop` frames of each other, an old view leaking into a new shot. A lone hard
 *  cut is none of these, and nothing inside an `allow` window [a, b] (frame indices: a crossfade, say) is flagged. */
export function jerks(d, { moving = 0.25, ratio = 2, floor = 0.5, fast = 10, run = 2, hard = 6, pop = 3, allow = [] } = {}) {
  const out = [], free = (i) => !allow.some(([a, b]) => i >= a && i <= b);
  const cut = (i) => d[i] >= hard && d[i] > 4 * Math.max(d[i - 1] ?? 0, d[i + 1] ?? 0);
  const med = (a) => [...a].sort((x, y) => x - y)[a.length >> 1];
  let lastCut = -Infinity;
  for (let i = 1; i < d.length; i++) {
    if (!free(i)) continue;
    if (cut(i)) {
      if (i - lastCut <= pop) out.push({ i, kind: 'pop' });
      lastCut = i;
      continue;
    }
    const w = [];
    for (let k = Math.max(1, i - 3); k <= Math.min(d.length - 1, i + 3); k++) if (k !== i) w.push(d[k]);
    const m = med(w);
    if (m > moving && d[i] > ratio * m && d[i] - m > floor) out.push({ i, kind: 'jump' });
    else if (d[i] > fast) {
      let a = i, b = i;
      while (a > 1 && d[a - 1] > fast && !cut(a - 1)) a--;
      while (b < d.length - 1 && d[b + 1] > fast && !cut(b + 1)) b++;
      if (b - a + 1 >= run) out.push({ i, kind: 'fast' });
    }
  }
  return out;
}

/** jerks() as runs a person can find: "3.50-4.20 s fast", one per kind and stretch, at `fps`. */
export function jerkSpans(js, fps = 30) {
  const spans = [];
  for (const j of js) {
    const s = spans[spans.length - 1];
    if (s && s.kind === j.kind && j.i - s.b <= 3) s.b = j.i;
    else spans.push({ kind: j.kind, a: j.i, b: j.i });
  }
  return spans.map((s) => `${(s.a / fps).toFixed(2)}${s.b > s.a ? '-' + (s.b / fps).toFixed(2) : ''} s ${s.kind}`);
}
