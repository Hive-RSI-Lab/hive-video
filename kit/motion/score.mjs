/* score.mjs (the demo-video skill) — a film's background score and the mixing tools that put sound under it. Every
   note is synthesized here, so like sound.mjs there is no sample, soundfont or loop and no licence to track (AUDIO.md
   says how to score a film and why).

    import { renderScore, reverb, duck, add, gain, fade, toLoudness, midi } from '<skill>/motion/score.mjs';
    const notes = [{ at: 0.3, inst: 'felt', note: 'F#4', vel: 0.4, dur: 3 }, { at: 0, inst: 'pad', note: 'D3', dur: 6 }];
    const music = reverb(renderScore(notes, { dur: 20, bright: (t) => 0.4 }), { decay: 3, wet: 0.35 });
    const fx = mix(cues, { dur: 20 });                                  // sound.mjs
    const out = add(duck(toLoudness(music, -20).bus, fx, { depth: 4 }), fx);  // then sound.mjs's master(out, ...)

A note is { at (s), inst, note ('F#4') or midi or f (Hz), dur (s the key is held, default 1), vel (0-1, default 0.5),
pan (-1 to 1) }. The instruments: `felt`, a felt-damped piano (inharmonic partials that die faster the higher they
are, a soft hammer, a damper on release, so hold it longer for pedal); `pad`, three detuned saws through a low-pass
that `bright(t)` (0-1, the film's intensity) opens and closes, slow in and out; `sub`, a sine under the root; and a beat
kit for an upbeat cut (`kick`, `clap`, `snare`, `hat`, `ohat`, `crash`, `impact`, `riser` over its dur, `bass`, `stab`, a
supersaw chord tone that `bright(t)` opens, and `pluck`). A bus is
{ L, R } (Float32Array at RATE). `reverb` convolves a bus with a synthesized room (decorrelated noise, darker as it
dies, RT60 `decay`) by FFT; `duck` lowers a bus under another (a sidechain: the key's envelope, attack and release);
`pump` dips a bus on each beat of a list (the kick's sidechain, drawn);
`toLoudness` sets a bus to an integrated loudness (ffmpeg's ebur128); `fade`, `gain`, `add` and `filter` are the rest. */
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { rng } from './motion.mjs';
import { RATE, biquad, dB, hit, len, loudness, noise, pan, writeWav } from './sound.mjs';

const TAU = 2 * Math.PI;
const NAMES = { C: 0, D: 2, E: 4, F: 5, G: 7, A: 9, B: 11 };

