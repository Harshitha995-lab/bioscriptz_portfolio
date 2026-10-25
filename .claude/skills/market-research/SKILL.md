---
name: market-research
description: Run full brand, product and competitor research on a company and combine it into one report with content and positioning takeaways. Use when the user asks to research a brand, a product, a client, a prospect or its competitors, or types /market-research followed by a brand name or URL.
argument-hint: <brand name or URL> [competitors to include]
---

# Market research

Research the brand in `$ARGUMENTS` using three specialist agents in parallel, then combine their work into one decision-ready report.

## 1. Set up

- Work out the brand name and website from `$ARGUMENTS`. If only a name is given, find the official site with one quick search. If the name is ambiguous (several companies share it), ask the user which one before going further.
- Note any competitors the user named.
- Make a slug from the brand name (lowercase, hyphens), and use the folder `research/<slug>/` in the project root.

## 2. Research in parallel

Launch all three agents in a single message so they run at the same time:

| Agent | Output file |
|---|---|
| `brand-researcher` | `research/<slug>/brand.md` |
| `product-researcher` | `research/<slug>/product.md` |
| `competitor-researcher` | `research/<slug>/competitors.md` |

Give each agent: the brand name, the website URL, the output file path, today's date, and (for `competitor-researcher`) any competitors the user named.

## 3. Combine

When all three finish, read their files and write `research/<slug>/report.md`:

```
# <Brand> — Research Report
_Researched <date>_

## TL;DR
5 bullets: what the brand is, who it serves, how it wins, where it's weak, the biggest opportunity.

## Brand at a glance
Positioning, audience, voice — the essentials from brand.md.

## Product at a glance
Lineup, hero product, how it works, pricing, what customers love and hate.

## Competitive landscape
Comparison table (top 4–5) and positioning map from competitors.md.

## Opportunities
3–5 specific, actionable openings, each tied to evidence from the three reports.

## Content angles
8–10 post/newsletter ideas for this brand or its founder (LinkedIn, X, newsletter), each with a one-line hook and the insight behind it. Favour founder storytelling, the science behind the product explained simply, and points of difference competitors aren't claiming.

## Open questions
What the public sources couldn't answer and is worth asking the founder.

## Detailed reports
Links to brand.md, product.md and competitors.md.
```

Resolve contradictions between the agents' reports by checking the sources; don't paper over them. Keep every claim traceable to the detailed reports.

## 4. Finish

Tell the user where the report is, and give them the TL;DR and the top 3 opportunities in chat.
