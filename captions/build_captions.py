#!/usr/bin/env python3
"""Turn Whisper word timestamps into animated, word-highlighted ASS captions.

Accepts openai-whisper / faster-whisper JSON (segments[].words[]) or WhisperX JSON (word_segments[]).

Look:
  * Inter Bold, white, 36px (CSS px: the font's em box is 36px tall), subtle drop shadow
  * the word being spoken is highlighted in the accent colour; words not yet spoken are slightly dimmed
  * each caption group slides up + fades in, and fades out at the end
  * captions sit in the lower-third and are kept inside the visible picture
    (pillarboxed / letterboxed footage is auto-detected with ffmpeg cropdetect)

Usage:
  python build_captions.py words.json --video input.mp4 -o captions.ass
"""
import argparse
import json
import os
import re
import subprocess
from collections import Counter

from fontTools.ttLib import TTFont

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_FONT = os.path.join(HERE, "fonts", "Inter-Bold.ttf")


# ---------- helpers ----------

def ass_color(hex_rgb, alpha=0):
    """#RRGGBB -> &HAABBGGRR (ASS colour order is BGR, alpha 00 = opaque)."""
    h = hex_rgb.lstrip("#")
    r, g, b = h[0:2], h[2:4], h[4:6]
    return f"&H{alpha:02X}{b}{g}{r}".upper()


def ass_tag_color(hex_rgb):
    """#RRGGBB -> &HBBGGRR& for inline override tags."""
    h = hex_rgb.lstrip("#")
    return f"&H{h[4:6]}{h[2:4]}{h[0:2]}&".upper()


def ass_time(cs):
    """centiseconds -> H:MM:SS.cc"""
    h, rem = divmod(cs, 360000)
    m, rem = divmod(rem, 6000)
    s, c = divmod(rem, 100)
    return f"{h}:{m:02d}:{s:02d}.{c:02d}"


def escape(text):
    return text.replace("\\", "/").replace("{", "(").replace("}", ")")


def probe_video(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "csv=p=0", path],
        capture_output=True, text=True, check=True).stdout.strip()
    w, h = out.split(",")[:2]
    return int(w), int(h)


def detect_picture_area(path, duration=30):
    """Find the real picture inside black bars. Returns (w, h, x, y) or None."""
    res = subprocess.run(
        ["ffmpeg", "-hide_banner", "-ss", "2", "-t", str(duration), "-i", path,
         "-vf", "cropdetect=24:2:0", "-f", "null", "-"],
        capture_output=True, text=True)
    crops = re.findall(r"crop=(\d+):(\d+):(\d+):(\d+)", res.stderr)
    if not crops:
        return None
    return tuple(int(v) for v in Counter(crops).most_common(1)[0][0])


