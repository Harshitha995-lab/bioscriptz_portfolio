# Breakdown: "Your launch is buried in tabs" (30 s Reel)

| File | What it is |
|---|---|
| `renders/saas-reel-30s-9x16.mp4` | Final Reel: 1080 x 1920, 30 fps, 30 s, silent audio track |
| `renders/cover.jpg` | Frame 1, used as the Reel cover |
| `build/reel.html` | The video as code. Open it to watch; add `?guides` to see the Instagram safe zone |
| `script.md` / `beat-sheet.md` | The script and the shot plan |

## 1. The idea
Every SaaS founder's team knows the pain of a launch scattered across tabs.
The Reel turns that pain into a picture (tabs piling up), then fixes it in one
move (all the tabs fly into one search bar). Everything after that shows what
"one place" feels like, one feature per shot.

Style: the **dark purple launch-film reference** (cosmic gradients, frosted
glass, giant words, 1 to 3 s shots) combined with **Charlie Hills' motion
effects** as the shots themselves.

## 2. Retention logic, beat by beat

| Time | Shot | Effect used | Why it holds attention |
|---|---|---|---|
| 0.0 to 2.6 | "Your launch is buried in tabs." | Masked type | The hook is on frame 1 (the cover). The middle line is filled with moving light, so the eye goes straight to "buried". A pain, named in 5 words. |
| 2.6 to 5.4 | Tabs pile up, then fly into one search bar | Tab cascade (built for this Reel) | Shows the problem instead of saying it. The collapse at 4.3 s is the first big payoff. |
| 5.4 to 8.8 | Query types, results drop in, a ring lands | Search → results | Typing creates a small "what will it find?" suspense. |
| 8.8 to 12.2 | The first result grows into a full board | Card → workspace | Continuity: the same card the viewer just saw becomes the whole app, so the cut feels like a reveal. |
| 12.2 to 15.4 | Cursor glides across a dock, icons magnify | Magnetic dock | Constant motion and a label that changes every half second. |
| 15.4 to 18.8 | Bars grow, shrink into dots, line draws, tag pops | Chart morph | One shape turns into another, which is satisfying to watch. No figures are shown, because none were supplied. |
| 18.8 to 22.2 | "Idea" sends dots to four channels | Flowing paths | Makes an abstract benefit (repurposing) visible. |
| 22.2 to 25.4 | "Less / busywork. / More / launches." | Giant kinetic words | A tempo change: a word slams in every 0.75 s. This is the line people remember. |
| 25.4 to 30.0 | Dots gather into the logo, then name, tagline, CTA | Particle logo | A closing reward, with the CTA held about 2 s. The Reel loops straight back to the hook, which counts as a rewatch. |

**Pacing:** 9 shots in 30 s, one every 3.3 s on average, with something moving
inside every shot at all times. Captions change on every shot, so muted viewers
follow the whole story.

## 3. Techniques
- **Scene system.** Each shot is a "scene" with a start and end time and its
  own `update(time)` function. One `render(t)` draws any frame, and
  `window.seek(t)` lets the renderer capture all 900 frames exactly.
- **Push cuts.** Each scene enters from 92% size with a 12 px blur clearing
  over 0.35 s, and leaves by growing to 106% while blurring over 0.25 s. That
  is the fast "camera push" feel of the reference.
- **Living background.** Three huge blurred colour blobs (violet, blue, pink)
  drift on slow sine waves, plus 70 faint stars. The background never stops,
  even when the content holds.
- **Motion vocabulary:** ease-out for arrivals, ease-in-out for morphs and
  camera moves, a small overshoot only on pops (tabs, tag, nodes), SVG line
  draws (chart, paths), Gaussian magnification (dock), and canvas particles
  (logo).
- **Safe zone:** all words sit inside x 60 to 940 and y 250 to 1500, clear of
  Instagram's username, caption and buttons.

## 4. How to reuse it
1. Copy the project folder, then edit the `C` block at the top of
   `build/reel.html`: product name, URL, tagline, hook lines, search query,
   results, board lanes, tool names, channels and every caption.
2. Change the colours in `:root`.
3. Render:

```bash
node tools/render-video.js clients/<client>/projects/<video>/build/reel.html clients/<client>/projects/<video>/renders/reel.mp4 --w 1080 --h 1920 --dur 30
```

## 5. What would make it stronger
- **Voiceover and music.** The cuts at 2.6, 5.4, 8.8, 12.2, 15.4, 18.8, 22.2
  and 25.4 s are ready for music hits. A voiceover can read the script lines as
  written.
- **Real product screens** in shots 3 to 6 instead of mock UI.
- **One real result** with its source in shot 6 (for example, a real
  sign-up increase) to replace the "Best week" tag.
- **A/B test the hook:** "Your launch is buried in tabs." against a question
  version, such as "How many tabs is your launch in?"
