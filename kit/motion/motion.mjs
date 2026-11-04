/* motion.mjs (the demo-video skill) — the maths of drawn motion, pure, shared by pieces.mjs, a film and the selfcheck.

Every function takes the film's time in seconds and returns a value, so a frame is a function of its time and a
render is frame-exact however loaded the box is. One easing family for a whole film (EASE), springs that settle
without bouncing unless asked, and the timing helpers a scripted film keeps reaching for. */

export const clamp = (x, a = 0, b = 1) => Math.min(b, Math.max(a, x));
export const lerp = (a, b, p) => a + (b - a) * p;

/** A CSS cubic-bezier(x1, y1, x2, y2) as an easing function of 0..1, solved by Newton steps with a bisection fallback. */
export function bezier(x1, y1, x2, y2) {
  const cx = 3 * x1, bx = 3 * (x2 - x1) - cx, ax = 1 - cx - bx;
  const cy = 3 * y1, by = 3 * (y2 - y1) - cy, ay = 1 - cy - by;
  const X = (s) => ((ax * s + bx) * s + cx) * s, Y = (s) => ((ay * s + by) * s + cy) * s;
  const dX = (s) => (3 * ax * s + 2 * bx) * s + cx;
  return (x) => {
    if (x <= 0) return 0;
    if (x >= 1) return 1;
    let s = x;
    for (let i = 0; i < 8; i++) {
      const e = X(s) - x, d = dX(s);
      if (Math.abs(e) < 1e-7) return Y(s);
      if (Math.abs(d) < 1e-6) break;
      s -= e / d;
    }
    let lo = 0, hi = 1; s = x;
    for (let i = 0; i < 40; i++) { if (X(s) < x) lo = s; else hi = s; s = (lo + hi) / 2; }
    return Y(s);
  };
}

/** The one easing family: `out` for entrances (fast off, long settle), `inOut` for moves between two rests, `in` for
 *  exits, `snap` for a hard 0.3 s return, `linear` for typing and fades. */
export const EASE = {
  out: bezier(0.16, 1, 0.3, 1),
  inOut: bezier(0.65, 0, 0.35, 1),
  in: bezier(0.7, 0, 0.84, 0),
  snap: bezier(0.85, 0, 0.15, 1),
  linear: (x) => x,
};

/** a..b as t goes t0..t1, eased, held at the ends. */
export const tween = (t, t0, t1, a, b, ease = EASE.out) =>
  t1 <= t0 ? (t < t0 ? a : b) : lerp(a, b, ease(clamp((t - t0) / (t1 - t0))));

/** A spring from 0 to 1 released at `at`: 0 before it, then the step response of a mass on a spring at `freq` Hz with
 *  damping ratio `damping`. The default (1, critically damped) never overshoots; below 1 it bounces, on purpose. */
export function spring(t, at, { freq = 1.6, damping = 1 } = {}) {
  const x = t - at;
  if (x <= 0) return 0;
  const w = 2 * Math.PI * freq, z = damping;
  if (z >= 1) {
    if (z === 1) return 1 - (1 + w * x) * Math.exp(-w * x);
    const r = Math.sqrt(z * z - 1), a = -w * (z - r), b = -w * (z + r);
    return 1 - (b * Math.exp(a * x) - a * Math.exp(b * x)) / (b - a);
  }
  const wd = w * Math.sqrt(1 - z * z);
  return 1 - Math.exp(-z * w * x) * (Math.cos(wd * x) + (z * w / wd) * Math.sin(wd * x));
}

/** How long spring() takes to come within `eps` of 1 and stay there, found on a 1 ms grid. */
export function settle(opts = {}, eps = 0.005) {
  let last = 0;
  for (let ms = 1; ms <= 10000; ms++) if (Math.abs(1 - spring(ms / 1000, 0, opts)) > eps) last = ms;
  return (last + 1) / 1000;
}


