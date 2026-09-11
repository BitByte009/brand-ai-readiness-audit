# Shared finding contract

Detectors return JSON lists of unscored findings: check_id, category, title,
proposed base severity, confidence, mechanism, impact, observed signal, evidence
text, observation IDs, source URLs, affected scope and suggested action. Actions
include a summary, proposed priority, repair instructions and validation steps.
Use the [common builder](../lib/common/findings.py), not a copied skill-local builder.

[Prioritization](../skills/evidence-prioritization/SKILL.md) normalizes, deduplicates,
scores, ranks and assigns final IDs. [Orchestration](../skills/audit-orchestrator/SKILL.md)
binds evidence and assembles the [final report](../schemas/report.schema.json).
Provenance does not prove interpretation accuracy. Capability gaps and proactive
opportunities are not defects and do not enter severity totals. Keep distinct
mechanisms even when they concern the same artifact.
