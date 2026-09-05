# Implementation and test-suite overfitting audit

## Scope and conclusion

Reviewed the common library, observation collector/crawler/renderer/probe,
classifier, all six skill script groups, their rule references, seven original
pytest modules, fixture builder/server/corpus, and marketplace validator.
The principal risk is proxy-to-conclusion leakage: a URL shape, markup spelling,
small sample, or site archetype is sometimes treated as proof of a defect.
There is no justification for replacing useful direct checks with an abstract
classifier. The changes below preserve those checks and correct bounded cases
where the existing observations support a more general rule.

This is not a claim that every remaining heuristic has been eliminated. The
remaining-risk inventory distinguishes measurement gaps from implementable fixes.

## Implemented changes: OLD ASSUMPTION → GENERALIZED RULE → NEW TEST

Test names below are in `tests/`; related rule references were updated with the
implementation. Existing positive tests remain unless they explicitly asserted
the retired assumption.

| OLD ASSUMPTION | GENERALIZED RULE | NEW TEST / regression |
|---|---|---|
| Equal observation payloads identify the same observation, even on different pages. | Identity includes type, source URL and payload; repeated templates retain independently resolvable evidence. | `test_deterministic_foundation.py::test_observation_ids_include_type_and_source_url_in_identity` |
| JSON-LD is a top-level object/array in an exactly spelled script MIME type. | Parse MIME essence case-insensitively; traverse graph/list/set containers while retaining meaningful nodes. Common extraction, entity profiling, classification and schema validation share these mechanics. | `test_extract_jsonld_flattens_containers_and_normalizes_type_uris`; `test_classify_archetype_from_graph_node_with_schema_type_uri`; `test_integration_entity_profile_reads_graph_identity_node_with_type_uri` |
| Schema types are bare strings in one spelling or the first list element. | Match supported Schema.org URI/compact/bare names across type lists, without treating an unrelated vocabulary's local name as Schema.org. | `test_schema_type_normalization_does_not_conflate_foreign_vocabularies`; `test_d_extract_04_validates_product_inside_parameterized_jsonld_graph` |
| Only the first item of a list-valued structured property can satisfy a requirement. | Resolve the required property across every list branch; retain deterministic missing-field and malformed-JSON checks. | `test_crawl_render_audit.py::test_d_extract_04_checks_dotted_property_across_all_list_elements` |
| Any query string means utility/facet content. | Query syntax alone does not establish a page role; primary content can be query-addressed. Keep conventional utility-role path checks. | `test_crawl_render_audit.py::test_is_utility_path` includes content, attribution and search queries; `test_engagement_audit.py::test_query_addressed_content_is_not_automatically_utility` |
| The affected sample is the entire in-scope population. | Unknown denominator remains null; no broad/narrow severity adjustment without a measured denominator. Both finding builders preserve this distinction. | `test_evidence_prioritization.py::test_unknown_population_does_not_infer_sitewide_scope` |
| One or two directly observed errors cannot have high confidence. | Sampling uncertainty applies to explicitly extrapolated claims, not direct observations. Keep the existing thin-extrapolation guard. | `test_normalize_preserves_single_direct_observation_confidence`; `test_normalize_drops_confidence_only_for_explicit_thin_extrapolation` |
| Shallow URLs imply important pages. | Boost the explicitly requested audit target when it is actually affected, regardless of path depth; context-only source URLs do not establish impact. | `test_score_explicitly_requested_deep_page_raises_severity`; `test_score_does_not_infer_importance_from_shallow_url_shape`; `test_context_url_does_not_promote_affected_page_importance` |
| A report should contain at most roughly 30% high/critical findings. | Score each defect on its evidence. Keep distribution telemetry, but adding unrelated findings cannot rewrite existing severity. | `test_distribution_guard_warns_but_preserves_evidence_backed_severities`; `test_finding_severity_is_invariant_to_unrelated_findings` |
| Same check ID plus a Jaccard overlap cutoff identifies duplicate defects. | Require same defect subtype (explicit dedupe key or mechanism) and overlapping affected instances; join connected components, not context URLs. | `test_dedupe_never_merges_distinct_subchecks_on_the_same_pages`; `test_dedupe_uses_affected_urls_not_context_urls_for_scope` |
| Merge scope can be reconstructed from all cited URLs; tied input order is immaterial. | Union affected samples, preserve the largest declared count as a lower bound, never sum overlapping counts, and break ties deterministically. | `test_dedupe_merge_does_not_double_count_heavily_overlapping_urls`; `test_dedupe_is_permutation_invariant_for_equal_confidence` |
| Accountability requires URLs containing about/contact. | Use role observations, named operator evidence and actionable contact channels. Retain exact conventional route segments as weak fallbacks, not arbitrary substrings. | `test_accountability_does_not_require_english_page_names`; `test_product_path_substrings_do_not_establish_accountability` |
| Any long number or mailto/tel prefix establishes contact. | Require phone-shaped visible evidence or a nonempty actionable destination; order IDs, copyright ranges and empty contact links do not qualify. | `test_empty_contact_and_author_links_are_not_named_channels`; product-path counterexamples include numeric IDs. |
| Named authors use an English byline or inline JSON-LD object. | Accept named metadata, itemprop, rel=author and graph-resolved authors in any script; an empty author link is not a name. | `test_author_signals_are_not_english_byline_specific`; `test_empty_contact_and_author_links_are_not_named_channels` |
| One attributed article absolves every article on a site. | Evaluate fetched classified articles independently; emit only the anonymous subset and its actual denominator/evidence IDs. | `test_author_findings_scope_only_anonymous_articles` |
| A copyright year more than two years old proves stale content. | Require an expired forward-framed claim; a rights date is not a content-review date. Preserve dated-event/offer arithmetic and archival guards. | `test_d_trust_02_copyright_alone_does_not_establish_staleness`; existing past/future event and offer tests remain. |
| A short brand name occurring inside any word proves identification. | Match escaped brand tokens at Unicode word boundaries in body, accessible image labels and title. | `test_short_brands_do_not_match_inside_unrelated_words` varies AI/Arc/One and unrelated words. |
| The final two hostname labels identify one organization. | Treat the audited host and its descendants as site-local, normalize www, and leave unrelated hosts external. Do not guess registrable domains or ownership. | `test_continuation_host_scope_does_not_guess_registrable_domains` covers co.uk, hosted tenants and valid descendants. |
| Printing corpus failures while exiting zero is adequate validation. | Exit nonzero for measured FP/FN, guardrail, coverage, skill, schema or quality failures. No fixture-name exceptions added. | `test_corpus_gate.py` exercises each failure class and a clean result. |

