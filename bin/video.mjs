#!/usr/bin/env node
/* video — the video module's command line. Every command is deterministic; none of them calls `heavy` itself, so run
   the slow ones (check, render, blender) as `heavy timeout N video ...`.

   video check [--blender]                  the kit's own checks (node kit, web encodes; Blender helpers with --blender).
                                            A pass is stamped against the kit's contents, so `render` skips it after.
   video new DIR                            a starter film script (film.mjs) for a web page, to edit
   video render FILM.mjs [ARGS...]          runs a film script with VIDEO_KIT set (import from it); checks the kit first
                                            unless a pass for this exact kit is stamped
   video stutters MP4 [--allow A-B,...]     frozen frames inside a move, and uneven motion (jumps, too-fast moves,
                                            pops), in seconds. Exit 1 on any stutter or jerk. A-B are seconds to skip
   video sheet MP4 PNG [N]                  a contact sheet of N frames (default 12): look at it before posting
   video mp4 IN OUT [CRF]                   the web MP4 (H.264 High, CRF 24, faststart)
   video gif IN OUT [--max MB] [--width W] [--fps F] [--colours C]
                                            a GIF; with --max (default 3) it steps width, fps and colours down from
                                            960 px / 12 fps / 64 until the file fits, and says what it chose
   video blender SHOT.py OUT/ [--quality preview|final] [--raw]
                                            a Blender shot rendered by the local Blender on the CPU (shot_main --render);
                                            --raw runs a plain scene script with -o OUT/#### -a
   video length FILE                        seconds */
