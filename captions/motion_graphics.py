#!/usr/bin/env python3
"""Word-anchored motion graphics for a vertical talking-head reel (ASS / libass).

Every element is triggered by a spoken word from the re-timed words JSON, so graphics land
on the beat. Motion language: snappy ease-out pops (~8 frames) with a small overshoot, clean
exits. Palette: white #FFFFFF, gold #FFC83D, coral #FF4D4D, ink #14121F @70%.

Graphics live in the top band (above the face) so they never cover it; captions sit below.
The beat plan below is for the "personal brand / just document" reel; edit BEATS for others.

Usage:
  python motion_graphics.py reel_words.json -o graphics.ass [--captions captions.ass --merge out.ass]
"""
import argparse
import math
import os
import re

from build_captions import FontMetrics, ass_tag_color, ass_time, load_words

HERE = os.path.dirname(os.path.abspath(__file__))
FONTS = os.path.join(HERE, "fonts")
W, H = 1080, 1920

WHITE, GOLD, CORAL, INK = (ass_tag_color(c) for c in ("#FFFFFF", "#FFC83D", "#FF4D4D", "#14121F"))
INK_A = "&H4D&"  # 70% opaque

MONT = FontMetrics(os.path.join(FONTS, "Montserrat-ExtraBold.ttf"))
PLAY = FontMetrics(os.path.join(FONTS, "PlayfairDisplay-BoldItalic.ttf"))
MONO = "DejaVu Sans Mono"


# ---------- word lookup ----------

class Words:
    def __init__(self, path):
        self.w = load_words(path)
        self.norm = [re.sub(r"[^a-z0-9']", "", x["text"].lower()) for x in self.w]

    def at(self, word, nth=1, after=0.0, end=False):
        word = word.lower()
        hits = [i for i, n in enumerate(self.norm) if n == word and self.w[i]["start"] >= after - 1e-6]
        i = hits[nth - 1]
        return self.w[i]["end" if end else "start"]

    @property
    def total(self):
        return self.w[-1]["end"] + 0.6


# ---------- drawing helpers ----------

def rrect(w, h, r):
    r = min(r, h / 2, w / 2)
    k = r * 0.45
    return (f"m {r} 0 l {w - r} 0 b {w - k} 0 {w} {k} {w} {r} l {w} {h - r} b {w} {h - k} {w - k} {h} {w - r} {h} "
            f"l {r} {h} b {k} {h} 0 {h - k} 0 {h - r} l 0 {r} b 0 {k} {k} 0 {r} 0").replace(".0 ", " ")


def poly(points):
    pts = [(round(x), round(y)) for x, y in points]
    return f"m {pts[0][0]} {pts[0][1]} l " + " ".join(f"{x} {y}" for x, y in pts[1:])


def stroke(points, width):
    """open polyline -> filled polygon of the given width (ASS has no strokes on open paths)."""
    left, right = [], []
    for i, (x, y) in enumerate(points):
        x0, y0 = points[max(i - 1, 0)]
        x1, y1 = points[min(i + 1, len(points) - 1)]
        dx, dy = x1 - x0, y1 - y0
        L = math.hypot(dx, dy) or 1
        nx, ny = -dy / L * width / 2, dx / L * width / 2
        left.append((x + nx, y + ny))
        right.append((x - nx, y - ny))
    return poly(left + right[::-1])


def star(r_out, r_in, n=5):
    pts = []
    for k in range(n * 2):
        r = r_out if k % 2 == 0 else r_in
        a = math.radians(-90 + k * 180 / n)
        pts.append((r_out + r * math.cos(a), r_out + r * math.sin(a)))
    return poly(pts)


def x_mark(s, t):
    """an X made of two bars, size s, bar thickness t."""
    c, h = s / 2, t / 2
    a = [(-c, -c + h * 1.4), (-c + h * 1.4, -c), (c, c - h * 1.4), (c - h * 1.4, c)]
    b = [(c - h * 1.4, -c), (c, -c + h * 1.4), (-c + h * 1.4, c), (-c, c - h * 1.4)]
    sh = lambda pts: [(x + c, y + c) for x, y in pts]
    return poly(sh(a)) + " " + poly(sh(b))


def fs(metrics, px):
    return round(px * metrics.libass_ratio, 1)


# ---------- motion ----------

def pop(scale_from=55, over=106, ms_in=170, ms_settle=100):
    return (f"\\fscx{scale_from}\\fscy{scale_from}\\alpha&HFF&"
            f"\\t(0,{ms_in // 2},\\alpha&H00&)\\t(0,{ms_in},0.6,\\fscx{over}\\fscy{over})"
            f"\\t({ms_in},{ms_in + ms_settle},\\fscx100\\fscy100)")


