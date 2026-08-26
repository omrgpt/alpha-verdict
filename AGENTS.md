# Ruler Project Hook

This file wires alpha-verdict to the Ruler compliance library. It is a
pointer, not a copy: the library lives at
**https://github.com/omrgpt/ruler** (canonical, always current). Never paste
requirement text here â€” link instead â€” so rule updates propagate everywhere
without editing every project.

## How to fetch the requirements (any agent, any machine)

With GitHub access (works from any project folder):

```bash
# one-time shallow clone of just the rulebook
gh repo clone omrgpt/ruler "$TEMP/ruler" -- --depth 1
#   -> rules live in $TEMP/ruler/docs/requirements/*.md
#   -> machine audit: powershell -File $TEMP/ruler/scripts/audit-compliance.ps1 -Target <project-folder>
# or fetch a single requirement file without cloning:
gh api repos/omrgpt/ruler/contents/docs/requirements/security-authentication.md -H "Accept: application/vnd.github.raw"
```

Local checkout (this PC): `C:\Users\PC\Documents\ruler` â€” use it if present;
it is kept in sync with GitHub and is faster. If both exist and disagree,
**GitHub wins**.

## Requirements & Compliance Governance (mandatory)

The master compliance checklist tracks **190 stable IDs** (v4). These apply
to every project and every agent.

| Area | File in `docs/requirements/` | IDs |
|---|---|---|
| Security, auth, web vulnerabilities, pipeline | security-authentication.md | SEC-001â€¦087 |
| Mobile apps | mobile.md | MOB-064â€¦069 |
| Backend performance & deletion mechanics | backend-performance.md | PERF-069â€¦080 |
| Legal, GCC PDPL / GDPR, minors, AI privacy | legal-compliance-gcc-gdpr.md | LEG-075â€¦100 |
| SEO, metadata & production config | seo-metadata-production.md | SEO-096â€¦109 |
| Conversion & content | conversion-content.md | CRO-085â€¦104 |
| UI, UX & frontend | ui-ux-frontend.md | UIX-105â€¦119 |
| Analytics & monitoring | analytics-monitoring.md | OPS-120â€¦129 |
| Tool costs & paid-plan behavior | tooling-costs.md | cost map |

### Hard rules

1. **Read before you write.** Before touching code in an area, read the
   matching requirement file(s) from the library (see fetch methods above).
2. **Cite IDs.** Commits/PRs/change summaries must cite the requirement IDs
   implemented or affected (e.g., `Implements SEC-028, LEG-079`).
3. **Evidence or it isn't done.** Never claim a requirement is satisfied
   without concrete evidence (`file:line`, test name, audit output, dated
   console reference). Report `UNVERIFIED` instead of guessing.
4. **Run the audit after changes** covered by SEC/UIX/LEG items:
   `powershell -File <ruler>/scripts/audit-compliance.ps1 -Target <project-folder>`
   All FAIL findings must be fixed; remaining WARNs must be justified against
   their cited IDs. The audit auto-detects web vs non-web targets; force with
   `-ProjectType Web|Library` only when auto-detection is wrong.
5. **No secrets in documentation.** Rules live in the library; credentials
   live only in gitignored `.env` files / secret managers (SEC-002, SEC-003).
6. **IDs are permanent.** To propose new requirements, append the next unused
   ID in the correct category file IN THE RULER REPO and mirror the row in
   its master checklist â€” never renumber or reuse. Deviations need an entry
   in the Exceptions Register of the relevant file.

