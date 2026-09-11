# Confidence model

| Tier | Meaning | Typical basis |
|---|---|---|
| high | Direct deterministic observation, reproducible by a third party | status codes, robots match, parse errors; one affected resource can be conclusive |
| medium | Deterministic trigger with model interpretation, or a thin sample explicitly extrapolated to a wider population | probe misses, template-cluster sample n<3 |
| low | Model judgement over text, both compared strings quoted | promise mismatch, materially-different descriptions |

Rules:
- LLM-only judgements are capped at medium confidence and medium severity. Every
  detector already enforces this at the source (each skill's own reference docs
  state it); this skill does not need to re-detect an LLM-judged finding to apply
  it, since the constraint is already reflected in what arrives.
- Confidence drops one tier only when the detector marks
  `affected.extrapolated: true` and fewer than 3 affected examples were observed.
  A small count alone is not uncertainty: one fetched 404 or one malformed
  JSON-LD block directly proves the defect on that resource. This keeps sample
  confidence separate from deterministic evidence strength.
- **The confidence floor is the `low` tier itself.** A finding whose confidence
  is `low` after the above adjustment is demoted into `demoted[]` — removed from
  `findings[]` entirely, its severity still computed and preserved, but never
  presented as an asserted defect. This is deliberate, not a bug: `low`
  confidence means the evidence itself is uncertain (an LLM-adjacent judgement
  with no corroborating deterministic signal, or a probe-only conclusion with no
  agreement from a second signal) — exactly the class of assertion the
  marketplace's false-positive control is built to keep out of the headline
  findings list. Borderline observations get an honest home in `demoted[]`
  instead of being forced into a binary "defect or nothing."
- Demotion happens *after* severity scoring, not before — a demoted finding's
  `scoring_trace` still shows what severity it would have carried, which is
  useful context for a report reader even though it isn't asserted as a defect.
