#!/usr/bin/env python3
"""Auto-edit a talking-head clip into a vertical reel, keeping word timings in sync.

  * jump cuts: removes chosen filler words (e.g. "honestly"), extra stutter spans and dead air
  * reframes a pillarboxed 9:16 picture (auto-detected) to fill 1080x1920
  * look: small exposure lift, warmer skin, calmer magenta/pink wall, soft vignette
  * slow punch-ins (100% -> 108%) on chosen words
  * optional desaturated "turn" moment
  * voice: high-pass, light denoise, de-ess, compression, loudness -14 LUFS / -1 dBTP
  * writes the re-timed words JSON so captions/graphics stay locked to the lips

Usage:
  python reel_edit.py input.mov words.json -o reel.mp4 --words-out reel_words.json \\
      --drop-words honestly --cut 32.91-33.04 --punch overcomplicating,professional,clearer
"""
import argparse
import json
import re
import subprocess

import numpy as np

from build_captions import detect_picture_area, load_words, probe_video


def norm(w):
    return re.sub(r"[^a-z0-9']", "", w.lower())


def rms_db(audio, a, b, sr=16000):
    seg = audio[int(a * sr):int(b * sr)]
    return 20 * np.log10(np.sqrt(np.mean(seg ** 2)) + 1e-9) if len(seg) else 0.0


def keep_intervals(words, duration, drop, extra_cuts, max_gap, keep_gap, audio=None, quiet_db=-20.0):
    cuts = []
    for w in words:
        if norm(w["text"]) in drop:
            cuts.append((w["start"], w["end"]))
    for a, b in extra_cuts:
        cuts.append((a, b))
    # dead air between consecutive words
    for a, b in zip(words, words[1:]):
        gap = b["start"] - a["end"]
        if gap > max_gap:
            s0, s1 = a["end"] + keep_gap / 2, b["start"] - keep_gap / 2
            # only real silence: word timings can be estimates, never cut through speech
            if audio is None or rms_db(audio, s0, s1) < quiet_db:
                cuts.append((s0, s1))
    cuts = sorted((max(0, a), min(duration, b)) for a, b in cuts if b - a > 0.03)
    merged = []
    for a, b in cuts:
        if merged and a <= merged[-1][1] + 0.02:
            merged[-1] = (merged[-1][0], max(b, merged[-1][1]))
        else:
            merged.append((a, b))
    keep, t = [], 0.0
    for a, b in merged:
        if a > t:
            keep.append((t, a))
        t = b
    if t < duration:
        keep.append((t, duration))
    return keep, merged


