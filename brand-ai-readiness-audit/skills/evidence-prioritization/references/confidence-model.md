# Confidence model

| Tier | Meaning | Typical basis |
|---|---|---|
| high | Deterministic observation, reproducible by a third party | status codes, robots match, parse errors, ratios over >=3 samples |
| medium | Deterministic trigger with model interpretation, or a single-sample deterministic result | probe misses, template-cluster n<3 |
| low | Model judgement over text, both compared strings quoted | promise mismatch, materially-different descriptions |

Rules:
- LLM-only judgements are capped at medium confidence and medium severity. Every
  detector already enforces this at the source (each skill's own reference docs
  state it); this skill does not need to re-detect an LLM-judged finding to apply
  it, since the constraint is already reflected in what arrives.
- Confidence drops one tier when the supporting sample (`affected.total_in_scope`
  on the finding itself, standing in for "the template cluster's size") is fewer
  than 3 — applied uniformly here, in `scripts/normalize.py`, rather than inside
  each detector, precisely so the rule can't drift into four different
  implementations. A `high` confidence with `total_in_scope < 3` becomes
  `medium`; `medium` and `low` are unaffected (there is nowhere lower to demote
  a thin-sample `medium` to that isn't already `low`'s job).
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
