#!/usr/bin/env python3
"""Score a draft against Charlie's own SPOKEN register.

Usage:
    python3 bin/spoken.py --build          rebuild bands from spoken/
    python3 bin/spoken.py path/to/draft.md score a draft

Calibrated on transcripts of Charlie talking to camera (IG reels + YouTube),
not on written essays. Written prose and transcribed speech diverge sharply:
speech runs LONGER per sentence, opens a third of its sentences with a
discourse marker, hedges four times as much, and contracts less than a
punchy written rewrite does.

Companion to score.py, which measures written-essay rhythm. Where the two
disagree, this one wins for "sounds transcribed".
"""
import json, os, re, sys, statistics as st

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROFILE = os.path.join(ROOT, 'voices', 'default', 'profile.json')
SPOKEN = os.path.join(ROOT, 'spoken')

PAT = {k: re.compile(v, re.I) for k, v in dict(
    dm=r"\b(so|right|okay|now|anyway|look|honestly|obviously|basically|actually"
       r"|literally|i mean|you know|alright|see)\b",
    hedge=r"\b(kind of|sort of|a bit|pretty much|maybe|probably|just|really|quite"
          r"|pretty|about|roughly)\b",
    vague=r"\b(thing|things|stuff|bit|bits|whatever|something|anything)\b",
    sub=r"\b(which|although|whereas|however|because|so that|even though|whilst)\b",
    contr=r"\w['’](s|t|re|ve|ll|d|m)\b",
    you=r"\b(you|your)\b",
    i=r"\b(I|my)\b",
).items()}
WORD = re.compile(r"[a-z']+")
SPLIT = re.compile(r'(?<=[.!?])\s+|\n+')
OPENER = re.compile(r'^\s*(So|Now|Right|Okay|And|But|Look|Because|Then|Anyway)\b')
HDR = re.compile(r'^#{1,6} .*$', re.M)
FM = re.compile(r'^---\n.*?\n---\n', re.S)
CODE = re.compile(r'```.*?```', re.S)

LABEL = {
    'startSo':  ('% sentences opening So/Now/And/But', 18,
                 'Open more sentences with So, Now, Right, And, But. Biggest single tell.'),
    'dm':       ('discourse markers /1k', 14,
                 'Add spoken connectives: so, right, look, honestly, I mean, you know.'),
    'hedge':    ('hedges /1k', 12,
                 'Add hedges: kind of, just, really, probably, pretty much. Speech is imprecise.'),
    'sent':     ('mean sentence words', 12,
                 'Speech runs LONG through coordination. Stop chopping. Join clauses with and/so/but.'),
    'sub':      ('subordinators /1k', 8,
                 'Let clauses trail: which, because, although, even though.'),
    'contr':    ('contractions /1k', 8,
                 'Match spoken contraction rate. Over-contracting reads written-punchy, not spoken.'),
    'vague':    ('vague nouns /1k', 7,
                 'Speech points at things: thing, stuff, bit. Written prose names them precisely.'),
    'i':        ('% words I/my', 7,
                 'First person. You talk about yourself more on camera than on the page.'),
    'you':      ('% words you/your', 7,
                 'Direct address to camera.'),
    'ttr':      ('lexical diversity', 7,
                 'Speech REUSES words. High diversity reads written. Repeat your nouns.'),
}


def clean(t):
    t = FM.sub('', t)
    t = CODE.sub('', t)
    t = HDR.sub('', t)
    t = re.sub(r'\[([^\]]*)\]\([^)]*\)', r'\1', t)
    t = re.sub(r'!\[[^\]]*\]\([^)]*\)', '', t)
    t = re.sub(r'^\*\*[^*]+\*\*\s*$', '', t, flags=re.M)
    return t


def measure(text):
    t = clean(text)
    w = WORD.findall(t.lower())
    n = len(w) or 1
    ss = [s for s in SPLIT.split(t) if s.strip() and any(c.isalpha() for c in s)]
    if len(ss) < 5:
        raise SystemExit('Too short to score (need 5+ sentences).')
    L = [len(s.split()) for s in ss]
    r = {k: round(1000 * len(p.findall(t)) / n, 2) for k, p in PAT.items()}
    r['you'] = round(100 * len(PAT['you'].findall(t)) / n, 2)
    r['i'] = round(100 * len(PAT['i'].findall(t)) / n, 2)
    r['sent'] = round(st.mean(L), 2)
    r['ttr'] = round(len(set(w)) / n, 3)
    r['startSo'] = round(100 * sum(1 for s in ss if OPENER.match(s)) / len(ss), 2)
    r['_words'] = n
    r['_sentences'] = len(ss)
    return r