/** A note name ('C4' is middle C, 'F#3', 'Bb2') as a MIDI number. */
export function midi(name) {
  const m = /^([A-G])([#b]?)(-?\d)$/.exec(name);
  if (!m) throw new Error(`score: "${name}" is not a note name`);
  return 12 * (Number(m[3]) + 1) + NAMES[m[1]] + (m[2] === '#' ? 1 : m[2] === 'b' ? -1 : 0);
}
const hz = (n) => (n.f ? n.f : 440 * 2 ** (((n.midi ?? midi(n.note)) - 69) / 12));

/* ---------- the instruments: each takes a note (with f, dur, vel, seed) and returns mono or [L, R] ---------- */

/** a sine partial added into out by phasor rotation (a multiply-add a sample, not a Math.sin), its amplitude falling
 *  from g by a factor k a sample */
function partial(out, f, g, k) {
  const step = (TAU * f) / RATE, cr = Math.cos(step), sr = Math.sin(step);
  let c = 1, s = 0;
  for (let i = 0; i < out.length; i++) { out[i] += s * g; const t = c * cr - s * sr; s = c * sr + s * cr; c = t; g *= k; }
}

/** detuned PolyBLEP saws ([detune, gain, left, right] each) through a low-pass whose cut-off follows fc(t) (new
 *  coefficients every 32 samples), shaped by env(t): [L, R] */
function saws(n, f, voices, fc, q, env, r, g = 1) {
  const L = new Float32Array(n), R = new Float32Array(n), fl = [0, 0, 0, 0], fr = [0, 0, 0, 0];
  const osc = voices.map(([d, vg, l, rr]) => ({ dt: (f * d) / RATE, p: r(), vg, l, rr }));
  let co;
  for (let i = 0; i < n; i++) {
    const t = i / RATE;
    if (i % 32 === 0) co = biquad('lp', Math.max(30, fc(t)), q);
    let xl = 0, xr = 0;
    for (const o of osc) {
      const v = (2 * o.p - 1 - blep(o.p, o.dt)) * o.vg;
      xl += v * o.l; xr += v * o.rr;
      o.p += o.dt; if (o.p >= 1) o.p -= 1;
    }
    const yl = co[0] * xl + co[1] * fl[0] + co[2] * fl[1] - co[3] * fl[2] - co[4] * fl[3];
    fl[1] = fl[0]; fl[0] = xl; fl[3] = fl[2]; fl[2] = yl;
    const yr = co[0] * xr + co[1] * fr[0] + co[2] * fr[1] - co[3] * fr[2] - co[4] * fr[3];
    fr[1] = fr[0]; fr[0] = xr; fr[3] = fr[2]; fr[2] = yr;
    const e = env(t) * g;
    L[i] = yl * e; R[i] = yr * e;
  }
  return [L, R];
}
const blep = (p, dt) => (p < dt ? ((p /= dt), p + p - p * p - 1) : p > 1 - dt ? ((p = (p - 1) / dt), p * p + p + p + 1) : 0);

export const INSTRUMENTS = {
  felt: ({ f, dur, vel, seed }) => {
    /* low notes ring longer; each partial has a quick first fall and a slow tail, as a piano string's two decays */
    const tau = Math.min(3.5, Math.max(0.35, 1.6 * (262 / f) ** 0.6)), end = Math.min(dur + 0.35, 5 * tau), n = len(end);
    const out = new Float32Array(n), K = Math.max(1, Math.min(10, Math.floor(12000 / f)));
    for (let k = 1; k <= K; k++) {
      const fk = f * k * Math.sqrt(1 + 0.0003 * k * k), a = k ** -1.6 * Math.exp(-(k - 1) * (0.9 - 0.6 * vel)), tk = tau / (1 + 0.35 * (k - 1));
      /* the two lowest partials are two strings a hair apart, so they beat slowly */
      for (const [d, w] of k <= 2 ? [[0.9998, 0.5], [1.0002, 0.5]] : [[1, 1]]) {
        partial(out, fk * d, 0.7 * a * w, Math.exp(-1 / (0.3 * tk * RATE)));
        partial(out, fk * d, 0.3 * a * w, Math.exp(-1 / (tk * RATE)));
      }
    }
    const thump = noise(len(0.06), seed, 'lp', 300 + 1500 * vel, 0.7, hit(0.0015, 0.01, 0.06), 0.25 * vel);
    for (let i = 0; i < n; i++) {
      const t = i / RATE, damper = t > dur ? Math.exp(-(t - dur) / 0.12) : 1;
      out[i] = (out[i] * Math.min(1, t / 0.004) * damper + (i < thump.length ? thump[i] : 0)) * vel * Math.min(1, (end - t) / 0.05);
    }
    return out;
  },
  pad: ({ f, dur, vel, seed, at, bright }) => {
    const att = Math.min(1.6, dur / 2), rel = 2.2, end = dur + rel, n = len(end), r = rng(seed);
    const L = new Float32Array(n), R = new Float32Array(n);
    /* three saws (PolyBLEP, so no aliasing fizz) a few cents apart: one left, one right, one in the middle */
    const osc = [[0.994, 0.8, 1, 0], [1, 0.6, 0.6, 0.6], [1.0055, 0.8, 0, 1]].map(([d, g, l, rr]) => ({ dt: (f * d) / RATE, p: r(), g, l, rr }));
    const blep = (p, dt) => (p < dt ? ((p /= dt), p + p - p * p - 1) : p > 1 - dt ? ((p = (p - 1) / dt), p * p + p + p + 1) : 0);
    const fl = [0, 0, 0, 0], fr = [0, 0, 0, 0];
    let co;
    for (let i = 0; i < n; i++) {
      const t = i / RATE;
      if (i % 64 === 0) co = biquad('lp', Math.min(9000, f + 250 + 2600 * bright(at + t)), 0.7);
      let xl = 0, xr = 0;
      for (const o of osc) {
        const v = (2 * o.p - 1 - blep(o.p, o.dt)) * o.g;
        xl += v * o.l; xr += v * o.rr;
        o.p += o.dt; if (o.p >= 1) o.p -= 1;
      }
      const yl = co[0] * xl + co[1] * fl[0] + co[2] * fl[1] - co[3] * fl[2] - co[4] * fl[3];
      fl[1] = fl[0]; fl[0] = xl; fl[3] = fl[2]; fl[2] = yl;
      const yr = co[0] * xr + co[1] * fr[0] + co[2] * fr[1] - co[3] * fr[2] - co[4] * fr[3];
      fr[1] = fr[0]; fr[0] = xr; fr[3] = fr[2]; fr[2] = yr;
      const env = Math.sin((Math.PI / 2) * Math.min(1, t / att)) ** 2 * Math.cos((Math.PI / 2) * Math.min(1, Math.max(0, (t - dur) / rel))) ** 2;
      L[i] = yl * env * 0.12 * vel; R[i] = yr * env * 0.12 * vel;
    }
    return [L, R];
  },
  sub: ({ f, dur, vel }) => {
    const end = dur + 1.5, out = new Float32Array(len(end));
    partial(out, f, 0.3 * vel, 1);
    for (let i = 0; i < out.length; i++) {
      const t = i / RATE;
      out[i] *= Math.sin((Math.PI / 2) * Math.min(1, t / 0.8)) ** 2 * Math.cos((Math.PI / 2) * Math.min(1, Math.max(0, (t - dur) / 1.5))) ** 2;
    }
    return out;
  },
  /* ---------- the beat: drums and synths for an upbeat cut (the hero film's v5 score) ---------- */
  /** a kick: a sine that drops from about 5x to its note (G1 sits well) in a few tens of ms, a click, a little drive */
  kick: ({ f, vel, seed }) => {
    const end = 0.6, n = len(end), out = new Float32Array(n), env = hit(0.001, 0.2, end);
    const click = noise(len(0.012), seed, 'hp', 2500, 0.7, hit(0.0004, 0.003, 0.012), 0.35);
    let ph = 0;
    for (let i = 0; i < n; i++) {
      const t = i / RATE;
      ph += (TAU * f * (1 + 4 * Math.exp(-t / 0.028))) / RATE;
      out[i] = (Math.tanh(1.8 * Math.sin(ph) * env(t)) / Math.tanh(1.8) + (i < click.length ? click[i] : 0)) * 0.62 * vel;
    }
    return out;
  },
  /** a clap: three quick band-passed bursts and a short tail */
  clap: ({ vel, seed }) => {
    const out = new Float32Array(len(0.4));
    for (const [o, tau, end, g] of [[0, 0.005, 0.011, 1], [0.011, 0.005, 0.011, 0.9], [0.022, 0.08, 0.37, 1]]) {
      const b = noise(len(end), seed + o * 1000, 'bp', 1300, 0.8, hit(0.0006, tau, end), 2 * g), k = Math.round(o * RATE);
      for (let i = 0; i < b.length; i++) out[k + i] += b[i] * vel;
    }
    return out;
  },
  /** a snare: a short 185 Hz body under bright noise */
  snare: ({ vel, seed }) => {
    const end = 0.35, n = len(end), body = new Float32Array(n), env = hit(0.001, 0.045, end);
    partial(body, 185, 0.5, 1);
    const hiss = noise(n, seed, 'bp', 3200, 0.6, hit(0.001, 0.1, end), 1.6);
    return body.map((x, i) => (x * env(i / RATE) + hiss[i]) * 0.62 * vel);
  },
  /** a closed hi-hat and an open one */
  hat: ({ vel, seed }) => noise(len(0.12), seed, 'hp', 7500, 0.7, hit(0.0005, 0.022, 0.12), 0.62 * vel),
  ohat: ({ vel, seed }) => noise(len(0.5), seed, 'hp', 6800, 0.7, hit(0.001, 0.14, 0.5), 0.34 * vel),
  /** a crash: wide high noise ringing about a second and a half */
  crash: ({ vel, seed }) => [seed, seed + 7].map((s) => noise(len(2.8), s, 'hp', 4200, 0.5, hit(0.002, 0.6, 2.8), 0.34 * vel)),
  /** an impact: a low boom that falls from 160 Hz with a thud on top, for the big cuts */
  impact: ({ vel, seed }) => {
    const end = 2.2, n = len(end), out = new Float32Array(n), env = hit(0.002, 0.45, end);
    const thud = noise(len(0.5), seed, 'lp', 900, 0.7, hit(0.001, 0.07, 0.5), 1.2);
    let ph = 0;
    for (let i = 0; i < n; i++) {
      const t = i / RATE;
      ph += (TAU * (38 + 122 * Math.exp(-t / 0.12))) / RATE;
      out[i] = (Math.tanh(1.5 * Math.sin(ph) * env(t)) * 0.9 + (i < thud.length ? thud[i] : 0)) * 0.68 * vel;
    }
    return out;
  },
  /** a riser: wide noise swept up a band-pass over `dur`, louder as it climbs, cut off at the top */
  riser: ({ dur, vel, seed }) => [seed, seed + 3].map((s) => noise(len(dur + 0.03), s, 'bp', (t) => 400 * 20 ** Math.min(1, t / dur) ** 2, 1.2,
    (t) => Math.min(1, t / dur) ** 2 * Math.min(1, Math.max(0, (dur + 0.03 - t) / 0.03)), 0.7 * vel)),
  /** a bass: a saw and a sine under it through a low-pass that snaps shut, a little drive, held for `dur` */
  bass: ({ f, dur, vel, seed }) => {
    const env = (t) => Math.min(1, t / 0.003) * (t < dur ? 1 : Math.exp(-(t - dur) / 0.03));
    const [L] = saws(len(dur + 0.15), f, [[1, 0.7, 1, 1]], (t) => 1.6 * f + (250 + 1400 * vel) * Math.exp(-t / 0.09), 1.1, env, rng(seed));
    const s = new Float32Array(L.length);
    partial(s, f, 0.5, 1);
    return L.map((x, i) => Math.tanh(1.6 * (x + s[i] * env(i / RATE))) * 0.69 * vel);
  },
  /** a supersaw chord tone: five saws spread wide, a filter that opens on the hit and with the film's `bright(t)` */
  stab: ({ f, dur, vel, seed, at, bright }) => saws(len(dur + 0.6), f, [[0.988, 0.6, 1, 0], [0.995, 0.8, 0.8, 0.2], [1, 1, 0.5, 0.5], [1.005, 0.8, 0.2, 0.8], [1.012, 0.6, 0, 1]],
    (t) => 1.2 * f + 500 + 4500 * vel * Math.exp(-t / 0.22) + 3000 * bright(at + t), 0.9,
    (t) => Math.min(1, t / 0.004) * (0.6 + 0.4 * Math.exp(-t / 0.25)) * (t < dur ? 1 : Math.exp(-(t - dur) / 0.12)), rng(seed), 0.28 * vel),
  /** a pluck for the hook: two saws a hair apart through a filter that closes fast */
  pluck: ({ f, dur, vel, seed }) => saws(len(Math.min(dur, 1) + 0.5), f, [[0.997, 1, 0.8, 0.2], [1.003, 1, 0.2, 0.8]],
    (t) => 1.5 * f + 4000 * Math.exp(-t / 0.1), 1, (t) => hit(0.002, 0.25, 9)(t) * (t < dur ? 1 : Math.exp(-(t - dur) / 0.08)), rng(seed), 0.45 * vel),
};

/** The notes rendered into a stereo bus dur s long; a note that runs past the end is cut there. `bright(t)` (0-1) is
 *  the pad's filter, the film's intensity at t. */
export function renderScore(notes, { dur, bright = () => 0.5 }) {
  const n = len(dur), L = new Float32Array(n), R = new Float32Array(n);
  for (const x of notes) {
    const inst = INSTRUMENTS[x.inst];
    if (!inst) throw new Error(`score: no instrument "${x.inst}" (have ${Object.keys(INSTRUMENTS).join(', ')})`);
    const out = inst({ dur: 1, vel: 0.5, seed: Math.round(x.at * 1000) + 1, ...x, f: hz(x), bright });
    const [a, b] = out instanceof Float32Array ? pan(out, x.pan || 0) : out, o = Math.round(x.at * RATE);
    for (let k = Math.max(0, -o); k < a.length && o + k < n; k++) { L[o + k] += a[k]; R[o + k] += b[k]; }
  }
  return { L, R };
}

/* ---------- the mixing tools ---------- */

/** in-place radix-2 FFT of re/im (Float64Array, a power of two long); inverse leaves out the 1/n */
function fft(re, im, inverse = false) {
  const n = re.length;
  for (let i = 1, j = 0; i < n; i++) {
    let bit = n >> 1;
    for (; j & bit; bit >>= 1) j ^= bit;
    j ^= bit;
    if (i < j) { let t = re[i]; re[i] = re[j]; re[j] = t; t = im[i]; im[i] = im[j]; im[j] = t; }
  }
  for (let size = 2; size <= n; size <<= 1) {
    const half = size >> 1, step = ((inverse ? 2 : -2) * Math.PI) / size, wr = Math.cos(step), wi = Math.sin(step);
    for (let s = 0; s < n; s += size) {
      let cr = 1, ci = 0;
      for (let k = 0; k < half; k++) {
        const a = s + k, b = a + half, tr = re[b] * cr - im[b] * ci, ti = re[b] * ci + im[b] * cr;
        re[b] = re[a] - tr; im[b] = im[a] - ti; re[a] += tr; im[a] += ti;
        const t = cr * wr - ci * wi; ci = cr * wi + ci * wr; cr = t;
      }
    }
  }
}

/** x convolved with h (x.length + h.length - 1 long), by FFT */
export function convolve(x, h) {
  const m = x.length + h.length - 1;
  let n = 1;
  while (n < m) n <<= 1;
  const ar = new Float64Array(n), ai = new Float64Array(n), br = new Float64Array(n), bi = new Float64Array(n);
  ar.set(x); br.set(h);
  fft(ar, ai); fft(br, bi);
  for (let i = 0; i < n; i++) { const r = ar[i] * br[i] - ai[i] * bi[i]; ai[i] = ar[i] * bi[i] + ai[i] * br[i]; ar[i] = r; }
  fft(ar, ai, true);
  const out = new Float32Array(m);
  for (let i = 0; i < m; i++) out[i] = ar[i] / n;
  return out;
}

/** The bus in a room: dry plus the wet return of a synthesized impulse response, seeded noise that is darker as it dies
 *  (from `bright` Hz to `dark` Hz) and falls 60 dB over `decay` s, one per side so the room is wide; unit energy, so
 *  `wet` is the return's level against the dry. The tail past the bus's end is cut. */
export function reverb({ L, R }, { decay = 2.4, predelay = 0.02, wet = 0.3, dry = 1, bright = 7000, dark = 1200, seed = 1 } = {}) {
  const n = len(decay * 1.1), pd = Math.round(predelay * RATE);
  const ir = (s) => {
    const h = noise(n, s, 'lp', (t) => bright * (dark / bright) ** Math.min(1, t / decay), 0.6,
      (t) => Math.min(1, t / 0.004) * Math.exp((-6.91 * t) / decay));
    const k = 1 / Math.sqrt(h.reduce((e, v) => e + v * v, 0));
    return h.map((v) => v * k);
  };
  const wl = convolve(L, ir(seed)), wr = convolve(R, ir(seed + 101)), oL = new Float32Array(L.length), oR = new Float32Array(R.length);
  for (let i = 0; i < L.length; i++) {
    const j = i - pd;
    oL[i] = L[i] * dry + (j >= 0 ? wl[j] : 0) * wet;
    oR[i] = R[i] * dry + (j >= 0 ? wr[j] : 0) * wet;
  }
  return { L: oL, R: oR };
}

/** The bus lowered under `key` (a sidechain): the key's peak envelope (rising over `attack` s, falling over `release`
 *  s) takes the bus down by up to `depth` dB, in proportion as it climbs from `threshold` dBFS to `range` dB above it,
 *  so the bus gives way to a cue and comes back after it. */
export function duck({ L, R }, key, { depth = 6, threshold = -45, range = 18, attack = 0.012, release = 0.35 } = {}) {
  const n = L.length, ka = Math.exp(-1 / (attack * RATE)), kr = Math.exp(-1 / (release * RATE));
  const oL = new Float32Array(n), oR = new Float32Array(n);
  let env = 0;
  for (let i = 0; i < n; i++) {
    const p = i < key.L.length ? Math.max(Math.abs(key.L[i]), Math.abs(key.R[i])) : 0;
    env = p > env ? p + (env - p) * ka : p + (env - p) * kr;
    const over = env > 0 ? 20 * Math.log10(env) - threshold : 0, g = dB(-depth * Math.min(1, Math.max(0, over / range)));
    oL[i] = L[i] * g; oR[i] = R[i] * g;
  }
  return { L: oL, R: oR };
}

/** The bus pumped by a beat (a kick's sidechain, drawn rather than keyed): at each time in `beats` it drops to `depth`
 *  dB under over `attack` s and comes back over `release` s on a half-cosine, so the chords breathe with the kick. */
export function pump({ L, R }, beats, { depth = 6, attack = 0.004, release = 0.22 } = {}) {
  const n = L.length, oL = new Float32Array(n), oR = new Float32Array(n), at = [...beats].sort((a, b) => a - b);
  let k = -1;
  for (let i = 0; i < n; i++) {
    const t = i / RATE;
    while (k + 1 < at.length && at[k + 1] <= t) k++;
    const d = k < 0 ? Infinity : t - at[k];
    const s = d < attack ? d / attack : d < attack + release ? 0.5 * (1 + Math.cos((Math.PI * (d - attack)) / release)) : 0, g = dB(-depth * s);
    oL[i] = L[i] * g; oR[i] = R[i] * g;
  }
  return { L: oL, R: oR };
}
/** the bus times g dB */
export const gain = ({ L, R }, g) => ({ L: L.map((x) => x * dB(g)), R: R.map((x) => x * dB(g)) });
/** buses summed sample by sample, as long as the first */
export function add(...buses) {
  const [{ L, R }] = buses, oL = Float32Array.from(L), oR = Float32Array.from(R);
  for (const b of buses.slice(1)) for (let i = 0; i < oL.length && i < b.L.length; i++) { oL[i] += b.L[i]; oR[i] += b.R[i]; }
  return { L: oL, R: oR };
}
/** the bus faded in over `inS` s from its start and out over `outS` s to silence on its last sample (sin², no click) */
export function fade({ L, R }, { inS = 0, outS = 0 } = {}) {
  const n = L.length, oL = new Float32Array(n), oR = new Float32Array(n);
  for (let i = 0; i < n; i++) {
    const a = inS ? Math.min(1, i / (inS * RATE)) : 1, b = outS ? Math.min(1, (n - 1 - i) / (outS * RATE)) : 1;
    const g = Math.sin((Math.PI / 2) * a) ** 2 * Math.sin((Math.PI / 2) * b) ** 2;
    oL[i] = L[i] * g; oR[i] = R[i] * g;
  }
  return { L: oL, R: oR };
}
/** an RBJ biquad ('lp', 'hp' or 'bp') at f Hz over both sides, as an EQ: a high-pass keeps the mud out of a bus */
export function filter({ L, R }, type, f, q = 0.707) {
  const [b0, b1, b2, a1, a2] = biquad(type, f, q);
  const run = (x) => {
    const y = new Float32Array(x.length);
    let x1 = 0, x2 = 0, y1 = 0, y2 = 0;
    for (let i = 0; i < x.length; i++) { y[i] = b0 * x[i] + b1 * x1 + b2 * x2 - a1 * y1 - a2 * y2; x2 = x1; x1 = x[i]; y2 = y1; y1 = y[i]; }
    return y;
  };
  return { L: run(L), R: run(R) };
}
/** the bus at `lufs` integrated, as ffmpeg's ebur128 reads it; returns { bus, I } (I before the gain) */
export function toLoudness(bus, lufs) {
  const dir = mkdtempSync(join(tmpdir(), 'dv-score-')), f = join(dir, 'bus.wav');
  try {
    writeWav(f, bus.L, bus.R);
    const { I } = loudness(f);
    if (!Number.isFinite(I)) throw new Error('toLoudness: the bus is silent');
    return { bus: gain(bus, lufs - I), I };
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
}
