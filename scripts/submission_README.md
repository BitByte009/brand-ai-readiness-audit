# Brand AI Readiness Audit

A provider-neutral Agent Skill Marketplace package for auditing a public
website's AI discoverability and the experience of visitors arriving from an AI
answer. It emits one evidence-backed report with prioritized recommendations.
It is recommend-only and never applies changes to the audited website.

## Six skills, one entrypoint

| Skill | Responsibility |
|---|---|
| **audit-orchestrator** — entrypoint | Collect once, compose detectors and prioritization, bind evidence, validate, and emit |
| crawl-render-audit | Crawl permission, rendering/extraction gaps, metadata, and structured data |
| entity-semantic-audit | Entity identity, explicit facts, and cross-page consistency |
| trust-freshness-audit | Freshness, attribution, accountability, and evidence-backed corroboration |
| engagement-audit | Cold-arrival orientation, answer access, and onward navigation |
| evidence-prioritization | Shared scoring, aggregation, deduplication, and action ranking |

The [manifest](marketplace.json) lists every skill and designates exactly one
entrypoint. The orchestrator performs one collection pass, the detector skills
read that observation store, and evidence prioritization produces the final
ranking. Proactive opportunities remain separate from asserted findings and
severity totals.

## Install and run

Python 3.12 is tested. From the extracted marketplace root:

```sh
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python skills/audit-orchestrator/scripts/run_audit.py https://example.com --out-dir output --save-evidence
```

On Windows, activate `.venv\Scripts\activate`. Optional Playwright 1.48+ and
Chromium enable rendering; without them, render-dependent checks are reported as
coverage gaps. No AI provider account or model weights are needed.

The input is a public URL or bare domain. `--max-pages N` overrides the default
30-page raw crawl budget. Keep this package's skills, libraries, references, and
schemas together.

The selected output directory receives:

- `report.json`: the required report plus scope, coverage, evidence references,
  and diagnostics.
- `report.md`: observed scope, ranked actions, detailed evidence, suggested
  fixes, and verification guidance.
- `observations.json`: optional evidence snapshot enabled by `--save-evidence`.

Each finding includes an ID, title, severity, evidence, and suggested action;
the report also includes the audited site, audit time, severity counts, summary,
and priority. Inspect `coverage` and `run.skill_failures`: zero findings do not
prove complete or clean coverage.

## Safety and limitations

Only anonymous, same-origin GET/HEAD requests pass the shared robots-aware
transport. Requests are paced and capped, and HTTP 429/503 responses stop further
requests. Public-address pinning, response limits, and browser routing restrict
private destinations, credentials, forms, background channels, and secondary
navigation. Run in an unprivileged sandbox with no secrets and suitable resource
limits. Local files in the specifically selected output directory may be
overwritten. See [SAFETY_AUDIT.md](SAFETY_AUDIT.md) and the
[shared runtime contract](references/skill-runtime.md) for exact boundaries.

Unsupported checks become explicit coverage gaps; the audit never invents
missing render, geometry, semantic, search, or corroboration evidence.

License: [MIT](LICENSE).
