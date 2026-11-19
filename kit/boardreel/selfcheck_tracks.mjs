/* selfcheck_tracks.mjs: what selfcheck.py measures on one track of tracks.mjs (it judges; this only measures). One JSON
   object out. selfcheck.py runs one process per track, side by side.

    node selfcheck_tracks.mjs LINE.wav TRACK [FILM.marks.json]

   TRACK is a name in TRACKS, or `cuts` for score.mjs's cut-by-cut score, of which only the sound is measured (to set
   the tracks' level jumps beside). The film is one of uneven scenes, as a short reel has: 2.1 s, 2.0 s (a cut inside it
   on the grid), 2.7 s, 4.8 s (a cut inside it off the grid) and a 2.4 s end card. `film` shows the thing working second
   (`major`) and builds once (`energy`); `plain` is the same cut with neither. With FILM.marks.json the film's marks
   are written there too, for a run of score.mjs itself. */
import { writeFileSync } from 'node:fs';
import { RATE } from '../motion/sound.mjs';
import * as cuts from './score.mjs';
import { TRACKS, mix, notes, plan, score } from './tracks.mjs';

const FR = [['a', 'open', 63], ['b', 'real', 45], ['b2', 'real', 15], ['c', 'request', 81], ['d', 'layout', 60], ['d2', 'layout', 84], ['e', 'end', 72]];
let f = 0;
const shots = FR.map(([name, section, frames]) => { const s = { name, section, start: +(f / 30).toFixed(4), frames }; f += frames; return s; });
const plain = { fps: 30, seconds: f / 30, lands: [0.5, 0.52, 0.9], hits: [2.9], shots };
const film = { ...plain, major: ['real'], energy: { open: 0.3, real: 0.45, request: 0.5, layout: 1, end: 0.25 } };
const said = { ...film, voice: { file: process.argv[2], at: 13 } };
let g = 0;
const NINE = [['a', 'open', 68], ['b', 'real', 68], ['c', 'request', 68], ['d', 'layout', 68], ['e', 'end', 72]].map(([name, section, frames]) => { const s = { name, section, start: +(g / 30).toFixed(4), frames }; g += frames; return s; });
const nine = { fps: 30, seconds: g / 30, lands: [], hits: [], shots: NINE, major: ['real'], energy: { open: 0.9, real: 0.9, request: 0.9, layout: 0.9, end: 0.25 } };
const QUIET = 4.1, OFF = 8.8, ON = 3.6, END = 11.6;        // request's cut (not a big moment), the cuts inside, the end card
const name = process.argv[3];
if (process.argv[4]) writeFileSync(process.argv[4], JSON.stringify(film));
if (!process.argv[2] || !(name === 'cuts' || TRACKS[name])) {
  console.error(`usage: node selfcheck_tracks.mjs LINE.wav ${['cuts', ...Object.keys(TRACKS)].join('|')} [FILM.marks.json]`);
  process.exit(2);
}

const near = (a, b, e = 1e-6) => Math.abs(a - b) < e;
/** the level of each quarter second up to `until`, dB */
const levels = (bus, until) => {
  const k = RATE / 4, out = [];
  for (let i = 0; i + k <= Math.round(until * RATE); i += k) {
    let s = 0;
    for (let j = i; j < i + k; j++) s += bus.L[j] * bus.L[j] + bus.R[j] * bus.R[j];
    out.push(10 * Math.log10(s / (2 * k) + 1e-12));
  }
  return out;
};
const whole = (bus, n) => bus.L.length === n && bus.R.length === n && bus.L.every(Number.isFinite) && bus.R.every(Number.isFinite);
const size = Math.round(film.seconds * RATE);
/** the sound itself: the whole film with the line said (`full`), and the plain cut with no line (`bare`) */
const sound = (full, bare) => {
  const v = cuts.voice(said).bus, l = levels(full, END), med = [...l].sort((a, b) => a - b)[l.length >> 1];
  let pv = 0, vv = 0;
  for (let i = Math.round(13 * RATE); i < Math.round(13.5 * RATE); i++) { pv += full.L[i] * v.L[i]; vv += v.L[i] * v.L[i]; }
  let rms = 0;
  for (let i = 0; i < size; i++) rms += bare.L[i] * bare.L[i];
  return { whole: whole(full, size) && whole(bare, size), first: +(l[0] - med).toFixed(1), low: +(Math.min(...l) - med).toFixed(1),
    jumps: l.filter((x, i) => i && Math.abs(x - l[i - 1]) >= 4.5).length, line: +(pv / vv).toFixed(3), bare: +Math.sqrt(rms / size).toFixed(4) };
};

