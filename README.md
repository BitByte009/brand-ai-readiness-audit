# Brand AI Readiness Audit

A provider-neutral Agent Skill Marketplace for auditing a public website's AI
discoverability and the experience of visitors arriving from an AI answer.
It produces one evidence-backed report with prioritized recommendations.
**Recommend-only: it never applies changes to the audited website.**

## Six skills, one entrypoint

| Skill | Responsibility |
|---|---|
| **audit-orchestrator** — entrypoint | Collect once, compose detectors and prioritization, bind evidence, validate and emit |
| crawl-render-audit | Crawl permission, rendering/extraction gaps, metadata and structured data |
| entity-semantic-audit | Entity identity, explicit facts and cross-page consistency |
| trust-freshness-audit | Freshness, attribution, accountability and corroboration when evidence exists |
| engagement-audit | Cold-arrival orientation, answer access and onward navigation |
| evidence-prioritization | Shared scoring, aggregation, deduplication and action ranking |

The [manifest](marketplace.json) designates exactly one entrypoint. Shared
`lib/site_observer` collects robots, sitemaps, raw pages, sampled renders, page
classifications and positive text-span probes. The four detector skills read the
same observation store without fetching again. Prioritization combines their
outputs; the entrypoint binds evidence and emits the final report. Proactive
opportunities remain separate from asserted findings and severity totals.

## Install and run

Python 3.12 is tested. From this marketplace root:

```sh
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
python -m pip install 'playwright>=1.48'
python -m playwright install chromium
python skills/audit-orchestrator/scripts/run_audit.py https://example.com --out-dir output --save-evidence
```

For runtime-only installation, use `requirements.txt`. Playwright/Chromium are
optional; missing browser capability is explicitly reported. On Windows activate
`.venv\Scripts\activate` instead. No AI provider account or model weights are needed.

Input is a public URL or bare domain. Optional `--max-pages N` overrides the default
30-page raw crawl budget. Keep all skills, libraries and schemas together.

Outputs in the selected directory:

- `report.json`: required Adobe schema plus scope, coverage, evidence references and diagnostics.
- `report.md`: observed scope, first three ranked actions, detailed evidence, fixes and verification.
- `observations.json`: optional evidence snapshot enabled by `--save-evidence`.

Inspect `coverage` and `run.skill_failures`; zero findings do not prove a clean site.
`run.elapsed_s` measures library-audit time. The CLI worker has a 280-second deadline;
a timeout emits an incomplete report. A deadline is not proof of complete coverage.

## Validate

```sh
python tests/validate_marketplace.py
python -B -m pytest -q -p no:cacheprovider
python tests/harness/run_corpus.py
python tests/harness/run_safety.py
```

The last two commands require Chromium and permission to run a local loopback server.
The corpus measures expected detections and explicit false-positive traps; its known
capability gaps are also reported. It is not an unseen-site accuracy benchmark.
The optional official `skills-ref` validator can be invoked with
`python tests/validate_marketplace.py --official` after installing it as documented
in `requirements-dev.txt`.

## Safety and limitations

Only anonymous, same-origin GET/HEAD requests pass the shared robots-aware transport.
Requests are paced and capped; HTTP 429/503 stops further requests. Public-address
pinning, response limits and browser routing restrict private destinations, credentials,
forms, active background channels and secondary navigation. Use an unprivileged host
sandbox with no secrets and suitable process/memory limits. Local output files may
be overwritten. See [SAFETY_AUDIT.md](SAFETY_AUDIT.md) for the exact boundary.

English vocabulary, OCR, semantic absence, external corroboration, SPA/hash navigation
and cross-origin rendering have documented limits. Unsupported checks become coverage
gaps; the audit does not invent evidence to fill them. See
[FINAL_COMPLIANCE.md](FINAL_COMPLIANCE.md) for the handout requirement matrix and
[SUBMISSION_FIXES.md](SUBMISSION_FIXES.md) for earlier fixes and verification.

## Submission

This workspace is the marketplace root. Build the submission with:

```sh
python scripts/package_submission.py
```

Submit `dist/submission.zip`. `marketplace.json` is directly at the ZIP root. The
builder excludes caches, environments, Git metadata and generated reports; rejects
recognized model-weight files; verifies integrity and the 50 MB limit; and replaces
the old ZIP only after validating its candidate. Stable metadata makes builds
reproducible. `.gitignore` alone does not filter a manually created ZIP.

The official handout and design documents are preserved. Earlier audit notes are
marked historical. SKILL.md links are relative to each skill root; their commands
run from that skill directory. Root README commands run from this directory.

License: [MIT](LICENSE).
