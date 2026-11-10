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

## Ghostwriting studio (Claude Code)

Charlie Hills' MIT-licensed skill packs live in `.claude/skills/`:
writing (`voice-builder`, `post-writer`, `hook-generator`, `content-matrix`,
`niche-research` and more), motion graphics (`brand-intake`, `vox-explainer`,
`animated-chart`, `launch-video`, `milestone-reveal` and more) and
`voiceprint`. Each person you write for gets a folder in `clients/`; see
`CLAUDE.md` for how the active client is chosen.
