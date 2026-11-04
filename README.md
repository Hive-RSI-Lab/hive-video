# video

Demo videos and highlight reels in code. A film script drives a web page frame by frame on a virtual clock
(Playwright and Chromium). Blender renders 3D shots, and ffmpeg makes the MP4 and a GIF small enough to post.
`video stutters` measures the motion, so "smooth" is a number, not an opinion.

- `bin/video.mjs` is the CLI (`video help`): check, new, render, stutters, sheet, mp4, gif, blender, length.
- `SKILL.md` is the workflow and the tricks that make a film smooth. Start there.
- `kit/` holds the director, camera, compositor, terminal recorder and selfcheck, with the API in `kit/KIT.md`.
  `kit/blender/` holds the 3D helpers, `kit/motion/` motion graphics, and `kit/AUDIO.md` sound.
- `templates/film.mjs` is the starter that `video new` copies.

It needs node, ffmpeg and Chromium. playwright-core installs itself into `~/.cache/hive-video` on first use.
Blender is needed only for 3D shots. Renders are slow and memory-hungry, so run them under your Hive's job limiter if it has one
(on H2 that is `heavy timeout N video render ...`); the docs show `heavy`, and work the same without it.

MIT licensed.
