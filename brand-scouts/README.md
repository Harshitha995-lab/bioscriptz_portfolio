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

Tested (173 unit tests, standard library only): triage filters, metric maths, dedupe, topic
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

## Watchlist, evidence-rated frameworks and production-ready scripts

Three more outputs in `out/week_<date>/`: `watchlist.md`, `frameworks.md` and `scripts/`.

**Watchlist** (`config/creators.txt`, one handle per line). Each run saves the numbers of every watched Reel to
`data/state/watchlist.jsonl` (with `--save-state`). From that history each creator gets a "usual" (median plays of their
most recent Reels, needing at least 5 Reels seen), and any recent Reel that beats it by `watchlist.outlier_k` (3x) is listed
in an outlier feed, with how fast it grew since the last run. History only ever grows, so baselines improve week by week.

**Frameworks** (`config/frameworks.json`, editable). Seven named story shapes (myth-bust, numbered list, curiosity gap,
problem-solution, before-after, confession-lesson, mystery-reveal). Each week every framework is rated by the data:
*supported* (winners use it more than non-winners on the same topics, after correcting for luck, or creators added it in enough
winning re-makes), *suggestive*, *thin*, *mixed* (two kinds of evidence disagree), *common-to-both* (non-winners use it as
often, so it does not set winners apart) or *not-favoured*. Evidence beats angle fit when a framework is chosen; no framework is
used more than `scripts.max_per_framework` times a week; the experiment slot takes an untested framework on purpose.

**Scripts.** For each shortlisted topic: a shot-by-shot script (time, spoken line, on-screen text, what to film, sound), the
three hooks (audio, on-screen text, video) plus alternatives to A/B test, caption, CTA, and a list of what only you can supply.
Put true stories and results in `config/my_material.md`; scripts may state only facts from there or from `brand_brief.md`,
and use `[bracketed placeholders]` for everything else.
The writer is shown how winners were built (hook type, loop, beats), **never their words**. Then code checks the draft and
sends failures back to the model for up to `scripts.max_rounds` rounds. A script is called *ready* only if it passes:
runtime fits the target; audio hook fits 3 seconds; short on-screen hook; a video hook; starts with the hook and ends with the
CTA; follows the framework's beats; has a CTA; **no figure that is not in your brief or material**; **no client story or
personal result without a source**; **no run of 6+ words shared with any winning Reel**. Otherwise it says *needs work* and
lists what is wrong.

What the checks cannot do: tell you whether a script is good, funny, true to you or likely to perform. They catch invented
numbers, unsourced claims, verbatim copying and an unfilmable structure; paraphrased copying and weak writing are not caught.
Read every script, and treat a script from a "thin" framework as a test, not a proven format.

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

---

## The 5-step agent on Apify's free plan (`agent.py`)

Nothing here has been run against real Apify, Instagram or Anthropic yet; it is tested on synthetic data only. Try it offline first: `python3 agent.py --sample harvest` then `outliers`, `analyse`, `script --topic "..." --from-reel sample_prof_3_01`, `vault list`.

| Step | Command |
|---|---|
| 1 Niche watchlist | `agent.py niche list` / `add-keywords` / `add-creators "<niche>" handle1 handle2` (edit `config/niches.json`) |
| 2 Viral outliers | `agent.py harvest --dry-run`, then `harvest`, then `outliers` |
| 3 Transcripts + hooks + winning formats | `agent.py analyse` → `out/agent/formats.md` |
| 4 Scripts / remix | `agent.py script --topic "..." [--from-reel ID]` |
| 5 Vault + export | `agent.py vault list/show/status/tag/note/search/export --format md\|csv\|json\|xlsx` |

**Setup (free plan):**
1. Create an Apify account (free plan: $5 credit a month, no rollover). In Billing, set a **monthly usage limit**; this is the real safety net.
2. Pick two actors in the Apify Store: one that returns Reels for keywords/hashtags, one for a profile's Reels. Put their ids, input templates and the **price per 1,000 results from the actor's page** in `config/apify.json`.
3. Copy `.env.example` to `.env`; add `APIFY_TOKEN` and `ANTHROPIC_API_KEY`. Never paste them into chat or commit them.
4. Add real creator handles per niche. Without creators, every outlier is "weak" (compared with follower count), and a small account can spike for reasons unrelated to the content.
5. `agent.py harvest --dry-run` shows how the budget splits; the real run refuses if it would not fit (exit 3) and passes a per-run spend cap to Apify. Reels are stored in `data/vault.db`, so analysing them again costs nothing.

