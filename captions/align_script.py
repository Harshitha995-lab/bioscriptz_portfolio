#!/usr/bin/env python3
"""Time a known script to the audio, without Whisper (works fully offline).

Use this when you already have the transcript (e.g. a .docx/.txt exported from Premiere,
Descript or Resolve) but can't run Whisper. Timings come from the audio itself:

  1. syllable beats ("nuclei") are detected from the voice energy envelope,
  2. each word's syllable count comes from the CMU pronouncing dictionary,
  3. sentence/comma breaks in the script are snapped to real pauses in the audio,
  4. between those anchors, syllables are spread across the detected beats.

Expect word timing within roughly +-0.2 s — good for word-by-word captions; Whisper is more exact.
Timestamps like "(00:05)" and a leading title line in the transcript are ignored, so a clip
that was sped up or re-cut after transcription still lines up.

Output is Whisper-style JSON, so it plugs straight into build_captions.py / build_stacked_captions.py.

Usage:
  python align_script.py video.mp4 transcript.docx -o words.json
"""
import argparse
import json
import re
import subprocess
import zipfile

import numpy as np
from scipy.signal import butter, find_peaks, sosfiltfilt

SR = 16000
VOWELS = ("AA", "AE", "AH", "AO", "AW", "AY", "EH", "ER", "EY", "IH", "IY", "OW", "OY", "UH", "UW")


# ---------- inputs ----------

def read_transcript(path):
    if path.lower().endswith(".docx"):
        xml = zipfile.ZipFile(path).read("word/document.xml").decode("utf-8")
        paras = ["".join(re.findall(r"<w:t[^>]*>([^<]*)</w:t>", p))
                 for p in re.findall(r"<w:p[ >].*?</w:p>", xml, re.S)]
    else:
        paras = open(path, encoding="utf-8").read().splitlines()
    timed = [p for p in paras if re.match(r"\s*\(\d+:\d+(:\d+)?\)", p)]
    if timed:  # timestamped transcript: drop the title line and the stamps
        paras = [re.sub(r"^\s*\(\d+:\d+(:\d+)?\)\s*", "", p) for p in timed]
    return " ".join(p.strip() for p in paras if p.strip())


def load_audio(video):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", video, "-ac", "1", "-ar", str(SR), "-f", "s16le", "-"],
                         capture_output=True, check=True).stdout
    return np.frombuffer(raw, dtype=np.int16).astype(float) / 32768


def syllable_dict(extra):
    try:
        from pocketsphinx import get_model_path
        path = get_model_path() + "/en-us/cmudict-en-us.dict"
    except ImportError:
        path = None
    d = {}
    if path:
        for line in open(path, encoding="utf-8"):
            parts = line.split()
            if "(" in parts[0]:
                continue
            d[parts[0]] = max(1, sum(1 for ph in parts[1:] if ph[:2] in VOWELS))
    d.update(extra)
    return d


def guess_syllables(word):
    groups = re.findall(r"[aeiouy]+", word.lower())
    n = len(groups) - (1 if word.lower().endswith("e") and len(groups) > 1 else 0)
    return max(1, n)


# ---------- audio analysis ----------

def analyse(audio, pause_db, min_pause):
    sos = butter(4, [300, 2500], btype="band", fs=SR, output="sos")
    band = sosfiltfilt(sos, audio)
    hop = SR // 100
    n = len(band) // hop
    env = np.sqrt((band[:n * hop].reshape(n, hop) ** 2).mean(1))
    win = np.hanning(9)
    env = np.convolve(env, win / win.sum(), "same")
    db = 20 * np.log10(env + 1e-9)

    nuclei, _ = find_peaks(db, distance=7, prominence=1.5, height=np.percentile(db, 30))
    nuclei = nuclei / 100

    thr = np.median(db) + pause_db
    low = db < thr
    pauses, i = [], 0
    while i < n:
        if low[i]:
            j = i
            while j < n and low[j]:
                j += 1
            if (j - i) / 100 >= min_pause:
                pauses.append((i / 100, j / 100))
            i = j
        else:
            i += 1
    voiced = np.where(~low)[0]
    speech = (voiced[0] / 100, voiced[-1] / 100) if len(voiced) else (0, n / 100)
    return nuclei, pauses, speech


# ---------- alignment ----------

