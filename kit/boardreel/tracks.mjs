/* tracks.mjs: scores for a board reel that never restart at a cut. reel.json picks one with "score": "steady" (or
   "piano", "laidback", "cinematic"); without the key the film gets score.mjs's cut-by-cut score ("cuts").

    node score.mjs FILM.mp4 FILM.marks.json OUT.mp4 --track steady [--lufs -16]

   What the cut-by-cut score does at every cut (restart the beat and the chords, swap the instruments by the section's
   energy, an impact, a crash and a riser) is what makes it sound like blocks. Here:
   - one grid of eighth notes runs through the whole film. Each section gets a whole number of eighths near EIGHTH s,
     so every section cut is on a bar line; bars are 8 eighths and a section's last bar takes the rest (4 to 11). The
     tempo bends by up to 6 % on a section of 2 s or more, more on a shorter one (0.6 s: 20 %), so keep sections of
     short shots at 2 s or more;
   - the chords go round bar by bar through the film, not from each section's start;
   - the energy is a curve: a rise leads into its cut, a fall trails it. Each layer's loudness follows the curve, so
     an instrument comes and goes over a second, never at a cut;
   - a riser and a crash only where the music arrives, at the film's peak and (softly) where it resolves; nothing on a
     shot cut that is off the grid;
   - the pad is the bed and is the loudest thing that lasts: it is there before the first frame, each chord swells as
     the last one dies, and the drums and the piano sit on it. (With a quiet pad every bar is a hit and its decay, and
     the level saws by 6 dB a bar: that is what sounds like blocks.) The beat is the same from where it arrives to
     where it stops (no kick on a bar's last eighth, which would stumble into the next bar's first), and the energy
     brings the top lines in and out. Only a section after the arrival with an energy under about 0.4 (laidback: 0.5)
     thins the beat too, as the energy curve falls into it, over a second and not at the cut.
   The music arrives with the first section named in the marks' `major` (the thing working); before it is an intro
   without a beat: the pad, a slow rising line on the piano, the parts' ticks, a soft thud on each case event. With no
   `major` the music is there from the first frame.
   The energy of a section is score.mjs's ENERGY by its name, or reel.json's `energy` (in the marks). A film that
   opens quietly and builds once says so there, e.g. { open: 0.3, request: 0.5, schematic: 0.7, layout: 1, end: 0.25 }.
   The four tracks share the plan and the frame (pad, sub, intro, the three big moments, the last chord) and differ in
   their chords and in `layers`, what is played on each eighth:
     steady     the cut-by-cut score's own instruments and key (D minor, D major for the thing working), one beat
     piano      one figure in eighths that never stops, a soft pad, no drums; D major
     laidback   half-time kick and snare, soft hats a little late, piano chords, a round bass
     cinematic  slow swells, a low plucked figure, a rising line on the piano, deep hits, no beat; D major */
import { add, duck, fade, filter, renderScore, reverb, toLoudness } from '../motion/score.mjs';
import { RATE, dB } from '../motion/sound.mjs';
import { ENERGY, VOICE, sections, voice } from './score.mjs';

const EIGHTH = 0.25, RESOLVE = new Set(['case', 'slot', 'end']);
const S = (x) => { const v = Math.min(1, Math.max(0, x)); return v * v * (3 - 2 * v); };
const step = (e, lo, hi) => S((e - lo) / (hi - lo));
const up = (k, n = 1) => k.replace(/-?\d/, (d) => String(+d + n));
const SUS = { Dsus: { pad: ['D3', 'A3', 'D4', 'E4'], sub: 'D2', major: true }, Asus: { pad: ['A2', 'E3', 'A3', 'D4'], sub: 'A1', major: true } };