/** The part of `text` typed by time t, typing from t0 to t1 at an even rate (whole characters). */
export const typed = (text, t, t0, t1) =>
  text.slice(0, Math.round(tween(t, t0, t1, 0, text.length, EASE.linear)));

/** A touch ripple at `at`: null outside [at, at + dur); else the ring's radius and opacity and the press dot's
 *  opacity. The ring grows fast then slows (EASE.out); the dot is the finger's press, gone by half way. */
export function ripple(t, at, { dur = 0.55, r0 = 10, r1 = 54 } = {}) {
  const d = t - at;
  if (d < 0 || d >= dur) return null;
  const p = d / dur;
  return { r: lerp(r0, r1, EASE.out(p)), ring: 1 - EASE.in(p) * 0.2 - p * 0.8, dot: p < 0.5 ? 0.9 * (1 - p / 0.5) : 0 };
}

/** A slow hand-held camera drift: a sum of three incommensurate sines per axis, amplitude `amp` px and a scale
 *  breathing of `breathe`, the same for the same seed. Its per-frame change is tiny, so it never reads as a move. */
export function drift(t, { amp = 4, breathe = 0.004, seed = 1 } = {}) {
  const f = [0.071, 0.113, 0.167], ph = [seed * 1.3, seed * 2.9, seed * 4.1];
  const s = (k) => f.reduce((acc, fr, i) => acc + Math.sin(2 * Math.PI * fr * t + ph[i] + k) / (i + 1), 0) / 1.8333;
  return { x: amp * s(0), y: amp * s(1.7), s: 1 + breathe * s(3.1) };
}

/** Camera keys [{t, s, fx, fy, ease?}] -> the view at time t: scale s centred on the design point (fx, fy). Between
 *  two keys it eases with the later key's ease (EASE.inOut by default), the scale in log space so a zoom is even. */
export function cameraKeys(keys, t) {
  if (!keys.length) return { s: 1, fx: null, fy: null };
  if (t <= keys[0].t) return { s: keys[0].s, fx: keys[0].fx, fy: keys[0].fy };
  for (let i = 1; i < keys.length; i++) {
    const a = keys[i - 1], b = keys[i];
    if (t < b.t) {
      const p = (b.ease || EASE.inOut)(clamp((t - a.t) / (b.t - a.t)));
      return { s: Math.exp(lerp(Math.log(a.s), Math.log(b.s), p)), fx: lerp(a.fx, b.fx, p), fy: lerp(a.fy, b.fy, p) };
    }
  }
  const z = keys[keys.length - 1];
  return { s: z.s, fx: z.fx, fy: z.fy };
}

/** The CSS transform that puts design point (fx, fy) at the frame's (cx, cy) at scale s. */
export const cameraCSS = ({ s, fx, fy }, cx, cy) => `translate(${cx - s * fx}px, ${cy - s * fy}px) scale(${s})`;

/** Sub-frame sample times for motion blur at time t: n samples spread over the shutter (a fraction of one frame,
 *  0.5 = a 180-degree shutter), centred on t, so the blurred frame sits where the sharp one would. */
export function blurTimes(t, fps, n = 6, shutter = 0.5) {
  if (n <= 1) return [t];
  const span = shutter / fps;
  return Array.from({ length: n }, (_, i) => t - span / 2 + (span * i) / (n - 1));
}

/** How far a point moved in the frame ending at t, in px, for position(t) -> {x, y}: what decides whether a move needs
 *  blur at all (a slow one is sharper without). */
export function frameTravel(position, t, fps) {
  const a = position(t - 1 / fps), b = position(t);
  return Math.hypot(b.x - a.x, b.y - a.y);
}

/** A seeded random number generator (mulberry32): the same seed gives the same film every render. */
export const rng = (seed) => () => {
  seed = (seed + 0x6d2b79f5) | 0;
  let x = Math.imul(seed ^ (seed >>> 15), 1 | seed);
  x = (x + Math.imul(x ^ (x >>> 7), 61 | x)) ^ x;
  return ((x ^ (x >>> 14)) >>> 0) / 4294967296;
};
