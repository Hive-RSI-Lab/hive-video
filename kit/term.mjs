/* term.mjs (the demo-video skill) — a real terminal, recorded and then filmed.

recordTerminal() runs tmux and bash for real, inside a bubblewrap sandbox that shows a made-up workspace: the home
directory you give it mounted at /home/<user>, a made-up host name, a passwd file that knows only that user, and a
clean environment. record.py writes what the terminal prints into an asciicast; your script types into the panes
from outside with `tmux send-keys`, at a typist's pace, and waits for each command to finish. Every printed byte is
checked against the denied words before the cast is kept.

terminalPage() writes a page that replays the cast with xterm.js at the film's size, so the director (film.mjs) can
film it like any other page: sharp text at 1080p, the same cursor-free camera, and cuts between marks. */
import { execFileSync, spawn } from 'node:child_process';
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { firstDenied, sleep } from './film.mjs';
import { mod } from './deps.mjs';

const HERE = dirname(fileURLToPath(import.meta.url));

/** The tmux look: a quiet status line with the session's name on the left, pane titles on the borders. */
export const TMUX_CONF = `
set -g default-terminal "xterm-256color"
set -g status-style "bg=#232136,fg=#908caa"
set -g status-left "#[bg=#c4a7e7,fg=#232136,bold] #S #[default] "
set -g status-left-length 40
set -g status-right "#[fg=#6e6a86]#h "
set -g window-status-format " #W "
set -g window-status-current-format "#[fg=#e0def4,bold] #W "
set -g pane-border-status top
set -g pane-border-format " #[bold]#{pane_title} "
set -g pane-border-style "fg=#44415a"
set -g pane-active-border-style "fg=#c4a7e7"
set -g base-index 0
set -g escape-time 0
set -g history-limit 5000
set -g automatic-rename off
set -g allow-rename off
`;

/** A prompt like `sam@workbench ~/dev/site $`, in colour. */
const BASHRC = (user, host) => `
PS1='\\[\\e[38;5;150m\\]${user}@${host}\\[\\e[0m\\] \\[\\e[38;5;110m\\]\\w\\[\\e[0m\\] \\$ '
PROMPT_COMMAND=
HISTFILE=/dev/null
alias ls='ls --color=auto'
alias grep='grep --color=auto'
`;

/**
 * Record a terminal session into `out` (an asciicast v2 file).
 *   home     a directory made for the film: it is the user's home inside, at /home/<user>
 *   bins     directories of tools to put on PATH inside, mounted at /tmp/bin0, bin1, ... (their real path never shows)
 *   env      extra variables inside, e.g. { EDITOR: 'nano' }
 *   script   async (t) => { ... } with t's verbs: type, enter, run, keys, tmux, split, title, hold, mark, wait
 *   deny     words that must not be printed; the recording fails if one is
 */