def align(tokens, syl, nuclei, pauses, speech):
    cum = np.concatenate([[0], np.cumsum(syl)]).astype(float)
    total = cum[-1]
    nuc = nuclei[(nuclei >= speech[0]) & (nuclei <= speech[1])]

    def t_of(s):  # global proportional estimate
        return float(np.interp(s * (len(nuc) - 1) / total, np.arange(len(nuc)), nuc))

    # candidate text breaks (after word i) and their strength
    breaks = [(i, 2.0 if tok.endswith((".", "!", "?")) else 1.0)
              for i, tok in enumerate(tokens[:-1]) if tok.endswith((".", ",", "!", "?", ";", ":"))]
    inner = [p for p in pauses if p[0] > speech[0] + 0.1 and p[1] < speech[1] - 0.1]

    # monotonic matching of breaks to pauses (DP), rewarding strength, penalising time distance
    B, P = len(breaks), len(inner)
    score = np.full((B + 1, P + 1), -1e9)
    back = {}
    score[0, :] = 0
    score[:, 0] = 0
    for b in range(1, B + 1):
        for p in range(1, P + 1):
            best, arg = score[b - 1, p], ("skip_b",)
            if score[b, p - 1] > best:
                best, arg = score[b, p - 1], ("skip_p",)
            i, strength = breaks[b - 1]
            ps, pe = inner[p - 1]
            dist = abs(t_of(cum[i + 1]) - (ps + pe) / 2)
            if dist < 1.6:
                m = score[b - 1, p - 1] + strength - dist * 1.2
                if m > best:
                    best, arg = m, ("match",)
            score[b, p] = best
            back[(b, p)] = arg
    anchors = []  # (syllable index, time)
    b, p = B, P
    while b > 0 and p > 0:
        arg = back[(b, p)][0]
        if arg == "match":
            i = breaks[b - 1][0]
            anchors.append((cum[i + 1], inner[p - 1]))
            b, p = b - 1, p - 1
        elif arg == "skip_b":
            b -= 1
        else:
            p -= 1
    anchors.reverse()

    # piecewise mapping: syllable index -> time, using nuclei inside each anchored span
    knots = [(0.0, speech[0], speech[0])] + [(s, ps, pe) for s, (ps, pe) in anchors] + [(total, speech[1], speech[1])]
    starts = []
    for k in range(len(knots) - 1):
        s0, _, t0 = knots[k]
        s1, t1, _ = knots[k + 1]
        span_nuc = nuc[(nuc >= t0) & (nuc <= t1)]
        for w in range(len(tokens)):
            if s0 <= cum[w] < s1 or (k == len(knots) - 2 and cum[w] == s1 and w == len(tokens)):
                frac = (cum[w] - s0) / max(s1 - s0, 1e-9)
                if len(span_nuc) >= 2:
                    # first syllable's vowel peak, minus a little for the consonant onset
                    x = frac * (len(span_nuc) - 1)
                    t = float(np.interp(x, np.arange(len(span_nuc)), span_nuc)) - 0.06
                    t = max(t, t0)
                else:
                    t = t0 + frac * (t1 - t0)
                starts.append((w, t))
    starts = [t for _, t in sorted(starts)]
    # ends: next word's start, or the anchor pause / speech end
    anchor_end = {int(np.searchsorted(cum, s)) - 1: ps for s, (ps, _) in anchors}
    words = []
    for w, tok in enumerate(tokens):
        end = anchor_end.get(w, starts[w + 1] if w + 1 < len(tokens) else speech[1])
        words.append({"word": " " + tok, "start": round(starts[w], 3), "end": round(max(end, starts[w] + 0.08), 3)})
    return words, len(anchors)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("video")
    p.add_argument("transcript", help=".docx or .txt with the spoken words, in order")
    p.add_argument("-o", "--output", default="words.json")
    p.add_argument("--pause-db", type=float, default=-12, help="pause threshold relative to median level (dB)")
    p.add_argument("--min-pause", type=float, default=0.18, help="shortest gap treated as a pause (s)")
    args = p.parse_args()

    text = read_transcript(args.transcript)
    tokens = re.findall(r"[A-Za-z0-9'’]+[.,!?;:]?", text)
    d = syllable_dict({"overcomplicating": 6})
    syl = [d.get(re.sub(r"[^a-z']", "", t.lower().replace("’", "'")), None) or guess_syllables(t) for t in tokens]

    audio = load_audio(args.video)
    nuclei, pauses, speech = analyse(audio, args.pause_db, args.min_pause)
    words, n_anchor = align(tokens, syl, nuclei, pauses, speech)

    json.dump({"language": "en", "source": "align_script.py", "segments": [
        {"start": words[0]["start"], "end": words[-1]["end"], "text": text, "words": words}]},
        open(args.output, "w", encoding="utf-8"), indent=1)
    print(f"{len(tokens)} words, {sum(syl)} syllables, {len(nuclei)} syllable beats, "
          f"{len(pauses)} pauses ({n_anchor} used as sentence anchors) -> {args.output}")
    print(f"speech {speech[0]:.2f}s – {speech[1]:.2f}s")


if __name__ == "__main__":
    main()
