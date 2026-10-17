# Brand Scouts: Build Spec (v0.1)

Status: Instagram steps 1-6 are implemented (harvest, triage, topic labelling, scoring, angle testing,
shortlist with the experiment slot) and unit tested offline; not yet run against live Apify/Anthropic.
Step 7 is Harshitha's decision. The Playbook and other platforms are not built.
See README.md.

## Goal
Every week, surface the winning personal-branding topics on Instagram Reels,
shortlist about 5 topics with 2-3 angles each, and hand them to Harshitha, who
makes the final pick. Other platforms (LinkedIn, X, YouTube, Substack, Reddit)
follow the same pipeline later.

## Source note
The pipeline below is adapted from a description of Vaibhav Sisinty's process
that Harshitha supplied. It is unverified and is used as a design reference,
not as a confirmed account of how he works.

## Brand brief (what "brand match" is judged against)
Harshitha is building a personal branding agency for founders and creators.
She helps them get virality AND conversion: founder-led LinkedIn content in the
founder's own voice and taste, tied to a sales funnel and pipeline. Her lens:
biotech-trained, mechanism-first, storytelling. Avoid: job-seeker branding tips,
generic listicles, hustle hype, vanity metrics.

## Pipeline (Instagram first)
1. HARVEST (daily). Target about 1,000 Reels per run: creators' recent Reels first, then keywords. Reels from many keywords and hashtags (start with 20-30,
   including Hinglish/Hindi terms) plus a small seed list of accounts.
   Creators are one source, not the unit of analysis.
2. TRIAGE. Drop duplicates, spam, off-topic. Work out each account's usual level (median plays) from all
   its fetched Reels BEFORE filtering. Apply the strict viral bar (min_heat, min_outperformance). Compute velocity (plays/day),
   outperformance (vs account size and median), comment-to-like ratio.
   Keep outliers only.
3. TOPICS. The Breakdown Analyst reads transcript + caption of each surviving
   Reel and assigns a topic label; Reels with the same label cluster into a
   candidate topic with its evidence (links, plays, accounts). Target ~100.
4. SCORE (about 100 topics -> top 10). One scorer prompt is run once per topic,
   in parallel, scoring 1-100 for viral potential against the DNA Playbook
   plus current viral data. Keep the top 10.
5. ANGLES (10 topics x 5 angles = 50 variations -> 5 topics with up to 3 angles
   each). The pasted source used 10 angles; Harshitha chose 5 (config/angles.txt).
   Each variation is scored on in-topic evidence, the angle's weekly average, a
   brand-fit check, and Playbook history when it exists.
6. 80/20 MIX. About 70-80% of picks come from Playbook/data; 20-30% are
   deliberate experiments outside past data, to avoid an echo chamber.
7. HUMAN DECISION. AI surfaces and ranks. Harshitha makes the final topic and
   angle choice. The system never decides or posts on its own.

## Viral analysis / Breakdown Analyst (separate agent, stronger model)
Implemented. See README.md, "Viral analysis". Describes each Reel blind to performance across three hook
channels (audio, on-screen text, video), format, story loop and spice; compares viral vs non-viral Reels on the
same topic in code; explains only what the numbers show. Original sketch kept below.

For each top Reel: link, hook (exact words + type), structure beat by beat,
proof, CTA and type, content angle, funnel move, why it worked, and a
"your version" idea. Topic tag from an editable fixed list.

## Scoring
- Stored internally 1-100; shown to the user as /10.
- Topic factors (weights adjustable): viral evidence 30, breadth (distinct
  accounts winning) 20, momentum vs last week 10, conversion signal 15,
  brand match 15, your history (Playbook) 10.
- While the Playbook is empty, "your history" is neutral and its weight is
  redistributed pro rata across the other factors.

## DNA Playbook (DEFERRED, to be built later)
A master repository (Google Sheet or database) of historical content
performance: topics, transcripts, written posts, likes, comments, views,
shares, and human-tagged angles that worked. Not built yet.
Build now: a PlaybookProvider interface that returns "no data" when empty, so
steps 4-5 run today and start using real history the moment it exists.
Every weekly run appends winners to it; Harshitha's own posts and results are
logged to it after she publishes.

## Rules
- Every score shows its factor breakdown and evidence links.
- Scrape public data only; no scraping through Harshitha's own logged-in
  accounts; no contact lists or private data.
- Secrets live in .env (never committed). Set a spending cap on scraper
  accounts. Flag empty or failed harvests instead of passing them on silently.
- Instagram data is a sample, not the whole platform; shares/saves are not
  public; visual hooks are not captured in transcripts.

## Open items
- Weekly scraping budget cap
- Harvest frequency (daily recommended)
- Final keyword list (draft of 30 to be reviewed)
- Reddit data-access route (later platform)
- "Radical triad system": Harshitha's term for the 100 -> 10 filter. Not a term the build
  recognises; ask what the three parts are. Until then the 100 -> 10 cut uses the topic score.