export async function recordTerminal({ out, cols = 150, rows = 42, home, user = 'sam', host = 'workbench', session = 'work',
  bins = [], env = {}, tmuxConf = TMUX_CONF, script, deny = [] }) {
  const work = mkdtempSync(join(tmpdir(), 'demo-term-'));
  const sock = join(work, 'tmux.sock'), marks = join(work, 'marks'), stop = join(work, 'stop');
  // every pane, the first and each split, starts the same shell with the made-up prompt
  writeFileSync(join(work, 'tmux.conf'), `${tmuxConf}\nset -g default-command "bash --rcfile ${join(work, 'bashrc')} -i"\n`);
  writeFileSync(join(work, 'bashrc'), BASHRC(user, host));
  writeFileSync(join(work, 'passwd'), `root:x:0:0::/root:/bin/bash\n${user}:x:${process.getuid()}:${process.getgid()}::/home/${user}:/bin/bash\n`);
  writeFileSync(join(work, 'group'), `root:x:0:\n${user}:x:${process.getgid()}:\n`);
  writeFileSync(marks, '');
  const PATH = [...bins.map((_, i) => `/tmp/bin${i}`), '/usr/local/bin', '/usr/bin', '/bin'].join(':');
  const inner = { HOME: `/home/${user}`, USER: user, LOGNAME: user, SHELL: '/bin/bash', TERM: 'xterm-256color',
    LANG: 'C.UTF-8', PATH, ...env };
  const bwrap = ['--ro-bind', '/', '/', '--dev', '/dev', '--proc', '/proc', '--tmpfs', '/tmp', '--tmpfs', '/home', '--tmpfs', '/root',
    '--bind', home, `/home/${user}`, '--bind', work, work,
    '--ro-bind', join(work, 'passwd'), '/etc/passwd', '--ro-bind', join(work, 'group'), '/etc/group',
    ...bins.flatMap((b, i) => ['--ro-bind', b, `/tmp/bin${i}`]),
    '--unshare-uts', '--unshare-pid', '--hostname', host, '--die-with-parent', '--chdir', `/home/${user}`,
    '--', 'env', '-i', ...Object.entries(inner).map(([k, v]) => `${k}=${v}`),
    'tmux', '-S', sock, '-f', join(work, 'tmux.conf'), 'new-session', '-s', session, '-x', String(cols), '-y', String(rows)];
  // the outer tmux calls reach the server through the socket; the recorder is the one client the film sees
  const rec = spawn('python3', [join(HERE, 'record.py'), '--out', out, '--cols', cols, '--rows', rows, '--marks', marks, '--stop', stop,
    '--', 'bwrap', ...bwrap], { stdio: ['ignore', 'ignore', 'inherit'] });
  const done = new Promise((ok, no) => rec.on('exit', (c) => (c === 0 ? ok() : no(new Error(`record.py exited ${c}`)))));
  // run with the sandbox's own environment: tmux gives a pane it opens the environment of the client that asked, and
  // ours would carry the real home, user and paths into the film
  const tmux = (...a) => execFileSync('/usr/bin/tmux', ['-S', sock, ...a], { encoding: 'utf8', env: inner, stdio: ['ignore', 'pipe', 'pipe'] }).trimEnd();
  for (let i = 0; !existsSync(sock) || !tmuxOk(tmux); i++) { if (i > 100) throw new Error('tmux did not start'); await sleep(50); }
  await sleep(300);
  const target = (pane) => (pane == null ? session : `${session}:.${pane}`);
  const capture = (pane) => tmux('capture-pane', '-p', '-t', target(pane));
  const t = {
    tmux,
    capture,
    hold: sleep,
    /** Type text into a pane at about `cps` keys a second, unevenly, as a person types. */
    async type(text, { pane, cps = 28 } = {}) {
      for (const ch of text) {
        // a lone ";" is tmux's command separator, so it goes escaped
        tmux('send-keys', '-t', target(pane), '-l', ch === ';' ? '\\;' : ch);
        await sleep((1000 / cps) * (0.6 + Math.random() * 0.8) * (ch === ' ' ? 1.3 : 1));
      }
    },
    async keys(...k) { tmux('send-keys', '-t', target(null), ...k); await sleep(60); },
    async enter({ pane } = {}) { tmux('send-keys', '-t', target(pane), 'Enter'); },
    /** Wait until `re` is on the pane's screen (or `ms` passes, then throw). */
    async wait(re, { pane, ms = 20000 } = {}) {
      const t0 = Date.now();
      while (!re.test(capture(pane))) { if (Date.now() - t0 > ms) throw new Error(`timed out waiting for ${re} in pane ${pane}`); await sleep(60); }
    },
    /** Type a command, press Enter and wait until the prompt is back (or `until` is on screen). */
    async run(cmd, { pane, cps, until, ms } = {}) {
      await t.type(cmd, { pane, cps });
      await sleep(180);
      await t.enter({ pane });
      if (until) return t.wait(until, { pane, ms });
      await sleep(150);
      const t0 = Date.now();
      for (;;) {
        const cmdNow = tmux('display', '-p', '-t', target(pane), '#{pane_current_command}');
        if (cmdNow === 'bash' && / \$ $/.test(capture(pane).trimEnd() + ' ') && capture(pane) !== '' && Date.now() - t0 > 100) break;
        if (Date.now() - t0 > (ms || 20000)) throw new Error(`timed out running ${cmd}`);
        await sleep(60);
      }
    },
    /** Split the current pane: 'h' side by side, 'v' one above the other; `size` is a percentage. Returns its index. */
    async split(dir = 'h', { size, title } = {}) {
      // the new pane starts where the current one is, as a person's split does
      // titled in the same tmux call, so the border never shows the default title first
      tmux('split-window', dir === 'h' ? '-h' : '-v', '-c', '#{pane_current_path}', ...(size ? ['-l', `${size}%`] : []), '-t', session,
        ...(title ? [';', 'select-pane', '-T', title] : []));
      const idx = Number(tmux('display', '-p', '-t', session, '#{pane_index}'));
      await sleep(200);
      return idx;
    },
    title(name, pane) { tmux('select-pane', '-t', target(pane), '-T', name); },
    select(pane) { tmux('select-pane', '-t', target(pane)); },
    /** A named point in the cast, with the panes' layout then (in cells), so the film can cut and zoom by name. */
    async mark(name) {
      const panes = tmux('list-panes', '-t', session, '-F', '#{pane_index} #{pane_left} #{pane_top} #{pane_width} #{pane_height}')
        .split('\n').map((l) => { const [i, x, y, w, h] = l.split(' ').map(Number); return { i, x, y, w, h }; });
      writeFileSync(marks, `${name}\t${JSON.stringify({ panes })}\n`, { flag: 'a' });
      // the recorder reads the marks between reads of the terminal: give it one turn before anything else is printed
      await sleep(80);
    },
  };
  try {
    t.title('shell', 0);
    await script(t);
    await t.mark('end');
    await sleep(300);
  } finally {
    writeFileSync(stop, '');
    await done.catch(() => {});
    try { tmux('kill-server'); } catch { /* gone */ }
    rmSync(work, { recursive: true, force: true });
  }
  const printed = readFileSync(out, 'utf8').split('\n').slice(1).filter(Boolean).map((l) => JSON.parse(l)).filter((e) => e[1] === 'o').map((e) => e[2]).join('');
  const hit = firstDenied(printed, deny);
  if (hit) { rmSync(out, { force: true }); throw new Error(`the terminal printed a denied word ("${hit}")`); }
  return out;
}

