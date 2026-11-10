# Breakdown: SaaS launch video template (60s)

Two cuts of the same video, built entirely in code. No After Effects, no camera,
no AI video generator.

| File | Format | Where it goes |
|---|---|---|
| `saas-template-60s-16x9.mp4` | 1920 x 1080, 30 fps, 60 s | LinkedIn, YouTube, website, X |
| `saas-template-60s-reel-9x16.mp4` | 1080 x 1920, 30 fps, 60 s | Instagram Reels, TikTok, YouTube Shorts, LinkedIn mobile |
| `index.html` / `reel.html` | Source for each cut | Open in a browser to watch it live |
| `poster.jpg` / `reel-cover.jpg` | Stills | Thumbnail / Reel cover |

---

## 1. The idea in one sentence

**"Your work is everywhere. All of it, in one place."** Every SaaS product
promises to replace chaos with one calm place. The video *shows* that
transformation instead of saying it: scattered app tiles snap into a tidy row,
then become one product window.

## 2. Why it holds attention (retention logic)

| Time | Beat | What the viewer sees | Why it keeps them watching |
|---|---|---|---|
| 0 to 5 s | **Hook** | "Your work is everywhere." with 8 floating app tiles | A pain the viewer feels right now. In the reel the headline is on screen from the very first frame, because a Reel's first frame is its cover and an empty first frame loses the scroll. |
| 5 to 9 s | **Turn** | Tiles fly into one neat row: "All of it, in one place." | Visual payoff in under 10 s. Chaos becomes order, which the brain enjoys. |
| 9 to 20 s | **Product** | Glass app window, slow 5% push-in, charts and tasks drawing themselves | Movement inside a still frame. Something new appears every 0.3 to 0.6 s so the eye never rests. |
| 20 to 30 s | **Interaction** | A prompt types live, three results slide in | Typing creates suspense ("what will it answer?"). The only typing in the video, so it stands out. |
| 30 to 36 s | **Reassurance** | Three ticks draw one by one | Answers "but does it work?" Each tick is a micro-reward. |
| 36 to 46 s | **How it works** | Connect, Automate, Grow, joined by a drawing line | Turns the product into 3 easy steps the viewer can remember. |
| 46 to 52 s | **Punchline** | "Less switching. More shipping." with an underline | The line people quote or screenshot. Rhythm: short, short. |
| 52 to 60 s | **Call to action** | Logo, name, tagline, button | Holds 6 s so it can be read on a phone. In the reel it then loops straight back to the hook, which Instagram counts as a rewatch. |

**Pacing rule used:** a new visual change every 0.3 to 1.2 s, a new scene
every 5 to 10 s, and one idea per scene.

## 3. How it is built (the technique)

1. **One HTML file per format.** Every element (text, tiles, window, chart) is a
   normal web element on a fixed-size stage: 1920 x 1080 or 1080 x 1920.
2. **One `render(t)` function draws any moment.** Given a time in seconds, it
   works out each element's opacity, position and scale. Nothing depends on the
   previous frame, so any second can be redrawn exactly. That is what
   `window.seek(seconds)` does.
3. **Motion vocabulary (kept small on purpose).**
   - *Ease-out cubic* for things arriving: fast start, soft landing.
   - *Ease-in-out* for camera moves and lines drawing.
   - *Rise and fade*: text enters 24 to 40 px below and settles.
   - *Line draw*: SVG strokes revealed with `stroke-dashoffset` (charts, ticks, step line, underline).
   - *Push-in*: the product window scales from 1.00 to 1.05 over 10 s.
   - *Blur-out*: the window blurs as the command box takes over, like a camera focus pull.
4. **Banned on purpose** (Charlie Hills' house rules): typewriter headlines,
   glow, bounce, gradient text, stock people, and any number nobody supplied.
   The mock dashboard has **no figures**. It uses bars, lines and pills only.
5. **Rendering.** A headless browser opens the file with `?render`, seeks to each
   of 1,800 frames (30 fps x 60 s), screenshots each one, and ffmpeg joins them
   into an MP4.
6. **Upload-safe export.** H.264 High, yuv420p, bt709, `+faststart`, and a silent
   audio track (some platforms reject or re-encode silent-less video).

## 4. How the vertical reel differs from the 16:9 cut

| Change | Why |
|---|---|
| Rebuilt layout, not a crop | Cropping 16:9 to 9:16 would cut the product window in half |
| All words kept inside **x 60 to 940, y 250 to 1500** | Instagram covers the top with the account name, the bottom with the caption, and the right with like, comment and share buttons. Open `reel.html?guides` to see this zone as a red box. |
| Hook visible on frame 1 | The first frame is the Reel's cover and the scroll-stopper |
| Product window narrower and taller; sidebar shows icons only | Fits a phone screen without tiny text |
| "How it works" stacked vertically | Three columns would be unreadable at phone width |
| Punchline on 4 lines at 150 px | Big type is what stops the thumb |
| No fade at the end; loops to the hook | Seamless loop encourages rewatches |

## 5. How to reuse it for a real client

1. Copy this folder to `clients/<client>/projects/<video-name>/`.
2. In both HTML files, edit the `CONFIG` block (product name, every line of
   copy, the typed prompt, results, checklist, steps, CTA) and the colour tokens
   in `:root` (`--bg`, `--ink`, `--accent`).
3. Better still, give Claude the real logo, real screenshots, real results with
   sources and the exact CTA. Real proof beats mock UI every time.
4. Check stills: open each file in a browser, or ask Claude to "check frames".
5. Render:

```bash
node tools/render-video.js clients/<client>/projects/<video>/index.html out-16x9.mp4 --w 1920 --h 1080 --dur 60
```

```bash
node tools/render-video.js clients/<client>/projects/<video>/reel.html out-reel.mp4 --w 1080 --h 1920 --dur 60
```

## 6. What would make it stronger next time

- **Sound.** A music bed timed to the beats (the cuts at 5, 9, 20, 30, 36, 46 and
  52 s are natural hit points), or a voiceover. Most Reels are watched muted, so
  the on-screen words stay.
- **Real proof.** A real screenshot in beat 3 and one sourced result in beat 5.
- **Shorter cut.** A 30 s Reel (hook, product, interaction, CTA) usually keeps a
  higher share of viewers to the end than 60 s. Worth testing both.