## Second pass: cross-script generalization

The first pass reviewed rule shape — URL forms, markup spellings, archetypes,
scope inference. It did not review the two primitives every text-based rule
sits on: how bytes become text, and how text becomes tokens. Both assumed
ASCII, and neither fails loudly. Reproduced end to end against a healthy Greek
site before fixing.

| OLD ASSUMPTION | GENERALIZED RULE | NEW TEST / regression |
|---|---|---|
| A response with no charset parameter is ISO-8859-1 (the HTTP/1.1 default `requests` applies). | Resolve encoding the way HTML5 and browsers do: transport charset, then BOM, then the document's own `<meta charset>`, then UTF-8 if the bytes are valid UTF-8, then Latin-1. Deterministic ladder, no character-set guessing library. | `test_deterministic_foundation.py::test_html_is_decoded_the_way_a_browser_decodes_it` (5 declaration styles); `test_an_explicit_transport_charset_still_wins_over_the_document`; `test_genuinely_latin1_bytes_are_not_forced_to_utf8` |
| Content words are `[a-z0-9]+`. | Tokenize on Unicode word characters, and approximate scripts written without spaces by character bigrams. ASCII output is unchanged. | `test_identical_text_is_recognized_as_identical_in_any_script`; `test_accented_words_are_not_split_at_the_accent`; `test_ascii_tokenization_is_unchanged_by_the_unicode_rewrite` |
| A word count is `len(text.split())`. | Charge spaceless runs at one word per three characters — below the real ratio, so the estimate under-counts rather than manufacturing substance. Spaced text scores exactly as before. | `test_word_thresholds_are_measurable_in_scripts_without_spaces` |
| A question heading ends in `"?"`. | Accept fullwidth, Arabic and Greek question marks; read a trailing `";"` as a question only when the heading is actually Greek. | `test_answered_questions_are_recognized_in_any_script`; `test_a_heading_ending_in_a_semicolon_is_not_a_question_in_latin_script` |

