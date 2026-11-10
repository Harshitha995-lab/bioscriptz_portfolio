#!/usr/bin/env python3
"""Transcribe a video with Whisper and save word-level timestamps as JSON.

Output follows the openai-whisper JSON shape:
  {"language": "en", "segments": [{"start", "end", "text", "words": [{"word", "start", "end", "probability"}]}]}

Usage:
  python transcribe.py input.mp4 -o words.json --model small
"""
import argparse
import json

from faster_whisper import WhisperModel


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("input", help="video or audio file")
    p.add_argument("-o", "--output", default="words.json")
    p.add_argument("--model", default="small", help="tiny | base | small | medium | large-v3 (bigger = more accurate, slower)")
    p.add_argument("--language", default="en", help="spoken language code, or 'auto'")
    p.add_argument("--prompt", default=None,
                   help="spelling hints for names/jargon, e.g. 'Bioscriptz, biotech, CRISPR, founders'")
    p.add_argument("--device", default="auto", help="auto | cpu | cuda")
    args = p.parse_args()

    model = WhisperModel(args.model, device=args.device, compute_type="int8")
    segments, info = model.transcribe(
        args.input,
        language=None if args.language == "auto" else args.language,
        initial_prompt=args.prompt,
        word_timestamps=True,
        vad_filter=True,  # skips silence so words don't drift into pauses
        vad_parameters={"min_silence_duration_ms": 300},
    )

    out = {"language": info.language, "segments": []}
    for s in segments:
        out["segments"].append({
            "start": s.start,
            "end": s.end,
            "text": s.text.strip(),
            "words": [{"word": w.word, "start": w.start, "end": w.end, "probability": w.probability}
                      for w in (s.words or [])],
        })
        print(f"[{s.start:6.2f} -> {s.end:6.2f}] {s.text.strip()}")

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"\nSaved {sum(len(s['words']) for s in out['segments'])} words to {args.output}")


if __name__ == "__main__":
    main()
