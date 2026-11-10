#!/usr/bin/env python3
"""Build a person's voice profile from their own transcripts.

Usage:
    python3 bin/profile.py <name>              build from voices/<name>/
    python3 bin/profile.py <name> --show       print an existing profile

Reads every transcript in voices/<name>/, measures the ten spoken-register
metrics, and mines the phrases that person actually reaches for: their
sentence openers, their connectives, their hedges, their repeated 2-4 word
phrases, and the vocabulary that is distinctively theirs.

The metrics tell a writer HOW they talk. The mined phrases tell it WHAT
they say. Both go in the profile; the draft stage uses both.

Output: voices/<name>/profile.json + profile.md
"""
import json, os, re, sys, statistics as st
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'bin'))
from spoken import measure, LABEL, clean  # noqa: E402

# Words too common to be distinctive. Everything else is fair game.
STOP = set("""a an the and or but so if then than that this these those there here
i me my we us our you your he she it its they them their what which who whom whose
is are was were be been being am do does did doing have has had having will would
can could should shall may might must to of in on at by for with from into about
as up down out over under again just really very much more most some any all no not
one two three like get got go going went make made take took know knew think thought
say said see saw come came want need thing things way ways time times right now new
also only even still back well because how when where why while does isn wasn don""".split())

FILLER = re.compile(r"\b(kind of|sort of|a bit|pretty much|you know|i mean|to be fair"
                    r"|honestly|obviously|basically|actually|literally|genuinely"
                    r"|essentially|frankly|really|just|quite|pretty)\b", re.I)
OPENER = re.compile(r'^\s*([A-Z][a-z]+)')
SPLIT = re.compile(r'(?<=[.!?])\s+|\n+')


def sentences(t):
    return [s.strip() for s in SPLIT.split(t)
            if s.strip() and any(c.isalpha() for c in s)]


def ngrams(words, n):
    return [' '.join(words[i:i + n]) for i in range(len(words) - n + 1)]


def dedupe_phrases(cands, keep=25):
    """Drop sliding-window duplicates of the same utterance.

    A 3-gram and 4-gram counter over one repeated line yields six near-identical
    entries ("oh my gosh", "my gosh oh", "gosh oh my", ...). Keep the first
    occurrence and discard any later phrase that shares most of its words.
    """
    out = []
    for p in cands:
        pw = set(p.split())
        if any(len(pw & set(q.split())) / max(1, len(pw)) >= 0.6 for q in out):
            continue
        out.append(p)
        if len(out) >= keep:
            break
    return out


def mine(text):
    t = clean(text)
    ss = sentences(t)
    words = re.findall(r"[a-z][a-z'’-]*", t.lower())

    openers = Counter()
    for s in ss:
        m = OPENER.match(s)
        if m:
            openers[m.group(1)] += 1

    fillers = Counter(f.lower() for f in FILLER.findall(t))

    phrases = Counter()
    for n in (3, 4):
        for g in ngrams(words, n):
            gw = g.split()
            if sum(1 for w in gw if w in STOP) > len(gw) - 2:
                continue          # mostly stopwords, not distinctive
            phrases[g] += 1

    vocab = Counter(w for w in words if w not in STOP and len(w) > 3)
    return openers, fillers, phrases, vocab, len(ss), len(words)


