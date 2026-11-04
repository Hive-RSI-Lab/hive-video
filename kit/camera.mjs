/* camera.mjs (the demo-video skill) — the camera's maths, one pure module: the director works out every frame's view
with it, and encodeClip's compositor puts the frame there (transformOf).

A page is filmed with the camera at rest. Each `d.camera(view)` becomes a cue {t, ms, box, fill, max, dip}: t is ms
on the film's clock, `box` is a box in the rest camera's pixels (null for the whole page). At render time
every output frame asks cameraAt(t) where the camera is and moves the captured frame there, so a move changes on
every frame of the film. A view is {x, y, s}: the point of the
rest frame at the centre, and the scale. */

/** Ease in and out (cubic), the pace of every move in the kit. */
export const ease = (t) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2);

/** The camera at rest on a frame of `size` {w, h}. */
export const rest = (size) => ({ x: size.w / 2, y: size.h / 2, s: 1 });

/** The view a cue asks for: `box` scaled so it takes `fill` of the frame, never under 1x or over `max`, its centre
 *  kept far enough from the edges that the frame stays inside the page. A null box is the whole page. */
export function viewFor(box, size, { fill = 0.92, max = 2.2 } = {}) {
  if (!box) return rest(size);
  const s = Math.max(1, Math.min(max, fill * Math.min(size.w / box.w, size.h / box.h)));
  const hw = size.w / 2 / s, hh = size.h / 2 / s;
  return { x: Math.min(size.w - hw, Math.max(hw, box.x + box.w / 2)), y: Math.min(size.h - hh, Math.max(hh, box.y + box.h / 2)), s };
}

/* One flight from view a to view v, starting at t0 and lasting ms: the centre eases along a line, the scale eases in
log space, and `dip` pulls back at the middle, so a long move between two places reads as a swoop. */
const fly = ({ a, v, t0, ms, dip }, t) => {
  const f = ms > 0 ? Math.min(1, Math.max(0, (t - t0) / ms)) : 1, e = ease(f);
  return {
    x: a.x + (v.x - a.x) * e, y: a.y + (v.y - a.y) * e,
    s: Math.exp(Math.log(a.s) + (Math.log(v.s) - Math.log(a.s)) * e) * (1 - (dip || 0) * Math.sin(Math.PI * f)),
  };
};

/** Where the camera is at `t` ms, given `cues` sorted by t and the view it started in (`from`, default at rest). A
 *  cue that starts while another is still flying starts from wherever that one had got to. */
export function cameraAt(t, cues, size, from = rest(size)) {
  let flight = { a: from, v: from, t0: -Infinity, ms: 0, dip: 0 };
  for (const c of cues) {
    if (c.t > t) break;
    flight = { a: fly(flight, c.t), v: viewFor(c.box, size, c), t0: c.t, ms: c.ms, dip: c.dip || 0 };
  }
  return fly(flight, t);
}

/** The transform that puts view `v` of a rest frame of `size` on screen: translate then scale, origin top left. */
export function transformOf(v, size) {
  return { tx: size.w / 2 - v.s * v.x, ty: size.h / 2 - v.s * v.y, s: v.s };
}