/** the film as bars and eighths: { secs, bars, eighths, arrive, energy(t), peak, release, dur } */
export function plan(marks, T) {
  const secs = sections(marks).map((s) => ({ ...s })), major = new Set(marks.major || []);
  const first = secs.findIndex((s) => major.has(s.name)), arrive = first > 0 ? secs[first].t0 : 0;
  const table = { ...ENERGY, ...(marks.energy || {}) };
  for (const s of secs) {
    s.kind = s.t0 < arrive - 1e-6 ? 'intro' : major.has(s.name) || RESOLVE.has(s.name) ? 'home' : 'away';
    s.e = table[s.name] ?? 0.5;
  }
  const mus = secs.filter((s) => s.kind !== 'intro'), steps = [];
  for (let i = 1; i < mus.length; i++) {
    const a = mus[i - 1], b = mus[i];
    if (b.e > a.e) steps.push([b.t0 - Math.min(1.2, 0.5 * (a.t1 - a.t0)), b.t0, b.e - a.e]);
    else if (b.e < a.e) steps.push([b.t0 - 0.05, b.t0 + Math.min(0.9, 0.4 * (b.t1 - b.t0)), b.e - a.e]);
  }
  const energy = (t) => steps.reduce((e, [a, b, d]) => e + d * S((t - a) / (b - a)), mus[0].e);
  let cyc = 0, intro = 0;
  const bars = [], eighths = [];
  secs.forEach((s, si) => {
    const n = Math.max(2, Math.round((s.t1 - s.t0) / EIGHTH)), d = (s.t1 - s.t0) / n, next = secs[si + 1];
    Object.assign(s, { n, d, bars: [], last: si === secs.length - 1 });
    for (let k = 0; k < n;) {
      const left = n - k, L = left >= 12 ? 8 : left, short = L <= 5 && k > 0;
      let name;
      if (s.kind === 'intro') name = T.intro[Math.min(intro, T.intro.length - 1)];
      else if (s.kind === 'home') name = short && next && next.kind === 'home' ? T.plagal : T.home;
      else if (short) name = next && next.kind === 'home' ? T.pre : s.bars[s.bars.length - 1].name;
      else name = T.cycle[cyc++ % T.cycle.length];
      const bar = { t0: s.t0 + k * d, t1: s.t0 + (k + L) * d, len: L, d, name, chord: T.chords[name], sec: s, short, e: s.kind === 'intro' ? 0 : energy(s.t0 + k * d) };
      if (!bar.chord) throw new Error(`tracks: no chord "${name}"`);
      s.bars.push(bar); bars.push(bar);
      for (let p = 0; p < L; p++) {
        const t = s.t0 + (k + p) * d;
        eighths.push({ t, d, pos: p, bar, sec: s, e: s.kind === 'intro' ? 0 : energy(t), i: eighths.length });
      }
      k += L;
    }
    if (s.kind === 'intro') intro++;
  });
  const away = secs.filter((s) => s.kind === 'away');
  const peak = away.length ? away.reduce((a, b) => (b.e > a.e ? b : a)) : null;
  const release = away.length ? secs.find((s) => s.kind === 'home' && s.t0 >= away[away.length - 1].t1 - 1e-6) || null : null;
  return { secs, bars, eighths, arrive, energy, peak, release, dur: marks.seconds };
}

/** the eighth a time falls on, or null when it is more than `within` s off the grid */
const onGrid = (P, t, within = 0.015) => P.eighths.find((x) => Math.abs(x.t - t) <= within) || null;

const PC = { C: 0, D: 2, E: 4, F: 5, G: 7, A: 9, B: 11 };
const pc = (k) => (PC[k[0]] + (k[1] === '#' ? 1 : k[1] === 'b' ? 11 : 0)) % 12;
/** true when a note is a semitone from one of the notes that will sound over its tail */
const rubs = (k, next) => next.some((q) => { const d = (pc(k) - pc(q) + 12) % 12; return d === 1 || d === 11; });
const LEAD = 1.2;                                          // the pad starts this long before the first frame