Downstream effect, measured: E-ANSWER-01 compares a title against its body by
word overlap. With an empty token set the overlap was always 0.0, so the check
fired on **every** content page of a healthy Greek site (3 of 3). It now fires
on none of them, and still fires on a genuine Greek title/body mismatch —
`test_engagement_audit.py::test_e_answer_01_never_fires_when_a_non_ascii_title_matches_its_body`
and `::test_e_answer_01_still_fires_on_a_genuine_non_ascii_mismatch`.

The corpus is entirely ASCII, so it could not have caught any of these and its
results are unchanged by the fixes. That is itself the finding: a corpus can
score 27/27 with 0 FP while an entire class of unseen sites is mishandled.

## Deterministic checks intentionally retained

- Observed HTTP failures, explicit robots/noindex signals, redirect loops,
  canonical-target failures and malformed structured data.
- Schema field checks, evidence-ID binding, report-schema validation, actual
  broken fragments and raw-versus-rendered observations.
- Crawl/request/time budgets and bounded sampling: these limit work, rather
  than proving defects. Changing them into inferred site quality would be wrong.
- Critical-check allowlist, confidence demotion and measured-scope modifiers.
  The 80% scope boundary and thin-extrapolation sample floor remain explicit
  calibration policy, not universal facts; no independent calibration dataset
  was available to justify substituting different numbers.
- Conventional role-name fallbacks and dated-claim phrase patterns remain
  precision-oriented fallbacks. Their language limits are not hidden.

## Remaining risks and why they were not mechanically rewritten

