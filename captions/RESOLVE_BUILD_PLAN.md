# DaVinci Resolve build plan: "I was overcomplicating my personal brand" reel

**Source:** `Timeline_1_2_1_1_1.mov`, 78.7s at 30 fps. It is a 608×1080 vertical picture pillarboxed inside 1920×1080.
**Target:** a 1080×1920 reel, about 77.4s after jump cuts. Planned build time is about 2 hours.

All timecodes below are measured from the audio (Vosk word timings aligned to the transcript), **not** the rough (mm:ss) stamps in the .docx. They refer to the **original clip**, with the timeline starting at `00:00:00:00`. If your timeline starts at `01:00:00:00`, add 1 hour. After the jump cuts in step 3, every later beat moves earlier. Snap each graphic to the word on the waveform; the "≈ after cuts" column gives you a guide.

> **Why the last captions drifted:** the earlier video had been sped up about 1.19× after transcription, and I timed it from syllable beats. This version is timed from real speech recognition, matched word by word to your script. Lip sync is now word-accurate (typically ±2 frames).

---

## 0. Files (in `captions/`)

| File | Use |
|---|---|
| `fonts/Montserrat-ExtraBold.ttf`, `fonts/PlayfairDisplay-BoldItalic.ttf`, `fonts/Poppins-*.ttf` | Install these before opening Resolve (step 1). |
| `examples/Timeline_1_captions_resolve.srt` | 2–4 word captions, timed to the **original** clip (with "honestly" already removed). |
| `Harshitha_reel_share.mp4` | My finished render, to use as a visual reference for every beat. |

---

## 1. Setup (10 min)

1. **Install fonts.**
   - **Windows:** right-click each `.ttf` → *Install for all users*.
   - **Mac:** double-click → *Install Font*.
   - Restart Resolve afterwards, because Fusion only scans fonts at launch.
2. **New timeline.** In the Media Pool, right-click → *Timelines → Create New Timeline*. Untick **Use Project Settings**, then:
   - *Format* tab: Resolution **Custom 1080 × 1920**, Frame rate **30**.
   - *Mismatched resolution*: **Scale full frame with crop**.
   - *Starting timecode*: `00:00:00:00`.
3. **Add tracks.**
   - Video: **V1** footage, **V2** graphics (Fusion comps), **V3** captions (or the Subtitle track), **V4** progress bar.
   - Audio: **A1** voice, **A2** music, **A3** SFX.
4. **Fill the frame.** Select the clip, then *Inspector → Transform → Zoom* **1.776** (linked). This makes the 608 px wide picture fill 1080 px, and the bars disappear.
   - If her eyes sit low in frame, set *Position Y* to −40 px so the face lands around 40–45% from the top.

## 2. Stabilize the opening (5 min)

1. Put the playhead at `00:00:02:00` and press **B** to blade the clip.
2. Select the first piece, then *Inspector → Stabilization*:
   - Mode **Similarity**, Strength 0.5, Smooth 0.6.
   - Click **Stabilize**, then raise *Zoom* slightly if edges show.
3. **Trim the start.** Speech starts at **0.18s**, so trim only **3 frames** (to `00:00:00:03`), not 0.3s, or you will clip the "I".

## 3. Jump cuts (10 min)

Blade (**B**) at each in and out point, then ripple-delete the piece (**Shift + Delete**). Zoom into the waveform and snap to the gaps.

| Remove (source) | What |
|---|---|
| `00:00:03:24` → `00:00:04:03` (3.81–4.11s) | "honestly" #1 |
| `00:00:15:18` → `00:00:16:03` (15.60–16.11s) | "honestly" #2 |
| `00:00:32:27` → `00:00:33:01` (32.91–33.04s) | "for-" stutter before "forgot" |
| `00:00:50:24` → `00:00:51:04` (50.79–51.12s) | "honestly" #3 |

- Add a **2-frame Cross Fade** on the audio at each cut (select the edit point, then *Ctrl/Cmd + T*). This hides clicks without a visible video dissolve.
- Leave the 0.2s breath at 36.3s; it is the natural pause before "people".
- **Transcript check against the audio:**
  - She does say **"I completely forgot one because…"**. There is no "thing" in the audio, so the caption keeps "one". The *graphic* in the turn moment still reads "…one thing."
  - "what actually you will build" is displayed as **"what you'll actually build"** (the words are re-timed across the same span).