/** what every track shares: the pad and the sub under each bar, the intro, the three big moments, the last chord */
function frame(P, marks, m, T) {
  const o = T.frame;
  P.bars.forEach((b, i) => {
    const nx = P.bars[i + 1], len = b.t1 - b.t0, introBar = b.sec.kind === 'intro', lead = i === 0 ? LEAD : 0;
    // a pad rings 2.2 s past its key. Only a note a semitone from one in the next chord is let go early (the third,
    // when major turns to minor); letting the whole chord go made a hole before the cut
    const v = introBar ? o.introPad : o.pad(b.e);
    for (const k of b.chord.pad) m({ at: b.t0 - lead, inst: 'pad', note: k, dur: lead + (nx && rubs(k, nx.chord.pad) ? Math.max(0.3, len - 0.7) : len + 0.2), vel: v });
    m({ at: b.t0 - lead, inst: 'sub', note: b.chord.sub, dur: lead + len, vel: introBar ? o.introPad * 0.5 : o.sub(b.e) });
  });
  // the parts seen landing tick (thinned to one a 70 ms, so a pour is a roll, not a buzz); a case event is a soft thud
  let lastLand = -1;
  marks.lands.forEach((t, i) => { if (t - lastLand < 0.07) return; lastLand = t; m({ at: t, inst: 'hat', note: 'C5', vel: o.tick * (0.75 + 0.25 * (i % 3) / 2), pan: Math.sin(i * 2.3) * 0.5 }); });
  marks.hits.forEach((t, i) => m({ at: t, inst: 'impact', note: 'D2', vel: o.thud * (i === marks.hits.length - 1 ? 1.3 : 1) }));
  // the intro's piano: one slow line that climbs to where the music arrives, a note every two eighths
  P.secs.filter((s) => s.kind === 'intro').forEach((s, i) => o.introFelt[Math.min(i, o.introFelt.length - 1)].forEach((k, j) => {
    const t = s.t0 + 2 * j * s.d;
    if (2 * j < s.n) m({ at: t, inst: 'felt', note: k, dur: 2.6, vel: o.introVel * (0.6 + 0.4 * t / P.arrive), pan: j % 2 ? 0.15 : -0.15 });
  }));
  const big = (t, lead, [riser, impact, crash]) => {
    if (riser && t > 0.3) { const d = Math.min(1.5, lead * 0.6); m({ at: t - d, inst: 'riser', note: 'C3', dur: d, vel: riser }); }
    if (impact) m({ at: t, inst: 'impact', note: 'D2', vel: impact });
    if (crash) m({ at: t, inst: 'crash', note: 'C5', vel: crash });
  };
  big(P.arrive, P.arrive, o.arrive);
  if (P.peak) { const i = P.secs.indexOf(P.peak); big(P.peak.t0, i > 0 ? P.peak.t0 - P.secs[i - 1].t0 : 0, o.peak); }
  if (P.release) { big(P.release.t0, 0, [0, o.release[1], o.release[2]]); o.chord(P.release.t0, P.release.bars[0].chord, 0.5).forEach(m); }
  // the other section cuts are not marked: the chord changes there and the music carries on
  // the last section, when the film ends at home: one chord, and nothing else under the voice
  const end = P.secs[P.secs.length - 1];
  if (end.kind === 'home' && end !== P.release) o.chord(end.t0, end.bars[0].chord, 0.45).forEach(m);
}
/** a chord on the piano, low to high, a hair apart as a hand rolls it */
const rolled = (notes) => (at, c, vel) => (c.full || notes).map((k, i) => ({ at: at + i * 0.018, inst: 'felt', note: k, dur: 3.2, vel: vel * (i < 2 ? 0.9 : 1) }));