const tmuxOk = (tmux) => { try { tmux('has-session'); return true; } catch { return false; } };

/** Read a cast: { width, height, events: [[t, kind, data]], marks: {name: {t, panes}} }. */
export function readCast(file) {
  const [head, ...lines] = readFileSync(file, 'utf8').split('\n').filter(Boolean);
  const { width, height } = JSON.parse(head);
  const events = lines.map((l) => JSON.parse(l));
  const marks = {};
  for (const [t, k, d] of events) if (k === 'm') { const m = JSON.parse(d); marks[m.name] = { t, panes: m.panes }; }
  return { width, height, events: events.filter((e) => e[1] === 'o'), marks };
}

/** A terminal colour scheme (xterm.js ITheme) and the page around it. */
export const THEME = {
  background: '#191724', foreground: '#e0def4', cursor: '#e0def4', selectionBackground: '#403d52',
  black: '#26233a', red: '#eb6f92', green: '#9ccfd8', yellow: '#f6c177', blue: '#31748f', magenta: '#c4a7e7', cyan: '#9ccfd8', white: '#e0def4',
  brightBlack: '#6e6a86', brightRed: '#eb6f92', brightGreen: '#9ccfd8', brightYellow: '#f6c177', brightBlue: '#31748f', brightMagenta: '#c4a7e7', brightCyan: '#9ccfd8', brightWhite: '#e0def4',
};

/**
 * Write a page that replays `cast` with xterm.js, filling a `width` x `height` viewport, and return its path.
 * In the page, window.player has: seek(mark) to draw everything up to a mark at once; play(from, to, {speed, idle})
 * to replay between two marks at the recorded pace (`speed` times faster, and no pause longer than `idle` seconds),
 * resolving when done; and rect(mark, pane) for a pane's box in page pixels, for the camera.
 */
