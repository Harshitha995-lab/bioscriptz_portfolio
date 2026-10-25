# bioscriptz_portfolio
## Research agent (Claude Code)

Run brand, product and competitor research on any company:

```
/market-research <brand name or URL> [competitors to include]
```

Three agents (`.claude/agents/`) research in parallel and the skill
(`.claude/skills/market-research/`) combines their work into
`research/<brand>/report.md`, with opportunities and content angles.