def out(dur_ms, ms=130):
    a = max(0, dur_ms - ms)
    return f"\\t({a},{dur_ms},1.6,\\fscx70\\fscy70\\alpha&HFF&)"


class Comp:
    def __init__(self):
        self.lines = []

    def add(self, layer, t0, t1, tags, body, style="G"):
        a, b = int(round(t0 * 100)), int(round(t1 * 100))
        if b > a:
            self.lines.append(f"Dialogue: {layer},{ass_time(a)},{ass_time(b)},{style},,0,0,0,,{{{tags}}}{body}")

    def shape(self, layer, t0, t1, x, y, path, colour, alpha="&H00&", extra="", an=5):
        self.add(layer, t0, t1, f"\\an{an}\\pos({round(x)},{round(y)})\\p1\\bord0\\shad0\\1c{colour}\\1a{alpha}{extra}",
                 path + "{\\p0}")

    def text(self, layer, t0, t1, x, y, txt, font, px, colour=WHITE, extra="", an=5, bord=0, shad=0, ital=False):
        f = f"\\fn{font.family}" if isinstance(font, FontMetrics) else f"\\fn{font}"
        size = fs(font, px) if isinstance(font, FontMetrics) else round(px * 1.17, 1)
        style = "\\b1\\i1" if ital else ""
        self.add(layer, t0, t1, f"\\an{an}\\pos({round(x)},{round(y)}){f}{style}\\fs{size}\\1c{colour}"
                                f"\\bord{bord}\\3c{INK}\\shad{shad}\\4c{INK}\\4a&H80&{extra}", txt)


def pill(c, t0, t1, x, y, label, px=30, fg=WHITE, bg=INK, bg_a=INK_A, dot=None, motion_in=True, extra_out=""):
    w = MONT.width(label, px) + 52 + (26 if dot else 0)
    h = px * 2.1
    dur = int((t1 - t0) * 1000)
    m = (pop() if motion_in else "") + (extra_out or out(dur))
    c.shape(3, t0, t1, x, y, rrect(w, h, h / 2), bg, bg_a, m)
    tx = x + (13 if dot else 0)
    c.text(4, t0, t1, tx, y + 1, label, MONT, px, fg, m)
    if dot:
        c.shape(4, t0, t1, x - w / 2 + 30, y, rrect(14, 14, 7), dot, "&H00&", m)
    return w


# ---------- the beat plan ----------

