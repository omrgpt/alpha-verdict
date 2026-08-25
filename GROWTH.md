# Growth runbook

This is the maintainer-facing distribution plan for AlphaVerdict. It complements
the code: nothing here changes the product's identity, and every tactic below
works only because the tool is honest by design.

## Positioning (locked)

> **Your LLM can write a trading strategy in 30 seconds. AlphaVerdict tells you
> if you can trust it.**

We are not an agent framework and we do not compete with Vibe-Trading,
ai-hedge-fund, freqtrade, or LEAN. They generate or execute strategies; AlphaVerdict
is the verification layer underneath all of them. Every public message — README,
HN title, Reddit post, tweet — uses this framing.

## Phase checklist

### Phase 0 — conversion funnel (ship before any promotion)

- [x] Hero SVG + verdict cards committed (`docs/assets/`, generated via
      `python scripts/make_assets.py`).
- [x] Real-data demo: `uvx alphaverdict demo --real`.
- [ ] Publish to PyPI: configure a trusted publisher on pypi.org
      (project `alphaverdict`, repo `omrgpt/alpha-verdict`, workflow
      `release.yml`), then tag `v0.2.0` and push.
- [x] PyPI publish step in `.github/workflows/release.yml`.
- [x] MCP server (`docs/mcp.md`) and GitHub Action (`docs/github-action.md`).
- [ ] Record a 15-second GIF of `demo --real` → report opening; embed at the top
      of the README above the hero (GIF beats SVG for motion proof).
- [x] Repo description, topics, and homepage set (see commands below).

Repo metadata commands:

```bash
gh repo edit omrgpt/alpha-verdict \
  --description "Adversarial research verdicts for stock strategies - deterministic reviewers that try to falsify your backtest before the market does" \
  --homepage "https://omrgpt.github.io/alpha-verdict/"

gh api repos/omrgpt/alpha-verdict/topics -X PUT \
  -f 'names[]=backtesting' -f 'names[]=finance' \
  -f 'names[]=point-in-time' -f 'names[]=python' \
  -f 'names[]=quantitative-finance' -f 'names[]=stocks' \
  -f 'names[]=strategy-validation' -f 'names[]=ai-agents' \
  -f 'names[]=llm' -f 'names[]=algorithmic-trading' \
  -f 'names[]=mcp' -f 'names[]=quant' -f 'names[]=investing'
```

### Phase 1 — audience before launch (2–4 weeks)

The ai-hedge-fund playbook: virattt built a numbered-agent thread first; the repo
hit #1 trending after the audience existed.

1. **Verdict-card content series** (the core engine). Run famous public strategies
   through AlphaVerdict and post the verdict card + top findings:

   - The golden-cross / RSI strategy from the most-viewed YouTube tutorial.
   - A ChatGPT-generated momentum screen ("I asked GPT for a quant strategy").
   - Classic factors (12-1 momentum, low-vol) as calibration baselines.

   Format: image of the verdict card → one-line finding summary → link to the
   full report.html. One card per day on X/Threads. These posts double as docs.

2. **Engage, don't announce**, in r/algotrading and r/quant threads about
   overfitting/backtests for 2+ weeks before launching. Answer with evidence,
   mention the tool only when directly relevant.

3. **Assemble a launch coalition** of 20–50 people (quant Twitter, colleagues,
   open-source friends) who agree to star within the first hours of launch day.

4. **Submit to awesome-quant** (Trading & Backtesting section):

   ```
   - [AlphaVerdict](https://github.com/omrgpt/alpha-verdict) - Adversarial research
     verdicts for stock strategies: five deterministic reviewers try to falsify your
     backtest (leakage, survivorship, costs, multiple testing).
   ```

5. **List in MCP directories** once the server ships in a release so agents can
   discover `alphaverdict mcp`.

### Phase 2 — the 48-hour concentrated launch

GitHub trending ranks star **velocity**. Python daily trending historically needs
roughly 50–100 stars/day; weekly lists ~250–400/week. Concentrate every channel
into a single window starting **Tuesday–Thursday, 9:00–12:00 PT**.

| Hour | Channel | Asset |
| --- | --- | --- |
| 0 | r/algotrading + r/quant | "Most backtests are lying to you — I built an adversarial auditor that proves it" + verdict cards |
| 6 | Hacker News | **Show HN: I built an audit council that tries to falsify your trading strategy** (submit yourself, immediately reply to comments) |
| 12–24 | Product Hunt | Launch with the GIF + real demo |
| 24 | X/Twitter thread | "We hit N stars in 24h" + best FAIL story + full report link |
| 36–48 | Dev.to cross-post, secondary subs (r/Python, r/algotrading follow-up), newsletter pitches | "How the council catches look-ahead leaks" technical deep-dive |

During the window: watch GitHub Insights traffic every few hours, reinforce
whichever channel leads, respond to every comment. After trending placement:
email 5–10 dev newsletters with "just launched + hit GitHub Trending" as proof.

### Phase 3 — compounding loops (months)

1. **GitHub Action adoption**: every PR comment is permanent distribution; add
   `post-comment: true` examples to awesome-actions lists.
2. **MCP registry listings**: agent users get verdicts without visiting GitHub;
   each registry entry is a standing discovery surface.
3. **Strategy Hub** (roadmap): community-submitted strategies with published
   verdicts → UGC flywheel where contributors share their own cards.
4. **Multi-language READMEs** (zh/ja/es) once traction appears — Vibe-Trading
   attributes significant reach to localized readmes.
5. **Ecosystem bridges**: vectorbt/backtrader strategy importers, OpenBB
   extension, qlib interop — each imports another community.
6. **Methodology authority**: deep dives on deflated Sharpe and prefix-invariance;
   reproduce one published factor study end-to-end and publish artifacts.
7. **Relaunch triggers**: every minor release with a headline feature (conformance
   kit, Strategy Hub, new reviewers) re-concentrates channels for another
   trending window. Each appearance raises the organic baseline (~10–20 stars/day
   per appearance historically), lowering the bar for the next one.

## Metrics that lead stars

Track weekly; stars are the lagging indicator.

| Metric | Target |
| --- | --- |
| Visitor → demo activation (clones/unique visitors running demo) | > 25% |
| Verdict reports shared externally per week | growing |
| MCP tool calls per week (once listed) | growing |
| Awesome-list / newsletter mentions per month | ≥ 1 |
| Projects rerunning weekly for 4+ weeks (research retention) | growing |
| Median time from issue opened to maintainer response (< 24h during launches) | < 24h |

## Anti-goals

- No purchased stars or coordinated fake bursts (velocity algorithms plus fake-star
  detection make this net-negative and reputation-fatal).
- No broker/live-trading features (red ocean; dilutes the trust wedge).
- No "AI picks" marketing (destroys the honesty positioning).
- No launch before the GIF, PyPI release, and metadata are live: first impressions
  per channel are non-renewable.
