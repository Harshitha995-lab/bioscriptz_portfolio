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
6. First run small: `python3 run_weekly.py --live --max-reels 50`, then open
   `out/week_<date>/raw_sample.json` and check the field names against `field_map`.
7. `--save-state` remembers this week's topics so next week can score momentum.

## What is tested, and what is not

Tested (53 unit tests, standard library only): triage filters, metric maths, dedupe, topic
labelling and grouping, score combination and missing-data handling, field mapping for several
Apify field-name styles, and the Apify/Anthropic glue code against stand-in modules.

**Not yet tested against the real services.** No live Apify run and no live Anthropic call has
happened. The actor's real input and output field names, its cost, and the quality of the
model's topic labels all need a first small live run.

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

The Breakdown Analyst's full template (structure, proof, funnel move per Reel), the weekly email,
the DNA Playbook, other platforms. The "radical triad system" is not implemented: it is not a term
I recognise, so the 100 -> 10 cut uses the topic score above until its three parts are defined.
