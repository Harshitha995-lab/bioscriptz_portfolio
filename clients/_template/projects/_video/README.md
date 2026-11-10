# Video project: <name>

Copy this folder to `clients/<client>/projects/<video-name>/` for every new video.

## What to put where (inputs)

| Folder / file | What goes in it |
|---|---|
| `inputs/reference-videos/` | 1 to 3 videos with high retention that you want this one to feel like. Add a line to `brief.md` on what you like about each (pace, hook, transitions, type). |
| `inputs/raw-footage/` | Raw clips: talking head, screen recordings, product shots, b-roll. |
| `inputs/research/` | Topic breakdown, market research, competitor research, audience research (PDF, DOCX, MD or links in a `.md`). |
| `script.md` | The script, line by line. Mark on-screen text with `[TEXT: ...]` if you already know it. |
| `brief.md` | Platform and format, length, goal, call to action, brand colours, anything that must or must not appear. |

## What Claude produces (outputs)

| File | What it is |
|---|---|
| `reference-breakdown.md` | Second-by-second teardown of each reference: hook, pacing (cuts per second), text style, transitions, retention tricks, what to borrow. |
| `beat-sheet.md` | Your script mapped to scenes with timings, on-screen text and the motion for each beat. Approved by you before building. |
| `build/index.html` | The video as code (16:9) and/or `build/reel.html` (9:16), with `window.seek()`. |
| `renders/*.mp4` | Upload-ready videos. |
| `BREAKDOWN.md` | How this video was made: idea, retention logic beat by beat, techniques, format choices, how to reuse it, what to improve. |

## The process

1. **Read inputs.** Research first, then script, then references.
2. **Break down the references.** What makes viewers stay? Write `reference-breakdown.md`.
3. **Beat sheet.** Map the script to scenes, applying what worked in the references and what the audience research says they care about. Wait for approval.
4. **Build.** One HTML file per format, from the client's `brand.md` and `MOTION.md`.
5. **Check.** One still from the middle of every beat: cut-off text, safe zones, wrong facts.
6. **Render.** `node tools/render-video.js build/reel.html renders/reel.mp4 --w 1080 --h 1920 --dur <seconds>`
7. **Write `BREAKDOWN.md`.**
