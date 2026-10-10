#!/usr/bin/env python3
"""Reel-style stacked captions: small words on top, one BIG bold word below — revealed word by word.

    steal my favourite        <- small (Poppins Medium); each word pops in as it is spoken
    fonts                     <- BIG (Poppins ExtraBold); bounces in on its word

Each caption group ends on a "punch" word (a content word, or a phrase like "personal brand")
that becomes the big line. Key moments get motion graphics: the big word turns the accent
colour and a burst of stars/sparkles pops around it.

Input is Whisper-style word JSON (from transcribe.py or align_script.py).

Usage:
  python build_stacked_captions.py words.json --video input.mp4 -o captions.ass
"""
import argparse
import math
import os
import re

from fontTools.ttLib import TTFont

from build_captions import (FontMetrics, ass_color, ass_tag_color, ass_time, detect_picture_area, escape,
                            load_words, probe_video)

HERE = os.path.dirname(os.path.abspath(__file__))
FONTS = os.path.join(HERE, "fonts")

STOP = set("""a an the and or but so if as at by for from in into of on onto to with without about over under
i me my mine you your yours we our us he she it its they them their this that these those there here
am is are was were be been being have has had do does did will would can could should shall may might must
what which who whom when where why how all any some more most just very really also too not no yes
because while than then out up down off again once only own same such each both few other actually honestly
get gets got go going thing""".split())

# multi-word punches shown together on the big line
PHRASES = ["personal branding", "personal brand", "video editing", "content pillars", "ai automation",
           "linkedin growth", "worst mistake", "experiment tracker", "polished videos", "perfect position",
           "create content", "own content"]

# punch words that get the accent colour + star burst
DEFAULT_KEYWORDS = ["overcomplicating", "professional", "worst mistake", "experienced", "documenting", "nuggets",
                    "personal brand", "personal branding", "clearer", "experiment tracker", "comment", "learn",
                    "skills", "testing", "linkedin growth", "ai automation", "opinions", "journey"]

KEEP_CASE = {"ai": "AI"}


def clean(word):
    return re.sub(r"[^\w'’-]", "", word)


def display(text, uppercase):
    words = [KEEP_CASE.get(w.lower(), w.lower()) for w in text.split()]
    out = " ".join(words)
    return out.upper() if uppercase else out


# ---------- grouping ----------

def group_words(words, min_top, max_top, max_gap, keywords=()):
    """-> list of {"top": [word...], "big": [word...]}.

    Small words build up on the top line; the group closes on a punch word (a content word or a
    phrase from PHRASES) once at least `min_top` small words are showing, at a clause break,
    at a pause, or when the top line is full.
    """
    toks = [clean(w["text"]).lower() for w in words]
    groups, top, i = [], [], 0
    while i < len(words):
        phrase = next((p.split() for p in PHRASES if toks[i:i + len(p.split())] == p.split()), None)
        n = len(phrase) if phrase else 1
        last = i + n - 1
        w, t = words[last], toks[last]
        gap_after = words[last + 1]["start"] - w["end"] if last + 1 < len(words) else 9
        is_content = bool(phrase) or (t not in STOP and len(t) >= 4)
        ends_clause = bool(re.search(r"[.,!?;:]$", w["text"]))
        need = 0 if phrase and " ".join(toks[i:i + n]) in keywords else 1 if phrase else min_top
        close = (is_content and len(top) >= need) \
            or len(top) >= max_top or last == len(words) - 1 \
            or ((ends_clause or gap_after > max_gap) and (is_content or top))
        if close:
            groups.append({"top": top, "big": words[i:i + n]})
            top = []
        else:
            top += words[i:i + n]
        i += n
    return groups


# ---------- motion graphics ----------

def star_path(r_out, r_in, points=5, rot=-90):
    pts = []
    for k in range(points * 2):
        r = r_out if k % 2 == 0 else r_in
        a = math.radians(rot + k * 180 / points)
        pts.append((round(r_out + r * math.cos(a)), round(r_out + r * math.sin(a))))
    return "m {} {} ".format(*pts[0]) + "l " + " ".join(f"{x} {y}" for x, y in pts[1:])