def build(words, c, handle):
    T = words.total

    # global: thin gold progress bar along the top edge
    c.shape(6, 0, T, 0, 14, rrect(W, 8, 4), WHITE, "&HC0&", an=7)
    c.shape(7, 0, T, 0, 14, rrect(W, 8, 4), GOLD, "&H00&", f"\\fscx0\\t(0,{int(T * 1000)},\\fscx100)", an=7)

    # 1) HOOK: title card + scribble + name tag
    t0, t1 = 0.05, words.at("overcomplicating", end=True) + 0.9
    dur = int((t1 - t0) * 1000)
    c.shape(3, t0, t1, 540, 300, rrect(940, 250, 34), INK, INK_A, pop() + out(dur))
    big = min(82, 860 / MONT.width("OVERCOMPLICATING", 1))
    title = (f"{{\\fn{MONT.family}\\fs{fs(MONT, 46)}\\1c{WHITE}}}I WAS\\N"
             f"{{\\fs{fs(MONT, big)}\\1c{GOLD}}}OVERCOMPLICATING\\N"
             f"{{\\fn{PLAY.family}\\b1\\i1\\fs{fs(PLAY, 60)}\\1c{WHITE}}}my personal brand")
    c.add(4, t0, t1, f"\\an5\\pos(540,300)\\bord0\\shad0\\q2{pop()}{out(dur)}", title)
    # hand-drawn tangle that draws on under the card
    pts = []
    for k in range(120):
        u = k / 119
        pts.append((150 + 780 * u + 38 * math.sin(u * 23), 438 + 12 * math.sin(u * 31) + 9 * math.cos(u * 47)))
    c.shape(4, t0 + 0.25, t1, 0, 0, stroke(pts, 5), GOLD, "&H00&",
            f"\\clip(0,0,0,{H})\\t(0,700,\\clip(0,0,{W},{H})){out(dur - 250)}", an=7)
    tn = 2.0
    pill(c, tn, t1, 540, 488 + 0, handle, px=24, fg=WHITE, dot=GOLD)

    # 2) THE LIST: chips on each spoken item, 2 per row in the top band
    items = [("Video editing", "video", 1), ("Positioning", "positioning", 1), ("Content creation", "creating", 1),
             ("Content pillars", "pillars", 1), ("AI automation", "ai", 1), ("LinkedIn growth", "linkedin", 1)]
    collapse = words.at("things", 1, after=words.at("linkedin"))
    grid = [(290, 205), (790, 205), (290, 300), (790, 300), (290, 395), (790, 395)]
    for (label, anchor, n), (x, y) in zip(items, grid):
        s = words.at(anchor, n)
        d = int((collapse + 0.22 - s) * 1000)
        exit_ = (f"\\t({d - 220},{d},1.8,\\fscx20\\fscy20\\frz{(-1) ** int(x > 540) * 40}\\alpha&HFF&)")
        pill(c, s, collapse + 0.22, x, y, label, px=34, dot=GOLD, extra_out=exit_)
    # TOO MUCH stamp slams in coral with a tiny shake
    s, e = collapse + 0.12, collapse + 1.5
    d = int((e - s) * 1000)
    slam = ("\\frz-8\\fscx260\\fscy260\\alpha&HFF&\\t(0,110,\\fscx94\\fscy94\\alpha&H00&)"
            "\\t(110,180,\\fscx100\\fscy100)\\t(180,220,\\frz-11)\\t(220,260,\\frz-5)\\t(260,300,\\frz-8)" + out(d))
    w = MONT.width("TOO MUCH", 84) + 60
    c.shape(4, s, e, 540, 300, rrect(w, 130, 18), CORAL, "&H00&", slam)
    c.shape(4, s, e, 540, 300, rrect(w - 16, 114, 12), INK, "&H00&", slam)
    c.text(5, s, e, 540, 302, "TOO MUCH", MONT, 84, CORAL, slam)

    # 3) THE MYTHS: four cards, each crossed out with a coral X
    myths = [("Look professional", "professional", 1), ("More polished videos", "polished", 1),
             ("Perfect positioning", "perfect", 1), ("Look experienced", "experienced", 1)]
    end_myths = words.at("content", 1, after=words.at("experienced")) + 0.5
    grid = [(290, 225), (790, 225), (290, 365), (790, 365)]
    for (label, anchor, n), (x, y) in zip(myths, grid):
        s = words.at(anchor, n)
        d = int((end_myths - s) * 1000)
        cw = pill(c, s, end_myths, x, y, label, px=31, extra_out=out(d))
        xs = s + 0.3
        dx = int((end_myths - xs) * 1000)
        stamp = ("\\frz-12\\fscx240\\fscy240\\alpha&HFF&\\t(0,100,\\fscx92\\fscy92\\alpha&H00&)"
                 "\\t(100,170,\\fscx100\\fscy100)" + out(dx))
        c.shape(5, xs, end_myths, x + cw / 2 + 2, y - 24, x_mark(54, 13), CORAL, "&H00&", stamp)
    # gold underline sweep under the "worst mistake" caption (big line sits at 78% height)
    s = words.at("worst")
    e = words.at("thought", 1, after=s)
    uw = min(PLAY.width("worst mistake", 124 * 1.05), 1080 * 0.86)
    c.shape(2, s + 0.1, e, 540 - uw / 2, 1498 + 22, rrect(uw, 10, 5), GOLD, "&H00&",
            f"\\clip(0,0,{round(540 - uw / 2)},{H})\\t(0,260,0.5,\\clip(0,0,{W},{H}))", an=7)

    # 4) THE TURN: "...one thing." while the picture goes black & white
    s, e = words.at("forgot"), words.at("people")
    d = int((e - s) * 1000)
    c.text(5, s + 0.1, e, 540, 300, "…one thing.", PLAY, 96, GOLD, pop(70, 104) + out(d - 100), ital=True,
           bord=3, shad=3)

    # 5) FEEDBACK: comment bubbles float up, then turn into gold sparks ("nuggets")
    nug = words.at("nuggets")
    bubbles = [("Try this", "suggest", 300, 330), ("Fix this", "opinions", 780, 260),
               ("Have you thought of…?", "correct", 560, 390)]
    for label, anchor, x, y in bubbles:
        s = words.at(anchor, 1, after=words.at("people"))
        d = int((nug - s) * 1000)
        bw = MONT.width(label, 28) + 50
        float_ = f"\\move({x},{y + 30},{x},{y - 25},0,{d})"
        gone = f"\\t({d - 120},{d},\\fscx10\\fscy10\\alpha&HFF&)"
        c.add(3, s, nug, f"\\an5{float_}\\p1\\bord0\\shad2\\4c{INK}\\4a&H90&\\1c{WHITE}{pop()}{gone}",
              rrect(bw, 62, 22) + f" m {bw * 0.25} 60 l {bw * 0.25 + 26} 60 l {bw * 0.22} 80" + "{\\p0}")
        c.add(4, s, nug, f"\\an5{float_}\\fn{MONT.family}\\fs{fs(MONT, 28)}\\1c{INK}\\bord0\\shad0{pop()}{gone}", label)
        # spark
        c.shape(5, nug, nug + 1.0, x, y - 25, star(26, 10), GOLD, "&H00&",
                "\\fscx0\\fscy0\\frz-40\\t(0,180,\\fscx120\\fscy120\\frz0)\\t(180,260,\\fscx100\\fscy100)"
                "\\t(260,1000,\\frz30)\\t(700,1000,\\alpha&HFF&)")

    # 6) GROWTH: XP counters in the top-left corner
    there = words.at("there", 1, after=nug)
    for k, (label, anchor, n, after) in enumerate([("+1 SKILLS", "skills", 1, 0), ("+1 OPINIONS", "opinions", 1, nug),
                                                     ("+1 LEARNING", "learn", 1, nug)]):
        s = words.at(anchor, n, after=after)
        e = there
        w = MONT.width(label, 26) + 44
        d = int((e - s) * 1000)
        m = pop(40, 112) + out(d)
        c.shape(3, s, e, 70 + w / 2, 200 + k * 64, rrect(w, 52, 26), GOLD, "&H00&", m)
        c.text(4, s, e, 70 + w / 2, 201 + k * 64, label, MONT, 26, INK, m)

    # 7) THE PAYOFF: line chart draws in; "POSITIONING" pulls into focus on "clearer"
    s = there
    e = words.at("content", 1, after=words.at("own")) + 0.5
    d = int((e - s) * 1000)
    clr = int((words.at("clearer") - s) * 1000)
    x0, x1, yb, yt = 160, 930, 410, 190
    c.shape(3, s, e, 540, 300, rrect(940, 270, 28), INK, INK_A, pop() + out(d))
    c.shape(4, s, e, x0, yb, rrect(x1 - x0, 4, 2), WHITE, "&H40&", pop() + out(d), an=4)
    c.shape(4, s, e, x0, yb, rrect(4, yb - yt, 2), WHITE, "&H40&", pop() + out(d), an=1)
    c.text(4, s, e, x1, yb + 24, "time documenting →", MONT, 20, WHITE, out(d), an=6)
    c.text(4, s, e, x0 + 14, yt - 4, "positioning clarity", MONT, 20, WHITE, out(d), an=7)
    pts = []
    for k in range(60):
        u = k / 59
        pts.append((x0 + 10 + (x1 - x0 - 20) * u, yb - 14 - (yb - yt - 40) * (u ** 1.6) + 10 * math.sin(u * 9) * (1 - u)))
    c.shape(5, s + 0.2, e, 0, 0, stroke(pts, 7), GOLD, "&H00&",
            f"\\clip(0,0,{x0},{H})\\t(0,{int(d * 0.8)},\\clip(0,0,{x1 + 10},{H})){out(d - 200)}", an=7)
    c.text(5, s, e, 620, 285, "POSITIONING", MONT, 54, WHITE,
           f"\\blur14\\alpha&H70&\\t({clr},{clr + 320},\\blur0\\alpha&H00&){out(d)}")

    # 8) PROOF: lab-notebook log types in line by line
    s = words.at("documenting", 1, after=words.at("own"))
    e = words.at("created") - 0.05
    d = int((e - s) * 1000)
    c.shape(3, s, e, 540, 300, rrect(860, 270, 22), INK, "&H33&", pop() + out(d))
    c.text(4, s, e, 140, 192, "EXPERIMENT LOG · DAY 01", MONO, 22, GOLD, out(d), an=4)
    rows = [("› learning", "learning", WHITE), ("› testing", "testing", WHITE), ("✓ what works", "works", GOLD),
            ("✗ what doesn't", "doesn't", CORAL), ("› building", "building", WHITE)]
    for k, (label, anchor, col) in enumerate(rows):
        t = words.at(anchor, 1, after=s)
        dd = int((e - t) * 1000)
        typed = "".join(f"{{\\alpha&HFF&\\t({j * 28},{j * 28 + 1},\\alpha&H00&)}}{ch}" for j, ch in enumerate(label))
        c.add(4, t, e, f"\\an4\\pos(150,{236 + k * 41})\\fn{MONO}\\fs{round(32 * 1.17, 1)}\\1c{col}\\bord0\\shad0"
                       f"{out(dd)}", typed)

    # 9) THE OFFER: tracker mockup card with a slight 3D tilt
    s, e = words.at("created"), words.at("comment")
    d = int((e - s) * 1000)
    tilt = f"\\fry-10\\frx6\\org(540,300){pop(60, 104)}\\t(300,{d},\\fry8){out(d)}"
    c.shape(3, s, e, 540, 300, rrect(760, 260, 26), WHITE, "&H00&", tilt)
    c.shape(4, s, e, 540, 196, rrect(760, 52, 26), GOLD, "&H00&", tilt)
    c.text(5, s, e, 540, 198, "PERSONAL BRAND EXPERIMENT TRACKER", MONT, 24, INK, tilt)
    for k, (lbl, done) in enumerate([("Hypothesis", True), ("What I posted", True), ("What worked", False)]):
        y = 262 + k * 52
        c.shape(5, s, e, 230, y, rrect(28, 28, 6), INK if done else WHITE, "&H00&",
                tilt + ("" if done else "\\bord3\\3c" + INK))
        c.text(5, s, e, 266, y, lbl, MONT, 24, INK, tilt, an=4)
        c.shape(5, s, e, 690, y, rrect(180, 14, 7), INK, "&HB0&", tilt)

    # 10) CTA: comment bubble types "personal branding", button pulses twice
    s, e = words.at("comment"), words.total
    d = int((e - s) * 1000)
    c.add(3, s, e, f"\\an5\\pos(540,320)\\p1\\bord0\\shad3\\4c{INK}\\4a&H80&\\1c{WHITE}{pop()}",
          rrect(720, 120, 30) + " m 150 118 l 196 118 l 130 156{\\p0}")
    typed = "".join(f"{{\\alpha&HFF&\\t({200 + j * 45},{201 + j * 45},\\alpha&H00&)}}{ch}"
                    for j, ch in enumerate("personal branding"))
    c.add(4, s, e, f"\\an4\\pos(220,320)\\fn{MONT.family}\\fs{fs(MONT, 46)}\\1c{INK}\\bord0\\shad0", typed)
    pulse = (f"{pop()}\\t(900,1050,\\fscx112\\fscy112)\\t(1050,1200,\\fscx100\\fscy100)"
             f"\\t(1350,1500,\\fscx112\\fscy112)\\t(1500,1650,\\fscx100\\fscy100)")
    c.shape(4, s + 0.15, e, 540, 210, rrect(250, 64, 32), GOLD, "&H00&", pulse)
    c.text(5, s + 0.15, e, 540, 212, "COMMENT", MONT, 30, INK, pulse)


