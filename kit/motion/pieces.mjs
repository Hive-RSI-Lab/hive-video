/* pieces.mjs (the demo-video skill) — the drawn motion pieces a film is cut from, as React components.

    import React from 'react';
    import { pieces } from '<skill>/motion/pieces.mjs';
    const { Ripple, MessageIn, Camera, MotionBlur, Crossfade, Typed } = pieces(React);

pieces(React) takes the film's own React, so this file needs no bundler and no JSX, and the selfcheck renders it with
react-dom/server. Every component takes the film's time `t` in seconds and is a pure function of it (motion.mjs), so
it is frame-exact under Remotion or any frame-stepped renderer. Sizes are design pixels; the render scales them. */
import { EASE, blurTimes, cameraCSS, clamp, drift, lerp, ripple, spring, tween, typed } from './motion.mjs';

export const AMBER = '#F0A63A';

export function pieces(React) {
  const h = React.createElement;
  const abs = (style) => ({ position: 'absolute', ...style });

  /** A touch ripple at (x, y) in its parent at time `at`: a ring that spreads and a press dot. No cursor, no hand. */
  function Ripple({ t, at, x = '50%', y = '50%', color = AMBER, scale = 1 }) {
    const r = ripple(t, at, { r1: 54 * scale, r0: 10 * scale });
    if (!r) return null;
    return h('div', { style: abs({ left: x, top: y, width: 0, height: 0, zIndex: 60, pointerEvents: 'none' }) },
      h('div', { 'data-piece': 'ring', style: abs({ left: -r.r, top: -r.r, width: 2 * r.r, height: 2 * r.r, borderRadius: '50%',
        border: `${4 * scale}px solid ${color}`, opacity: r.ring, boxSizing: 'border-box' }) }),
      r.dot > 0 && h('div', { 'data-piece': 'dot', style: abs({ left: -14 * scale, top: -14 * scale, width: 28 * scale, height: 28 * scale,
        borderRadius: '50%', background: color, opacity: r.dot * 0.6 }) }));
  }

  /** A new item in a list: its height opens on a spring so what is above slides up, and it rises and sharpens into place.
   *  The height opens as a grid row of `p`fr, which Chrome sizes to p times the item's real height, so no estimate is
   *  needed: an estimate over the real height stopped the slide dead before the spring had settled (a held frame), and one
   *  under it made the item jump when it finished. The row stays on after it has opened (only the clip goes): dropping it
   *  moved the text a fraction of a pixel and re-rastered it, a one-frame pop on a still frame. The blur drops while the rise still moves fast (q 0.85): Chrome rasters a
   *  filtered layer differently, so a blur ending on the spring's still tail pops a frame after a held one. `dur` opens a
   *  tall item on a smoothstep over that many s instead of the spring: its peak speed is 1.5x its mean (the spring starts at
   *  its fastest), and it comes to rest at `dur` exactly, so what it pushes up neither lurches nor creeps a pixel late. */
  const BLUR_END = 0.85;
  const smooth = (x) => x * x * (3 - 2 * x);
  function MessageIn({ t, at, rise = 18, dur, children }) {
    if (at != null && t < at) return null;
    const p = at == null ? 1 : dur ? smooth(clamp((t - at) / dur)) : spring(t, at, { freq: 2.0 });
    const q = at == null ? 1 : dur ? smooth(clamp((t - at) / (0.8 * dur))) : spring(t, at + 0.04, { freq: 2.4 });
    const done = p > 0.999;
    return h('div', { 'data-piece': 'message', style: at == null ? { flex: 'none' } : { flex: 'none', display: 'grid', gridTemplateRows: `${p}fr` } },
      h('div', { style: { minHeight: 0, overflow: done ? 'visible' : 'hidden' } },
      h('div', { style: { opacity: clamp(q * 1.4), transform: `translateY(${lerp(rise, 0, q)}px) scale(${lerp(0.985, 1, q)})`,
        transformOrigin: 'left bottom', filter: q < BLUR_END ? `blur(${(1 - q) * 3}px)` : 'none' } }, children)));
  }

  /** Text typed from t0 to t1, with a caret while typing (and blinking after, while `caret` is on). */
  function Typed({ t, t0, t1, text, caret = true, color = 'currentColor' }) {
    const s = t < t0 ? '' : typed(text, t, t0, t1);
    const on = caret && (t < t1 || Math.floor((t - t1) / 0.53) % 2 === 1);
    return h(React.Fragment, null, s,
      caret && h('span', { style: { display: 'inline-block', width: 2, height: '1.05em', background: color, verticalAlign: 'text-bottom',
        marginLeft: 1, opacity: on ? 1 : 0 } }));
  }

  /** A camera over a design-space stage: `view` {s, fx, fy} puts design point (fx, fy) at the frame's centre (cx, cy)
   *  at scale s. `depth` < 1 is a far layer (it moves and zooms less: parallax), and `drift` adds a slow hand-held sway. */
  function Camera({ view, t = 0, w = 1280, ht = 720, cx = w / 2, cy = ht / 2, depth = 1, driftAmp = 0, seed = 1, children }) {
    const d = driftAmp ? drift(t, { amp: driftAmp, seed }) : { x: 0, y: 0, s: 1 };
    const s = (1 + (view.s - 1) * depth) * d.s;
    const fx = view.fx == null ? cx : cx + (view.fx - cx) * depth, fy = view.fy == null ? cy : cy + (view.fy - cy) * depth;
    return h('div', { 'data-piece': 'camera', style: abs({ left: 0, top: 0, width: w, height: ht, transformOrigin: '0 0',
      transform: `translate(${d.x * depth}px, ${d.y * depth}px) ${cameraCSS({ s, fx, fy }, cx, cy)}` }) }, children);
  }

  /** Motion blur for a fast move: `render(t)` drawn at n sub-frame times across the shutter and averaged (layer k at
   *  opacity 1/(k+1) over the ones behind it weighs every sample equally). Pass n = 1 where the move is slow. */
  function MotionBlur({ t, fps = 30, n = 6, shutter = 0.5, render }) {
    const ts = blurTimes(t, fps, n, shutter);
    if (ts.length === 1) return render(t);
    return h('div', { 'data-piece': 'blur', style: abs({ inset: 0 }) },
      ...ts.map((ti, k) => h('div', { key: k, 'data-sample': k, style: abs({ inset: 0, opacity: 1 / (k + 1) }) }, render(ti))));
  }

  /** `from` until t0, `to` after t0 + dur, and a crossfade between: the one dissolve a film keeps for its end card. */
  /* each side is its own stacking context, so a z-index inside `from` stays there and `to` always paints over it */
  function Crossfade({ t, t0, dur = 0.5, from, to }) {
    const x = tween(t, t0, t0 + dur, 0, 1, EASE.inOut);
    return h('div', { style: abs({ inset: 0 }) },
      x < 1 && h('div', { style: abs({ inset: 0, isolation: 'isolate' }) }, from()),
      x > 0 && h('div', { style: abs({ inset: 0, opacity: x, isolation: 'isolate' }) }, to()));
  }

  return { Ripple, MessageIn, Typed, Camera, MotionBlur, Crossfade };
}