## 4. Punch-ins (10 min)

Push in on V1 from Zoom **1.776 → 1.918** (+8%) over about 3s, starting on these words. Then cut back to 1.776 on the next beat; a hard reset reads as a jump cut.

| Word | Source time | ≈ after cuts |
|---|---|---|
| overcomplicating | 5.16s | 4.9s |
| professional | 19.87s | 19.0s |
| worst mistake | 24.42s | 23.6s |
| documenting (online) | 35.1s | 34.2s |
| clearer | 56.91s | 55.6s |
| tracker | 70.5s | 69.7s |

For each one:
1. In *Inspector → Zoom*, add a keyframe at the word.
2. Move 3s later and set the value to 1.918.
3. Right-click the keyframes → **Ease Out**.

## 5. Color (15 min, Color page)

Grade one clip, then use *Ctrl/Cmd + C → Paste Attributes* to copy it to every piece after the cuts, so skin tone matches across the whole clip.

| Node | Tool | Settings |
|---|---|---|
| 01 Exposure | HDR palette → **Global wheel, Exposure** | +0.5. If you have no HDR palette, use *Primaries → Gain* to 1.10 and *Gamma* to +0.02. |
| 02 Warm skin | Primaries → Temp / Tint | Temp **+250**, Tint **+5**. Check with the *Vectorscope* skin-tone indicator. |
| 03 Tame wall | Curves → **Hue vs Sat** | Click the *magenta* swatch, then pull the magenta–pink point down to about **−35%** saturation. |
| 04 Vignette | Window → Circle (invert) | Softness 45. In *Primaries*, set Gain to 0.88 outside the window. |
| (on the "turn") | Saturation, keyframed | 33.04s → 36.66s: Sat **15**, with 4-frame ramps in and out. |

## 6. Captions (25 min)

**Style:**
- 2–4 words per caption, one line, centred, with the baseline at **72–78%** of the height (y ≈ 1380–1500). That sits below her chin and above the bottom 20% UI zone.
- Montserrat ExtraBold 74 px, white, **6 px stroke in #14121F**, plus a soft drop shadow (offset 4, blur 8, opacity 50%).
- The active word turns **gold #FFC83D** at 110%.
- Emphasis words switch to **Playfair Display Bold Italic**: overcomplicating, professional, polished, perfect, worst mistake, forgot, documenting, nuggets, clearer, experiment tracker, personal branding.

**A. Studio, fastest:**
1. Run *Timeline → Create Subtitles from Audio* (Language English, Max 4 words per line, 1 line).
2. Then *File → Import → Subtitle → `Timeline_1_captions_resolve.srt`* onto a second subtitle track, and use it to correct any misheard words. Delete the auto track afterwards.
3. **Resolve 20 Studio:** in *Effects Library → Titles*, use the **animated subtitle** presets on the subtitle track. Choose the word-highlight style, set the highlight colour to #FFC83D and the font to Montserrat ExtraBold.

**B. Free version:** import the SRT (*File → Import → Subtitle*). Then style the subtitle track: click the track header → *Inspector → Track Style*, set the font and size, *Stroke* 6 with #14121F, and turn on *Drop Shadow*.

- **Per-word gold highlight** (free or Studio): use **Text+** clips only on the emphasis lines.
  1. Right-click the *Styled Text* field → **Character Level Styling**.
  2. Select the word and set its *Color* to #FFC83D, Size 1.1, and *Font* Playfair Display Bold Italic.
  3. Keyframe it so the word flips gold exactly on its frame.
- **If you've cut first:** the SRT is in source time. Import it *before* the jump cuts (step 3) and the subtitle clips will ripple with the edit. Otherwise, slide each block earlier by the removed time (0.30s after 4.1s, 0.81s after 16.1s, 0.94s after 33.0s, 1.27s after 51.1s).

## 7. Motion graphics (45 min)