def burst(x0, x1, y_top, y_bot, start_cs, end_cs, palette, seed, bounds):
    """3–4 stars/sparkles around the big word's box, popping in staggered then spinning gently."""
    spots = [(x0 - 34, y_top + 6, 30, 5, 0), (x1 + 30, y_top - 4, 22, 4, 1), (x1 + 18, y_bot - 14, 16, 5, 2),
             (x0 - 18, y_bot - 6, 14, 4, 3)]
    if seed % 2:
        spots = spots[:3]
    lines = []
    lo, hi = bounds
    for n, (x, y, size, pts, k) in enumerate(spots):
        if not lo + size <= x <= hi - size:  # keep stars inside the picture: tuck them above the word
            x = min(max(x, lo + size + 6), hi - size - 6)
            y -= 46
        col = palette[(seed + n) % len(palette)]
        inner = 0.42 if pts == 5 else 0.28
        delay = 40 + n * 70
        dur = (end_cs - start_cs) * 10
        spin = 25 if (seed + n) % 2 else -25
        tags = (f"\\an5\\pos({round(x)},{round(y)})\\p1\\bord0\\shad0\\blur0.6\\1c{col}"
                f"\\fscx0\\fscy0\\frz{-spin * 2}"
                f"\\t({delay},{delay + 220},\\fscx115\\fscy115\\frz0)"
                f"\\t({delay + 220},{delay + 320},\\fscx100\\fscy100)"
                f"\\t({delay + 320},{max(dur, delay + 400)},\\frz{spin})\\fad(0,150)")
        lines.append(f"Dialogue: 2,{ass_time(start_cs)},{ass_time(end_cs)},Star,,0,0,0,,"
                     f"{{{tags}}}{star_path(size, size * inner, pts)}{{\\p0}}")
    return lines


# ---------- build ----------

