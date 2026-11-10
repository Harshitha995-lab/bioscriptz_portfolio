# Ghostwriting studio

This repo holds content skills for ghostwriting (posts, newsletters, motion
graphics) for several people. Each person has a folder in `clients/`.

## Active client

Active client: `clients/harshitha/`

Switch clients by saying "switch to <name>" (or editing the line above).
Create a new client by copying `clients/_template/` to `clients/<name>/`.

## Where profile files live

Skills from Charlie Hills' packs say they read and write `about-me.md`,
`voice.md`, `newsletter-voice.md`, `brand.md` and `MOTION.md` in the
"project root". In this repo, the project root for those files is the
**active client folder**, never the repo root. Before drafting, designing or
animating anything:

1. Read the active client's `about-me.md`, `voice.md`, `brand.md` and
   `MOTION.md` if they exist.
2. Never mix one client's voice, facts or brand into another client's work.
3. Save drafts to `clients/<name>/drafts/` and rendered videos and images to
   `clients/<name>/renders/`.

## Third-party skills

`.claude/skills/` includes MIT-licensed skills by Charlie Hills
(github.com/charlie947: motion-graphics-skills, social-media-skills,
voiceprint). Their licence is kept as `LICENSE.charlie-hills` in each folder.

## Video projects

Every video lives in `clients/<client>/projects/<video-name>/`, copied from
`clients/_template/projects/_video/` (see its README for what goes where).
For every motion graphics video:

1. Read the research, the script, then the reference videos.
2. Write `reference-breakdown.md` (what makes each reference hold attention).
3. Write `beat-sheet.md` and wait for approval before building.
4. Build in code with `window.seek()`; for Reels keep words inside
   x 60 to 940, y 250 to 1500 at 1080 x 1920, and show the hook on frame 1.
5. Check one still per beat, then render with `tools/render-video.js`.
6. Always finish with `BREAKDOWN.md`: the idea, retention logic beat by beat,
   techniques, format choices, how to reuse it, and what to improve.

Never invent a number, testimonial or result; use only what the inputs supply.