**Rules:**
- **Safe zone:** 60 px side margins, nothing in the top 8% (154 px) or the bottom 20% (from y 1536).
- **Where graphics go:** her face spans roughly x 300–780 and y 450–1300, so graphics live in the **top band, y 160–430** (the bookshelf area).
- **Motion:** pop in over 6–8 frames with ease-out and a 3–4 frame overshoot (scale 55% → 106% → 100%). Leave in 4 frames at 100% → 70% with opacity to 0. No slow fades.

### 7.1 Beat sheet

| # | Beat | Starts on (source) | Ends | Element (Resolve tool) |
|---|---|---|---|---|
| 0 | **Progress bar** | `00:00:00:00` | end | V4 Fusion comp: gold bar 8 px at y 14 grows left→right (recipe 7.6). |
| 1 | **Hook card** | 0:00:00:02 | "overcomplicating" +0.9s (6.1s) | Fusion: ink card 940×250 at y 300. Text+ "I WAS" (Montserrat 46) / **"OVERCOMPLICATING"** (gold, Montserrat ≈80, fit 860 px) / "my personal brand" (Playfair BI 60). A tangled scribble draws on under it (recipe 7.4 with a wavy open spline). |
| 1b | Name tag | 2.0s | 6.1s | Chip (7.2) with a gold dot: "Harshitha V. \| @yourhandle". |
| 2 | **List chips** | video editing 8.04 · positioning 9.06 · content creation 9.93 · content pillars 11.4 · AI automation ≈12.4 · LinkedIn growth 13.41 | "things" 18.48 | 6 chips (7.2), 2 per row at x 290 / 790, rows y 205 / 300 / 395. |
| 3 | **Collapse + TOO MUCH** | "things" 18.48 | +1.4s | Chips: Size → 0.2, Angle ±40, Opacity → 0 over 6 frames. "TOO MUCH" stamp (7.3) in coral at y 300 with a 3-frame **Camera Shake** on V1 (Effects → Fusion Effects → *Camera Shake*, Strength 0.3). Add an RGB split if you like (*Effects → ResolveFX Stylize → Prism Blur*, 2 frames). |
| 4 | **Myth cards + X** | professional 19.87 · polished 21.24 · perfect 23.01 · experienced 28.38 | "content" ≈30.5 | 4 cards in a 2×2 grid (x 290 / 790, y 225 / 365). A coral X (7.3) slams on each 0.3s after it appears. |
| 4b | Gold underline | "worst" 24.42 | "thought" 25.9 | 10 px gold bar under the caption, wiping left→right in 8 frames (Rectangle mask, *Width* keyframe), plus the punch-in from step 4. |
| 5 | **The turn** | "forgot" 33.04 | "people" 36.66 | Saturation 15 (step 5). Text+ "…one thing." in Playfair BI 96, gold, at y 300. Optional: Retime freeze of 6 frames on V1 (*Retime Controls → Freeze Frame*), but **do the freeze only on a V1 copy over a matching audio gap**, or lip sync breaks. Add a record-scratch on A3. |
| 6 | **Feedback bubbles** | suggest 38.86 · opinions 41.52 · correct 43.20 | "nuggets" 46.14 | Bubble (7.5): "Try this" (x 300, y 330), "Fix this" (x 780, y 260), "Have you thought of…?" (x 560, y 390). Each floats up 55 px over its life. At "nuggets", each pops into a gold spark. |
| 7 | **XP counters** | skills 48.90 · opinions (2nd) ≈49.7 · learn 51.72 | "there" 55.32 | Gold pills "+1 SKILLS / +1 OPINIONS / +1 LEARNING", top-left, x 70+, y 200 / 264 / 328. Pop with 112% overshoot. |
| 8 | **Line chart** | "there you go" 55.32 | "content." 64.44 | Recipe 7.7, in an ink card 940×270 at y 300. The line draws over 80% of the beat. "POSITIONING" (Montserrat 54) goes from Blur 14 → 0 over 9 frames at **"clearer" 56.91**. |
| 9 | **Lab log** | documenting 64.71 | "created" 69.2 | Ink card 860×270. Header "EXPERIMENT LOG · DAY 01" (mono 22, gold). Lines type on at learning 65.61, testing 66.58, "✓ what works" 67.14 (gold), "✗ what doesn't" 67.77 (coral), building 69.00. Use a mono font (JetBrains Mono / Courier). Text+ → *Write On* (end 0 → 1 over about 12 frames per line). |
| 10 | **Tracker offer** | "created" 69.24 | "comment" 76.08 | Your screenshot on a card 760×260 at y 300. Fusion: *ImagePlane3D → Renderer3D*, Rotation Y −10° → +8° over the beat, X +6°. Label "PERSONAL BRAND EXPERIMENT TRACKER". |
| 11 | **CTA** | "comment" 76.08 | end | White comment bubble at y 320; Text+ "personal branding" types on (Write On over 24 frames). Gold "COMMENT" pill at y 210 pulses twice (Size 1 → 1.12 → 1 at +0.9s and +1.35s). End card: handle. |