def build():
    files = [os.path.join(SPOKEN, f) for f in sorted(os.listdir(SPOKEN))
             if not f.startswith('.')]
    rows = []
    for f in files:
        try:
            rows.append(measure(open(f, errors='ignore').read()))
        except SystemExit:
            continue
    if len(rows) < 3:
        raise SystemExit(f'Only {len(rows)} usable transcripts. Add more to spoken/.')
    bands = {}
    for k in LABEL:
        v = [r[k] for r in rows]
        mean, sd = st.mean(v), (st.pstdev(v) or abs(st.mean(v)) * 0.15)
        label, weight, fix = LABEL[k]
        bands[k] = dict(lo=round(mean - sd, 2), hi=round(mean + sd, 2),
                        target=round(mean, 2), weight=weight, label=label, fix=fix)
    prof = dict(source='Charlie to camera: IG reels + YouTube transcripts',
                files=len(rows), words=sum(r['_words'] for r in rows),
                method='per-transcript mean +/- 1 SD', bands=bands, gate=80.0)
    json.dump(prof, open(PROFILE, 'w'), indent=2)
    print(f"{prof['files']} transcripts, {prof['words']:,} words -> spoken bands\n")
    print(f"  {'metric':<38}{'target':>9}{'band':>16}{'w':>4}")
    for k, b in sorted(bands.items(), key=lambda x: -x[1]['weight']):
        rng = '{} - {}'.format(b['lo'], b['hi'])
        print("  {:<38}{:>9}{:>16}{:>4}".format(b['label'], b['target'], rng, b['weight']))
    print(f'\n{PROFILE}')


def resolve(name=None):
    """voices/<name>/profile.json, else the legacy single profile."""
    if name:
        p = os.path.join(ROOT, 'voices', name, 'profile.json')
        if not os.path.exists(p):
            raise SystemExit(f'No profile for "{name}". Run: python3 bin/profile.py {name}')
        return p
    return PROFILE


def score(path, name=None):
    prof = json.load(open(resolve(name)))
    m = measure(open(path).read())
    lost, rows = 0.0, []
    for k, b in prof['bands'].items():
        v = m[k]
        ok = b['lo'] <= v <= b['hi']
        pen = 0.0
        if not ok:
            span = (b['hi'] - b['lo']) or 1
            d = (b['lo'] - v) / span if v < b['lo'] else (v - b['hi']) / span
            pen = b['weight'] * min(1.0, d)
            lost += pen
        rows.append((b['label'], v, b['target'], ok, round(pen, 1),
                     '' if ok else b['fix'] + (' (LOW)' if v < b['lo'] else ' (HIGH)'),
                     b['weight']))
    rows.sort(key=lambda r: (-r[4], -r[6]))
    sc = round(max(0.0, 100 - lost), 1)
    print(f"\n  {os.path.basename(path)}  —  {m['_words']} words, {m['_sentences']} sentences")
    print('  ' + '-' * 92)
    print(f"  {'metric':<38}{'yours':>8}{'target':>9}{'':>6}{'-pts':>6}  fix")
    print('  ' + '-' * 92)
    for label, v, tgt, ok, pen, fix, _ in rows:
        print(f"  {label:<38}{v:>8}{tgt:>9}{('ok' if ok else 'FAIL'):>6}{pen:>6}  {fix}")
    print('  ' + '-' * 92)
    print(f"\n  SPOKEN SCORE  {sc} / 100   [{'SHIP' if sc >= prof['gate'] else 'REWRITE'}]"
          f"   gate {prof['gate']}")
    print("  Measures how closely this reads as transcribed speech. Structure only.\n")


if __name__ == '__main__':
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    if not sys.argv[1:]:
        raise SystemExit(__doc__)
    if '--build' in sys.argv:
        build()
    else:
        score(args[0], args[1] if len(args) > 1 else None)