/* ---------- steady: the cut-by-cut score's instruments, D minor with D major for the thing working, made continuous ---------- */
const T1 = {
  title: 'steady beat',
  chords: {
    ...SUS,
    Dm: { pad: ['D3', 'F3', 'A3'], sub: 'D2', arp: ['A4', 'D5', 'F5', 'A5'], hook: ['D4', 'F4', 'A4', 'C5', 'A4', 'F4', 'D5', 'A4'] },
    Bb: { pad: ['Bb2', 'D3', 'F3'], sub: 'Bb1', arp: ['Bb4', 'D5', 'F5', 'Bb5'], hook: ['D4', 'F4', 'Bb4', 'C5', 'Bb4', 'F4', 'D5', 'Bb4'] },
    F: { pad: ['F2', 'A3', 'C4'], sub: 'F1', arp: ['A4', 'C5', 'F5', 'A5'], hook: ['C4', 'F4', 'A4', 'C5', 'A4', 'F4', 'C5', 'A4'] },
    C: { pad: ['C3', 'E3', 'G3'], sub: 'C2', arp: ['G4', 'C5', 'E5', 'G5'], hook: ['C4', 'E4', 'G4', 'C5', 'G4', 'E4', 'D5', 'G4'] },
    D: { pad: ['D3', 'A3', 'D4', 'F#4', 'A4'], sub: 'D2', arp: ['A4', 'D5', 'F#5', 'A5'], hook: ['D4', 'F#4', 'A4', 'B4', 'A4', 'F#4', 'D5', 'A4'], major: true },
    G: { pad: ['D3', 'G3', 'B3', 'D4'], sub: 'G1', arp: ['B4', 'D5', 'G5', 'B5'], hook: ['D4', 'G4', 'B4', 'D5', 'B4', 'G4', 'D5', 'B4'], major: true },
  },
  intro: ['Dsus', 'Asus'], cycle: ['Dm', 'Bb', 'F', 'C'], pre: 'C', home: 'D', plagal: 'G',
  pump: 2,
  frame: { pad: (e) => 1.6 + 0.7 * e, sub: (e) => 0.3 + 0.3 * e, introPad: 1.3, introFelt: [['D4', 'A4', 'D5', 'E5'], ['A4', 'E5', 'A5']], introVel: 0.3, tick: 0.24, thud: 0.4,
    arrive: [0.6, 0.7, 0.4], peak: [0.6, 0.7, 0.4], release: [0, 0.35, 0.22], chord: rolled(['D3', 'A3', 'D4', 'F#4', 'A4', 'D5']) },
  layers(P, x, m, kicks) {
    const { t, d, pos, e } = x, c = x.bar.chord;
    if (pos % 2 === 0) {
      // the kick on every half bar is the beat; the ones between come only at the top. None on a bar's last eighth:
      // the next bar's first kick is one eighth after it (a section's last bar may be 9 eighths long)
      const kv = x.bar.len - pos < 2 ? 0 : pos % 4 === 0 ? (0.4 + 0.2 * e) * step(e, 0.2, 0.4) : (0.35 + 0.3 * e) * step(e, 0.8, 0.97);
      if (kv > 0.04) { m({ at: t, inst: 'kick', note: 'G1', vel: kv }); kicks.push([t, kv]); }
      const bv = (0.3 + 0.3 * e) * step(e, 0.25, 0.45);
      if (bv > 0.03) m({ at: t, inst: 'bass', note: up(c.sub), dur: 1.7 * d, vel: bv });
      const q = pos / 2;
      m({ at: t, inst: 'felt', note: c.arp[[0, 1, 2, 3, 2, 1][q % 6]], dur: 1.4, vel: 0.3 * (1 - 0.55 * step(e, 0.5, 0.85)), pan: q % 2 ? 0.2 : -0.2 });
      if (pos % 4 === 0) { const sv = 0.5 * step(e, 0.85, 1); if (sv > 0.03) for (const k of c.pad.slice(0, 3)) m({ at: t, inst: 'stab', note: up(k), dur: 0.5, vel: sv }); }
    } else {
      const hv = (0.2 + 0.2 * e) * step(e, 0.2, 0.4);
      if (hv > 0.02) m({ at: t, inst: 'hat', note: 'C5', vel: hv, pan: 0.15 });
    }
    const pv = (0.36 + 0.1 * e) * step(e, 0.6, 0.8);
    if (pv > 0.03) m({ at: t, inst: 'pluck', note: c.hook[pos % 8], dur: 0.22, vel: pv, pan: Math.sin(x.i * 0.9) * 0.35 });
  },
  cut(P, x, m) {                                          // a shot cut that falls on the grid
    if (x.sec.kind === 'home') for (const k of ['D4', 'A4']) m({ at: x.t, inst: 'felt', note: k, dur: 1.6, vel: 0.3 });
    else if (x.e >= 0.5) m({ at: x.t, inst: 'snare', note: 'C4', vel: 0.22 });
  },
};