def remap(t, keep):
    """source time -> edited time (times inside a cut snap to the cut point)."""
    out = 0.0
    for a, b in keep:
        if t <= a:
            return out
        if t <= b:
            return out + (t - a)
        out += b - a
    return out


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("video")
    p.add_argument("words")
    p.add_argument("-o", "--output", default="reel.mp4")
    p.add_argument("--words-out", default="reel_words.json")
    p.add_argument("--drop-words", default="", help="comma-separated filler words to cut (e.g. honestly)")
    p.add_argument("--cut", action="append", default=[], help="extra source span to remove, e.g. 32.91-33.04")
    p.add_argument("--max-gap", type=float, default=0.4, help="pauses longer than this get tightened (s)")
    p.add_argument("--keep-gap", type=float, default=0.18, help="pause length left after tightening (s)")
    p.add_argument("--quiet-db", type=float, default=-24.0, help="a pause is only cut if quieter than this (dBFS)")
    p.add_argument("--size", default="1080x1920")
    p.add_argument("--fps", type=int, default=30)
    p.add_argument("--punch", default="", help="comma-separated words that start a slow 100->108%% push-in")
    p.add_argument("--punch-len", type=float, default=3.0)
    p.add_argument("--desat", default="", help="'word1-word2' span to show in black & white (the turn)")
    p.add_argument("--no-look", action="store_true", help="skip colour adjustments")
    p.add_argument("--crf", type=int, default=18)
    args = p.parse_args()

    W, H = map(int, args.size.split("x"))
    words = load_words(args.words)
    duration = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of",
                                     "csv=p=0", args.video], capture_output=True, text=True).stdout)
    drop = {norm(w) for w in args.drop_words.split(",") if w.strip()}
    extra = [tuple(map(float, c.split("-"))) for c in args.cut]
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", args.video, "-ac", "1", "-ar", "16000", "-f", "s16le", "-"],
                         capture_output=True, check=True).stdout
    audio = np.frombuffer(raw, dtype=np.int16).astype(float) / 32768
    keep, cuts = keep_intervals(words, duration, drop, extra, args.max_gap, args.keep_gap, audio, args.quiet_db)

    # re-timed words (dropped words removed)
    new_words = []
    for w in words:
        if norm(w["text"]) in drop:
            continue
        s, e = remap(w["start"], keep), remap(w["end"], keep)
        new_words.append({"word": " " + w["text"], "start": round(s, 3), "end": round(max(e, s + 0.05), 3)})
    total = sum(b - a for a, b in keep)
    json.dump({"language": "en", "source": "reel_edit.py", "segments": [
        {"start": 0, "end": total, "text": " ".join(w["word"].strip() for w in new_words), "words": new_words}]},
        open(args.words_out, "w"), indent=1)

    # ---- video chain ----
    area = detect_picture_area(args.video)
    vw, vh = probe_video(args.video)
    pw, ph, px, py = area if area else (vw, vh, 0, 0)

    parts, labels = [], []
    for i, (a, b) in enumerate(keep):
        d = b - a
        parts.append(f"[0:v]trim={a:.3f}:{b:.3f},setpts=PTS-STARTPTS[v{i}]")
        fade = min(0.012, d / 3)
        parts.append(f"[0:a]atrim={a:.3f}:{b:.3f},asetpts=PTS-STARTPTS,"
                     f"afade=t=in:d={fade:.3f},afade=t=out:st={d - fade:.3f}:d={fade:.3f}[a{i}]")
        labels.append(f"[v{i}][a{i}]")
    parts.append("".join(labels) + f"concat=n={len(keep)}:v=1:a=1[vc][ac]")

    vf = [f"crop={pw}:{ph}:{px}:{py}", f"scale={W}:{H}:flags=lanczos", "setsar=1", f"fps={args.fps}"]
    if not args.no_look:
        vf += ["eq=brightness=0.035:contrast=1.05:saturation=1.04:gamma=1.06",
               "colorbalance=rs=0.02:bs=-0.03:rm=0.035:gm=0.005:bm=-0.03",
               "huesaturation=hue=0:saturation=-0.35:colors=m",  # calmer magenta/pink wall
               "vignette=angle=PI/5:mode=forward"]

    # punch-ins: z ramps 1 -> 1.08 over punch-len after each chosen word, then resets
    punch_words = {norm(w) for w in args.punch.split(",") if w.strip()}
    starts, last = [], -99
    for w in new_words:
        if norm(w["word"]) in punch_words and w["start"] - last > args.punch_len + 1:
            starts.append(w["start"])
            last = w["start"]
    if starts:
        terms = "+".join(f"between(it,{s:.2f},{s + args.punch_len:.2f})*(it-{s:.2f})/{args.punch_len}"
                         for s in starts)
        vf.append(f"zoompan=z='1+0.08*({terms})':x='iw/2-(iw/zoom/2)':y='ih*0.45-(ih/zoom*0.45)'"
                  f":d=1:s={W}x{H}:fps={args.fps}")
    if args.desat:
        a_w, b_w = args.desat.split("-")
        ta = next(w["start"] for w in new_words if norm(w["word"]) == norm(a_w))
        tb = next(w["start"] for w in new_words if norm(w["word"]) == norm(b_w) and w["start"] > ta)
        vf.append(f"hue=s=0.15:enable='between(t,{ta:.2f},{tb:.2f})'")
    parts.append("[vc]" + ",".join(vf) + "[vout]")

    af = ("highpass=f=80,afftdn=nr=10:nf=-45,deesser=i=0.4,"
          "acompressor=threshold=-20dB:ratio=3:attack=8:release=120:makeup=3,"
          "loudnorm=I=-14:TP=-1.0:LRA=8")
    parts.append(f"[ac]{af},aresample=48000[aout]")

    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", args.video, "-filter_complex", ";".join(parts),
           "-map", "[vout]", "-map", "[aout]", "-c:v", "libx264", "-preset", "medium", "-crf", str(args.crf),
           "-pix_fmt", "yuv420p", "-profile:v", "high", "-level", "4.1", "-c:a", "aac", "-b:a", "192k",
           "-movflags", "+faststart", "-map_metadata", "-1", args.output]
    subprocess.run(cmd, check=True)
    print(f"cut {len(cuts)} spans ({duration - total:.2f}s removed): {duration:.2f}s -> {total:.2f}s")
    print(f"punch-ins at: {', '.join(f'{s:.1f}s' for s in starts) or 'none'}")
    print(f"-> {args.output}, re-timed words -> {args.words_out}")


if __name__ == "__main__":
    main()
