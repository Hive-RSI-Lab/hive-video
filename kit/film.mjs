/* film.mjs (the demo-video skill) — what every demo video shares: a director that films a few short beats of a page
frame by frame, a cursor and a camera drawn over them, a check that nothing real is in frame, and the encode: each
beat a clip with its caption, the clips cut or crossfaded into one film, and a GIF of it. A surface seeds its own
fake data, starts its own throwaway server and writes the script.

The page runs on a virtual clock (Playwright's clock, with the page's CSS animations held and set by it) that moves
one frame at a time, and each frame is captured at 2x after the clock has moved, so a film is frame-exact at 30 or
60 fps however slow the box is: an animation, a scroll or typing moves exactly one frame's worth a frame, and a slow
capture only makes the render take longer. The cursor, the click ring and the camera are not in the page: each frame
records where they are, and encodeClip draws them over the capture in a compositor page before one near-lossless
encode of the image sequence; stitch makes the final encode. */
import { mkdirSync, writeFileSync, rmSync, symlinkSync } from 'node:fs';
import { execFileSync, spawnSync } from 'node:child_process';
import { dirname, extname, join, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { cameraAt, transformOf } from './camera.mjs';

export const FFMPEG = process.env.FFMPEG || '/usr/bin/ffmpeg';

/* The pace (docs/demo-video-research.md): a film of about 20 s and never over MAX_FILM_S, quick cuts, and a result
held at least RESULT_MS so it can be read — a floor for a result, not the pace of the film. */
export const RESULT_MS = 800;
export const MAX_FILM_S = 30;

/* The caption, in one place: a strip of its own below (or above) the page, drawn by ffmpeg, so it never covers what
it describes. One caption per beat. The look is the library's: its paper and ink, a rust mark before the words, and
Source Serif. Change the look here and nowhere else; a surface with a font of its own sets CAPTION.font (or
DEMO_CAPTION_FONT), and without either it is the system's semibold serif. */
const serif = () => { try { return execFileSync('fc-match', ['-f', '%{file}', 'serif:semibold'], { encoding: 'utf8' }); } catch { return ''; } };
export const CAPTION = {
  at: 'bottom',                                  // 'bottom' or 'top'
  height: 56,                                    // px; the page's viewport is the film's height less this
  bg: '#FAF8F3', rule: '#DED8CA',                // the library's paper, and a hairline between it and the page
  ink: '#15140F', accent: '#9C4221',             // the words, and the mark before them
  font: process.env.DEMO_CAPTION_FONT || serif(), size: 23,
  x: 36,                                         // left inset of the mark; the words follow it
};

// The director's zoom (CSS zoom on the root), so a layout made for 1280x720 fills a 1920x1080 viewport sharply.
const ZOOM = String.raw`(() => {
  const z = window.__demoZoom;
  if (!z || z === 1) return;
  const zoom = () => { document.documentElement.style.zoom = z; };
  if (document.documentElement) zoom(); else addEventListener('DOMContentLoaded', zoom);
  // Chrome does not divide viewport units by the root's zoom: 100vh would be zoom times the window. Rewrite them in
  // every same-origin style rule, once each, so a page sized in vh/vw fits the frame.
  const done = new WeakSet(), unit = /(-?[\d.]+)([dsl]?v(?:h|w|min|max))\b/g;
  const walk = (rules) => {
    for (const r of rules) {
      if (r.cssRules) walk(r.cssRules);
      if (!r.style || done.has(r)) continue;
      done.add(r);
      for (const prop of [...r.style]) {
        const v = r.style.getPropertyValue(prop);
        if (unit.test(v)) r.style.setProperty(prop, v.replace(unit, (m) => 'calc(' + m + ' / ' + z + ')'), r.style.getPropertyPriority(prop));
        unit.lastIndex = 0;
      }
    }
  };
  const fix = () => { for (const sheet of document.styleSheets) { try { walk(sheet.cssRules); } catch (e) {} } };
  addEventListener('DOMContentLoaded', fix);
  addEventListener('load', fix);
  addEventListener('load', () => new MutationObserver(fix).observe(document.head, { childList: true }));
})();`;

/* The page's CSS animations and transitions on the film's clock. The first time a frame sees an animation it pauses
it and notes where it was; from then on every frame sets it to the page's (virtual) performance.now() since then, so
an animation moves exactly one frame's worth per frame. FREE hands them back to the real clock between beats. An
animation the page paused itself is left alone. */
const SEEK = String.raw`(() => {
  const t = performance.now();
  for (const a of document.getAnimations()) {
    if (a.__dv == null) { if (a.playState === 'paused') continue; a.__dv = t - (a.currentTime || 0); a.pause(); }
    a.currentTime = t - a.__dv;
  }
})()`;
const FREE = String.raw`(() => { for (const a of document.getAnimations()) if (a.__dv != null) { delete a.__dv; a.play(); } })()`;

/** A hand's pace along a move (minimum jerk): it sets off gently, is quickest in the middle and settles. */
export const handEase = (t) => t * t * t * (10 - 15 * t + 6 * t * t);
/** How long a hand takes to cross `dist` px (Fitts's law): a short hop is quick, a long reach longer but not in
 *  proportion, and never over 900 ms. */
export const reachMs = (dist) => (dist < 1 ? 0 : Math.round(Math.min(900, 160 + 115 * Math.log2(1 + dist / 60))));

/** Every render runs the kit's own selfcheck first (once per process tree), so a broken kit fails loudly before
 *  anything is filmed. DEMO_VIDEO_CHECKED is set for the rest of the run and inherited by the selfcheck itself. */
export function preflight() {
  if (process.env.DEMO_VIDEO_CHECKED) return;
  process.env.DEMO_VIDEO_CHECKED = '1';
  const r = spawnSync(process.execPath, ['--no-warnings', join(dirname(fileURLToPath(import.meta.url)), 'selfcheck.mjs')],
    { encoding: 'utf8', env: process.env });
  if (r.status !== 0) throw new Error(`demo-video selfcheck failed, so nothing was filmed:\n${(r.stdout || '') + (r.stderr || '')}`);
}

let filming = null;   // the director whose beat is open: sleep() is its clock while it is
const realSleep = (ms) => new Promise((r) => setTimeout(r, ms));
/** Wait `ms`: on the film's clock inside a beat (so many frames), on the real one outside. */
export const sleep = (ms) => (filming ? filming.hold(ms) : realSleep(ms));

/* How long the script may sit in a beat without a director call before the film's clock runs on its own, so a page
call that waits on page time and was not given to d.wait() still finishes. Each frame is still exact; only the
length of that stretch then depends on how long the script took. */
const IDLE_MS = 1500;

/** The director of one page. The page runs on a virtual clock (Playwright's clock plus its CSS animations held and
 *  set per frame) that moves only when the film does, and each frame is captured at `scale`x the viewport, so the
 *  film is frame-exact at `fps` whatever the box's load. Frames are taken only inside the director's own calls that
 *  take time (hold, show, sleep, moveTo, click, type, press, scrollTo, drag, camera with ms, wait); a `beat()` takes
 *  none until the first of them, so a camera cue given right after it is in force from its first frame. The cursor
 *  and the click ring are not in the page: each frame records where they are, and encodeClip draws them. Call it
 *  before the page's first goto, so its clock is installed before the page's scripts run. */
export async function director(page, { frames, deny = [], zoom = 1, fps = 30, scale = 2 }) {
  preflight();
  if (!Number.isInteger(fps) || fps <= 0) throw new Error(`fps is ${fps}: a whole number of frames a second, 30 or 60`);
  await page.addInitScript(`window.__demoZoom = ${Number(zoom)};`);
  await page.addInitScript(ZOOM);
  await page.clock.install();
  // the clock's own time, kept before the page's scripts run (an app may wrap Date, and pauseAt is on the clock's time)
  await page.addInitScript('(() => { const D = Date; window.__filmNow = () => D.now(); })();');
  const cdp = await page.context().newCDPSession(page);
  const vp = (page.viewportSize && page.viewportSize()) || { width: 1280, height: 720 };
  const size = { w: vp.width, h: vp.height };
  const beats = [];   // {name, caption, shots: [{file, k, cursor, click}], ended, pumped}
  const cues = [];    // the camera's moves, {t (ms on the film's clock), ms, box, fill, max, dip}
  const clicks = [];  // {k, x, y}
  let k = 0, n = 0, pos = null, sent = null, state = 'idle', busy = 0, last = Date.now(), lock = Promise.resolve(), seed = 7;
  const rand = () => ((seed = (seed * 16807) % 2147483647) / 2147483647);
  const frameOf = (ms) => Math.max(0, Math.round((ms * fps) / 1000));
  const cur = () => beats[beats.length - 1];
  mkdirSync(frames, { recursive: true });
  // a press, the director's or the script's own, is where the click ring spreads from
  const down = page.mouse.down.bind(page.mouse);
  page.mouse.down = (o) => { clicks.push({ k, x: pos ? pos.x : 0, y: pos ? pos.y : 0 }); return down(o); };

  /* One frame: the clock on by 1/fps (whole ms that add up exactly), the animations set to it, the mouse where the
  cursor is, and the page captured. Outside a beat (state idle) there is no frame to take. */
  const step = async () => {
    // frame i is the i-th taken (from 0); a cue or a press made with i frames taken is in force from frame i
    const i = k++, dt = Math.round((k * 1000) / fps) - Math.round((i * 1000) / fps);
    await page.clock.runFor(dt);
    await Promise.all(page.frames().map((f) => f.evaluate(SEEK).catch(() => {})));
    if (pos && (!sent || sent.x !== pos.x || sent.y !== pos.y)) { await page.mouse.move(pos.x, pos.y); sent = { ...pos }; }
    const { data } = await cdp.send('Page.captureScreenshot',
      { format: 'png', optimizeForSpeed: true, clip: { x: 0, y: 0, width: size.w, height: size.h, scale } });
    const file = join(frames, `f${String(++n).padStart(6, '0')}.png`);
    writeFileSync(file, Buffer.from(data, 'base64'));
    const c = clicks[clicks.length - 1];
    cur().shots.push({ file, k: i, cursor: pos && { ...pos }, click: c && { x: c.x, y: c.y, age: (i - c.k) / fps } });
  };
  /* Everything that takes frames goes through here, one at a time. The first call of a beat stops the page's clock. */
  const frames_ = (fn) => {
    busy++;
    last = Date.now();
    const run = lock.then(async () => {
      if (state === 'armed') {
        // the page's clock is running until now, so aim a little ahead of it, and further if it got there first
        for (let ahead = 50; ; ahead *= 4) {
          try { await page.clock.pauseAt((await page.evaluate(() => (window.__filmNow || Date.now)())) + ahead); break; } catch (e) { if (ahead > 5000 || !/past/.test(e.message)) throw e; }
        }
        state = 'rolling';
      }
      return fn();
    });
    lock = run.catch(() => {});
    return run.finally(() => { busy--; last = Date.now(); });
  };
  const steps = (count) => frames_(async () => { for (let i = 0; i < count; i++) await step(); });
  // the script sat in a beat on something that waits on page time: run the clock until it calls the director again
  const pump = setInterval(() => {
    if (busy || state === 'idle' || Date.now() - last < IDLE_MS) return;
    frames_(async () => { while (busy === 1 && state !== 'idle') { await step(); cur().pumped++; } }).catch(() => {});
  }, 200);
  pump.unref();
  /* Back to real time: the clock runs again and the animations are handed back. The beat stays current (a cut). */
  const release = async () => {
    const was = state;
    if (was === 'idle') return;
    state = 'idle';   // first, so a running pump stops after its frame
    filming = null;
    await lock;
    if (was === 'rolling') {
      await page.clock.resume();
      await Promise.all(page.frames().map((f) => f.evaluate(FREE).catch(() => {})));
    }
  };
  const end = async () => {
    const b = cur();
    if (!b || b.ended) return;
    await release();
    b.ended = true;
    if (b.pumped) console.warn(`demo: beat ${b.name}: the clock ran on its own for ${b.pumped} frames; give a page call that waits on page time to d.wait()`);
    await d.scrub();
  };
  /** The cursor from where it is to `to` over `ms`, bent sideways by `bend` px at the middle, one position a frame. */
  const glide = async (to, ms, bend) => {
    if (state === 'idle' || !pos) { pos = { x: to.x, y: to.y }; await page.mouse.move(pos.x, pos.y); sent = { ...pos }; return; }
    const from = { ...pos }, dist = Math.hypot(to.x - from.x, to.y - from.y), count = frameOf(ms);
    const nx = -(to.y - from.y) / (dist || 1), ny = (to.x - from.x) / (dist || 1);
    await frames_(async () => {
      for (let i = 1; i <= count; i++) {
        const t = handEase(i / count), arc = Math.sin(Math.PI * t) * bend;
        pos = { x: from.x + (to.x - from.x) * t + nx * arc, y: from.y + (to.y - from.y) * t + ny * arc };
        await step();
      }
    });
    pos = { x: to.x, y: to.y };
  };
  const d = {
    page, fps, size, scale,
    /** Start the next beat, a clip of its own under `caption` (the caption is checked like the page). */
    async beat(name, caption) {
      await end();
      const hit = firstDenied(caption, deny);
      if (hit) throw new Error(`a real name is in the caption ("${hit}")`);
      beats.push({ name, caption, shots: [], ended: false, pumped: 0 });
      await d.scrub();
      state = 'armed';
      filming = d;
      last = Date.now();
    },
    /** Resume the current beat after a cut. */
    async roll() { if (state === 'idle') { state = 'armed'; filming = d; last = Date.now(); } },
    /** Pause the current beat: what happens until the next roll() is not in it, and runs in real time. */
    cut: () => release(),
    /** End the last beat. */
    stop: () => end(),
    /** Let `ms` of the film pass: that many frames, the page's clock on with them. Outside a beat, real time. */
    hold: (ms) => (state === 'idle' ? realSleep(ms) : steps(frameOf(ms))),
    /** Hold on a result long enough to read it: at least RESULT_MS, whatever the pace around it. */
    show: (ms = RESULT_MS) => { if (ms < RESULT_MS) throw new Error(`a result is held ${ms} ms, under the ${RESULT_MS} ms floor`); return d.hold(ms); },
    /** Film until `promise` (a page call that takes page time: typing in the page, a replay, a scroll) settles, and
     *  return what it gave. Fails after `max` ms of film. Outside a beat it is just awaited. */
    async wait(promise, { max = 60000 } = {}) {
      let done = false, value, error;
      Promise.resolve(promise).then((v) => { done = true; value = v; }, (e) => { done = true; error = e; });
      if (state === 'idle') return promise;
      await frames_(async () => {
        for (let i = 0; !done; i++) {
          if (i >= frameOf(max)) throw new Error(`d.wait: still waiting after ${max} ms of film`);
          await step();
        }
      });
      if (error) throw error;
      return value;
    },
    /** Move the camera to `view` over `ms`: 'all' (the whole page), a locator, or a box {x, y, w, h} in screen pixels.
     *  The page is never moved (it is filmed at rest, so a box, the cursor and a click are all in the same pixels
     *  whatever the camera does): the move is kept as a cue on the film's clock and drawn by encodeClip, and this
     *  takes `ms` of film. Right after beat() the cue is in force from the beat's first frame. `fill` is how much of
     *  the frame the box takes, `max` caps the zoom (research: 1.5-2.2x reads as a zoom, more loses the place),
     *  `dip` pulls back mid-flight for a swoop. */
    async camera(view, { ms = 700, fill = 0.92, max = 2.2, dip = 0 } = {}) {
      let box = null;
      if (view !== 'all') {
        box = view;
        if (typeof view.boundingBox === 'function') {
          const r = await view.boundingBox();
          if (!r) throw new Error('nothing to point the camera at: ' + view);
          box = { x: r.x, y: r.y, w: r.width, h: r.height };
        }
      }
      await lock;
      cues.push({ t: (k * 1000) / fps, ms, box, fill, max, dip });
      if (ms > 0) await d.hold(ms);
    },
    /** Move the cursor to (x, y) as a hand does: along a slight arc, easing off and settling, in `ms` (by default
     *  longer for a longer reach, reachMs). The first move of a film puts the cursor there without travel. */
    async moveTo(x, y, ms) {
      const dist = pos ? Math.hypot(x - pos.x, y - pos.y) : 0;
      const bend = Math.min(40, dist * 0.08) * (pos && x > pos.x ? -1 : 1);
      await glide({ x, y }, ms ?? reachMs(dist), bend);
    },
    /** Tell the page where the mouse is again (after a reload the page has forgotten it). */
    async park() { if (pos) { await page.mouse.move(pos.x, pos.y); sent = { ...pos }; } },
    /** The point to aim at in a locator's box: fx, fy are fractions of its width and height. */
    async aim(loc, fx = 0.5, fy = 0.5) {
      // a toolbar that re-renders between the lookup and the scroll detaches the element: look it up again
      for (let i = 0; ; i++) {
        try { await loc.scrollIntoViewIfNeeded(); break; } catch (e) { if (i >= 3 || !/not attached/.test(e.message)) throw e; await realSleep(100); }
      }
      const b = await loc.boundingBox();
      if (!b) throw new Error('nothing to aim at: ' + loc);
      return { x: b.x + b.width * fx, y: b.y + b.height * fy };
    },
    async click(loc, opts = {}) {
      const p = await d.aim(loc, opts.fx, opts.fy);
      await d.moveTo(p.x, p.y);
      await d.hold(70);
      await page.mouse.down(); await d.hold(50); await page.mouse.up();
      await d.hold(opts.after ?? 220);
      await d.scrub();
    },
    /** Scroll `loc`'s nearest scrolling box, eased over `ms`, until its middle sits at `frac` of the viewport's
     *  height (as far as the box can go). In the page, on its clock, so the scroll moves one frame's worth a frame. */
    async scrollTo(loc, frac = 0.45, ms = 450) {
      await d.wait(loc.evaluate((el, [frac, ms]) => new Promise((done) => {
        let box = el.parentElement;
        while (box && !(box.scrollHeight > box.clientHeight + 1 && /(auto|scroll)/.test(getComputedStyle(box).overflowY))) box = box.parentElement;
        box = box || document.scrollingElement;
        const r = el.getBoundingClientRect();
        const from = box.scrollTop;
        const to = Math.max(0, Math.min(box.scrollHeight - box.clientHeight, from + r.top + r.height / 2 - innerHeight * frac));
        const e = (t) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2);
        const t0 = performance.now();
        const step = (now) => {
          const t = Math.min(1, (now - t0) / ms);
          box.scrollTop = from + (to - from) * e(t);
          if (t < 1) requestAnimationFrame(step); else done();
        };
        requestAnimationFrame(step);
      }), [frac, ms]));
      await d.hold(80);
    },
    /** Drag-select from one point to another, quick but visible. */
    async drag(a, b, ms = 320) {
      await d.moveTo(a.x, a.y); await d.hold(60);
      await page.mouse.down();
      await glide(b, ms, 0);
      await page.mouse.up(); await d.hold(120);
    },
    /** Type as a quick typist does, about `cps` keys a second of film, not every key at the same speed (the same
     *  uneven pace on every render). */
    async type(text, cps = 32) {
      let due = 0, at = 0;
      for (const ch of text) {
        await page.keyboard.type(ch);
        due += (1000 / cps) * (0.6 + rand() * 0.8) * (ch === ' ' ? 1.3 : 1);
        const count = frameOf(due) - at;
        at += count;
        await d.hold((count * 1000) / fps);
      }
    },
    async press(key, after = 250) { await page.keyboard.press(key); await d.hold(after); },
    /** Fail if any denied word is on screen: the visible text, field values and the tab title. */
    async scrub() {
      const seen = await page.evaluate(() => [document.title, document.body.innerText,
        ...[...document.querySelectorAll('input, textarea')].map((e) => e.value || e.placeholder || '')].join('\n'));
      const hit = firstDenied(seen, deny);
      if (hit) throw new Error(`a real name is in frame ("${hit}") at ${page.url()}`);
    },
    /** The beats, each with its frames and where the camera, the cursor and a click are on each:
     *  [{name, caption, fps, size, scale, frames: [{file, dur, view, cursor, click}], camera: {size, cues}}]. */
    beats() {
      return beats.map((b) => ({
        name: b.name, caption: b.caption, fps, size, scale,
        frames: b.shots.map((s) => ({ file: s.file, dur: 1 / fps, view: cameraAt((s.k * 1000) / fps, cues, size), cursor: s.cursor, click: s.click })),
        camera: { size, cues },
      }));
    },
  };
  return d;
}