const o = {};
if (name === 'cuts') o.sound = sound(cuts.mix(said), cuts.score(plain));
else {
  const T = TRACKS[name], P = plan(film, T), { notes: n } = notes(film, T);
  const is = (x, ...k) => k.includes(x.inst);
  o.kinds = P.secs.map((s) => s.kind);
  o.big = [P.arrive, P.peak && P.peak.name, P.release && P.release.name];
  o.bars = P.secs.every((s) => P.eighths.some((x) => near(x.t, s.t0, 1e-9) && x.pos === 0));
  o.joined = near(P.eighths[0].t, 0) && P.eighths.every((x, i) => near(x.t + x.d, i + 1 < P.eighths.length ? P.eighths[i + 1].t : film.seconds, 1e-9));
  o.bend = +Math.max(...P.secs.map((s) => Math.abs(s.d / 0.25 - 1))).toFixed(4);
  const pads = n.filter((x) => is(x, 'pad'));
  o.lead = Math.min(...pads.map((x) => x.at));
  o.holes = [];
  for (let t = 0; t < film.seconds - 0.05; t += 0.05) if (!pads.some((x) => x.at <= t && t < x.at + x.dur)) o.holes.push(+t.toFixed(2));
  o.unmarked = n.filter((x) => (is(x, 'impact', 'crash', 'snare') && near(x.at, QUIET, 0.02)) || (is(x, 'riser') && near(x.at + x.dur, QUIET, 0.02))).length;
  o.risers = n.filter((x) => is(x, 'riser')).length;
  o.crashes = n.filter((x) => is(x, 'crash')).length;
  o.off = n.filter((x) => near(x.at, OFF)).length;
  o.on = n.filter((x) => near(x.at, ON) && is(x, 'felt') && near(x.dur, 1.6)).length;
  o.intro = n.filter((x) => x.at < P.arrive - 1e-6 && is(x, 'kick', 'snare', 'bass', 'stab', 'pluck')).length;
  // the beat: where a track has a kick, it is on the same eighths of every bar from where the music arrives to the end
  // card (not on a bar's last eighth)
  const kicks = n.filter((x) => is(x, 'kick'));
  o.kicks = kicks.length;
  o.beat = P.eighths.filter((x) => x.sec.kind !== 'intro' && !x.sec.last && x.pos % 4 === 0 && x.bar.len - x.pos >= 2).every((x) => kicks.some((k) => near(k.at, x.t)));
  // no two kicks an eighth apart, on a film whose every section ends in a bar of 9 eighths, at the top of the energy
  const tk = notes(nine, T).notes.filter((x) => is(x, 'kick')).map((x) => x.at).sort((a, b) => a - b);
  o.nine = { bars: plan(nine, T).bars.map((b) => b.len), kicks: tk.length, tight: tk.filter((t, i) => i && t - tk[i - 1] < 0.375).map((t) => +t.toFixed(2)) };
  o.kickEnd = kicks.filter((k) => k.at >= END - 1e-6).length;
  const Q = plan(plain, T), q = notes(plain, T).notes;
  o.plain = { arrive: Q.arrive, intro: Q.secs.filter((s) => s.kind === 'intro').length, early: q.filter((x) => x.at < 0.5 && !is(x, 'pad', 'sub')).length };
  o.sound = sound(mix(said, T), score(plain, T));
}
console.log(JSON.stringify(o));