/* ---------- piano: a piano: one figure in eighths that never stops, a soft pad under it, no drums; D major ---------- */
const FIG = [0, 2, 1, 2, 3, 2, 1, 2];
const T2 = {
  title: 'piano',
  chords: {
    Dsus: { pad: ['D3', 'A3', 'E4'], sub: 'D2', major: true }, Asus: { pad: ['A2', 'E3', 'D4'], sub: 'A1', major: true },
    Bm: { pad: ['B2', 'F#3', 'D4'], sub: 'B1', lh: ['B2', 'F#3'], rh: ['B3', 'D4', 'F#4', 'B4'], top: ['F#5', 'D5'], major: true },
    G: { pad: ['G2', 'D3', 'B3'], sub: 'G1', lh: ['G2', 'D3'], rh: ['B3', 'D4', 'G4', 'B4'], top: ['E5', 'D5'], major: true },
    'D/F#': { pad: ['F#2', 'D3', 'A3'], sub: 'F#1', lh: ['F#2', 'D3'], rh: ['A3', 'D4', 'F#4', 'A4'], top: ['A5', 'F#5'], major: true },
    A: { pad: ['A2', 'E3', 'C#4'], sub: 'A1', lh: ['A2', 'E3'], rh: ['A3', 'C#4', 'E4', 'A4'], top: ['E5', 'C#5'], major: true },
    D: { pad: ['D3', 'A3', 'F#4'], sub: 'D2', lh: ['D2', 'A2'], rh: ['A3', 'D4', 'F#4', 'A4'], top: ['D5', 'A5'], major: true, full: ['D2', 'A2', 'D3', 'A3', 'D4', 'F#4', 'A4', 'D5'] },
  },
  intro: ['Dsus', 'Asus'], cycle: ['Bm', 'G', 'D/F#', 'A'], pre: 'A', home: 'D', plagal: 'G',
  pump: 0,
  frame: { pad: (e) => 1.25 + 0.5 * e, sub: (e) => 0.22 + 0.22 * e, introPad: 1.15, introFelt: [['D4', 'A4', 'D5', 'E5'], ['A4', 'E5', 'A5']], introVel: 0.3, tick: 0.13, thud: 0.3,
    arrive: [0.4, 0.3, 0], peak: [0.4, 0.3, 0], release: [0, 0.2, 0], chord: rolled(['D2', 'A2', 'D3', 'A3', 'D4', 'F#4', 'A4', 'D5']) },
  layers(P, x, m) {
    const { t, d, pos, e } = x, c = x.bar.chord, n = FIG[pos % 8];
    m({ at: t, inst: 'felt', note: c.rh[n], dur: 1, vel: 0.2 + 0.2 * e + (pos === 0 ? 0.05 : pos % 4 === 0 ? 0.03 : 0) + 0.02 * Math.sin(x.i * 1.7), pan: 0.12 });
    if (pos === 0) m({ at: t, inst: 'felt', note: c.lh[0], dur: x.bar.len * d, vel: 0.26 + 0.15 * e, pan: -0.15 });
    if (pos === 4 && x.bar.len >= 6) m({ at: t, inst: 'felt', note: c.lh[1], dur: 4 * d, vel: 0.22 + 0.14 * e, pan: -0.15 });
    const mv = (0.25 + 0.17 * e) * step(e, 0.45, 0.65);
    if (mv > 0.03 && (pos === 0 || (pos === 4 && x.bar.len >= 6))) m({ at: t, inst: 'felt', note: c.top[pos ? 1 : 0], dur: 4 * d + 0.4, vel: mv, pan: 0.25 });
    const ov = 0.15 * step(e, 0.75, 0.95);
    if (ov > 0.02 && pos % 2 === 0) m({ at: t, inst: 'felt', note: up(c.rh[n]), dur: 0.5, vel: ov, pan: 0.3 });
  },
  cut(P, x, m) { if (x.sec.kind === 'home' && x.sec === P.release) for (const k of ['D4', 'A4']) m({ at: x.t, inst: 'felt', note: k, dur: 1.6, vel: 0.26 }); },
};