Not built: DNA Playbook, weekly email, platforms other than Instagram.

---

## Web app: type a topic, get the top outliers decoded (`web.py`)

    python3 web.py --sample     # offline demo at http://127.0.0.1:8000, synthetic data, no spend
    python3 web.py              # live

Enter any topic (personal branding, daily cosmetics, …) and a window (7, 14 or 30 days). It builds search terms, harvests inside the free-plan budget, also fetches the best hits' creators' own recent Reels (so each creator has a "usual" to be an outlier against), then decodes the **top 10** outliers:

hook (spoken / on-screen / visual) · content angle · creator · rate of revelation (new-information beats per 10 s, from the video length or the transcript length) · super hook (all three hooks present and aligned) · contrarian take · call to action · link. Each card can be turned into your own script, saved to the vault.

- A live run shows its estimated cost and needs a click to confirm; one run at a time; default cap $1.50 per topic (`--max-run-usd`), so about three topics fit in the $5 free credit.
- Content angle, rate of revelation, super hook and contrarian are computed in code from the breakdown, not asked of the model. Anything that needs video frames (on-screen text, visual hook, super hook) says "unknown" without ffmpeg rather than guessing.
- Not verified live. In sample mode every topic shows synthetic personal-branding Reels.
- Binds to 127.0.0.1 only and rejects foreign Host/Origin headers (the server can spend money). Don't expose it to the internet.

### Which model?
`config/settings.json` → `models` sets the model per task (`analysis`, `scripts`); `ANTHROPIC_MODEL_ANALYSIS` / `ANTHROPIC_MODEL_SCRIPTS` override it. Both default to `claude-sonnet-5-5` until you have compared. To compare on your own data: `python3 agent.py compare-models --a claude-haiku-5-5 --b claude-sonnet-5-5 --n 10` runs the same stored Reels through both and lists every disagreement for you to judge.

### Brand mode and audience section
In the web app choose **Brand**: enter the brand, its category (so "Minimalist" means the skincare brand, not minimalism), optionally its Instagram handle and up to 3 competitor handles. It searches category-qualified terms, fetches the brand's and competitors' own recent Reels first, and adds **What the audience says**: comments sorted into question / complaint / praise / price / comparison / purchase-intent, plus accounts and hashtags mentioned alongside. Counting is done in code, examples are verbatim comments. Limits: only the few comments per Reel the scraper returns, skewed to strong feelings, including the creator's own replies. It is not market, product or pricing research; those need other data sources that are not connected. Sample mode uses synthetic comments.

### Free AI option: Gemini
Set `LLM_PROVIDER=gemini` and `GEMINI_API_KEY=...` in `.env` (key from Google AI Studio), run `pip install google-genai`, and the whole app uses Gemini instead of Claude. Set `LLM_PROVIDER=anthropic` to switch back. `GEMINI_MODEL` picks the model; names change, so use one your AI Studio account lists. The free tier is rate limited, so calls are spaced about 4 seconds apart and retried when Google says "too many requests". Not tested against the real service. Compare quality on your own Reels with `agent.py compare-models --a gemini:<model> --b claude-sonnet-5-5`.

## Creators mode (recommended)

Instead of sampling a hashtag, Creators mode searches Instagram for **creators** on a topic (Apify user search), reads each
creator's latest Reels from the same result (one charge per creator, about $0.11 for a topic), and then:

- **Top creators table**: up to 10, ranked by *median* plays of their recent Reels, with quotas per size so micro-creators
  (<10k followers) sit next to small (<100k) and big names. Creators with fewer than 3 recent Reels are left out.
- **Top outlier Reels**: the usual outlier logic against each creator's own median (pinned posts, photos and other
  accounts' posts are dropped), decoded as before, each tagged with its creator size.
- Results are stored under the topic name plus " (creators)", separate from hashtag runs.

Limits: one user search returns the profile's latest posts only (about a dozen), so "usual" is based on those. The
winning-format roll-up per topic and tier is not in the web app yet.