### 7.2 Recipe: chip pop-in (Fusion macro, build once, reuse ×12)

1. On V2 add *Effects → Toolbox → **Fusion Composition*** and open it on the Fusion page.
2. Build the nodes:
   - `Background1`: Color #14121F, Alpha 0.7.
   - `Rectangle1` (mask on Background1): Width 0.34, Height 0.04, **Corner Radius 0.5**.
   - `Text1` (Text+): Montserrat ExtraBold, Size 0.032, white, "Video editing".
   - Optional `Ellipse1` mask on a gold `Background2` for the dot.
   - `Merge1` (Text over pill), then `Transform1`, then `MediaOut1`.
3. Keyframe **Transform1 → Size**: frame 0 = 0.55, frame 5 = 1.06, frame 8 = 1.00. Keyframe Opacity (on Merge1 *Blend*) from 0 at frame 0 to 1 at frame 3.
4. Open the *Spline Editor*, select the keys, and press **Shift+S** (smooth), then pull the out-handles flat to get the ease-out.
5. Animate the exit at the end: Size 1 → 0.7 and Blend → 0 over 4 frames.
6. Select all nodes → right-click → **Macro → Create Macro**. Expose Text1 *Styled Text*, Background1 *Color*, Rectangle1 *Width*, and Transform1 *Center*. Save it to `…/Fusion/Templates/Edit/Titles/Chip.setting`. It now appears in *Effects Library → Titles* as **Chip**.

### 7.3 Recipe: X stamp / TOO MUCH stamp

