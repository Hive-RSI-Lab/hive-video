/* The board reel's score, built from the cut's own marks, so it can never drift from the picture: a re-timed cut
   gets a new score by running this again (reel.py does after every cut), and checks.py fails a film whose score was
   made from other marks than the picture's.

    node score.mjs FILM.mp4 FILM.marks.json OUT.mp4 [--lufs -16]

   Every section cut lands on a hit with a riser into it, every shot cut inside a section on an impact, every part
   seen landing on a hat, every case event (the board into the base, the lid shut) on a hit. The energy of each
   section comes from its name (open high, the request quiet, building through schematic and layout to the
   assembly, a resolve in D major for the case), or from reel.json's `energy` per section, passed in the marks.
   The beat restarts on each section cut, so cuts are always on the one. Writes OUT.mp4 and OUT.score.json
   ({marks: sha1 of the marks file}). */
import { createHash } from 'node:crypto';
import { readFileSync, writeFileSync } from 'node:fs';
import { add, fade, filter, pump, renderScore, reverb, toLoudness } from '../motion/score.mjs';
import { master } from '../motion/sound.mjs';

export const ENERGY = { open: 0.8, request: 0.2, research: 0.45, schematic: 0.6, layout: 0.75, assembly: 1, case: 0.55,
  slot: 0.35, end: 0.25 };
const CH = [['D3', 'F3', 'A3', 'D2'], ['Bb2', 'D3', 'F3', 'Bb1'], ['F2', 'A3', 'C4', 'F1'], ['C3', 'E3', 'G3', 'C2']];
const MAJOR = ['D3', 'A3', 'D4', 'F#4', 'A4'];
const ARP = ['A4', 'D5', 'F5', 'A5', 'F5', 'D5', 'C5', 'A4'];
const HOOK = ['D4', 'F4', 'A4', 'C5', 'A4', 'F4', 'D5', 'A4'];
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
  let resolved = false;
  secs.forEach((s, si) => {
    const e = E[s.name] ?? 0.5, len = s.t1 - s.t0, resolve = s.name === 'case' || s.name === 'end' || s.name === 'slot';
    if (si > 0) {
      hit(s.t0, 0.6 + 0.5 * e);
      m({ at: Math.max(0, s.t0 - Math.min(1.5, (s.t0 - secs[si - 1].t0) * 0.6)), inst: 'riser', note: 'C3', dur: Math.min(1.5, (s.t0 - secs[si - 1].t0) * 0.6), vel: 0.4 + 0.5 * e });
    } else hit(0, 0.8);
    // harmony: the minor turn while the board is being made, D major once it is whole
    for (let t = s.t0; t < s.t1 - 0.05; t += 2) {
      const d = Math.min(2.2, s.t1 - t + 0.2), c = resolve ? null : chordAt(t, s);
      for (const k of c ? c.slice(0, 3) : MAJOR) m({ at: t, inst: 'pad', note: k, dur: d, vel: 0.3 + 0.3 * e });
      m({ at: t, inst: 'sub', note: c ? c[3] : 'D2', dur: d, vel: 0.3 + 0.3 * e });
    }
    if (resolve && !resolved) { for (const k of ['D4', 'F#4', 'A4', 'D5']) m({ at: s.t0, inst: 'felt', note: k, dur: 3.2, vel: 0.5 }); resolved = true; }
    // the beat: half-second grid from the section's cut
    for (let i = 0; i * 0.5 < len - 0.05; i++) {
      const t = s.t0 + i * 0.5, c = chordAt(t, s);
      if (e >= 0.4 && !resolve && (e >= 0.6 || i % 2 === 0)) { m({ at: t, inst: 'kick', note: 'G1', vel: 0.4 + 0.55 * e }); kick.push(t); }
      if (e >= 0.4 && !resolve) m({ at: t + 0.25, inst: 'hat', note: 'C5', vel: 0.2 + 0.25 * e, pan: 0.15 });
      if (e >= 0.6 && !resolve) m({ at: t, inst: 'bass', note: up(c[3]), dur: 0.42, vel: 0.3 + 0.35 * e });
      if (e >= 0.9 && i % 2 === 0) for (const k of c.slice(0, 3)) m({ at: t, inst: 'stab', note: up(k), dur: 0.5, vel: 0.5 });
      if (e < 0.4 || resolve) m({ at: t, inst: 'felt', note: (resolve ? ['D5', 'A5'] : ARP)[i % (resolve ? 2 : 8)], dur: 1.4, vel: resolve ? 0.22 : 0.3, pan: i % 2 ? 0.2 : -0.2 });
    }
    if (e >= 0.75 && !resolve) for (let i = 0; i * 0.25 < len - 0.05; i++) m({ at: s.t0 + i * 0.25, inst: 'pluck', note: HOOK[i % 8], dur: 0.22, vel: 0.36 + 0.1 * e, pan: Math.sin(i * 0.9) * 0.35 });
    for (const t of s.cuts) { m({ at: t, inst: 'impact', note: 'D2', vel: 0.5 }); m({ at: t, inst: 'snare', note: 'C4', vel: 0.45 }); }
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

export const stamp = (file) => createHash('sha1').update(readFileSync(file)).digest('hex');

if (import.meta.url === `file://${process.argv[1]}`) {
  const [video, marksFile, out] = process.argv.slice(2);
  if (!out) { console.error('usage: node score.mjs FILM.mp4 FILM.marks.json OUT.mp4 [--lufs -16]'); process.exit(2); }
  const li = process.argv.indexOf('--lufs');
  const marks = JSON.parse(readFileSync(marksFile, 'utf8'));
  master(add(score(marks)), { video, out, lufs: li > 0 ? +process.argv[li + 1] : -16, tp: -1.5 });
  writeFileSync(out.replace(/\.mp4$/, '') + '.score.json', JSON.stringify({ marks: stamp(marksFile), seconds: marks.seconds }));
  console.log(`score: ${out}  ${sections(marks).map((s) => `${s.name}@${s.t0.toFixed(1)}`).join(' ')}  ${marks.lands.length} lands, ${marks.hits.length} hits`);
}