def build(args):
    W, H = probe_video(args.video) if args.video else (args.width, args.height)
    area = detect_picture_area(args.video) if args.video and not args.no_autocrop else None
    pw, ph, px0, py0 = area if area else (W, H, 0, 0)
    cx = px0 + pw / 2
    max_w = pw * args.width_frac

    top_m = FontMetrics(os.path.join(FONTS, "Poppins-Medium.ttf"))
    big_m = FontMetrics(os.path.join(FONTS, "Poppins-ExtraBold.ttf"))
    emph_file = os.path.join(FONTS, args.emph_font) if args.emph_font else None
    emph_m = FontMetrics(emph_file) if emph_file else None
    m_desc = {}
    for m, f in ((top_m, "Poppins-Medium.ttf"), (big_m, "Poppins-ExtraBold.ttf")) + \
            (((emph_m, args.emph_font),) if emph_m else ()):
        t = TTFont(os.path.join(FONTS, f))
        m_desc[m] = t["OS/2"].usWinDescent / t["head"].unitsPerEm      # baseline offset per px
        m.ascent = t["OS/2"].sTypoAscender / t["head"].unitsPerEm * 0.72  # lowercase ascender ≈ 0.72 em

    words = load_words(args.words)
    keywords = set(k.strip().lower() for k in (args.keywords.split(",") if args.keywords else DEFAULT_KEYWORDS))
    groups = group_words(words, args.min_top, args.max_top, args.max_gap, keywords)

    white, accent = ass_tag_color("#FFFFFF"), ass_tag_color(args.accent)
    palette = [ass_tag_color(c) for c in args.star_colors.split(",")]
    base_y = py0 + ph * args.y_frac  # baseline of the big word

    header = f"""[Script Info]
; Generated by build_stacked_captions.py
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 2
ScaledBorderAndShadow: yes
YCbCr Matrix: TV.709

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Top,{top_m.family},{round(args.top_size * top_m.libass_ratio, 1)},{ass_color('#FFFFFF')},{ass_color('#FFFFFF')},{ass_color(args.ink, args.ink_alpha)},{ass_color(args.ink, 0x70)},0,0,0,0,100,100,0,0,1,{args.top_outline},2,2,0,0,0,1
Style: Big,{big_m.family},{round(args.big_size * big_m.libass_ratio, 1)},{ass_color('#FFFFFF')},{ass_color('#FFFFFF')},{ass_color(args.ink, args.ink_alpha)},{ass_color(args.ink, 0x60)},0,0,0,0,100,100,-1,0,1,{args.big_outline},4,2,0,0,0,1
Style: Star,{big_m.family},20,{ass_color('#FDE047')},{ass_color('#FDE047')},{ass_color('#000000', 0xFF)},{ass_color('#000000', 0xFF)},0,0,0,0,100,100,0,0,1,0,0,5,0,0,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    cs = lambda t: int(round(t * 100))
    lines, last_burst, n_burst = [], -99, 0
    for gi, g in enumerate(groups):
        first = (g["top"] or g["big"])[0]
        start = first["start"]
        nxt = groups[gi + 1] if gi + 1 < len(groups) else None
        end = (nxt["top"] or nxt["big"])[0]["start"] if nxt else g["big"][-1]["end"] + args.linger
        end = min(end, g["big"][-1]["end"] + args.max_hold)
        s_cs, e_cs = cs(start), cs(end)
        if e_cs <= s_cs:
            continue

        big_text = display(" ".join(clean(w["text"]) for w in g["big"]), args.uppercase)
        key = big_text.lower() in keywords
        bm = emph_m if (key and emph_m) else big_m
        size = args.big_size * (args.emph_scale if bm is emph_m else 1)
        # fit the big line to the picture width
        big_px = min(size, max_w / max(bm.width(big_text, 1), 1e-6))
        big_fs = round(big_px * bm.libass_ratio, 1)
        big_w = bm.width(big_text, big_px)
        big_y = round(base_y + m_desc[bm] * big_px)          # \an2 anchors the bottom of the line box
        big_top = base_y - bm.ascent * big_px
        fade = 120

        # --- small top line, words revealed one by one ---
        if g["top"]:
            top_words = [display(clean(w["text"]), args.uppercase) for w in g["top"]]
            top_px = min(args.top_size, max_w / max(top_m.width(" ".join(top_words), 1), 1e-6))
            top_y = round(big_top - args.gap + m_desc[top_m] * top_px)
            parts = []
            for w, t in zip(g["top"], top_words):
                o = max(0, (cs(w["start"]) - s_cs) * 10)
                parts.append(f"{{\\alpha&HFF&\\fscy55\\t({o},{o + 130},\\alpha&H00&\\fscy100)}}{escape(t)}")
            tags = f"\\pos({round(cx)},{top_y})\\fs{round(top_px * top_m.libass_ratio, 1)}\\blur1.2\\fad(0,{fade})"
            lines.append(f"Dialogue: 1,{ass_time(s_cs)},{ass_time(e_cs)},Top,,0,0,0,,{{{tags}}}" + " ".join(parts))

        # --- BIG punch word, bounces in on its own timestamp ---
        b_cs = max(s_cs, cs(g["big"][0]["start"]))
        colour = f"\\1c{accent}" if key else ""
        font = f"\\fn{bm.family}\\b1\\i1" if bm is emph_m else ""
        tags = (f"\\pos({round(cx)},{big_y}){font}\\fs{big_fs}{colour}\\blur1.5"
                f"\\fscx45\\fscy45\\alpha&H60&"
                f"\\t(0,120,\\fscx112\\fscy112\\alpha&H00&)\\t(120,230,\\fscx100\\fscy100)\\fad(0,{fade})")
        if e_cs > b_cs:
            lines.append(f"Dialogue: 1,{ass_time(b_cs)},{ass_time(e_cs)},Big,,0,0,0,,{{{tags}}}{escape(big_text)}")

        # --- motion graphics on key moments ---
        if key and not args.no_stars and start - last_burst >= args.burst_gap and e_cs - b_cs > 40:
            lines += burst(cx - big_w / 2, cx + big_w / 2, big_top, base_y, b_cs, e_cs, palette, n_burst,
                           (px0, px0 + pw))
            last_burst, n_burst = start, n_burst + 1

    with open(args.output, "w", encoding="utf-8") as f:
        f.write(header + "\n".join(lines) + "\n")
    print(f"{len(words)} words -> {len(groups)} stacked captions, {n_burst} star bursts -> {args.output}")
    if area and (pw, ph) != (W, H):
        print(f"Picture area {pw}x{ph} at x={px0}; captions centred at x={round(cx)}, big baseline y={round(base_y)}")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("words", help="Whisper-style word JSON")
    p.add_argument("-o", "--output", default="captions.ass")
    p.add_argument("--video")
    p.add_argument("--width", type=int, default=1080)
    p.add_argument("--height", type=int, default=1920)
    p.add_argument("--top-size", type=float, default=40, help="small line size, px")
    p.add_argument("--big-size", type=float, default=118, help="big word max size, px (auto-shrinks to fit)")
    p.add_argument("--gap", type=float, default=14, help="space between small line and big word, px")
    p.add_argument("--y-frac", type=float, default=0.84, help="big word baseline, fraction of picture height")
    p.add_argument("--width-frac", type=float, default=0.88)
    p.add_argument("--min-top", type=int, default=2, help="small words to show before a punch word")
    p.add_argument("--max-top", type=int, default=6, help="max small words before forcing a punch")
    p.add_argument("--max-gap", type=float, default=0.5, help="pause that ends a caption (s)")
    p.add_argument("--linger", type=float, default=0.4)
    p.add_argument("--max-hold", type=float, default=1.2, help="longest a caption stays after its last word (s)")
    p.add_argument("--accent", default="#FDE047", help="colour of key big words")
    p.add_argument("--star-colors", default="#FDE047,#F9A8D4,#FFFFFF")
    p.add_argument("--keywords", help="comma-separated punch words that get accent + stars")
    p.add_argument("--burst-gap", type=float, default=2.5, help="min seconds between star bursts")
    p.add_argument("--no-stars", action="store_true")
    p.add_argument("--emph-font", help="font file in fonts/ for key words, e.g. PlayfairDisplay-BoldItalic.ttf")
    p.add_argument("--emph-scale", type=float, default=1.05, help="size multiplier for the emphasis font")
    p.add_argument("--ink", default="#000000", help="outline/shadow colour")
    p.add_argument("--ink-alpha", type=lambda x: int(x, 0), default=0xA0, help="outline transparency 0x00-0xFF")
    p.add_argument("--top-outline", type=float, default=2)
    p.add_argument("--big-outline", type=float, default=2.5)
    p.add_argument("--uppercase", action="store_true")
    p.add_argument("--no-autocrop", action="store_true")
    build(p.parse_args())


if __name__ == "__main__":
    main()