- **X:**
  - Make two `Rectangle` masks (Width 0.06, Height 0.012), Angle 45 and −45, combined with *Paint Mode: Merge*, on a coral `Background` (#FF4D4D).
  - Keyframe *Transform → Size*: frame 0 = **2.4**, frame 3 = 0.92, frame 5 = 1.0. Set Angle −12 and Opacity 0→1 over frames 0–2.
  - Add a soft *stamp thud* on A3 at frame 3.
- **TOO MUCH:**
  - Text+ Montserrat ExtraBold, coral, with *Shading Element 2* (Outline) in coral at 6 px on an ink rounded-rect plate.
  - Use the same slam (2.6 → 0.94 → 1.0), then *Angle* −8 → −11 → −5 → −8 over frames 6–9 for the shake.

### 7.4 Recipe: hand-drawn scribble / line draw-on

1. Draw an **open** `Polygon` mask (don't close the spline) on a gold `Background`.
2. In the mask's *Controls*, untick **Solid** and set **Border Width 0.004**.
3. Keyframe **Write On → End** from 0 to 1 over 20 frames (the scribble), or over the beat length (the chart line).

### 7.5 Recipe: comment bubble → gold spark

1. Build the bubble:
   - White `Background` masked by a `Rectangle` (Corner Radius 0.35), plus a `Polygon` tail (3 points, *Paint Mode: Merge*).
   - Merge `Text+` (Montserrat 0.028, ink) over it.
   - Add a `DropShadow` (Softness 0.02, Opacity 0.4).
2. Animate it:
   - *Transform → Center Y*: float from +0.015 to −0.013 over the whole life.
   - Pop in with recipe 7.2's keys.
3. At the "nuggets" frame:
   - Bubble *Size* → 0.1 and *Blend* → 0 over 4 frames.
   - On the same frame, add an `sStar` (Fusion 18 shape tool, 5 points, Inner Radius 0.4) → `sRender` → gold, Size 0 → 1.2 → 1.0 over frames 0–8, Angle −40 → +30, fading out by frame 30.

### 7.6 Recipe: progress bar

- Gold `Background` with a `Rectangle` mask: Height 0.004, Center Y 0.993, **Center X 0.0**.
- Keyframe **Width 0 → 2.0** across the whole timeline. Because the centre sits on the left edge, only the right half shows, so the bar grows from left to right.
- Add a second, white rectangle at 25% opacity behind it as the track.

### 7.7 Recipe: line chart draw-on

- **Card:** ink `Background` (0.7) + `Rectangle` (Corner Radius 0.12), 940×270 px at y 300.
- **Axes:** two thin `Rectangle` masks on a white Background (opacity 0.75). X axis: 770×4 px at y 410. Y axis: 4×220 px at x 160.
- **Labels:** Text+ "time documenting →" (bottom right) and "positioning clarity" (top left), Montserrat 20.
- **Line:** an open `Polygon` rising from bottom-left to top-right with a small wobble early on. Use Border 0.006, gold, and keyframe *Write On End* 0 → 1 over 80% of the beat (recipe 7.4).
- **Focus pull:** Text+ "POSITIONING", Montserrat 54 → `Blur` (Size **14 → 0** over 9 frames starting on "clearer") + Blend 0.45 → 1.

## 8. Sound (15 min, Fairlight)

1. **A1 voice:**
   - Studio: *Inspector → Audio → **Voice Isolation*** at 60–70.
   - Free: *Fairlight FX → **Noise Reduction*** (Auto Speech mode, Threshold auto, Ratio about 3).
   - Then *Fairlight FX → **De-Esser*** (Frequency 6.5 kHz, Range −6 dB).
2. **Track Dynamics** (double-click the A1 dynamics slot):
   - **Compressor:** Threshold −20 dB, Ratio 3:1, Attack 8 ms, Release 120 ms, makeup to taste.
   - **Limiter:** **−1.0 dBTP**.
3. **Loudness:**
   - In *Project Settings → Fairlight*, set *Target Loudness Level* to **−14 LUFS**.
   - Right-click the voice clips → **Normalize Audio Levels** → ITU-R BS.1770-4, *Target* −14 LUFS, True Peak **−1**.
   - Check that Integrated reads about −14 on the Loudness meter. My render measured −14.2 LUFS.
4. **A2 music:**
   - A lo-fi or ambient bed at **−26 dB**.
   - Duck it under the voice: on A2 *Dynamics* set *Compressor → Side Chain / Key* **on** with the key input from A1. In A1's *Dynamics* panel, set *Send* to that key. Use Threshold −35, Ratio 4:1, Release 300 ms.
5. **A3 SFX** at −20 to −24 dB:
   - whoosh on each card entry
   - soft pop per chip
   - record-scratch at **33.0s** ("forgot")
   - stamp thud on each X and on TOO MUCH (18.6s)
   - ding on the CTA (76.1s)

## 9. Render (5 min, Deliver page)

**Reels / Shorts / X preset:** *Custom Export*:
- *Format* **MP4**, *Codec* **H.264**, *Encoder* hardware if offered.
- **1080 × 1920**, **30 fps**, *Quality* → **Restrict to 14000 kb/s**, *Profile* High, *Keyframes* Auto.
- *Audio*: AAC, 320 kb/s, 48 kHz.
- *Save As New Preset* → "Reel 1080x1920 14M".

**LinkedIn 4:5 (1080 × 1350):**
1. Duplicate the timeline (right-click → *Duplicate Timeline*).
2. In *Timeline Settings*, set **1080 × 1350**. The 4:5 frame trims 285 px from the top and the bottom.
3. Move the graphics (V2/V4) **down by about 150 px** and the captions (V3) **up by about 150 px**. In 4:5, the caption baseline sits at y ≈ 1200 and the graphics band at y ≈ 300–560.
4. Check that no graphic is clipped.
5. Render with the same preset at 1080×1350 and 12 Mb/s.

---

### 2-hour order of work
1. Steps 1–4: setup, cuts and punch-ins (35 min).
2. Step 5: colour (15 min).
3. Step 6: captions (25 min).
4. Build the 3 macros: chip, stamp, bubble (20 min).
5. Lay out beats 0–11 using the beat sheet (25 min).
6. Step 8: sound (15 min).
7. Step 9: render (5 min).
