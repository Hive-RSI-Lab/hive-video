#!/usr/bin/env python3
"""record.py — record a real terminal into an asciicast v2 file (the demo-video skill).

    record.py --out FILE.cast --cols 150 --rows 42 [--marks FILE] [--stop FILE] -- COMMAND [ARG...]

It runs COMMAND in a pseudo-terminal of that size and writes every byte it prints, with the time it came, until the
command exits or the file named by --stop appears (the driver creates it, so what the command prints on its way out,
tmux's "[exited]", is not in the film). Nothing is typed from here: a driver types into the session from outside
(term.mjs does it with `tmux send-keys`). Each line the driver appends to --marks, `<name>\\t<json>`, becomes a
marker event ("m") at the time it was read, so a player can play the cast from one mark to the next.
"""
import argparse, codecs, fcntl, json, os, pty, select, struct, sys, termios, time


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', required=True)
    ap.add_argument('--cols', type=int, default=150)
    ap.add_argument('--rows', type=int, default=42)
    ap.add_argument('--marks')
    ap.add_argument('--stop')
    ap.add_argument('cmd', nargs=argparse.REMAINDER)
    a = ap.parse_args()
    cmd = a.cmd[1:] if a.cmd[:1] == ['--'] else a.cmd
    if not cmd:
        ap.error('no command')
    pid, fd = pty.fork()
    if pid == 0:
        # the size is set on our own side of the pty before the command starts, so it never draws at 80x24 first
        fcntl.ioctl(0, termios.TIOCSWINSZ, struct.pack('HHHH', a.rows, a.cols, 0, 0))
        os.execvp(cmd[0], cmd)
    t0 = time.monotonic()
    events, dec, marks_at = [], codecs.getincrementaldecoder('utf-8')('replace'), 0
    while True:
        if a.stop and os.path.exists(a.stop):
            break
        if a.marks and os.path.exists(a.marks):
            with open(a.marks) as f:
                f.seek(marks_at)
                for line in f.readlines():
                    if line.endswith('\n'):
                        marks_at += len(line.encode())
                        name, _, data = line.rstrip('\n').partition('\t')
                        events.append([round(time.monotonic() - t0, 4), 'm', json.dumps({'name': name, **json.loads(data or '{}')})])
        r, _, _ = select.select([fd], [], [], 0.02)
        if not r:
            continue
        try:
            data = os.read(fd, 65536)
        except OSError:
            break
        if not data:
            break
        text = dec.decode(data)
        if text:
            events.append([round(time.monotonic() - t0, 4), 'o', text])
    try:
        os.kill(pid, 15)
    except ProcessLookupError:
        pass
    with open(a.out, 'w') as f:
        f.write(json.dumps({'version': 2, 'width': a.cols, 'height': a.rows, 'env': {'TERM': 'xterm-256color'}}) + '\n')
        for e in events:
            f.write(json.dumps(e, ensure_ascii=False) + '\n')
    return 0


if __name__ == '__main__':
    sys.exit(main())
