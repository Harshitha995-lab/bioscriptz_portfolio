#!/usr/bin/env python3
"""Prove every sentence in a draft came from the transcript.

Usage:
    python3 bin/trace.py <draft.md> <transcript.txt> [--gate 90]

This is the gate that matters. Pangram reads the prose, not the pipeline, so
what decides the verdict is how much of the finished text is literally the
author's own wording. Ideas sourced from a human do not help. Sentences do.

Measured on this system, 31/07/2026, same article and same source recording,
varying only the proportion of model-composed sentences:

    100.0% traceable  ->  100% human
     87.5% traceable  ->  100% human
     71.7% traceable  ->   58% human
     61.7% traceable  ->   57% human
     13.5% traceable  ->  100% AI

It is a threshold, not a slope. Somewhere between 87.5% and 71.7% the verdict
flips, and past that point adding more composed text barely changes it. The
gate is set at 85%, just under the last measured pass.

In practice: about one sentence in eight can be model-composed. That is enough
for the joins and transitions, and not enough for a section.

Each sentence is classified against the transcript:

  VERBATIM  >= 0.85 of its content words appear in one transcript region
  EDITED    0.55 - 0.85, recognisably his sentence, cut or joined
  COMPOSED  < 0.55, written by the model

COMPOSED sentences are the failure. The tool prints them so the author can
retype each one in their own words. That retyping IS the work. Do not
"improve" a composed sentence, replace it with a human one.

Headings are excluded from the score. Signposting is not voice.
"""
import difflib, re, sys, os

STOP = set("""a an the and or but so if then than that this these those there here is are was
were be been being am do does did doing have has had having will would can could should
of in on at by for with from into to as up down out over under again it its i me my we us
our you your he she they them their what which who not no""".split())


def words(t):
    return re.findall(r"[a-z][a-z'’-]*", t.lower())


def content(t):
    return [w for w in words(t) if w not in STOP and len(w) > 2]


def strip_md(t):
    t = re.sub(r'^---\n.*?\n---\n', '', t, flags=re.S)
    t = re.sub(r'```.*?```', '', t, flags=re.S)
    t = re.sub(r'!\[[^\]]*\]\([^)]*\)', '', t)
    t = re.sub(r'\[([^\]]*)\]\([^)]*\)', r'\1', t)
    return t


def sentences(t, drop_headings=True):
    out = []
    for block in t.split('\n\n'):
        b = block.strip()
        if not b:
            continue
        if drop_headings and (b.startswith('#') or re.fullmatch(r'\*\*[^*]+\*\*', b)):
            continue
        for s in re.split(r'(?<=[.!?])\s+', b.replace('\n', ' ')):
            s = s.strip()
            if s and len(s.split()) >= 3 and any(c.isalpha() for c in s):
                out.append(s)
    return out


def best_match(sent_words, src_words, window_pad=12):
    """Highest fraction of sent_words found inside any comparable source window."""
    if not sent_words:
        return 0.0
    sm = difflib.SequenceMatcher(None, sent_words, src_words, autojunk=False)
    blocks = [b for b in sm.get_matching_blocks() if b.size]
    if not blocks:
        return 0.0
    # Anchor on the largest match, then count how many of the sentence's words
    # appear anywhere in the surrounding source window.
    big = max(blocks, key=lambda b: b.size)
    lo = max(0, big.b - len(sent_words) - window_pad)
    hi = min(len(src_words), big.b + len(sent_words) + window_pad)
    window = src_words[lo:hi]
    pool = list(window)
    hits = 0
    for w in sent_words:
        if w in pool:
            pool.remove(w)
            hits += 1
    return hits / len(sent_words)


def main():
    if len(sys.argv) < 3:
        raise SystemExit(__doc__)
    draft_p, src_p = sys.argv[1], sys.argv[2]
    gate = 85.0
    if '--gate' in sys.argv:
        gate = float(sys.argv[sys.argv.index('--gate') + 1])

    draft = strip_md(open(draft_p).read())
    src_words = content(open(src_p, errors='ignore').read())
    if len(src_words) < 50:
        raise SystemExit('Transcript too short to trace against.')

    rows = []
    for s in sentences(draft):
        sw = content(s)
        score = best_match(sw, src_words)
        tag = 'VERBATIM' if score >= 0.85 else ('EDITED' if score >= 0.55 else 'COMPOSED')
        rows.append((tag, round(score, 2), len(s.split()), s))

    total_w = sum(r[2] for r in rows) or 1
    by = {t: sum(r[2] for r in rows if r[0] == t) for t in ('VERBATIM', 'EDITED', 'COMPOSED')}
    his = 100 * (by['VERBATIM'] + by['EDITED']) / total_w
    composed = [r for r in rows if r[0] == 'COMPOSED']

    print(f"\n  {os.path.basename(draft_p)}  traced against  {os.path.basename(src_p)}")
    print('  ' + '-' * 74)
    for t in ('VERBATIM', 'EDITED', 'COMPOSED'):
        n = sum(1 for r in rows if r[0] == t)
        print(f"  {t:<10}{n:>4} sentences{by[t]:>7} words{100*by[t]/total_w:>7.1f}%")
    print('  ' + '-' * 74)
    print(f"  HIS WORDS  {his:.1f}%   gate {gate}%   "
          f"[{'PASS' if his >= gate else 'FAIL'}]")

    if composed:
        print(f"\n  RETYPE THESE {len(composed)} SENTENCES IN YOUR OWN WORDS.")
        print("  Do not ask the model to improve them. Say them out loud and type what you say.\n")
        for _, sc, _, s in composed:
            print(f"   [{sc:.2f}] {s}")
    else:
        print("\n  Nothing composed. Every sentence traces to something you said.")

    print(f"\n  Traceability predicts the verdict. It does not guarantee it —"
          f"\n  a genuinely human piece still flags occasionally.\n")
    sys.exit(0 if his >= gate else 1)


if __name__ == '__main__':
    main()
