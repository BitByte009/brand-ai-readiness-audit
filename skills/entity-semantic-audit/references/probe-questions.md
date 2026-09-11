# Canonical probe questions

The extraction probe runs in `<marketplace-root>/lib/site_observer/probe.py` over the machine-readable
text only — what a non-rendering fetcher would receive. A question the probe cannot
answer from that text is evidence, not opinion.

| # | Question | Consumed by |
|---|---|---|
| Q1 | What entity does this page belong to? | entity, engagement |
| Q2 | What kind of thing is that entity? | entity |
| Q3 | What does it offer or do? | entity |
| Q4 | Where does it operate, if that is relevant? | entity |
| Q5 | What question does this page answer? | crawl, engagement |
| Q6 | What does it cost, if applicable? | crawl, trust |
| Q7 | When was this last updated? | trust |
| Q8 | How would a visitor take the next step? | engagement |

Each answer records: answered yes/no, the answer, the supporting text span, and a hash
of the input text so the derivation is auditable. Temperature 0, fixed prompt,
structured output. All questions for a page are batched into one model call.
