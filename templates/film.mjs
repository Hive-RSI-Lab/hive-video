// A film of a web page: heavy timeout 1800 video render film.mjs [OUT_DIR]
// Edit URL, the beats and DENY. Writes OUT_DIR/film.mp4 (aim for about 20 s). See the module's SKILL.md.
import { execSync } from 'node:child_process';
import { mkdirSync, rmSync } from 'node:fs';
import { join } from 'node:path';
import os from 'node:os';

const KIT = process.env.VIDEO_KIT || join(os.homedir(), 'modules/video/kit');
const { director, encodeClip, stitch, checkLength } = await import(join(KIT, 'film.mjs'));
const { launch } = await import(join(KIT, 'deps.mjs'));

const URL = 'http://127.0.0.1:8000/';   // a throwaway server with made-up data, never a real account
const out = process.argv[2] || join(process.env.TMPDIR || os.tmpdir(), 'vid', 'film');
const work = join(out, 'work');
rmSync(work, { recursive: true, force: true });
mkdirSync(work, { recursive: true });

// words that must never be on screen: this machine, its user, the git identity, real project names
const git = (k) => { try { return execSync(`git config ${k}`, { encoding: 'utf8' }).trim(); } catch { return ''; } };
const DENY = [os.hostname(), os.userInfo().username, git('user.name'), git('user.email')].filter((w) => w && w.length > 2);

// Film-only polish goes in an init script, not the app: here new list items ease in instead of popping.
const POLISH = `(() => {
  const css = 'li{animation:film-in .4s cubic-bezier(.16,1,.3,1) both}@keyframes film-in{from{opacity:0;transform:translateY(10px)}}';
  addEventListener('DOMContentLoaded', () => { const s = document.createElement('style'); s.textContent = css; document.head.appendChild(s); });
})();`;

const browser = await launch(['--hide-scrollbars']);
let beats;
try {
  const ctx = await browser.newContext({ viewport: { width: 1920, height: 1080 }, colorScheme: 'dark' });
  const page = await ctx.newPage();
  const d = await director(page, { frames: join(work, 'frames'), deny: DENY, zoom: 1.5 });   // before the first goto
  await page.addInitScript(POLISH);
  await page.goto(URL);
  await page.clock.runFor(500);

  // 1. the ask: one idea a beat, the thing working in the first 2 s
  await d.beat('ask', 'Say what you want');
  const box = page.locator('input, textarea').first();
  await d.camera(box, { ms: 600, fill: 0.8, max: 1.8 });
  await d.click(box);
  await d.type('Something short and real-sounding', 32);
  await d.press('Enter', 200);

  // 2. the result: pull back, wait for it, zoom onto it, hold it
  await d.beat('result', 'It comes back');
  await d.camera('all', { ms: 500 });
  await d.hold(1500);
  await d.camera(page.locator('main').first(), { ms: 600, fill: 0.9, max: 1.8 });
  await d.show(1500);
  await d.stop();
  beats = d.beats();
} finally {
  await browser.close();
}

const clips = [];
for (const beat of beats) {
  const mp4 = join(work, `${beat.name}.mp4`);
  console.log(`${beat.name}: ${(await encodeClip(beat, { mp4, work })).toFixed(2)} s`);
  clips.push(mp4);
}
const film = join(out, 'film.mp4');
stitch(clips, { mp4: film });
console.log(`wrote ${film}: ${checkLength(film).toFixed(1)} s. Next: video stutters ${film}; video sheet ${film} sheet.png`);