/* ---------- laidback: a laid-back beat: half-time kick and snare, soft hats a little late, piano chords, a round bass ---------- */
const T3 = {
  title: 'laid-back beat',
  chords: {
    ...SUS,
    Dm: { pad: ['F3', 'A3', 'C4', 'E4'], sub: 'D2', bass: 'D2', lick: [[2, 'A4', 1], [3, 'C5', 1], [4, 'D5', 4]] },
    Bb: { pad: ['D3', 'F3', 'A3', 'C4'], sub: 'Bb1', bass: 'Bb1', lick: [[3, 'F5', 2], [5, 'D5', 3]] },
    F: { pad: ['A3', 'C4', 'E4', 'G4'], sub: 'F1', bass: 'F2', lick: [[2, 'A4', 1], [3, 'C5', 1], [4, 'E5', 4]] },
    C: { pad: ['E3', 'G3', 'A3', 'D4'], sub: 'C2', bass: 'C2', lick: [[3, 'G5', 2], [5, 'E5', 2], [7, 'D5', 1]] },
    D: { pad: ['F#3', 'A3', 'C#4', 'E4'], sub: 'D2', bass: 'D2', lick: [[2, 'A4', 1], [3, 'B4', 1], [4, 'F#5', 4]], major: true },
    G: { pad: ['B3', 'D4', 'F#4', 'A4'], sub: 'G1', bass: 'G1', lick: [[0, 'B4', 4]], major: true },
  },
  intro: ['Dsus', 'Asus'], cycle: ['Dm', 'Bb', 'F', 'C'], pre: 'C', home: 'D', plagal: 'G',
  pump: 1.5,
  frame: { pad: (e) => 1.6 + 0.7 * e, sub: (e) => 0.3 + 0.25 * e, introPad: 1.3, introFelt: [['D4', 'A4', 'D5', 'E5'], ['A4', 'E5', 'A5']], introVel: 0.3, tick: 0.18, thud: 0.35,
    arrive: [0.5, 0.6, 0.3], peak: [0.4, 0.5, 0.3], release: [0, 0.35, 0.2], chord: rolled(['D3', 'A3', 'F#4', 'A4', 'C#5', 'E5']) },
  layers(P, x, m, kicks) {
    const { d, pos, e } = x, c = x.bar.chord, len = x.bar.len, t = x.t + (pos % 2 ? 0.1 * d : 0);   // the off-beats sit back
    const kick = (v) => { if (v > 0.04) { m({ at: t, inst: 'kick', note: 'G1', vel: v }); kicks.push([t, v]); } };
    if (pos === 0) kick(0.48 * step(e, 0.3, 0.5));
    if ((pos === 5 && len > 6) || (pos === 8 && len >= 10)) kick(0.38 * step(e, 0.3, 0.5));
    if (pos === 4 && len >= 6) { const v = (0.2 + 0.1 * e) * step(e, 0.3, 0.5); if (v > 0.03) m({ at: t, inst: 'snare', note: 'C4', vel: v }); }
    const hv = (pos % 2 ? 0.1 : 0.16) * step(e, 0.25, 0.45);
    if (hv > 0.02) m({ at: t, inst: 'hat', note: 'C5', vel: hv, pan: pos % 2 ? 0.25 : 0.1 });
    if (pos === 0) c.pad.forEach((k, i) => m({ at: t + i * 0.012, inst: 'felt', note: k, dur: Math.min(len, 6) * d, vel: 0.2 + 0.08 * e }));
    if (pos === 3 && len >= 6) { const v = (0.17 + 0.05 * e) * step(e, 0.3, 0.5); if (v > 0.03) c.pad.slice(1).forEach((k, i) => m({ at: t + i * 0.012, inst: 'felt', note: k, dur: 2 * d, vel: v })); }
    const bv = step(e, 0.25, 0.45);
    if (bv > 0.05) {
      if (pos === 0) m({ at: t, inst: 'bass', note: c.bass, dur: Math.min(len, 4.7) * d, vel: 0.4 * bv });
      if (pos === 3 && len >= 6) { const g = step(e, 0.6, 0.8); if (g > 0.05) m({ at: t, inst: 'bass', note: c.bass, dur: 0.8 * d, vel: 0.3 * bv * g }); }
      if (pos === 5 && len > 6) m({ at: t, inst: 'bass', note: c.bass, dur: (len - 5.2) * d, vel: 0.36 * bv });
    }
    const lv = 0.34 * step(e, 0.6, 0.8);
    if (lv > 0.03) for (const [p, k, n] of c.lick) if (p === pos && p < len) m({ at: t, inst: 'felt', note: k, dur: n * d + 0.3, vel: lv, pan: 0.2 });
  },
  cut(P, x, m) { if (x.sec.kind === 'home' && x.sec === P.release) for (const k of ['A4', 'E5']) m({ at: x.t, inst: 'felt', note: k, dur: 1.6, vel: 0.24 }); },
};