import { execFileSync, spawnSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { cpSync, existsSync, mkdirSync, readdirSync, readFileSync, statSync, writeFileSync } from 'node:fs';
import { homedir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const KIT = join(ROOT, 'kit');
const CACHE = process.env.VIDEO_CACHE || join(homedir(), '.cache', 'hive-video');
const [cmd, ...args] = process.argv.slice(2);
const die = (m) => { console.error(`video: ${m}`); process.exit(2); };
const run = (bin, a, opt = {}) => spawnSync(bin, a, { stdio: 'inherit', ...opt }).status ?? 1;
const flag = (name, def) => { const i = args.indexOf(name); if (i < 0) return def; const v = args[i + 1]; args.splice(i, 2); return v; };

function kitHash() {
  const h = createHash('sha256');
  const walk = (d) => { for (const f of readdirSync(d).sort()) { const p = join(d, f); const s = statSync(p);
    if (s.isDirectory()) { if (f !== 'node_modules' && f !== '__pycache__') walk(p); } else if (/\.(mjs|py|sh)$/.test(f)) h.update(p + '\0').update(readFileSync(p)); } };
  walk(KIT);
  return h.digest('hex').slice(0, 16);
}
const stamp = () => join(CACHE, `checked-${kitHash()}`);

async function measure(mp4, allowS) {
  const { frameDiffs, stutters, jerks, jerkSpans } = await import(join(KIT, 'motion/measure.mjs'));
  const [n, dd] = execFileSync('ffprobe', ['-v', 'error', '-select_streams', 'v:0', '-show_entries', 'stream=r_frame_rate', '-of', 'csv=p=0', mp4], { encoding: 'utf8' }).trim().split(/[,\s]/)[0].split('/').map(Number);
  const fps = n / (dd || 1);
  const d = frameDiffs(mp4);
  const allow = allowS.map(([a, b]) => [Math.floor(a * fps), Math.ceil(b * fps)]);
  const st = stutters(d).filter((i) => !allow.some(([a, b]) => i >= a && i <= b));
  const js = jerks(d, { allow });
  return { fps, frames: d.length, stutters: st.map((i) => +(i / fps).toFixed(2)), jerks: jerkSpans(js, fps) };
}

const size = (f) => statSync(f).size / 1e6;
const gifOnce = (i, o, w, f, c) => execFileSync(join(KIT, 'web-encode.sh'), ['gif', i, o, String(w), String(f), String(c)], { stdio: 'inherit' });

switch (cmd) {
  case 'check': {
    const blender = args.includes('--blender');
    let bad = run(process.execPath, ['--no-warnings', join(KIT, 'selfcheck.mjs')], { env: { ...process.env, DEMO_VIDEO_CHECKED: '1' } });
    bad |= run('bash', [join(KIT, 'web-encode.sh'), 'selfcheck']);
    if (blender) bad |= run('python3', [join(KIT, 'blender/selfcheck.py')]);
    if (bad) { console.log('video check: FAILED'); process.exit(1); }
    mkdirSync(CACHE, { recursive: true }); writeFileSync(stamp(), new Date().toISOString() + '\n');
    console.log('video check: all passed');
    break;
  }
  case 'new': {
    const dir = args[0] || die('new DIR');
    mkdirSync(dir, { recursive: true });
    const out = join(dir, 'film.mjs');
    if (existsSync(out)) die(`${out} is already there`);
    cpSync(join(ROOT, 'templates/film.mjs'), out);
    console.log(`wrote ${out}: edit the URL, the beats and the deny list, then: heavy timeout 1800 video render ${out}`);
    break;
  }
  case 'render': {
    const film = args.shift() || die('render FILM.mjs');
    const env = { ...process.env, VIDEO_KIT: KIT, VIDEO_MODULE: ROOT };
    if (existsSync(stamp())) env.DEMO_VIDEO_CHECKED = '1';
    else console.error('video: no check stamped for this kit, so the film runs the selfcheck first (a few minutes)');
    process.exit(run(process.execPath, ['--no-warnings', resolve(film), ...args], { env }));
  }
  case 'stutters': {
    const mp4 = args[0] || die('stutters MP4');
    const allow = (flag('--allow', '') || '').split(',').filter(Boolean).map((s) => s.split('-').map(Number));
    const m = await measure(mp4, allow);
    console.log(`${mp4}: ${m.frames} frames at ${m.fps} fps, ${(m.frames / m.fps).toFixed(2)} s`);
    console.log(`stutters: ${m.stutters.length}${m.stutters.length ? '  at ' + m.stutters.join(', ') + ' s' : ''}`);
    console.log(`jerks: ${m.jerks.length}${m.jerks.length ? '\n  ' + m.jerks.join('\n  ') : ''}`);
    process.exit(m.stutters.length || m.jerks.length ? 1 : 0);
  }
  case 'sheet': {
    const [mp4, png, n] = args;
    if (!png) die('sheet MP4 PNG [N]');
    const { contactSheet } = await import(join(KIT, 'film.mjs'));
    contactSheet(mp4, png, { n: Number(n || 12) });
    console.log(png);
    break;
  }
  case 'mp4': {
    const [i, o, crf] = args;
    if (!o) die('mp4 IN OUT [CRF]');
    process.exit(run(join(KIT, 'web-encode.sh'), ['mp4', i, o, ...(crf ? [crf] : [])]));
  }
  case 'gif': {
    const max = Number(flag('--max', '3')), W = flag('--width'), F = flag('--fps'), C = flag('--colours');
    const [i, o] = args;
    if (!o) die('gif IN OUT [--max MB] [--width W] [--fps F] [--colours C]');
    const tries = [];
    for (const w of W ? [+W] : [960, 840, 720]) for (const f of F ? [+F] : [12, 10]) for (const c of C ? [+C] : [64, 48, 32]) tries.push([w, f, c]);
    tries.sort((a, b) => b[0] * b[1] * b[2] - a[0] * a[1] * a[2]);
    let last;
    for (const [w, f, c] of tries) {
      gifOnce(i, o, w, f, c); last = [w, f, c];
      const mb = size(o);
      console.log(`gif ${w} px, ${f} fps, ${c} colours: ${mb.toFixed(2)} MB`);
      if (mb <= max) { console.log(`${o}: kept`); process.exit(0); }
    }
    console.log(`${o}: still over ${max} MB at ${last.join('/')}; cut it shorter (web-encode.sh gif takes SS T)`);
    process.exit(1);
  }
  case 'blender': {
    const quality = flag('--quality', 'preview'), raw = args.includes('--raw');
    const [shot, out] = args.filter((a, i) => a !== '--raw' && !a.startsWith('--') && !['--quality', '--frames'].includes(args[i - 1]));
    if (!out) die('blender SHOT.py OUT/ [--quality preview|final] [--raw]');
    mkdirSync(out, { recursive: true });
    const env = { ...process.env, PYTHONPATH: [join(KIT, 'blender'), process.env.PYTHONPATH].filter(Boolean).join(':'), VIDEO_BLENDER: join(KIT, 'blender') };
    const frames = flag('--frames');
    // official builds ignore PYTHONPATH without --python-use-system-env; a shot that fails must stop, not render the default cube
    const base = ['-b', '--python-use-system-env', '--factory-startup', '--python-exit-code', '1', '--python', resolve(shot)];
    const a = raw ? [...base, '-o', join(resolve(out), '####'), '-a']
      : [...base, '--', '--quality', quality, '--render', resolve(out), ...(frames ? ['--frames', frames] : [])];
    process.exit(run(process.env.BLENDER || 'blender', a, { env }));
  }
  case 'length': console.log(execFileSync('ffprobe', ['-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', args[0]], { encoding: 'utf8' }).trim()); break;
  default:
    console.log(readFileSync(fileURLToPath(import.meta.url), 'utf8').split('*/')[0].replace(/^#!.*\n\/\* ?/, ''));
    process.exit(cmd && cmd !== 'help' && cmd !== '-h' && cmd !== '--help' ? 2 : 0);
}