class FontMetrics:
    """Measures text with the actual font file so lines can be wrapped to fit the safe area."""

    def __init__(self, path):
        f = TTFont(path)
        self.upm = f["head"].unitsPerEm
        self.cmap = f.getBestCmap()
        self.hmtx = f["hmtx"].metrics
        os2 = f["OS/2"]
        # libass sizes a font so that (winAscent + winDescent) == Fontsize.
        # We want the em box to be the requested px size (same as CSS/Figma), so scale up.
        self.libass_ratio = (os2.usWinAscent + os2.usWinDescent) / self.upm
        self.family = f["name"].getDebugName(16) or f["name"].getDebugName(1)

    def width(self, text, px):
        units = 0
        for ch in text:
            glyph = self.cmap.get(ord(ch)) or self.cmap.get(ord("n"))
            units += self.hmtx.get(glyph, (self.upm // 2, 0))[0]
        return units * px / self.upm


# ---------- words -> groups ----------

def load_words(path):
    data = json.load(open(path, encoding="utf-8"))
    if "word_segments" in data:  # WhisperX
        raw = data["word_segments"]
    else:
        raw = [w for s in data.get("segments", []) for w in s.get("words", [])]
    words = []
    for w in raw:
        text = w.get("word", w.get("text", "")).strip()
        if not text or "start" not in w or "end" not in w:
            continue
        words.append({"text": text, "start": float(w["start"]), "end": float(w["end"])})
    words.sort(key=lambda w: w["start"])
    # make timings monotonic, non-overlapping and never zero-length
    for i, w in enumerate(words):
        if i and w["start"] < words[i - 1]["end"]:
            words[i - 1]["end"] = max(words[i - 1]["start"] + 0.05, w["start"])
            w["start"] = max(w["start"], words[i - 1]["end"])
        w["end"] = max(w["end"], w["start"] + 0.05)
    return words


def group_words(words, max_words, max_width, metrics, px, max_gap):
    """Split into short caption phrases: break on pauses, sentence ends, word count or width."""
    groups, cur = [], []
    for w in words:
        if cur:
            gap = w["start"] - cur[-1]["end"]
            too_wide = metrics.width(" ".join(x["text"] for x in cur + [w]), px) > max_width * 2
            if (len(cur) >= max_words or gap > max_gap or too_wide
                    or re.search(r"[.!?]$", cur[-1]["text"])):
                groups.append(cur)
                cur = []
        cur.append(w)
    if cur:
        groups.append(cur)
    return groups


def wrap(group, max_width, metrics, px):
    """Return index where a second line starts (None = single line), choosing the most balanced split."""
    texts = [w["text"] for w in group]
    if metrics.width(" ".join(texts), px) <= max_width or len(texts) < 2:
        return None
    best = min(range(1, len(texts)), key=lambda i: abs(
        metrics.width(" ".join(texts[:i]), px) - metrics.width(" ".join(texts[i:]), px)))
    return best


# ---------- ASS output ----------

def build(args):
    W, H = probe_video(args.video) if args.video else (args.width, args.height)
    metrics = FontMetrics(args.font)

    # Picture area (inside any black bars) decides both width limit and vertical position.
    area = None
    if args.video and not args.no_autocrop:
        area = detect_picture_area(args.video)
    pw, ph, px0, py0 = area if area else (W, H, 0, 0)
    if area and (pw, ph) != (W, H):
        print(f"Picture area detected inside frame: {pw}x{ph} at x={px0}, y={py0}")

    cx = px0 + pw / 2
    # lower-third: y_frac of the picture height (0.86 of 1920 = ~1650px on a 1080x1920 frame)
    baseline_y = py0 + ph * args.y_frac
    max_width = pw * args.width_frac

    font_px = args.font_size
    ass_size = round(font_px * metrics.libass_ratio, 1)

    words = load_words(args.words)
    if args.uppercase:
        for w in words:
            w["text"] = w["text"].upper()
    groups = group_words(words, args.max_words, max_width, metrics, font_px, args.max_gap)

    white = ass_tag_color("#FFFFFF")
    accent = ass_tag_color(args.accent)
    dim_alpha = f"&H{round(args.dim * 255):02X}&"  # fill-only transparency for upcoming words

    header = f"""[Script Info]
; Generated by build_captions.py
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 2
ScaledBorderAndShadow: yes
YCbCr Matrix: TV.709

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Caption,{metrics.family},{ass_size},{ass_color('#FFFFFF')},{ass_color(args.accent)},{ass_color('#000000', 0x80)},{ass_color('#000000', 0x50)},-1,0,0,0,100,100,0,0,1,{args.outline},{args.shadow},2,0,0,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = []
    cs = lambda t: int(round(t * 100))
    for gi, g in enumerate(groups):
        next_start = groups[gi + 1][0]["start"] if gi + 1 < len(groups) else None
        g_end = g[-1]["end"] + args.linger
        if next_start is not None:
            g_end = min(g_end, next_start)
        split = wrap(g, max_width, metrics, font_px)
        x, y = round(cx), round(baseline_y)

        for i, w in enumerate(g):
            start = w["start"]
            end = g[i + 1]["start"] if i + 1 < len(g) else g_end
            if cs(end) <= cs(start):
                continue
            text = ""
            for j, other in enumerate(g):
                t = escape(other["text"])
                if j == i:  # active word in accent colour
                    t = f"{{\\c{accent}}}{t}{{\\c{white}}}"
                elif j > i:  # not yet spoken: slightly dimmed
                    t = f"{{\\1a{dim_alpha}}}{t}{{\\1a&H00&}}"
                if j:
                    text += "\\N" if j == split else " "
                text += t

            # entrance on the group's first word: slide up 14px + fade in
            if i == 0:
                tags = f"\\move({x},{y + 14},{x},{y},0,{args.anim_ms})"
            else:
                tags = f"\\pos({x},{y})"
            fade_in = args.anim_ms if i == 0 else 0
            fade_out = min(120, (cs(end) - cs(start)) * 10 // 2) if i == len(g) - 1 else 0
            tags += f"\\blur{args.blur}"
            if fade_in or fade_out:
                tags += f"\\fad({fade_in},{fade_out})"
            lines.append(f"Dialogue: 0,{ass_time(cs(start))},{ass_time(cs(end))},Caption,,0,0,0,,{{{tags}}}{text}")

    with open(args.output, "w", encoding="utf-8") as f:
        f.write(header + "\n".join(lines) + "\n")
    print(f"{len(words)} words -> {len(groups)} caption groups -> {args.output}")
    print(f"Frame {W}x{H}, captions centred at x={round(cx)}, baseline y={round(baseline_y)}, "
          f"max line width {round(max_width)}px, font {metrics.family} {font_px}px (ASS size {ass_size})")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("words", help="Whisper JSON with word timestamps")
    p.add_argument("-o", "--output", default="captions.ass")
    p.add_argument("--video", help="source video (used for resolution + black-bar detection)")
    p.add_argument("--width", type=int, default=1080, help="frame width if --video not given")
    p.add_argument("--height", type=int, default=1920, help="frame height if --video not given")
    p.add_argument("--font", default=DEFAULT_FONT)
    p.add_argument("--font-size", type=float, default=36, help="px (CSS-equivalent em size)")
    p.add_argument("--accent", default="#FACC15", help="highlight colour, e.g. #FACC15 (yellow) or #6366F1 (indigo)")
    p.add_argument("--y-frac", type=float, default=0.86,
                   help="caption baseline as fraction of picture height (0.86 ~= y 1650 on 1920)")
    p.add_argument("--width-frac", type=float, default=0.86, help="max line width as fraction of picture width")
    p.add_argument("--max-words", type=int, default=4, help="max words on screen at once")
    p.add_argument("--max-gap", type=float, default=0.6, help="start a new caption after a pause this long (s)")
    p.add_argument("--linger", type=float, default=0.35, help="keep the last word up this long after it ends (s)")
    p.add_argument("--anim-ms", type=int, default=160, help="entrance animation length")
    p.add_argument("--outline", type=float, default=1.5, help="soft dark edge width (px)")
    p.add_argument("--shadow", type=float, default=3, help="drop shadow offset (px)")
    p.add_argument("--blur", type=float, default=0.8, help="softens outline + shadow edges")
    p.add_argument("--dim", type=float, default=0.15, help="transparency of not-yet-spoken words (0 = off)")
    p.add_argument("--uppercase", action="store_true")
    p.add_argument("--no-autocrop", action="store_true", help="don't detect black bars; use full frame")
    build(p.parse_args())


if __name__ == "__main__":
    main()
