/* render.mjs (the demo-video skill) — renders a drawn film (a Remotion composition built from pieces.mjs) frame-exact.

    import { renderFilm, renderStills, frameCost } from '<skill>/motion/render.mjs';
    await renderFilm({ entry: 'film.jsx', out: 'film.mp4', scale: 1.5 });      // 1280x720 design -> 1920x1080
    await renderStills({ entry, frames: [0, 300], dir: 'stills' });
    const ms = await frameCost({ entry, frames: [0, 29] });                     // ms a frame on this box, now

Each frame is a pure function of its number, rendered by Chromium to a lossless PNG and encoded once to H.264
yuv420p (TV range), then remuxed with faststart; a loaded box only makes the render slower. `publicDir` is served as
Remotion's static files (fonts, frame sequences). The modules are MOTION_PINS from deps.mjs. */
import { execFileSync } from 'node:child_process';
import { mkdirSync, rmSync } from 'node:fs';
import { createRequire } from 'node:module';
import { dirname, join } from 'node:path';
import { MOTION_PINS, chrome, modules } from '../deps.mjs';

let remo;
function load() {
  if (remo) return remo;
  const nm = modules(MOTION_PINS), req = createRequire(join(dirname(nm), 'x.js'));
  remo = { nm, ...req('@remotion/bundler'), ...req('@remotion/renderer') };
  return remo;
}

const bundles = new Map();
async function prepare({ entry, id = 'Film', publicDir, props = {} }) {
  const r = load();
  const key = entry + '|' + (publicDir || '');
  if (!bundles.has(key)) {
    bundles.set(key, await r.bundle({
      entryPoint: entry, rootDir: dirname(entry), publicDir, enableCaching: false,
      webpackOverride: (c) => ({ ...c, resolve: { ...c.resolve, modules: [r.nm, 'node_modules'] } }),
    }));
  }
  /* a heavy frame on a box at load 30 took over Remotion's 30 s default and killed a whole render, so a frame gets 3 min */
  const opts = { serveUrl: bundles.get(key), inputProps: props, browserExecutable: chrome() || null, chromeMode: 'chrome-for-testing',
    logLevel: 'error', timeoutInMilliseconds: 180000 };
  return { r, opts, composition: await r.selectComposition({ ...opts, id }) };
}

/** Renders frames [from, to] (all when not given) of composition `id` to `out`: PNG frames, one H.264 encode at `crf`,
 *  faststart. Returns the ms a frame took. */
export async function renderFilm({ entry, id, out, publicDir, props, scale = 1.5, crf = 14, frames, concurrency = 3, log = true }) {
  const { r, opts, composition } = await prepare({ entry, id, publicDir, props });
  const raw = out.replace(/\.mp4$/, '') + '.raw.mp4';
  mkdirSync(dirname(out), { recursive: true });
  const t0 = Date.now();
  let last = -1;
  await r.renderMedia({ ...opts, composition, codec: 'h264', crf, pixelFormat: 'yuv420p', imageFormat: 'png', x264Preset: 'slow',
    scale, muted: true, concurrency, frameRange: frames || null, outputLocation: raw, overwrite: true,
    onProgress: ({ progress }) => { const p = Math.floor(progress * 10); if (log && p !== last) { last = p; console.log(`render ${p * 10}%`); } } });
  const n = frames ? frames[1] - frames[0] + 1 : composition.durationInFrames;
  const ms = (Date.now() - t0) / n;
  execFileSync('ffmpeg', ['-hide_banner', '-loglevel', 'error', '-y', '-i', raw, '-map', '0:v:0', '-c', 'copy', '-movflags', '+faststart', out]);
  rmSync(raw, { force: true });
  return ms;
}

/** PNG stills of the given frames into `dir` as f<frame>.png, for checks and contact sheets. */
export async function renderStills({ entry, id, frames, dir, publicDir, props, scale = 1.5 }) {
  const { r, opts, composition } = await prepare({ entry, id, publicDir, props });
  mkdirSync(dir, { recursive: true });
  const files = [];
  for (const f of frames) {
    const output = join(dir, `f${String(f).padStart(4, '0')}.png`);
    await r.renderStill({ ...opts, composition, frame: f, output, overwrite: true, scale });
    files.push(output);
  }
  return files;
}

/** The ms one frame of [from, to] costs to render and encode on this box now: what picks 30 or 60 fps for a film. */
export async function frameCost({ entry, id, frames, publicDir, props, scale = 1.5, concurrency = 3 }) {
  const out = join(process.env.TMPDIR || '/tmp', `motion-cost-${process.pid}.mp4`);
  const ms = await renderFilm({ entry, id, out, frames, publicDir, props, scale, concurrency, log: false });
  rmSync(out, { force: true });
  return ms;
}
