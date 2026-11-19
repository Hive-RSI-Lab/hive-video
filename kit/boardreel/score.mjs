/* The board reel's score, built from the cut's own marks, so it can never drift from the picture: a re-timed cut
   gets a new score by running this again (reel.py does after every cut), and checks.py fails a film whose score was
   made from other marks than the picture's.

    node score.mjs FILM.mp4 FILM.marks.json OUT.mp4 [--lufs -16] [--track cuts|steady|piano|laidback|cinematic]

   Two kinds of score. `cuts` (the default, described below) marks every cut, and on a film of short scenes that
   sounds like blocks: the beat, the chords and the instruments restart every few seconds. The others (reel.json's
   `score`, built in tracks.mjs) are one piece of music from before the first frame to the end, with the section cuts
   on its bar lines; use one of them for a film whose scenes are short.

   Every section cut lands on a hit with a riser into it, every shot cut inside a section on an impact (soft, with a
   felt fifth, once the film has resolved), with a quiet snare on it only when the last snare or the section's own hit
   is SNARE_GAP s back: a run of quick cuts is not a run of snares. Every part
   seen landing on a hat, every case event (the board into the base, the lid shut) on a hit. The energy of each
   section comes from its name (open high, the request quiet, building through schematic and layout to the
   assembly, a resolve in D major for the case), or from reel.json's `energy` per section, passed in the marks.
   A section named in reel.json's `major` keeps the beat of its energy and plays it in D major: the thing working
   (a film that shows the product in use before it goes back to how it was made).
   The beat restarts on each section cut, so cuts are always on the one.
   A spoken line (reel.json's `end.voice`, in the marks as voice: {file, at}) is mixed in at its second, and the music
   steps back under it. Writes OUT.mp4 and OUT.score.json ({marks: sha1 of the marks file, seconds, track}). */
import { spawnSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { readFileSync, writeFileSync } from 'node:fs';
import { add, duck, fade, filter, pump, renderScore, reverb, toLoudness } from '../motion/score.mjs';
import { RATE, len, limit, master } from '../motion/sound.mjs';

const FFMPEG = process.env.FFMPEG || '/usr/bin/ffmpeg';
/** the least time between two snares, and from a section's opening hit to its first */
export const SNARE_GAP = 1.5;
/** the spoken line: its loudness on the bus (the music's is -18) and the most its own peaks may reach there (dBFS:
 *  speech is peaky, and held to this it passes the master's limiter untouched), how far the music steps back under it
 *  (dB), how much of a small room it gets, and the least quiet after it before the film ends (s) */
export const VOICE = { lufs: -17.5, peak: -6.5, duck: 7, room: 0.12, tail: 0.15 };

export const ENERGY = { open: 0.8, request: 0.2, research: 0.45, schematic: 0.6, layout: 0.75, assembly: 1, case: 0.55,
  slot: 0.35, end: 0.25 };
const CH = [['D3', 'F3', 'A3', 'D2'], ['Bb2', 'D3', 'F3', 'Bb1'], ['F2', 'A3', 'C4', 'F1'], ['C3', 'E3', 'G3', 'C2']];
const MAJOR = ['D3', 'A3', 'D4', 'F#4', 'A4'];
const ARP = ['A4', 'D5', 'F5', 'A5', 'F5', 'D5', 'C5', 'A4'];
const HOOK = ['D4', 'F4', 'A4', 'C5', 'A4', 'F4', 'D5', 'A4'];
const DMAJ = ['D3', 'F#3', 'A3', 'D2'], HOOK_MAJ = ['D4', 'F#4', 'A4', 'B4', 'A4', 'F#4', 'D5', 'A4'];
const up = (k, n = 1) => k.replace(/\d/, (d) => String(+d + n));

/** consecutive shots of one section as [{name, t0, t1, cuts: [shot starts after the first]}] */
export function sections(marks) {
  const out = [];
  for (const s of marks.shots) {
    const last = out[out.length - 1];
    const t1 = s.start + s.frames / marks.fps;
    if (last && last.name === s.section) { last.cuts.push(s.start); last.t1 = t1; } else out.push({ name: s.section, t0: s.start, t1, cuts: [] });
  }
  return out;
}

/** the notes of the score: pure, so a test can check where every hit falls */
export function notes(marks) {
  const n = [], kick = [], E = { ...ENERGY, ...(marks.energy || {}) };
  const secs = sections(marks), dur = marks.seconds;
  const m = (x) => n.push(x);
  const hit = (at, v) => { m({ at, inst: 'impact', note: 'D2', vel: v }); m({ at, inst: 'crash', note: 'C5', vel: v * 0.6 }); };
  const chordAt = (t, s) => CH[Math.floor((t - s.t0) / 2) % 4];
  const MAJ = new Set(marks.major || []);
  let resolved = false;                                       // whether the section before this one resolved
  secs.forEach((s, si) => {
    const e = E[s.name] ?? 0.5, len = s.t1 - s.t0, resolve = s.name === 'case' || s.name === 'end' || s.name === 'slot';
    const major = resolve || MAJ.has(s.name);
    if (si > 0) {
      hit(s.t0, 0.6 + 0.5 * e);
      m({ at: Math.max(0, s.t0 - Math.min(1.5, (s.t0 - secs[si - 1].t0) * 0.6)), inst: 'riser', note: 'C3', dur: Math.min(1.5, (s.t0 - secs[si - 1].t0) * 0.6), vel: 0.4 + 0.5 * e });
    } else hit(0, 0.8);
    // harmony: the minor turn while the board is being made, D major once it is whole
    for (let t = s.t0; t < s.t1 - 0.05; t += 2) {
      const d = Math.min(2.2, s.t1 - t + 0.2), c = major ? null : chordAt(t, s);
      for (const k of c ? c.slice(0, 3) : MAJOR) m({ at: t, inst: 'pad', note: k, dur: d, vel: 0.3 + 0.3 * e });
      m({ at: t, inst: 'sub', note: c ? c[3] : 'D2', dur: d, vel: 0.3 + 0.3 * e });
    }
    if (resolve && !resolved) for (const k of ['D4', 'F#4', 'A4', 'D5']) m({ at: s.t0, inst: 'felt', note: k, dur: 3.2, vel: 0.5 });
    resolved = resolve;
    // the beat: half-second grid from the section's cut
    for (let i = 0; i * 0.5 < len - 0.05; i++) {
      const t = s.t0 + i * 0.5, c = major ? DMAJ : chordAt(t, s);
      if (e >= 0.4 && !resolve && (e >= 0.6 || i % 2 === 0)) { m({ at: t, inst: 'kick', note: 'G1', vel: 0.4 + 0.55 * e }); kick.push(t); }
      if (e >= 0.4 && !resolve) m({ at: t + 0.25, inst: 'hat', note: 'C5', vel: 0.2 + 0.25 * e, pan: 0.15 });
      if (e >= 0.6 && !resolve) m({ at: t, inst: 'bass', note: up(c[3]), dur: 0.42, vel: 0.3 + 0.35 * e });
      if (e >= 0.9 && i % 2 === 0) for (const k of c.slice(0, 3)) m({ at: t, inst: 'stab', note: up(k), dur: 0.5, vel: 0.5 });
      if (e < 0.4 || resolve) m({ at: t, inst: 'felt', note: (major ? ['D5', 'A5'] : ARP)[i % (major ? 2 : 8)], dur: 1.4, vel: resolve ? 0.22 : 0.3, pan: i % 2 ? 0.2 : -0.2 });
    }
    if (e >= 0.75 && !resolve) for (let i = 0; i * 0.25 < len - 0.05; i++) m({ at: s.t0 + i * 0.25, inst: 'pluck', note: (major ? HOOK_MAJ : HOOK)[i % 8], dur: 0.22, vel: 0.36 + 0.1 * e, pan: Math.sin(i * 0.9) * 0.35 });
    // a cut inside a section: an impact, and a quiet snare when the last one (or the section's own hit) is SNARE_GAP
    // back; in a resolved section (real footage, the case) a soft thump and a felt fifth
    let snare = s.t0;
    for (const t of s.cuts) {
      m({ at: t, inst: 'impact', note: 'D2', vel: resolve ? 0.32 : 0.5 });
      if (resolve) for (const k of ['D4', 'A4']) m({ at: t, inst: 'felt', note: k, dur: 1.6, vel: 0.3 });
      else if (t - snare > SNARE_GAP - 1e-6) { m({ at: t, inst: 'snare', note: 'C4', vel: 0.25 }); snare = t; }
    }
  });
  // every part seen landing ticks (thinned to one a 70 ms, so a pour reads as a roll, not a buzz)
  let lastLand = -1;
  marks.lands.forEach((t, i) => { if (t - lastLand < 0.07) return; lastLand = t; m({ at: t, inst: 'hat', note: 'C5', vel: 0.18 + 0.08 * (i % 3) / 2, pan: Math.sin(i * 2.3) * 0.5 }); });
  marks.hits.forEach((t, i) => { hit(t, i === marks.hits.length - 1 ? 1.1 : 0.7); if (i === marks.hits.length - 1) for (const k of MAJOR) m({ at: t, inst: 'pad', note: k, dur: Math.min(5, dur - t), vel: 0.5 }); });
  return { notes: n.filter((x) => x.at >= 0 && x.at < dur), kick, bright: (t) => { const s = secs.find((x) => t >= x.t0 && t < x.t1); return s ? 0.2 + 0.8 * (E[s.name] ?? 0.5) : 0.4; } };
}

export function score(marks) {
  const { notes: n, kick, bright } = notes(marks);
  const dry = renderScore(n, { dur: marks.seconds, bright });
  const room = reverb(pump(dry, kick, { depth: 5 }), { decay: 2.6, wet: 0.28 });
  return fade(toLoudness(filter(room, 'hp', 30), -18).bus, { inS: 0.02, outS: 1.6 });
}

/** The film's spoken line as buses as long as the film: marks.voice = { file, at } is a recording of it (anything
 *  ffmpeg reads) and the second it starts on. Mono in the middle, the rumble under 90 Hz out, at VOICE.lufs on the bus
 *  with its peaks held to VOICE.peak.
 *  Returns { dry, bus }: `dry` keys the duck, `bus` has a little of a small room on it so the line sits in the music's
 *  space. A take that is not over VOICE.tail s before the film ends is refused: a line cut off is worse than none. */
export function voice(marks) {
  const { file, at } = marks.voice;
  const r = spawnSync(FFMPEG, ['-v', 'error', '-i', file, '-map', '0:a:0', '-ac', '1', '-ar', String(RATE), '-f', 'f32le', '-'], { maxBuffer: 1 << 28 });
  if (r.status !== 0 || !r.stdout || r.stdout.length < 4) throw new Error(`score: cannot read the voice ${file}: ${String(r.stderr || r.error || '').trim() || 'no audio in it'}`);
  const k = r.stdout.length >> 2, n = len(marks.seconds), o = Math.round(at * RATE);
  if (!(o >= 0) || (o + k) / RATE > marks.seconds - VOICE.tail + 1e-6) {
    throw new Error(`score: the voice (${(k / RATE).toFixed(2)} s, from ${at} s) is not over ${VOICE.tail} s before the film ends at ${marks.seconds} s: start it sooner or give the end card more frames`);
  }
  const L = new Float32Array(n);
  for (let i = 0; i < k; i++) L[o + i] = r.stdout.readFloatLE(i * 4);
  const loud = toLoudness(filter({ L, R: L }, 'hp', 90), VOICE.lufs).bus;
  const [a, b] = limit(loud.L, loud.R, 10 ** (VOICE.peak / 20));
  const dry = { L: a, R: b };
  return { dry, bus: fade(reverb(dry, { decay: 1.1, predelay: 0.012, wet: VOICE.room }), { outS: 0.1 }) };
}

/** the film's whole track: the music and, with marks.voice, the line, the music VOICE.duck dB lower while it is said */
export function mix(marks) {
  const music = score(marks);
  if (!marks.voice) return music;
  const v = voice(marks);
  return add(duck(music, v.dry, { depth: VOICE.duck, attack: 0.04, release: 0.5 }), v.bus);
}

export const stamp = (file) => createHash('sha1').update(readFileSync(file)).digest('hex');

if (import.meta.url === `file://${process.argv[1]}`) {
  const [video, marksFile, out] = process.argv.slice(2);
  const opt = (k) => { const i = process.argv.indexOf(k); return i > 0 ? process.argv[i + 1] : undefined; };
  const usage = (why) => { console.error(`${why ? why + '\n' : ''}usage: node score.mjs FILM.mp4 FILM.marks.json OUT.mp4 [--lufs -16] [--track cuts|steady|piano|laidback|cinematic]`); process.exit(2); };
  if (!out || out.startsWith('--')) usage();
  const marks = JSON.parse(readFileSync(marksFile, 'utf8')), name = opt('--track') || 'cuts', lufs = opt('--lufs');
  const lay = (bus, what) => {
    master(bus, { video, out, lufs: lufs === undefined ? -16 : +lufs, tp: -1.5 });
    writeFileSync(out.replace(/\.mp4$/, '') + '.score.json', JSON.stringify({ marks: stamp(marksFile), seconds: marks.seconds, track: name, voice: marks.voice ? stamp(marks.voice.file) : null }));
    console.log(`score: ${out}  ${what}  ${marks.lands.length} lands, ${marks.hits.length} hits${marks.voice ? `, a voice at ${marks.voice.at} s` : ''}`);
  };
  if (name === 'cuts') lay(mix(marks), sections(marks).map((s) => `${s.name}@${s.t0.toFixed(1)}`).join(' '));
  // tracks.mjs imports this file, so it is loaded once this file is whole: no `await` here, which would wait on itself
  else import('./tracks.mjs').then((t) => (t.TRACKS[name] ? lay(t.mix(marks, t.TRACKS[name]), `"${name}"  ${t.describe(marks, t.TRACKS[name])}`) : usage(`score: no track "${name}"`)));
}
