---
name: market-research
description: Run full brand, product, competitor, Reddit and research-paper research on a company and combine it into one story-led report with content and script angles. Use when the user asks to research a brand, a product, a client, a prospect or its competitors, or types /market-research followed by a brand name or URL.
argument-hint: <brand name or URL> [competitors to include]
---

# Market research

Research the brand in `$ARGUMENTS` using five specialist agents in parallel. Then combine their work into one story-led report.

## 1. Set up

- Work out the brand name and website from `$ARGUMENTS`. If only a name is given, find the official site with one quick search. If the name is ambiguous (several companies share it), ask the user which one before going further.
- Note any competitors the user named.
- Make a slug from the brand name (lowercase, hyphens). Use the folder `research/<slug>/` in the project root.

## 2. Research in parallel

Launch all five agents in a single message so they run at the same time:

| Agent | Output file | Give it |
|---|---|---|
| `brand-researcher` | `research/<slug>/brand.md` | Brand, URL. Ask it to dig hardest into the founder's origin story. |
| `product-researcher` | `research/<slug>/product.md` | Brand, URL |
| `competitor-researcher` | `research/<slug>/competitors.md` | Brand, URL, competitors the user named |
| `reddit-researcher` | `research/<slug>/reddit.md` | Brand, plus 3–5 topics: its category, its technology, its main competitors |
| `science-researcher` | `research/<slug>/papers.md` | Brand, its technology and the claims it makes (from its website or the user) |

Give every agent the output path and today's date.

## 3. Combine

When all five finish, read their files and write `research/<slug>/report.md`:

```
# <Brand> — Research Report
_Researched <date>_

## TL;DR
5 bullets: what the brand is, who it serves, how it wins, where it's weak, the biggest opportunity.

## The story
The brand told as a concrete narrative, origin to now, in 4–6 short paragraphs: the problem, the founder and why
they started, the turning points, where it stands today, and the open chapter ahead. Real names, places, dates and
numbers only. This is the base for scripts.

## Brand at a glance
Positioning, audience, voice, channels — the essentials from brand.md.

## Product at a glance
Lineup, hero product, how it works, pricing, what customers love and hate.

## Competitive landscape
Comparison table (top 4–5) and positioning map from competitors.md.

## What people are saying
Themes from reddit.md with the best verbatim quotes, and the questions people keep asking.

## What the science says
Each key claim with its verdict and the paper behind it, plus the most surprising facts, from papers.md.

## Opportunities
3–5 specific, actionable openings, each tied to evidence from the reports.

## Content and script angles
8–10 post or video ideas (LinkedIn, X, newsletter, reels). Each gets a one-line hook and the story, Reddit quote or
paper behind it. Favour founder storytelling, the science explained simply, and answers to the questions people ask.

## Sources
Key links, plus links to the five detailed reports.
```

Do not end with a checklist or tick boxes. Where a fact is unconfirmed, say so in the sentence that uses it. Resolve contradictions between the agents' reports by checking the sources. Keep every claim traceable to the detailed reports.

## 4. Finish

Tell the user where the report is. Give them the TL;DR and the top 3 opportunities in chat.