HEADER = f"""[Script Info]
; Generated by motion_graphics.py
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 2
ScaledBorderAndShadow: yes
YCbCr Matrix: TV.709

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: G,{MONT.family},40,&H00FFFFFF,&H00FFFFFF,&H001F1214,&H80000000,0,0,0,0,100,100,0,0,1,0,0,5,0,0,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("words")
    p.add_argument("-o", "--output", default="graphics.ass")
    p.add_argument("--handle", default="Harshitha V.", help="name tag text, e.g. 'Harshitha V. | @yourhandle'")
    p.add_argument("--captions", help="captions .ass to merge with (styles + events are combined)")
    p.add_argument("--merge", help="write the merged captions+graphics .ass here")
    args = p.parse_args()

    c = Comp()
    build(Words(args.words), c, args.handle)
    open(args.output, "w", encoding="utf-8").write(HEADER + "\n".join(c.lines) + "\n")
    print(f"{len(c.lines)} graphic events -> {args.output}")

    if args.captions and args.merge:
        cap = open(args.captions, encoding="utf-8").read()
        style_g = [l for l in HEADER.splitlines() if l.startswith("Style: G,")][0]
        cap = cap.replace("\n\n[Events]", "\n" + style_g + "\n\n[Events]", 1)
        open(args.merge, "w", encoding="utf-8").write(cap.rstrip("\n") + "\n" + "\n".join(c.lines) + "\n")
        print(f"captions + graphics -> {args.merge}")


if __name__ == "__main__":
    main()