| Area reviewed | Remaining dependence / limitation | Appropriate next mechanism |
|---|---|---|
| `lib/common/robots.py`, crawl checks | Simplified agent/group/path matching; named bot lists; content-length and challenge phrase thresholds. | Protocol-conformance tests and per-agent policy evaluation; distinguish observed denial from inferred soft errors. Replacing bot names with another generic string would not solve this. |
| Collector, crawl, probe | Several detectors require sitemap, page-classification, alternate-host or model-probe observations that are not produced by the ordinary live path. Route-shape clusters are not actual template equivalence. | Add explicit producers/capabilities and coverage contracts before treating missing observations as negative evidence. Probe capability is presently unavailable by construction. |
| Site classification and applicability | One archetype plus type/path precedence is weak for hybrid, multilingual and noncommercial sites; type normalization fixes representation, not applicability. | Faceted page-purpose evidence and explicit abstention. Requires a contract migration across consumers rather than another path allowlist. |
| Crawl locale/duplicate/budget checks | Two-letter paths stand in for locales; a successful alternate host can stand in for duplicate content; query ratios stand in for wasted crawl work. | Compare language/alternate relationships, actual equivalent content and observed duplicate work/frontier exhaustion. Several requisite observations are not collected today. |
| Render checks | Three new links, ten repeated CSS-class siblings, page-shaped pagination URLs, adjacent disclosure siblings. A complete large collection can look incomplete. | Filter actual navigable internal destinations; require evidence of missing collection members or observed load-more behavior, and explicitly linked control/panel relationships. No new speculative collection-size cutoff was introduced. |
| Extract checks | File extensions, exact h1 structure, repeated metadata within route clusters, and any unlabelled image beside a probe miss remain imperfect proxies. | Representation headers, accessible document naming, actual template evidence and a relation between missing fact and media carrier. |
| Entity profile/checks | Title/H1 candidates, dominant-name proportions, automatic alias/legal-name assumptions, type keywords and sitewide Organization markup can confuse page topics with operator facts. | Provenanced subject identity and explicit aliases/relations; evaluate conflicts only for the same subject/property. Graph handling is improved, but is not full JSON-LD context expansion or entity resolution. |
| Engagement | Character counts approximate first screen; depth approximates arrival context; overlay classes/text approximate blocking; empty breadcrumbs can pass; continuation assumes internal next steps. | Viewport/occlusion and active-dialog observations, actual breadcrumb destinations, explicit task completion/continuation semantics. Brand word boundaries remain imperfect for scripts without word spacing. |
| Trust | English date/claim patterns; whole-page citation proximity and date inventories; archetype suppression; a named embedded organization can be mistaken for an operator. Exact role paths are still weak signals. | Bind source/date/operator evidence to the particular claim/subject. Preserve uncertainty when relationships are absent rather than invent them from global page text. |
| Prioritization | Mechanism prose is a fallback subtype key; sampled affected URLs cannot prove disjoint populations or reconstruct an exact union. | Stable detector-supplied subtype IDs and explicit population identity/full affected sets. Current counts are conservative lower bounds. |
| Tests and corpus | Most tests use hand-built stores and English, example.com/Acme-style fixtures. Corpus scoring mainly compares check-ID sets; recommendation/evidence length and severity enum checks do not prove substantive correctness. Confirmed/unreachable misses are tracked separately. | Continue metamorphic tests across brands, routes, languages and representations; add independently authored fixtures with multiplicity, scope and evidence-span assertions. The new CI gate enforces existing metrics, not semantic ground truth. |
| Packaging | `tests/validate_marketplace.py` is a pre-existing `NotImplementedError("skeleton")` stub. | Implement the promised packaging validator as separate unfinished work; do not count it as passing or silently remove it. |

## Verification

Baseline before this audit: **290 pytest tests passed**.

Final results:

- **338 pytest tests passed**, including 48 additional test cases over baseline.
- **19/19 real HTTP + Playwright/Chromium corpus fixtures passed**: 27 expected
  check-ID presences matched, 34 emitted findings, zero measured false positives,
  false negatives or guardrail violations; 34/34 passed each existing quality
  metric. Schema, coverage and skill-failure gates also passed (exit 0).
- `git diff --check` passed.
- `tests/validate_marketplace.py` was run and failed with its pre-existing
  `NotImplementedError("skeleton")`; packaging validation is not claimed green.

The initial browserless corpus run exposed two missing expected render-dependent
checks and one unexpected entity check. After installing isolated temporary
Playwright/Chromium dependencies, the full real-browser rerun passed without
changing fixture expectations. Raw results are in `tests/harness/results.json`.
Documented structurally untestable/confirmed misses remain separate from measured
corpus failures; zero measured misses does not mean complete capability coverage.
No corpus expected-findings lists were weakened to fit the implementation.

Reproduction from the package directory in this environment:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/private/tmp/brand-audit-test-deps PLAYWRIGHT_BROWSERS_PATH=/private/tmp/brand-audit-browsers /opt/homebrew/bin/python3.12 -m pytest -q
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/private/tmp/brand-audit-test-deps PLAYWRIGHT_BROWSERS_PATH=/private/tmp/brand-audit-browsers /opt/homebrew/bin/python3.12 tests/harness/run_corpus.py
```

The corpus requires permission to bind loopback HTTP and launch the browser.
