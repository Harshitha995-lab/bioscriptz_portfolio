# Animated word-highlight captions

Burns kinetic, word-by-word captions onto a video. The original frame and audio stay unchanged, and the captions are layered on top.

| Setting | Value |
|---|---|
| Font | **Inter Bold** (bundled in `fonts/`, SIL OFL). The reel style uses **Poppins**. |
| Size | **36px**, measured like CSS/Figma (the em box is 36px). libass sizes fonts differently, so the script converts automatically. |
| Colour | White text with a subtle soft drop shadow and a thin dark edge for contrast on busy backgrounds |
| Highlight | The word being spoken turns **#FACC15** (bright yellow). Use `--accent "#6366F1"` for indigo. |
| Motion | Each phrase slides up 14px and fades in over 160ms. Upcoming words are slightly dimmed, and the phrase fades out at the end. |
| Position | Lower third: the baseline sits at 86% of the picture height, which is y ≈ 1650 on a 1080×1920 frame |
| Timing | Whisper word-level timestamps (faster-whisper with VAD) |

### Pillarboxed footage is handled automatically
`Timeline_1_1_1.mp4` is a **vertical 9:16 recording inside a 1920×1080 frame**, with black bars left and right. The script runs `ffmpeg cropdetect` and finds the real picture at `608×1080 @ x=656`. It then:
- centres the captions on the picture (x = 960),
- keeps every line within 86% of the picture width (≈523px), so text never spills onto the black bars,
- places the lower third at y ≈ 929, which is the same relative spot as y 1650 on a 1080×1920 reel.

Use `--no-autocrop` to ignore the bars and lay out over the full frame.

## Setup (once)

```bash
# macOS: brew install ffmpeg      Windows: winget install ffmpeg      Ubuntu: sudo apt install ffmpeg
cd captions
python3 -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

The first run downloads the Whisper model (~460 MB for `small`).

## Run it

```bash
./render.sh /path/to/Timeline_1_1_1.mp4
```

This writes three files next to the input video:
- `Timeline_1_1_1_words.json`: the Whisper transcript with word timings
- `Timeline_1_1_1_captions.ass`: the animated captions (editable)
- `Timeline_1_1_1_captioned.mp4`: **the final video**

Useful variations:

```bash
./render.sh video.mp4 --accent "#6366F1"            # indigo highlight
./render.sh video.mp4 --uppercase --max-words 3     # punchier, reel-style
MODEL=medium PROMPT="Bioscriptz, biotech, founders" ./render.sh video.mp4   # better accuracy + spelling hints
SKIP_TRANSCRIBE=1 ./render.sh video.mp4             # re-style without re-transcribing
```

On Windows, run the three commands from `render.sh` by hand (see "Step by step" below), or use Git Bash.

## Reel style: small line + BIG word (word by word)

`build_stacked_captions.py` makes stacked captions: a small Poppins Medium line on top, then one big Poppins ExtraBold punch word underneath.

- **Word-by-word reveal:** each small word pops in as you say it, and the big word bounces in on its own timestamp.
- **Accent words:** key words (`--keywords`, or the built-in list such as *overcomplicating* and *personal brand*) turn yellow and get a star burst.
- **Fitting:** long punch words shrink automatically to fit the picture.

```bash
python3 build_stacked_captions.py words.json --video video.mp4 -o stacked.ass
ffmpeg -i video.mp4 -vf "ass=stacked.ass:fontsdir=fonts" -c:v libx264 -crf 16 -c:a copy video_captioned.mp4
```

Useful flags: `--top-size 40`, `--big-size 118`, `--accent "#FDE047"`, `--no-stars`, `--uppercase`, `--min-top 2 --max-top 6` (how many small words appear before each punch).

### No Whisper? Time your own transcript
If you already have the transcript (for example the `.docx` that Premiere or Resolve exports), `align_script.py` times it to the audio offline. It needs no model download, only `pip install scipy pocketsphinx`.

```bash
python3 align_script.py video.mp4 Timeline_1.docx -o words.json
```

It detects the syllable beats in your voice, snaps sentence breaks to real pauses, and ignores the transcript's `(00:05)` stamps. That means it still works if the clip was sped up or re-cut after you transcribed it. Expect roughly ±0.2s accuracy per word; Whisper is more exact.

## Editing in DaVinci Resolve

Resolve can't play `.ass` animations. Instead, render the captions as a **transparent overlay clip** and stack it above your footage. The video stays untouched on V1, and you keep full control in the edit.

```bash
./overlay.sh /path/to/Timeline_1_1_1.mp4
```

This creates:
- `Timeline_1_1_1_captions_overlay.mov`: ProRes 4444 with alpha, same size, fps and length as your video
- `Timeline_1_1_1_captions.srt`: plain subtitles (optional)

In Resolve (the free version works):
1. **Project settings → Master Settings:** timeline resolution **1920×1080**, frame rate **24**. Set these *before* adding clips.
2. **Media page:** import `Timeline_1_1_1.mp4` and `Timeline_1_1_1_captions_overlay.mov`.
3. **Edit page:** put the video on **V1** and the overlay on **V2**, both starting at 00:00:00:00. They're the same length, so they line up frame-for-frame.
4. The overlay's transparency should work automatically. If you see a black frame instead, right-click the overlay in the Media Pool → **Clip Attributes → Alpha mode: Straight**.
5. Edit as normal. If you trim or cut V1, select both clips and link them (**Ctrl/Cmd + Alt + L**) so the captions stay in sync.
6. **Deliver page:** export as H.264/H.265 MP4 at 1920×1080.

Tips:
- **Moving or resizing captions:** select the V2 clip → Inspector → Transform (Position Y / Zoom). Because the captions are one layer, this moves all of them together.
- **Changing words, colours or timing:** fix `Timeline_1_1_1_words.json` or pass flags (`--accent`, `--max-words`…), then rerun with `SKIP_TRANSCRIBE=1 ./overlay.sh …` and in Resolve right-click the clip → **Replace Clip**.
- **Editable text inside Resolve:** File → Import → **Subtitle** → choose the `.srt`. This gives plain, phrase-level subtitles you can retype and style in the Inspector, but without the word-by-word highlight.

## Step by step (same thing, manually)

```bash
# 1. Transcribe with word timestamps
python3 transcribe.py video.mp4 -o words.json --model small

