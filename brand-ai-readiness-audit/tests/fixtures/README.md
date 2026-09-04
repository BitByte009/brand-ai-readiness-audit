# Adversarial fixture corpus

Static local sites served over loopback. Offline and deterministic: no network, no
flakiness, fast enough to run on every change, and it makes the generalization claim
testable rather than asserted.

Shape per fixture:

    <fixture-id>/
      site/          static files served at the fixture root
      expected.json  expected check IDs, expected severity band, and expected NON-findings

`expected.json` must list expected non-findings as well as findings. Half the value of
this corpus is proving we stay quiet on sites that do not need a feature.

Planned fixtures are enumerated in `corpus.json`. Content is Day 6 work.