def build(name):
    d = os.path.join(ROOT, 'voices', name)
    if not os.path.isdir(d):
        raise SystemExit(f'No transcripts at voices/{name}/. Run bin/transcribe.sh first.')
    files = [os.path.join(d, f) for f in sorted(os.listdir(d))
             if f.endswith(('.txt', '.md', '.vtt')) and not f.startswith('profile')]
    if not files:
        raise SystemExit(f'voices/{name}/ has no .txt/.md transcripts.')

    metrics, O, F, P, V = [], Counter(), Counter(), Counter(), Counter()
    total_s = total_w = 0
    for f in files:
        raw = open(f, errors='ignore').read()
        try:
            metrics.append(measure(raw))
        except SystemExit:
            continue
        o, fl, p, v, ns, nw = mine(raw)
        O += o; F += fl; P += p; V += v
        total_s += ns; total_w += nw

    if len(metrics) < 2:
        raise SystemExit(f'Only {len(metrics)} usable transcripts. Need 2+ '
                         f'(aim for 5,000+ words for a stable profile).')

    bands = {}
    for k in LABEL:
        vals = [m[k] for m in metrics]
        mean = st.mean(vals)
        sd = st.pstdev(vals) or abs(mean) * 0.15
        label, weight, fix = LABEL[k]
        # Every metric is a rate or a percentage, so it cannot be negative.
        # With a wide spread, sd exceeds the mean and mean-sd goes below zero,
        # which makes the band un-failable and meaningless.
        bands[k] = dict(lo=round(max(0.0, mean - sd), 2), hi=round(mean + sd, 2),
                        target=round(mean, 2), weight=weight, label=label, fix=fix)

    prof = dict(
        name=name, files=len(metrics), words=total_w, sentences=total_s,
        method='per-transcript mean +/- 1 SD', gate=80.0, bands=bands,
        openers=[w for w, c in O.most_common(14) if c > 1],
        fillers=[w for w, c in F.most_common(12) if c > 1],
        phrases=dedupe_phrases([p for p, c in P.most_common(60) if c > 1]),
        vocab=[w for w, c in V.most_common(40) if c > 2],
    )
    json.dump(prof, open(os.path.join(d, 'profile.json'), 'w'), indent=2)
    write_md(prof, d)
    show(prof)
    print(f"\n{os.path.join(d, 'profile.md')}")


def write_md(p, d):
    b = p['bands']
    L = [f"# Voice profile: {p['name']}", '',
         f"Built from {p['files']} transcripts, {p['words']:,} words, "
         f"{p['sentences']:,} sentences of this person actually speaking.", '',
         '## How they talk', '',
         '| Property | Target | Band |', '|---|---|---|']
    for k, v in sorted(b.items(), key=lambda x: -x[1]['weight']):
        L.append(f"| {v['label']} | {v['target']} | {v['lo']} – {v['hi']} |")
    L += ['', '## What they say', '',
          '**Sentence openers they reach for:** ' + ', '.join(p['openers']) or '—', '',
          '**Their fillers and hedges:** ' + ', '.join(p['fillers']) or '—', '',
          '**Phrases they repeat:**', '']
    L += [f'- {x}' for x in p['phrases'][:20]] or ['- (none recurring)']
    L += ['', '**Vocabulary that is theirs:** ' + ', '.join(p['vocab'][:30]), '',
          '## How to use this', '',
          'The bands govern rhythm. The phrases govern texture. A draft that hits',
          'the bands but uses none of their phrases will read like a generic',
          'speaker, not like them.', '',
          'This profile describes a real person. Do not use it to write in their',
          'voice without their consent.', '']
    open(os.path.join(d, 'profile.md'), 'w').write('\n'.join(L) + '\n')


def show(p):
    print(f"\n  {p['name']} — {p['files']} transcripts, {p['words']:,} words\n")
    print(f"  {'metric':<38}{'target':>9}{'band':>16}")
    for k, v in sorted(p['bands'].items(), key=lambda x: -x[1]['weight']):
        rng = '{} - {}'.format(v['lo'], v['hi'])
        print("  {:<38}{:>9}{:>16}".format(v['label'], v['target'], rng))
    print(f"\n  openers : {', '.join(p['openers'][:10])}")
    print(f"  fillers : {', '.join(p['fillers'][:8])}")
    print(f"  phrases : {'; '.join(p['phrases'][:6])}")


if __name__ == '__main__':
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    n = sys.argv[1]
    if '--show' in sys.argv:
        show(json.load(open(os.path.join(ROOT, 'voices', n, 'profile.json'))))
    else:
        build(n)