# 2. (optional) fix any misheard words in words.json. Only edit the "word" text, not the times.

# 3. Build the animated caption file
python3 build_captions.py words.json --video video.mp4 -o captions.ass

# 4a. PREVIEW instantly, no render needed
ffplay -vf "ass=captions.ass:fontsdir=fonts" video.mp4

# 4b. Render the final video (high quality, audio copied untouched)
ffmpeg -i video.mp4 -vf "ass=captions.ass:fontsdir=fonts" \
  -map 0:v:0 -map 0:a? -c:v libx264 -preset slow -crf 16 -pix_fmt yuv420p \
  -c:a copy -movflags +faststart video_captioned.mp4
```

### Bit-exact alternative (no re-encode)
Burning captions in always re-encodes the video. CRF 16 is visually lossless, but if you want the original pixels untouched, attach the captions as a styled subtitle track instead. VLC, mpv and IINA render the animation; Instagram and YouTube uploads will *not* show it.

```bash
ffmpeg -i video.mp4 -i captions.ass -map 0 -map 1 -c copy \
  -attach fonts/Inter-Bold.ttf -metadata:s:t mimetype=font/ttf video_softsubs.mkv
```

## Tweaking
All options: `python3 build_captions.py --help`. The main ones:

| Flag | Default | What it does |
|---|---|---|
| `--font-size` | 36 | text size in px |
| `--accent` | `#FACC15` | highlight colour |
| `--y-frac` | 0.86 | vertical position (fraction of picture height) |
| `--max-words` | 4 | words on screen at once |
| `--shadow` / `--outline` / `--blur` | 3 / 1.5 / 0.8 | shadow offset, edge thickness, softness |
| `--dim` | 0.15 | transparency of words not yet spoken (0 = off) |
| `--uppercase` | off | ALL CAPS |

To fine-tune individual lines or timings by hand, open the `.ass` file in [Aegisub](https://aegisub.org) (free).
