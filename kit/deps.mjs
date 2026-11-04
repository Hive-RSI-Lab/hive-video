/* deps.mjs (the demo-video skill) — the node modules and the browser every film needs, found or installed once.

Modules come from DEMO_NODE_MODULES when it is set, else from VIDEO_CACHE or ~/.cache/hive-video, where the first run installs the
versions in PINS with npm: Playwright's driver and xterm.js. A drawn film (motion/) also needs MOTION_PINS, Remotion and
React, installed beside them the first time `modules(MOTION_PINS)` is asked for. The browser is the newest Chromium in
~/.cache/ms-playwright (CHROME to name another); it films the page and composites the frames. */
import { execFileSync } from 'node:child_process';
import { existsSync, mkdirSync, readFileSync, readdirSync, writeFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { homedir } from 'node:os';
import { dirname, join } from 'node:path';

export const PINS = {
  'playwright-core': '1.62.1', '@xterm/xterm': '6.0.0',
};
export const MOTION_PINS = {
  remotion: '4.0.530', '@remotion/bundler': '4.0.530', '@remotion/renderer': '4.0.530', react: '19.3.0', 'react-dom': '19.3.0',
};
const CACHE = process.env.VIDEO_CACHE || join(homedir(), '.cache', 'hive-video');

/** The node_modules directory the film's modules load from, installing PINS (and `extra`) into the cache on first use;
 *  what the cache already has stays in its package.json. */
export function modules(extra = {}) {
  if (process.env.DEMO_NODE_MODULES) return process.env.DEMO_NODE_MODULES;
  const nm = join(CACHE, 'node_modules'), want = { ...PINS, ...extra };
  if (Object.keys(want).every((p) => existsSync(join(nm, p, 'package.json')))) return nm;
  mkdirSync(CACHE, { recursive: true });
  const pkg = join(CACHE, 'package.json');
  const had = existsSync(pkg) ? JSON.parse(readFileSync(pkg, 'utf8')).dependencies || {} : {};
  writeFileSync(pkg, JSON.stringify({ private: true, dependencies: { ...had, ...want } }, null, 2));
  console.log('demo: installing the film\'s node modules into ' + CACHE + ' (once)');
  execFileSync('npm', ['install', '--no-audit', '--no-fund', '--prefer-offline'], { cwd: CACHE, stdio: 'inherit' });
  return nm;
}

/** A path inside one of the modules, e.g. mod('@xterm/xterm', 'lib/xterm.js'). */
export const mod = (name, ...rest) => join(modules(), name, ...rest);

/** A module from the film's node_modules, e.g. need('playwright-core'). */
export const need = (name) => createRequire(join(dirname(modules()), 'x.js'))(name);

/** The Chromium to use: CHROME, else the newest in the Playwright cache, else undefined (Playwright's own). */
export function chrome() {
  if (process.env.CHROME) return process.env.CHROME;
  const cache = join(homedir(), '.cache', 'ms-playwright');
  const dirs = !existsSync(cache) ? [] : readdirSync(cache).filter((d) => /^chromium-\d+$/.test(d)).sort((a, b) => b.split('-')[1] - a.split('-')[1]);
  for (const d of dirs) { const p = join(cache, d, 'chrome-linux64', 'chrome'); if (existsSync(p)) return p; }
  for (const p of ['/usr/bin/google-chrome', '/usr/bin/chromium', '/usr/bin/chromium-browser']) if (existsSync(p)) return p;
  return undefined;
}

/** Chromium, launched headless, from the Playwright cache when one is there. */
export async function launch(args = []) {
  const { chromium } = need('playwright-core');
  const executablePath = chrome();
  return chromium.launch({ headless: true, args, ...(executablePath ? { executablePath } : {}) });
}