/* ---------- cinematic: cinematic: slow swells, a low plucked figure, a rising line on the piano, deep hits, no beat; D major ---------- */
const T4 = {
  title: 'cinematic',
  chords: {
    Dsus: { pad: ['D3', 'A3', 'D4', 'E4'], sub: 'D2', major: true }, Asus: { pad: ['A2', 'E3', 'A3', 'D4'], sub: 'A1', major: true },
    G: { pad: ['G3', 'B3', 'D4'], sub: 'G1', ost: ['G2', 'D3', 'G3', 'D3'], motif: [[0, 'B4', 4], [4, 'D5', 4]], major: true },
    A: { pad: ['A3', 'C#4', 'E4'], sub: 'A1', ost: ['A2', 'E3', 'A3', 'E3'], motif: [[0, 'C#5', 4], [4, 'E5', 4]], major: true },
    Bm: { pad: ['B3', 'D4', 'F#4'], sub: 'B1', ost: ['B2', 'F#3', 'B3', 'F#3'], motif: [[0, 'D5', 4], [4, 'F#5', 4]], major: true },
    Dup: { pad: ['A3', 'D4', 'F#4'], sub: 'D2', ost: ['D3', 'A3', 'D4', 'A3'], motif: [[0, 'A5', 6], [6, 'F#5', 2]], major: true },
    D: { pad: ['D3', 'A3', 'D4', 'F#4'], sub: 'D2', ost: ['D2', 'A2', 'D3', 'A2'], motif: [[0, 'F#5', 4], [4, 'A5', 4]], major: true },
    G2: { pad: ['G3', 'B3', 'D4'], sub: 'G1', ost: ['G2', 'D3', 'G3', 'D3'], motif: [[0, 'G5', 4]], major: true },
  },
  intro: ['Dsus', 'Asus'], cycle: ['G', 'A', 'Bm', 'Dup'], pre: 'A', home: 'D', plagal: 'G2',
  pump: 0,
  frame: { pad: (e) => 1.8 + 0.8 * e, sub: (e) => 0.3 + 0.3 * e, introPad: 1.4, introFelt: [['D4', 'A4', 'D5', 'E5'], ['A4', 'E5', 'A5']], introVel: 0.3, tick: 0.15, thud: 0.4,
    arrive: [0.5, 0.5, 0.2], peak: [0.6, 0.55, 0.25], release: [0, 0.35, 0], chord: rolled(['D2', 'A2', 'D3', 'A3', 'D4', 'F#4', 'A4', 'D5']) },
  layers(P, x, m) {
    const { t, d, pos, e } = x, c = x.bar.chord, len = x.bar.len;
    const ov = (0.42 + 0.3 * e) * step(e, 0.25, 0.45);
    if (ov > 0.03) m({ at: t, inst: 'pluck', note: c.ost[pos % 4], dur: 0.2, vel: ov * (pos % 4 === 0 ? 1.15 : 1), pan: pos % 2 ? 0.15 : -0.15 });
    const hi = step(e, 0.75, 0.95);
    if (hi > 0.05) m({ at: t, inst: 'pluck', note: up(c.ost[pos % 4]), dur: 0.2, vel: ov * 0.6 * hi, pan: pos % 2 ? -0.3 : 0.3 });
    if (pos === 0 && hi > 0.05) {
      for (const k of c.pad) m({ at: t, inst: 'stab', note: up(k), dur: Math.max(0.4, len * d - 0.3), vel: 0.26 * hi });
      if (x.sec !== P.peak || x.bar !== x.sec.bars[0]) m({ at: t, inst: 'impact', note: 'D2', vel: 0.2 * step(e, 0.8, 1) + 0.001 });
    }
    const mv = (0.28 + 0.16 * e) * step(e, 0.35, 0.55);
    if (mv > 0.03) for (const [p, k, n] of c.motif) if (p === pos && p < len) {
      m({ at: t, inst: 'felt', note: k, dur: n * d + 0.5, vel: mv, pan: 0.15 });
      if (hi > 0.05) m({ at: t, inst: 'felt', note: up(k, -1), dur: n * d + 0.5, vel: mv * 0.7 * hi, pan: -0.1 });
    }
  },
  cut() {},
};

