/* sound.mjs (the demo-video skill) — a drawn film's sound effects, made here from a cue list. Every sound is
   synthesized from sines and seeded noise, so there is no recording or sample library and no licence to track.

    import { mix, master } from '<skill>/motion/sound.mjs';
    const fx = mix([{ at: 0.6, kind: 'send' }, { at: 1.7, kind: 'message', pan: 0.3 }, { at: 34, kind: 'whoosh', dur: 1.2 }], { dur: 57 });
    const stats = master(fx, { video: 'film.mp4', out: 'film.mp4' });   // { I, LRA, TP } of the film's own AAC track

A cue is { at (s), kind, gain (dB, default 0), pan (-1 left to 1 right), pitch (a ratio, default 1), dur (s, for the
kinds that last), to (the pan a whoosh or air ends on) }. `VOICES` holds the kinds: tap, key, typing, send, message, pop,
chime, blip, done, soft-no, whoosh, rise, pad, and the two quiet ones a film under a score wants, tick and air
(AUDIO.md). Each is level-matched, so a gain is a mix decision, and each is a pure
function of its cue (its noise is seeded from the cue's time), so the same cues make the same samples.

`master` takes the stereo mix to the target loudness (-16 LUFS integrated by default) with a look-ahead limiter
holding the sample peaks 1.5 dB under the true-peak target (-1.5 dBTP), room for the AAC encode, measuring each pass with ffmpeg's ebur128 until
it is within 0.2 LU, then muxes it into the video as AAC, copying the video stream, and returns ffmpeg's reading of
the result as played. An AAC whose true peak still reads over the target is limited and encoded again with more room. */
import { execFileSync, spawnSync } from 'node:child_process';
import { copyFileSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { rng } from './motion.mjs';

export const RATE = 48000;
/* dB under the true-peak target the limiter holds the samples at: the inter-sample peaks and the AAC encode take ~1 */
const AAC_ROOM = 1.5;
const FFMPEG = process.env.FFMPEG || '/usr/bin/ffmpeg';
const TAU = 2 * Math.PI;
export const dB = (g) => 10 ** (g / 20);

/* ---------- the parts every voice is made of ---------- */

export const len = (s) => Math.max(1, Math.round(s * RATE));
/** a hit: up over `a` s, then an exponential fall with time constant `tau`, faded to nothing over its last 5 ms of `end` */
export const hit = (a, tau, end) => (t) => (t < a ? t / a : Math.exp(-(t - a) / tau)) * Math.min(1, Math.max(0, (end - t) / 0.005));
/** a swell over `end` s: sin² up to its top at `top` of the way, then down, so it starts and ends silent */
const swell = (end, top = 0.5) => (t) => {
  const u = t / end, v = u < top ? u / top : (1 - u) / (1 - top);
  return Math.sin((Math.PI / 2) * Math.min(1, Math.max(0, v))) ** 2;
};

/** sines at f Hz (or f(t) for a glide): partials [ratio, gain, tau?], a partial with tau dying faster than env */
function tone(n, f, partials, env, g = 1) {
  const out = new Float32Array(n), ph = partials.map(() => 0);
  for (let i = 0; i < n; i++) {
    const t = i / RATE, fi = typeof f === 'function' ? f(t) : f;
    let v = 0;
    partials.forEach(([r, pg, tau], k) => {
      ph[k] += (TAU * fi * r) / RATE;
      v += Math.sin(ph[k]) * pg * (tau ? Math.exp(-t / tau) : 1);
    });
    out[i] = v * env(t) * g;
  }
  return out;
}

/** RBJ biquad coefficients: 'lp', 'hp' or 'bp' (band-pass, 0 dB at its centre) */
export function biquad(type, f, q) {
  const w = (TAU * Math.min(f, RATE * 0.45)) / RATE, c = Math.cos(w), al = Math.sin(w) / (2 * q), a0 = 1 + al;
  const b = type === 'lp' ? [(1 - c) / 2, 1 - c, (1 - c) / 2] : type === 'hp' ? [(1 + c) / 2, -(1 + c), (1 + c) / 2] : [al, 0, -al];
  return [b[0] / a0, b[1] / a0, b[2] / a0, (-2 * c) / a0, (1 - al) / a0];
}

/** seeded white noise through a filter whose cut-off follows fc(t) (new coefficients every 32 samples), shaped by env */
export function noise(n, seed, type, fc, q, env, g = 1) {
  const r = rng(seed), out = new Float32Array(n);
  let x1 = 0, x2 = 0, y1 = 0, y2 = 0, co;
  for (let i = 0; i < n; i++) {
    const t = i / RATE;
    if (i % 32 === 0) co = biquad(type, typeof fc === 'function' ? fc(t) : fc, q);
    const x = r() * 2 - 1, y = co[0] * x + co[1] * x1 + co[2] * x2 - co[3] * y1 - co[4] * y2;
    x2 = x1; x1 = x; y2 = y1; y1 = y;
    out[i] = y * env(t) * g;
  }
  return out;
}

/** the parts summed, each [buffer, offset in s]; the result is as long as the longest reaches */
function sum(...parts) {
  const at = parts.map(([b, o = 0]) => [b, Math.round(o * RATE)]);
  const out = new Float32Array(Math.max(...at.map(([b, o]) => b.length + o)));
  for (const [b, o] of at) for (let i = 0; i < b.length; i++) out[i + o] += b[i];
  return out;
}

/** constant-power pan of a mono buffer; p from -1 (left) to 1 (right), or p(t) for a pan that moves */
export function pan(m, p) {
  const L = new Float32Array(m.length), R = new Float32Array(m.length);
  for (let i = 0; i < m.length; i++) {
    const a = ((Math.min(1, Math.max(-1, typeof p === 'function' ? p(i / RATE) : p)) + 1) * Math.PI) / 4;
    L[i] = m[i] * Math.cos(a) * Math.SQRT2;
    R[i] = m[i] * Math.sin(a) * Math.SQRT2;
  }
  return [L, R];
}

/* a mallet on a soft bar: the fundamental with a short fourth-octave knock, as a marimba's note sounds */
const pluck = (f, tau = 0.11, end = 0.5) => tone(len(end), f, [[1, 0.7], [4, 0.14, 0.012], [10, 0.03, 0.004]], hit(0.002, tau, end));
/* a small bell: inharmonic partials that die faster the higher they are */
const bell = (f, tau = 0.35, end = 1.2) => tone(len(end), f, [[1, 0.6], [2, 0.18, 0.25], [2.76, 0.1, 0.12], [5.4, 0.04, 0.05]], hit(0.003, tau, end));

/* ---------- the voices: each returns a mono buffer (panned by the cue) or [L, R] ---------- */

export const VOICES = {
  /* a touch on glass: a short bright tick over a soft low tock */
  tap: (c) => sum([tone(len(0.06), 1500 * c.pitch, [[1, 0.5], [2.3, 0.15, 0.006]], hit(0.0015, 0.012, 0.06))],
    [noise(len(0.03), c.seed, 'bp', 4500, 0.8, hit(0.0005, 0.004, 0.03), 0.3)],
    [tone(len(0.06), 210 * c.pitch, [[1, 0.6]], hit(0.002, 0.018, 0.06))]),
  /* one key of a quiet keyboard: a band of noise and a low thock, both gone in a few ms */
  key: (c) => sum([noise(len(0.04), c.seed, 'bp', 2600 * c.pitch, 1.2, hit(0.0005, 0.007, 0.04), 0.9)],
    [tone(len(0.04), 150 * c.pitch, [[1, 0.5]], hit(0.001, 0.012, 0.04))]),
  /* keys across dur s (1 by default) at about cps a second, each a little different, every sixth a heavier space bar */
  typing: (c) => {
    const r = rng(c.seed), parts = [], cps = c.cps || 13, d = c.dur || 1;
    for (let t = 0, k = 0; t < d; t += (0.7 + 0.6 * r()) / cps, k++) {
      const space = k % 6 === 5;
      parts.push([VOICES.key({ seed: c.seed + k + 1, pitch: (space ? 0.75 : 0.85 + 0.35 * r()) * c.pitch }).map((v) => v * dB(space ? 1 : -3 * r())), t]);
    }
    return sum(...parts);
  },
  /* a message going: a quick upward glide and a breath of noise with it */
  send: (c) => sum([tone(len(0.16), (t) => 520 * c.pitch * 2 ** Math.min(1, t / 0.07), [[1, 0.6], [2, 0.12]], hit(0.004, 0.045, 0.16))],
    [noise(len(0.12), c.seed, 'bp', (t) => 1500 * 3 ** Math.min(1, t / 0.08), 1.5, hit(0.01, 0.03, 0.12), 0.25)]),
  /* a message arriving: two quick soft plucks, the second a fifth up */
  message: (c) => sum([pluck(784 * c.pitch)], [pluck(784 * 1.5 * c.pitch, 0.13).map((v) => v * 0.55), 0.055]),
  /* an emoji reaction: a small bubble */
  pop: (c) => tone(len(0.09), (t) => 600 * c.pitch * 2.2 ** Math.min(1, t / 0.03), [[1, 0.7]], hit(0.003, 0.03, 0.09)),
  /* a notification: two small bells, a fifth apart */
  chime: (c) => sum([bell(1318.5 * c.pitch)], [bell(1975.5 * c.pitch).map((v) => v * 0.7), 0.1]),
  /* a message riding the diagram: a short high ping with a little sparkle */
  blip: (c) => tone(len(0.25), 1760 * c.pitch, [[1, 0.6], [3, 0.08, 0.01]], hit(0.002, 0.05, 0.25)),
  /* a result: three plucks up a major triad, the last held longest */
  done: (c) => sum([pluck(1046.5 * c.pitch)], [pluck(1318.5 * c.pitch), 0.075], [pluck(1568 * c.pitch, 0.22, 0.8), 0.15]),
  /* something undone: two mellow notes stepping down, soft rather than an alarm */
  'soft-no': (c) => sum([tone(len(0.5), 587.3 * c.pitch, [[1, 0.6], [2, 0.1]], hit(0.006, 0.14, 0.5))],
    [tone(len(0.6), 466.2 * c.pitch, [[1, 0.6], [2, 0.1]], hit(0.006, 0.18, 0.6)), 0.12]),
  /* air past the lens for a camera move of dur s: a band of noise that sweeps up and back, panning from pan to `to` */
  whoosh: (c) => {
    const d = c.dur || 0.8, fc = (t) => (250 + 2200 * Math.sin(Math.PI * Math.min(1, t / d)) ** 2) * c.pitch;
    const body = sum([noise(len(d), c.seed, 'bp', fc, 0.8, swell(d, 0.55), 0.9)], [noise(len(d), c.seed + 7, 'lp', 600, 0.7, swell(d, 0.5), 0.4)]);
    const p0 = c.pan || 0, p1 = c.to ?? p0;
    return pan(body, (t) => p0 + (p1 - p0) * Math.min(1, t / d));
  },
  /* a light rise into a 3D shot, landing at at + dur: an open fifth that grows, a band of noise climbing with it */
  rise: (c) => {
    const d = c.dur || 1.0, n = len(d);
    const env = (t) => (Math.min(1, t / (d * 0.92)) ** 2.2) * Math.min(1, Math.max(0, (d - t) / 0.06));
    const chord = [220, 329.6, 440, 659.3].flatMap((f) => [[f * c.pitch, 1 - 0.003], [f * c.pitch, 1 + 0.003]]);
    return sum(...chord.map(([f, dt]) => [tone(n, f * dt, [[1, 0.12], [2, 0.02]], env)]),
      [noise(n, c.seed, 'bp', (t) => 400 * 12.5 ** Math.min(1, t / d), 2, env, 0.25)]);
  },
  /* a fingertip on glass, felt rather than heard: a soft band of noise and a little low body, no pitch to it */
  tick: (c) => sum([noise(len(0.03), c.seed, 'bp', 2000 * c.pitch, 0.9, hit(0.0008, 0.004, 0.03), 0.9)],
    [tone(len(0.04), 320 * c.pitch, [[1, 0.35]], hit(0.0015, 0.008, 0.04))]),
  /* a breath of air for a camera move of dur s: dark noise that swells and goes, panning from pan to `to`, no sweep */
  air: (c) => {
    const d = c.dur || 1, env = (t) => swell(d, 0.45)(t) ** 1.5;
    const body = sum([noise(len(d), c.seed, 'lp', 900 * c.pitch, 0.5, env, 0.8)], [noise(len(d), c.seed + 3, 'bp', 1800 * c.pitch, 0.7, env, 0.15)]);
    const p0 = c.pan || 0, p1 = c.to ?? p0;
    return pan(body, (t) => p0 + (p1 - p0) * Math.min(1, t / d));
  },
  /* a warm chord for the end: slow in, held, slow out over dur s */
  pad: (c) => {
    const d = c.dur || 3, n = len(d), env = (t) => Math.min(1, t / 0.5) * Math.min(1, Math.max(0, (d - t) / (d * 0.6)));
    const chord = [261.6, 329.6, 392, 523.3].flatMap((f) => [f * 0.998, f * 1.002]);
    return sum(...chord.map((f) => [tone(n, f * c.pitch, [[1, 0.1], [2, 0.012]], env)]));
  },
};

/* each voice's gain at cue gain 0, from levels(): they then peak at the same short-term loudness, so a cue's gain is the
   mix's choice alone. A voice that lasts (typing, whoosh, rise, pad) is measured at its default dur. */
export const LEVEL = { tap: -7.1, key: -2.3, typing: -4.9, send: -9.1, message: -14.2, pop: -8.9, chime: -16.6, blip: -11.5, done: -17.4,
  'soft-no': -13.6, whoosh: -12.3, rise: -9.4, tick: 1.1, air: -1.4, pad: -9.9 };

/** One cue's samples as [L, R], at its level and gain, before it is placed. */
export function voice(c) {
  const v = VOICES[c.kind];
  if (!v) throw new Error(`sound: no voice "${c.kind}" (have ${Object.keys(VOICES).join(', ')})`);
  const out = v({ pitch: 1, seed: Math.round(c.at * 1000) + 1, ...c });
  const [a, b] = out instanceof Float32Array ? pan(out, c.pan || 0) : out;
  const g = dB((LEVEL[c.kind] || 0) + (c.gain || 0));
  return [a.map((x) => x * g), b.map((x) => x * g)];
}

/** The cues mixed into a stereo float track dur s long, at RATE. A cue that runs past the end is cut there. */
export function mix(cues, { dur }) {
  const n = len(dur), L = new Float32Array(n), R = new Float32Array(n);
  for (const c of cues) {
    const [a, b] = voice(c), o = Math.round(c.at * RATE);
    for (let k = Math.max(0, -o); k < a.length && o + k < n; k++) { L[o + k] += a[k]; R[o + k] += b[k]; }
  }
  return { L, R };
}

/** The peak short-term loudness of a mono or stereo buffer (100 ms windows of the K-weighted mean square, as
 *  BS.1770 weights it), in LUFS: how loud a voice sounds at its loudest, which is what levels() matches. */
export function shortLoudness(L, R = L) {
  /* BS.1770's K-weighting at 48 kHz: a high shelf, then a high-pass */
  const pre = [1.53512485958697, -2.69169618940638, 1.19839281085285, -1.69065929318241, 0.73248077421585];
  const rlb = [1.0, -2.0, 1.0, -1.99004745483398, 0.99007225036621];
  const kw = (x) => [pre, rlb].reduce((s, [b0, b1, b2, a1, a2]) => {
    const y = new Float64Array(s.length);
    let x1 = 0, x2 = 0, y1 = 0, y2 = 0;
    for (let i = 0; i < s.length; i++) { y[i] = b0 * s[i] + b1 * x1 + b2 * x2 - a1 * y1 - a2 * y2; x2 = x1; x1 = s[i]; y2 = y1; y1 = y[i]; }
    return y;
  }, x);
  const a = kw(L), b = R === L ? a : kw(R), w = len(0.1);
  let s = 0, best = 0;
  for (let i = 0; i < a.length; i++) {
    s += a[i] * a[i] + b[i] * b[i];
    if (i >= w) s -= a[i - w] * a[i - w] + b[i - w] * b[i - w];
    best = Math.max(best, s / w);
  }
  return best > 0 ? -0.691 + 10 * Math.log10(best) : -Infinity;
}

/** The gain each voice needs at cue gain 0 so it peaks at `ref` LUFS short-term: what LEVEL holds. */
export function levels(ref = -20) {
  return Object.fromEntries(Object.keys(VOICES).map((k) => {
    const out = VOICES[k]({ kind: k, at: 0, pitch: 1, seed: 1 });
    const [a, b] = out instanceof Float32Array ? pan(out, 0) : out;
    return [k, Math.round((ref - shortLoudness(a, b)) * 10) / 10];
  }));
}

/** A look-ahead peak limiter: the gain slides down over the `ahead` s before a peak so the peak lands on `ceiling`
 *  (linear), and comes back up with a `release` s time constant. Returns new [L, R]. */
export function limit(L, R, ceiling, { ahead = 0.002, release = 0.06 } = {}) {
  const n = L.length, w = Math.max(1, Math.round(ahead * RATE)), need = new Float32Array(n);
  for (let i = 0; i < n; i++) { const p = Math.max(Math.abs(L[i]), Math.abs(R[i])); need[i] = p > ceiling ? ceiling / p : 1; }
  /* the least gain any sample in [i, i + w] needs, by a sliding-minimum deque */
  const least = new Float32Array(n).fill(1), dq = new Int32Array(n);
  let h = 0, t = 0;
  for (let j = 0; j < n + w; j++) {
    if (j < n) { while (t > h && need[dq[t - 1]] >= need[j]) t--; dq[t++] = j; }
    while (h < t && dq[h] < j - w) h++;
    if (j - w >= 0 && j - w < n) least[j - w] = h < t ? need[dq[h]] : 1;
  }
  /* averaged over the w + 1 samples up to i, it ramps down ahead of the peak and is at or under the peak's need on it */
  const a = new Float32Array(n), b = new Float32Array(n), k = 1 - Math.exp(-1 / (release * RATE));
  let s = 0, g = 1;
  for (let i = 0; i < n; i++) {
    s += least[i];
    if (i > w) s -= least[i - w - 1];
    const avg = s / Math.min(i + 1, w + 1);
    g = avg < g ? avg : g + (avg - g) * k;
    a[i] = L[i] * g; b[i] = R[i] * g;
  }
  return [a, b];
}

/** A stereo 32-bit float WAV at RATE. */
export function writeWav(file, L, R) {
  const n = L.length, data = Buffer.alloc(n * 8), h = Buffer.alloc(44);
  for (let i = 0; i < n; i++) { data.writeFloatLE(L[i], i * 8); data.writeFloatLE(R[i], i * 8 + 4); }
  h.write('RIFF', 0); h.writeUInt32LE(36 + data.length, 4); h.write('WAVE', 8); h.write('fmt ', 12); h.writeUInt32LE(16, 16);
  h.writeUInt16LE(3, 20); h.writeUInt16LE(2, 22); h.writeUInt32LE(RATE, 24); h.writeUInt32LE(RATE * 8, 28); h.writeUInt16LE(8, 32);
  h.writeUInt16LE(32, 34); h.write('data', 36); h.writeUInt32LE(data.length, 40);
  writeFileSync(file, Buffer.concat([h, data]));
}

/** ffmpeg's ebur128 reading of a file's first audio stream: integrated loudness I (LUFS), loudness range LRA (LU) and
 *  true peak TP (dBTP). */
export function loudness(file) {
  const r = spawnSync(FFMPEG, ['-hide_banner', '-nostats', '-i', file, '-map', '0:a:0', '-af', 'ebur128=peak=true', '-f', 'null', '-'],
    { encoding: 'utf8', maxBuffer: 1 << 26 });
  const s = (r.stderr || '').slice((r.stderr || '').lastIndexOf('Summary:'));
  const num = (re, what) => {
    const m = s.match(re);
    if (!m) throw new Error(`loudness: ffmpeg gave no ${what} for ${file}`);
    return m[1] === '-inf' ? -Infinity : Number(m[1]);
  };
  return { I: num(/I:\s+(-inf|-?[\d.]+) LUFS/, 'integrated loudness'), LRA: num(/LRA:\s+(-?[\d.]+) LU/, 'loudness range'),
    TP: num(/Peak:\s+(-inf|-?[\d.]+) dBFS/, 'true peak') };
}

/** The mix at `lufs` (integrated) with its peaks held `room` dB under `tp`, muxed into `video` as AAC at `kbps` (the video
 *  stream copied, faststart) and written to `out`, which may be `video` itself. `wav` keeps the mastered track there.
 *  Both are judged on the AAC as played, up to `tries` encodes: one whose true peak reads over `tp` (a punchy beat's
 *  transients overshoot more than `room`) is limited again with the room widened by the overshoot, and one whose
 *  loudness reads more than 0.2 LU off `lufs` (the encode drops what is over its cutoff) is mastered again aiming off by
 *  the difference. A true peak still over after the last is refused. Returns ffmpeg's ebur128 reading of out's audio,
 *  the gain it took and the room it ended with. */
export function master({ L, R }, { video, out, lufs = -16, tp = -1.5, kbps = 192, wav, room = AAC_ROOM, tries = 4 } = {}) {
  if (!L.some((x) => x !== 0) && !R.some((x) => x !== 0)) throw new Error('master: the mix is silent');
  const dir = mkdtempSync(join(tmpdir(), 'dv-sound-')), track = join(dir, 'fx.wav'), tmp = join(dir, 'out.mp4');
  try {
    let gain = 0, aim = lufs, got, played;
    for (let enc = 0; enc < tries; enc++) {
      for (let pass = 0; pass < 5; pass++) {
        const g = dB(gain), [a, b] = limit(L.map((x) => x * g), R.map((x) => x * g), dB(tp - room));
        writeWav(track, a, b);
        got = loudness(track);
        if (Math.abs(got.I - aim) <= 0.2) break;
        gain += aim - got.I;
      }
      if (Math.abs(got.I - aim) > 0.2) throw new Error(`master: the mix reached ${got.I} LUFS, not ${aim}`);
      execFileSync(FFMPEG, ['-hide_banner', '-loglevel', 'error', '-y', '-i', video, '-i', track, '-map', '0:v:0', '-map', '1:a:0',
        '-c:v', 'copy', '-c:a', 'aac', '-b:a', `${kbps}k`, '-ar', String(RATE), '-movflags', '+faststart', tmp]);
      played = loudness(tmp);
      const over = played.TP > tp, off = Math.abs(played.I - lufs) > 0.2;
      if (!over && !off) break;
      if (over) room += played.TP - tp + 0.2;
      if (off) aim += lufs - played.I;
    }
    if (played.TP > tp) throw new Error(`master: the AAC's true peak is ${played.TP} dBTP after ${tries} encodes, over ${tp}`);
    if (wav) copyFileSync(track, wav);
    copyFileSync(tmp, out);
    return { ...played, gain, room };
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
}
