# Sound for a demo film

A product film's sound is mostly its music. The effects are touches under it, there because the viewer sees a hand or a
camera do something, and a viewer should hardly notice them as separate sounds. The bleep for every message and the
whoosh for every move are what make a film sound cheap.

## What good product films do

- **The score carries the film.** One quiet piece follows the cut: calm while the viewer reads, a lift where the film
  opens up (its big shot), and a resolve on the end card. Pick a stable pulse and a melody that doesn't compete
  with what is on screen; the music should change where the picture changes, not on a bar line.
- **Effects are tactile and few.** Score a touch you can see (a tap, typing, a send), and the one or two big camera
  moves with a breath of air. Leave out messages arriving, badges, panes sliding and reactions; the picture says those.
  Five well-placed sounds beat fifty.
- **Make on-screen events musical.** When something happening wants a sound (a notification, a run of merges), play
  it as a note of the score, in its key, rather than as a separate chime.
- **Mix the effects under the score.** Duck the music a few dB under each touch (a sidechain with a short attack and a
  release around 0.4 s) instead of turning the effects up. Put both in a room: a long one for the music, a short dry
  one for the effects, so they sit in one space.
- **Master for where it plays.** About -16 LUFS integrated with the true peak under -1 dBTP for the web and social; a
  loudness range under about 10 LU so it holds up on a phone speaker. Fade to silence on the last frame.

Sources: [IRPR on product-video sound](https://sounddesign.irpr.agency/applications/product-videos/) and
[on UI sounds people stop muting](https://sounddesign.irpr.agency/solutions/ui-sounds-annoying/) (short, soft, balanced
cues), [Sonilo on music for software demos](https://sonilo.com/blog/guides/background-music-software-demo-videos)
(ducking is an editorial choice, music that leaves room), and Apple's
[Behind the Mac: Skywalker Sound](https://starwars.com/news/behind-the-mac-skywalker-sound) (foley anchors the track,
design only supports it).

## The tools here

- `motion/score.mjs`: the score. Notes ({ at, inst, note, dur, vel, pan }) rendered by three synthesized instruments:
  `felt` (a felt piano), `pad` (detuned saws through a low-pass that the film's intensity `bright(t)` opens) and
  `sub`; and for an upbeat cut, a beat kit: `kick`, `clap`, `snare`, `hat`, `ohat`, `crash`, `impact`, `riser`, `bass`,
  `stab` (supersaw chords) and `pluck` (a hook). Then the mixing tools: `pump` (chords breathing on the kick),
  `reverb` (FFT convolution with a synthesized room), `duck` (the sidechain), `filter` (EQ), `fade`, `gain`, `add`, and
  `toLoudness` (a bus to a LUFS level).
- `motion/sound.mjs`: the effects (`mix` of cues; `tick` and `air` are the quiet ones a scored film wants) and
  `master` (the limiter and the loudness loop, muxed in as AAC).
- An ad wants the other shape: a beat whose tempo puts every cut on a beat (120 BPM when the cuts sit on half
  seconds), a crash on each cut, a build into the big shot, the music in front and the touches lifted over it.
  `demos/hero-v4/sound.mjs` is that one. Even an ad can be too loud: its first cut at -14 LUFS was, so it now masters
  at -16.4 LUFS with the true peak at or below -3 dBTP.
- `master` measures the AAC it muxed, not only the WAV it limited, because the AAC encode can raise the peak. When
  the AAC's true peak is over `tp` it limits again with that much more room, and when its loudness is more than 0.2 LU
  off it aims again, for up to four encodes.
- The quiet pattern, as v4 did it: the score in a room at -20 LUFS, the effects in a small room,
  the score ducked under the effects, the sum faded out on the last frame, then `master`. Render a 30 s preview of the
  mastered track to listen to on its own.

## Licences

Every sound in this skill is synthesized by its own code (MIT, with the repo), so there is no sample, soundfont or loop
in it and nothing to credit. Keep it that way, or record the source and licence of anything added here: the repo's
core is published under MIT, so only CC0 or public-domain material may come in, never CC-BY-NC, "free for personal
use", or anything behind a login.