/** The first denied word in `text`, any case; none: undefined. */
export function firstDenied(text, deny) {
  const low = String(text).toLowerCase();
  return deny.find((w) => low.includes(w.toLowerCase()));
}

const hex = (c) => c.replace(/^#/, '0x');
const q = ['-hide_banner', '-loglevel', 'error', '-y'];
/* THE ENCODER: plain ffmpeg (libx264) on the CPU. */
const ff = (args) => execFileSync(FFMPEG, args, { stdio: 'inherit' });
const H264 = ['-c:v', 'libx264', '-preset', 'slow', '-crf', '16', '-pix_fmt', 'yuv420p', '-movflags', '+faststart'];

/** The ffmpeg filter that adds the caption strip (CAPTION's look) to a frame, its words read from `textFile`.
 *  Exported for the selfcheck. */
export function captionFilter(textFile, cap = CAPTION) {
  const H = cap.height, strip = cap.at === 'top' ? '0' : `ih-${H}`;
  const pad = cap.at === 'top' ? `pad=iw:ih+${H}:0:${H}:color=${hex(cap.bg)}` : `pad=iw:ih+${H}:0:0:color=${hex(cap.bg)}`;
  const rule = `drawbox=x=0:y=${cap.at === 'top' ? H - 1 : `ih-${H}`}:w=iw:h=1:color=${hex(cap.rule)}:t=fill`;
  const bar = `drawbox=x=${cap.x}:y=${strip}+${Math.round(H / 2 - cap.size * 0.55)}:w=3:h=${Math.round(cap.size * 1.1)}:color=${hex(cap.accent)}:t=fill`;
  // drawtext calls the frame's height h, not ih
  const words = `drawtext=fontfile='${cap.font}':textfile='${textFile}':fontsize=${cap.size}:fontcolor=${hex(cap.ink)}:` +
    `x=${cap.x + 16}:y=${cap.at === 'top' ? '0' : `h-${H}`}+(${H}-lh)/2:y_align=font`;
  return [pad, rule, bar, words].join(',');
}

/* The compositor's page: one canvas the film's size. draw() puts a captured frame (at `scale`x) where the camera
has it, then the cursor and the click ring over it, all in the rest frame's pixels moved by the camera, so the
cursor stays on the page it points at. The cursor is the kit's arrow; the ring spreads and fades over 0.4 s. */
const COMPOSITOR = String.raw`<!doctype html><html><body style="margin:0;overflow:hidden">
<canvas id="c"></canvas><script>
const c = document.getElementById('c'), g = c.getContext('2d');
const ARROW = new Path2D('M3 2 L3 21 L8 16.5 L11.5 24 L14.8 22.6 L11.4 15.2 L18 15.2 Z');
window.draw = async ({ src, w, h, scale, bg, tx, ty, s, cursor, click }) => {
  if (c.width !== w) { c.width = w; c.height = h; }
  const im = new Image(); im.src = src; await im.decode();
  g.setTransform(1, 0, 0, 1, 0, 0);
  g.fillStyle = bg; g.fillRect(0, 0, w, h);
  g.imageSmoothingEnabled = true; g.imageSmoothingQuality = 'high';
  g.drawImage(im, tx, ty, (im.width / scale) * s, (im.height / scale) * s);
  if (click && click.age < 0.4) {
    const f = click.age / 0.4, e = 1 - Math.pow(1 - f, 2);
    g.setTransform(s, 0, 0, s, tx, ty);
    g.globalAlpha = 0.9 * (1 - e);
    g.strokeStyle = '#9C4221'; g.lineWidth = 3;
    g.beginPath(); g.arc(click.x, click.y, 16.5 * (0.3 + 1.1 * e), 0, 2 * Math.PI); g.stroke();
    g.globalAlpha = 1;
  }
  if (cursor) {
    g.setTransform(s, 0, 0, s, tx + s * (cursor.x - 3), ty + s * (cursor.y - 2));
    g.shadowColor = 'rgba(0,0,0,.35)'; g.shadowBlur = 3 * s; g.shadowOffsetY = 2 * s;
    g.fillStyle = '#111'; g.fill(ARROW);
    g.shadowColor = 'transparent';
    g.strokeStyle = '#fff'; g.lineWidth = 1.6; g.lineJoin = 'round'; g.stroke(ARROW);
  }
};
</script></body></html>`;

/* The one near-lossless encode between the frames and the film (stitch makes the final one). */
const CLIP = ['-c:v', 'libx264', '-preset', 'medium', '-crf', '6', '-pix_fmt', 'yuv420p', '-movflags', '+faststart'];

/** One beat's clip: every frame the director took, framed by the camera, with the cursor and the click ring drawn
 *  on it (the compositor above, in Chromium), then the image sequence encoded once at -framerate `fps`, near
 *  lossless, with its caption strip when it has a caption. Resolves to the clip's seconds. */
export async function encodeClip(beat, { mp4, work, bg = '#ffffff' }) {
  if (!beat.frames.length) throw new Error(`beat ${beat.name} has no frames`);
  const dir = join(work, `${beat.name}.frames`), text = join(work, `${beat.name}.caption.txt`);
  rmSync(dir, { recursive: true, force: true });
  mkdirSync(dir, { recursive: true });
  writeFileSync(join(work, `${beat.name}.camera.json`), JSON.stringify(beat.camera));   // the moves, to check a clip against
  const html = join(work, 'compositor.html');
  writeFileSync(html, COMPOSITOR);
  const { launch } = await import('./deps.mjs');
  const browser = await launch(['--allow-file-access-from-files']);
  try {
    const { w, h } = beat.size;
    const page = await (await browser.newContext({ viewport: { width: w, height: h } })).newPage();
    const cdp = await page.context().newCDPSession(page);
    await page.goto(pathToFileURL(html).href);
    for (const [i, f] of beat.frames.entries()) {
      const { tx, ty, s } = transformOf(f.view, beat.size);
      await page.evaluate((o) => window.draw(o), { src: pathToFileURL(f.file).href, w, h, scale: beat.scale, bg, tx, ty, s, cursor: f.cursor, click: f.click });
      const { data } = await cdp.send('Page.captureScreenshot', { format: 'png', optimizeForSpeed: true, clip: { x: 0, y: 0, width: w, height: h, scale: 1 } });
      writeFileSync(join(dir, `c${String(i + 1).padStart(6, '0')}.png`), Buffer.from(data, 'base64'));
    }
  } finally { await browser.close(); }
  writeFileSync(text, beat.caption || '');
  const vf = beat.caption ? captionFilter(text) + ',' : '';
  ff([...q, '-framerate', String(beat.fps), '-i', join(dir, 'c%06d.png'),
    '-vf', `${vf}scale=trunc(iw/2)*2:trunc(ih/2)*2:out_range=tv,format=yuv420p`, ...CLIP, mp4]);
  if (!process.env.DEMO_KEEP) rmSync(dir, { recursive: true, force: true });
  return beat.frames.length / beat.fps;
}

/** Frames, each {file, dur} (a still of the shot's own timing), as a clip at `fps`: each output frame is the latest
 *  frame that has begun by then, linked into one numbered image sequence and encoded once at -framerate, so every
 *  timestamp is an exact 1/fps step (a concat list rounds them). yuv420p in TV range (a full-range PNG or JPEG shows
 *  washed out in some players), with an optional extra filter `vf`. `list` names the work directory's stem. Returns
 *  seconds. */
export function encodeFrames(frames, { mp4, list, vf = '', fps = 30 }) {
  const kept = frames.filter((f) => f.dur > 0);
  if (!kept.length) throw new Error(`no frames for ${mp4}`);
  const secs = kept.reduce((s, f) => s + f.dur, 0), count = Math.max(1, Math.round(secs * fps));
  const seq = `${list}.seq`, ext = extname(kept[0].file);
  rmSync(seq, { recursive: true, force: true });
  mkdirSync(seq, { recursive: true });
  let i = 0, start = 0;
  for (let o = 0; o < count; o++) {
    const t = (o + 0.5) / fps;   // the middle of the output frame, so a frame of exactly 1/fps lands on one
    while (i + 1 < kept.length && start + kept[i].dur <= t) { start += kept[i].dur; i++; }
    symlinkSync(resolve(kept[i].file), join(seq, `s${String(o + 1).padStart(6, '0')}${ext}`));
  }
  ff([...q, '-framerate', String(fps), '-i', join(seq, `s%06d${ext}`),
    '-vf', `${vf ? vf + ',' : ''}scale=trunc(iw/2)*2:trunc(ih/2)*2:out_range=tv,format=yuv420p`, ...CLIP, mp4]);
  rmSync(seq, { recursive: true, force: true });
  return count / fps;
}

/** Where each crossfade starts, for clips of these lengths joined with `fade` seconds of overlap. Exported for the
 *  selfcheck. */
export function fadeOffsets(lengths, fade) {
  const out = [];
  let t = 0;
  for (let i = 0; i < lengths.length - 1; i++) { t += lengths[i] - fade; out.push(t); }
  return out;
}

/** The clips joined into one film, the film's one final encode: hard cuts by default (fade 0), or each crossfading
 *  into the next over `fade` s. The film runs at the first clip's frame rate. */
export function stitch(clips, { mp4, fade = 0 }) {
  const probe = FFMPEG.replace(/ffmpeg$/, 'ffprobe');
  const r = execFileSync(probe, ['-v', 'error', '-select_streams', 'v', '-show_entries', 'stream=r_frame_rate', '-of', 'csv=p=0', clips[0]],
    { encoding: 'utf8' }).trim();
  if (clips.length === 1 || !fade) {
    const graph = clips.map((_, i) => `[${i}:v]`).join('') + `concat=n=${clips.length}:v=1:a=0[v]`;
    ff([...q, ...clips.flatMap((c) => ['-i', c]), '-filter_complex', graph, '-map', '[v]', '-r', r, ...H264, mp4]);
    return;
  }
  const at = fadeOffsets(clips.map(lengthOf), fade);
  let graph = '', last = '0:v';
  at.forEach((off, i) => {
    const out = i === at.length - 1 ? 'v' : `x${i}`;
    graph += `[${last}][${i + 1}:v]xfade=transition=fade:duration=${fade}:offset=${off.toFixed(3)}[${out}];`;
    last = out;
  });
  ff([...q, ...clips.flatMap((c) => ['-i', c]), '-filter_complex', graph.replace(/;$/, ''), '-map', '[v]',
    '-r', r, ...H264, mp4]);
}

/** A GIF of a film: fewer frames, smaller, its own palette. */
export function toGif(mp4, { gif, work, width = 960, fps = 12 }) {
  const pal = join(work, 'palette.png');
  const vf = `fps=${fps},scale=${width}:-1:flags=lanczos`;
  execFileSync(FFMPEG, [...q, '-i', mp4, '-vf', `${vf},palettegen=stats_mode=diff`, pal], { stdio: 'inherit' });
  execFileSync(FFMPEG, [...q, '-i', mp4, '-i', pal, '-lavfi', `${vf}[x];[x][1:v]paletteuse=dither=bayer:bayer_scale=5:diff_mode=rectangle`, gif], { stdio: 'inherit' });
  rmSync(pal, { force: true });
}

/** Seconds of a media file, from ffprobe beside ffmpeg. */
export function lengthOf(file) {
  const probe = FFMPEG.replace(/ffmpeg$/, 'ffprobe');
  return Number(execFileSync(probe, ['-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', file], { encoding: 'utf8' }).trim());
}

/** Fail when a film runs over MAX_FILM_S (DEMO_LONG=1 lets a long one through on purpose). Returns its length. */
export function checkLength(mp4, max = MAX_FILM_S) {
  const secs = lengthOf(mp4);
  if (secs > max && !process.env.DEMO_LONG) throw new Error(`${mp4} is ${secs.toFixed(1)} s, over ${max} s: cut it down`);
  return secs;
}

/** A contact sheet of a film: `n` frames spread evenly over it, tiled `cols` wide, each `width` px, into one PNG. Look
 *  at it before calling a film done: it shows at a glance what is on screen, and anything that should not be. */
export function contactSheet(mp4, png, { n = 12, cols = 4, width = 480 } = {}) {
  const secs = lengthOf(mp4), rows = Math.ceil(n / cols);
  execFileSync(FFMPEG, [...q, '-i', mp4, '-vf', `fps=${(n / secs).toFixed(5)},scale=${width}:-2,tile=${cols}x${rows}:padding=6:margin=6:color=white`,
    '-frames:v', '1', '-update', '1', png], { stdio: 'inherit' });
  return png;
}