export const TRACKS = { steady: T1, piano: T2, laidback: T3, cinematic: T4 };

/** the notes of a track: { notes, kicks: [[t, vel]], bright(t), plan } */
export function notes(marks, T) {
  const P = plan(marks, T), n = [], kicks = [], m = (x) => n.push(x);
  frame(P, marks, m, T);
  for (const x of P.eighths) if (x.sec.kind !== 'intro' && !(x.sec.last && x.sec.kind === 'home')) T.layers(P, x, m, kicks);
  for (const s of P.secs) if (s.kind !== 'intro') for (const t of s.cuts) { const x = onGrid(P, t); if (x) T.cut(P, { ...x, t }, m); }
  const bright = (t) => (t < P.arrive ? 0.15 + 0.5 * S(t / P.arrive) : 0.2 + 0.8 * P.energy(t));
  return { notes: n.filter((x) => (x.at >= 0 || x.inst === 'pad' || x.inst === 'sub') && x.at < P.dur && x.vel > 0), kicks, bright, plan: P };
}

/** the bus dipped on each kick by up to `depth` dB, less for a soft one (the kit's pump has one depth for all) */
function pumpBy({ L, R }, kicks, { depth = 5, attack = 0.004, release = 0.22 } = {}) {
  const n = L.length, oL = new Float32Array(n), oR = new Float32Array(n), at = [...kicks].sort((a, b) => a[0] - b[0]);
  let k = -1;
  for (let i = 0; i < n; i++) {
    const t = i / RATE;
    while (k + 1 < at.length && at[k + 1][0] <= t) k++;
    const dt = k < 0 ? Infinity : t - at[k][0];
    const s = dt < attack ? dt / attack : dt < attack + release ? 0.5 * (1 + Math.cos((Math.PI * (dt - attack)) / release)) : 0;
    const g = k < 0 ? 1 : dB(-depth * Math.min(1, at[k][1] / 0.9) * s);
    oL[i] = L[i] * g; oR[i] = R[i] * g;
  }
  return { L: oL, R: oR };
}

export function score(marks, T) {
  const { notes: n, kicks, bright } = notes(marks, T);
  const dry = renderScore(n, { dur: marks.seconds, bright });
  const room = reverb(T.pump ? pumpBy(dry, kicks, { depth: T.pump }) : dry, { decay: 2.6, wet: 0.28 });
  return fade(toLoudness(filter(room, 'hp', 30), -18).bus, { inS: 0.02, outS: 1.6 });
}

export function mix(marks, T) {
  const music = score(marks, T);
  if (!marks.voice) return music;
  const v = voice(marks);
  return add(duck(music, v.dry, { depth: VOICE.duck, attack: 0.04, release: 0.5 }), v.bus);
}

/** one line per section for the log: its bars and chords */
export const describe = (marks, T) => plan(marks, T).secs.map((s) => `${s.name}@${s.t0.toFixed(1)} ${s.bars.map((b) => `${b.name}(${b.len})`).join(' ')}`).join('  ');