export function terminalPage(castFile, { dir, width = 1280, height = 720, pad = 28, font, fontFamily = 'DejaVu Sans Mono', theme = THEME, title = '' }) {
  mkdirSync(dir, { recursive: true });
  const cast = readCast(castFile);
  const face = font ? `@font-face{font-family:"DemoMono";src:url("${pathToFileURL(font).href}")}` : '';
  const family = font ? '"DemoMono"' : JSON.stringify(fontFamily);
  const html = `<!doctype html><meta charset="utf-8"><title>${title}</title>
<link rel="stylesheet" href="${pathToFileURL(mod('@xterm/xterm', 'css', 'xterm.css')).href}">
<style>${face}
html,body{margin:0;width:${width}px;height:${height}px;overflow:hidden;background:${theme.background}}
#stage{position:absolute;inset:0;transform-origin:0 0}
#term{position:absolute;left:${pad}px;top:${pad}px}
.xterm-viewport{overflow:hidden!important}
</style>
<div id="stage"><div id="term"></div></div>
<script src="${pathToFileURL(mod('@xterm/xterm', 'lib', 'xterm.js')).href}"></script>
<script>
const CAST = ${JSON.stringify(cast)};
(async () => {
  await document.fonts.load('16px ${family.replace(/"/g, '\\"')}');
  const W = ${width - 2 * pad}, H = ${height - 2 * pad};
  const mk = (size) => { const t = new Terminal({ cols: CAST.width, rows: CAST.height, fontSize: size, fontFamily: ${JSON.stringify(family)},
    theme: ${JSON.stringify(theme)}, allowProposedApi: true, cursorBlink: false, scrollback: 0, lineHeight: 1.0 }); return t; };
  // the largest font whose grid fits the page
  let size = 30, term;
  for (;;) {
    term = mk(size); term.open(document.getElementById('term'));
    const s = document.querySelector('#term .xterm-screen').getBoundingClientRect();
    if ((s.width <= W && s.height <= H) || size <= 8) break;
    term.dispose(); size -= 0.5;
  }
  const screen = document.querySelector('#term .xterm-screen').getBoundingClientRect();
  const cw = screen.width / CAST.width, ch = screen.height / CAST.height;
  // centre the grid
  const el = document.getElementById('term');
  el.style.left = (${width} - screen.width) / 2 + 'px'; el.style.top = (${height} - screen.height) / 2 + 'px';
  const ox = (${width} - screen.width) / 2, oy = (${height} - screen.height) / 2;
  let at = 0;   // index of the next event to write
  const tOf = (m) => (m == null ? 0 : m === 'end' && !CAST.marks.end ? Infinity : CAST.marks[m].t);
  const write = (d) => new Promise((r) => term.write(d, r));
  window.player = {
    async seek(mark) { const to = tOf(mark); let buf = ''; while (at < CAST.events.length && CAST.events[at][0] <= to) buf += CAST.events[at++][2]; await write(buf); },
    play(from, to, { speed = 1, idle = 0.5 } = {}) {
      return (async () => {
        if (from != null) await window.player.seek(from);
        const end = tOf(to);
        let clock = performance.now(), last = at ? CAST.events[at - 1][0] : 0;
        while (at < CAST.events.length && CAST.events[at][0] <= end) {
          const [t, , d] = CAST.events[at++];
          clock += Math.min(t - last, idle) * 1000 / speed; last = t;
          const wait = clock - performance.now();
          if (wait > 4) await new Promise((r) => setTimeout(r, wait));
          term.write(d);
        }
        await write('');
      })();
    },
    /** A pane's box at a mark, in page pixels; no pane: the whole grid. */
    rect(mark, pane) {
      if (pane == null) return { x: ox, y: oy, w: screen.width, h: screen.height };
      const p = CAST.marks[mark].panes.find((q) => q.i === pane);
      return { x: ox + p.x * cw, y: oy + (p.y - 1) * ch, w: p.w * cw, h: (p.h + 1) * ch };
    },
    size, ready: true,
  };
})();
</script>`;
  const file = join(dir, 'terminal.html');
  writeFileSync(file, html);
  return file;
}
