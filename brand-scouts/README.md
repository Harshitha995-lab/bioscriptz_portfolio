# Brand Scouts: Instagram winners agent

Finds the personal-branding topics winning on Instagram Reels each week and ranks them.
Design and rules: [SPEC.md](SPEC.md).

```
harvest (Apify) -> triage -> label Reels (LLM) -> group into topics -> score (100 -> top 10)
  -> test each top topic against 5 angles -> shortlist (4 data-backed + 1 experiment) -> shortlist.md
```

## Try it now (no keys needed)

```
python3 run_weekly.py --sample        # synthetic data; writes out/week_<date>/shortlist.md and top10.md
python3 -m unittest discover -s tests -t .
```

Sample mode uses made-up Reels and a simple rule-based stand-in for the language model.
**Its rankings mean nothing about real Instagram.** It exists to prove the pipeline works.

## Run it for real

1. `pip install -r requirements.txt`
2. Copy `.env.example` to `.env` and add `APIFY_TOKEN` and `ANTHROPIC_API_KEY`.
3. In Apify, set a **monthly usage limit** on the account. This is the real spending guard.
4. Pick an Instagram Reels scraper in the Apify Store, then fill in `config/apify.json`
   (`actor_id`, and `input_template` to match that actor's input fields).
5. Review `config/keywords.txt` (draft list) and `config/brand_brief.md` (draft brief).
6. Optional: add creators. Put their Instagram handles in `config/creators.txt` and set
   `profile_actor_id` (and `profile_input_template`) in `config/apify.json`. Their recent Reels are
   fetched first, and with 5+ Reels per account the agent learns each account's "usual" level, so
   virality is measured against that account's own normal. Leave the file empty to skip.
7. First run small: `python3 run_weekly.py --live --max-reels 50`, then open
   `out/week_<date>/raw_sample.json` and check the field names against `field_map`.
8. `--save-state` remembers this week's topics so next week can score momentum.

## What is tested, and what is not

Tested (129 unit tests, standard library only): triage filters, metric maths, dedupe, topic
labelling and grouping, score combination and missing-data handling, field mapping for several
Apify field-name styles, and the Apify/Anthropic glue code against stand-in modules.

**Not yet tested against the real services.** No live Apify run and no live Anthropic call has
happened. The actor's real input and output field names, its cost, and the quality of the
model's topic labels all need a first small live run.

## Scale: about 1,000 Reels, a strict viral bar, up to 100 topics

`python3 run_weekly.py --live --max-reels 1000` (the default cap in `config/settings.json`).
After cleaning, only Reels that clear **both** parts of the viral bar continue:
`min_heat` 80 (top ~20% of this pool) and `min_outperformance` 3.0 (at least 3x the account's usual,
or 3x its follower count when the usual is unknown). Topics are capped at `max_topics` 100.

On a *synthetic* pool of 1,000 random Reels the default bar kept about 115. That shows how strict it
is, not what Instagram will give. Fewer than 20 survivors prints a warning. 115 Reels would group
into well under 100 topics, so getting close to 100 topics means scraping more Reels or loosening the
bar; thin topics (one Reel or one account) are flagged in the report instead of hidden.

## The viral Reel library: 100 winners across different keywords

`out/week_<date>/viral_reels.md` (and `.json`). One entry per viral Reel, with its **full transcript**, its
hooks, format, storytelling loop, spice and CTA, and, where possible, a direct comparison with the same
creator's earlier weaker version of the same topic.

- **Scale and spread.** `harvest.max_reels` (default 3,000) with `per_keyword_runs: true` in `config/apify.json`
  runs the scraper once per keyword so every Reel knows which keyword found it. The library then takes the best
  Reels round-robin across keywords: at most `per_keyword_cap` (5) per keyword and `per_account_cap` (2) per
  creator. For 100 Reels at 5 per keyword you need at least 20 keywords that each produced enough viral Reels;
  the report says so when it falls short. Set `resultsLimit` in `input_template` to the Reels wanted per keyword.
- **Twins: your 42K vs 6.1M example.** For each winner, the agent fetches that creator's recent Reels, labels them
  against the winner's topic, and takes the nearest miss that got at least `twin_min_ratio` (10x) fewer plays as
  its "earlier version". Both are described blind to their numbers and the presentation features that changed are
  listed. This is the strongest evidence in the system because audience, voice and topic are held constant.
  Across many pairs, a sign test (one pair per creator, corrected for many features) reports changes that repeat.
  **About six pairs all changing the same way are needed before it can beat chance**, so early weeks will say
  "not enough pairs" rather than guess. One pair is an example, not proof: timing, sound and the algorithm also
  move reach.
- **Transcripts.** Used as scraped. When missing and a video URL exists, the video is downloaded to a temporary
  folder, its audio is extracted with ffmpeg and transcribed with faster-whisper (`pip install faster-whisper`;
  downloads a model on first use; CPU, can be slow). Nothing is kept except the text. Transcripts are stored in
  your own `out/` folder for study; do not republish other creators' words.
- **Not verified live:** the transcription engine (faster-whisper is not installed in the test environment),
  the follow-up profile scrape, and whether your chosen actors return video URLs and keywords.

## Viral analysis: why one Reel on a topic travelled further than another

`out/week_<date>/viral_analysis.md`. Built on one idea: the same topic gets presented differently by
different creators, so compare Reels on the **same topic** that reached very different audiences.

1. **Comparison group.** Reels that failed the viral bar are not thrown away. They are labelled against the
   top topics' names and become the "non-viral" side of each topic (up to `peer_pool_max`).
2. **Describe, blind.** For the strongest viral Reels and a spread of the non-viral ones, the analyst writes down
   how each is built: **three hook channels** (audio = first spoken line, text = on-screen text in the first 3 s,
   video = what we see in the first 3 s), format, tone, pacing, story loop (open question, payoff, re-hook),
   "spice" devices (specific number, personal stake, named enemy, pattern interrupt...), beats and CTA. It is
   **never shown plays, likes or follower counts**, so it cannot explain a success after the fact. Words come from
   `config/viral_vocab.json`, which you can edit.
3. **Compare, in code.** Each presentation feature becomes a yes/no. Viral vs non-viral prevalence is compared with
   Fisher's exact test, corrected for testing many features at once (Benjamini-Hochberg). Pooled results are
   **matched per topic**, so one big topic cannot masquerade as a presentation effect. Each result is read as
   "likely real", "possible (may be luck)" or "weak".
4. **Explain.** Only then does a model write the explanation, a what-to-copy list and a fill-in-the-blank template,
   under rules to claim nothing the numbers do not show.

Why the correction: on 500 simulated pure-noise datasets, an uncorrected analysis reported a "pattern" 52% of the
time; with the correction a false "likely real" pattern appeared 3% of the time.

**Video and on-screen-text hooks need frames.** They come from the first ~3 s and two later frames of each video,
which needs a direct video URL from the scraper (`videoUrl`) and `ffmpeg` on the machine. Without them, the
report says "not analysed" for the text and video hooks, format, tone and pacing, and covers the audio hook, loop,
spice, CTA and structure from the transcript. Videos are downloaded to a temporary folder, sampled, and deleted;
nothing is kept. Settings are under `viral_analysis` in `config/settings.json`.

Limits: a comparison needs at least 3 Reels per side; small samples mostly show nothing, and the report says so
instead of inventing reasons. It shows correlation in this week's sample, not proof of cause. Cost is not measured:
each analysed Reel is one model call with up to 6 small images, so cap it with `viral_analysis.max_reels`.

## The angle step

The top 10 topics are each tested against the 5 angles in `config/angles.txt` (story, contrarian,
proof, how-to, authority). An angle's score blends: how that angle did **inside this topic** this
week (35), how that angle does **across all topics** this week (20), a **fit check** against your
brand brief that also drafts a pitch and hook (30), and your history once the Playbook exists (15).
Evidence is pulled toward the angle's weekly average, so one lucky Reel cannot carry an angle, and an
**untested angle gets no bonus for missing data**: it is judged on fit alone and labelled
"untested (experiment)". The shortlist is 5 topics x up to 3 angles, with 1 slot (20%) kept for an
experiment. If no experiment candidate exists, the slot goes to the next-best topic and a note says so.
Settings are in `config/settings.json` under `shortlist`.

## How scores work

Each topic is scored 0-100 (shown /10) from: viral evidence 30, breadth 20, momentum 10,
conversion 15, brand match 15, your history 10. Factors are ranked **against this week's other
topics**, so scores are relative. Factors with no data (momentum in week one, history until the
DNA Playbook exists) give up their weight pro rata to the rest.

Known limits: shares and saves are not public; a keyword search only returns what Instagram
surfaces, so this is a sample of the platform; "plays vs followers" stands in for "vs the
account's usual" when the account's median is unknown; transcripts depend on the actor.

## Not built yet

The weekly email, the DNA Playbook, other platforms. The "radical triad system" is not implemented: it is not a term
I recognise, so the 100 -> 10 cut uses the topic score above until its three parts are defined.
