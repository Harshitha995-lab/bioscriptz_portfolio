# bioscriptz_portfolio
## Research agent (Claude Code)

Run brand, product and competitor research on any company:

```
/market-research <brand name or URL> [competitors to include]
```

Five agents (`.claude/agents/`: brand, product, competitor, Reddit and
science researchers) research in parallel and the skill
(`.claude/skills/market-research/`) combines their work into
`research/<brand>/report.md`, a story-led report with opportunities and
content and script angles.
