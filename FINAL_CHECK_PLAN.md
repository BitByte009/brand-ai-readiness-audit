# Final submission plan

Source of truth: official Round 3 handout, pages 1–6. Internal taxonomy IDs are
not mandatory Adobe checks. Competition placement cannot be verified locally.

1. Revalidate explicit rules: root manifest, one entrypoint, every skill, composition,
   both problem domains, required report fields, recommendations, safety, portability,
   ZIP size/model weights, runtime and README. Record evidence and uncertainty.
2. Improve reviewer and operator experience: measured scope, clear incomplete status,
   first actions and fuller proactive rationale. Keep report content derived from evidence.
3. Correct entrypoint instructions and make packaging atomic and reproducible, excluding
   caches and generated outputs without losing required dependencies.
4. Validate with offline regression tests, browser corpus, adversarial safety scenarios,
   marketplace checks and tests against a fresh extraction of the candidate ZIP.
5. Replace dist/submission.zip only after candidate validation. Record checksum, size,
   test results, explicit requirement matrix and residual limitations.

Do not weaken safety to expand coverage, invent external evidence, claim an unseen-site
benchmark, or turn optional internal checks into invented handout requirements.

Implementation and source-rule review complete. Final candidate extraction is the last release gate; completion is recorded in the delivery message.
