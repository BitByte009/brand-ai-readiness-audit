"""Regression cases for live collection, conservative evidence, and packaging."""
import json
import shutil
import sys
import zipfile
from pathlib import Path

import jsonschema
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
for skill in ("audit-orchestrator", "crawl-render-audit", "entity-semantic-audit", "engagement-audit", "trust-freshness-audit"):
    sys.path.insert(0, str(ROOT / "skills" / skill / "scripts"))
import run_audit
import detect_crawl
import detect_render
import detect_extract
import detect_engagement
import build_entity_profile
import build_claim_table
import detect_trust
from lib.common.observations import make_observation
from lib.common.budget import Budget
from lib.site_observer.sitemap import discover
from scripts import package_submission

URL = "https://example.com/"


def store_for(html, rendered=None):
    observations = [make_observation("HTTP_FETCH", URL, {"html": html, "status_code": 200})]
    if rendered is not None:
        observations.append(make_observation("RENDER", URL, {"html": rendered, "status": "ok", "status_code": 200}))
    return {"target": {"audited_host": "example.com"}, "observations": observations, "archetype": ""}


def audit(html):
    return run_audit.run_audit(URL, {"include_evidence": True}, fetch=lambda _: {"html": html, "status_code": 200},
                               robots_fetcher=lambda _: {"status": "missing"}, render_capability={"available": False}, sleep=lambda _: None)


def test_proactive_extraction_runs_through_entrypoint_and_renders():
    html = "<html lang='en'><body><main>" + "<p>Subscribe to our newsletter for weekly updates.</p>" * 20 + "<p>The plan costs $20 per month.</p></main></body></html>"
    report = audit(html)
    assert report["run"]["schema_valid"] and not report["run"]["skill_failures"]
    opportunities = [o for o in report["proactive_opportunities"] if o.get("check_id") == "D-EXTRACT-08"]
    assert len(opportunities) == 1
    import render_report
    assert opportunities[0]["opportunity"] in render_report.render_markdown(report)
    ids = {o["id"] for o in report["evidence_store"]["observations"]}
    assert set(opportunities[0]["observation_ids"]) <= ids
    schema = json.loads((ROOT / "schemas/observation.schema.json").read_text())
    jsonschema.validate(report["evidence_store"], schema)


def test_local_probe_abstains_from_absence_and_reports_limits():
    report = audit('<html lang="fr"><body><p>Bienvenue dans notre entreprise française.</p></body></html>')
    assert {"LANGUAGE_UNSUPPORTED", "PROBE_LIMITED", "SEARCH_UNAVAILABLE"} <= {c["reason"] for c in report["coverage"]}
    probes = [o for o in report["evidence_store"]["observations"] if o["type"] == "PROBE"]
    assert probes and probes[0]["value"]["questions"] == []
    assert not any(f['check_id'] == 'D-TRUST-06' for f in report['findings'])


def test_sitemap_discovery_is_bounded_and_collects_only_same_origin():
    calls = []
    def fetch(url):
        calls.append(url)
        if url.endswith('sitemap.xml'):
            body = '<sitemapindex>' + ''.join(f'<sitemap><loc>{URL}{n}.xml</loc></sitemap>' for n in range(5)) + '</sitemapindex>'
        else:
            body = f'<urlset><url><loc>{URL}hidden</loc></url><url><loc>https://other.example/private</loc></url></urlset>'
        return {"status_code": 200, "html": body}
    result = discover(URL, {"status": "missing"}, fetch)
    assert len(calls) == 3 and result["partial"]
    assert result["entries"] == [{"loc": URL + "hidden"}]


def test_unmeasured_sitemap_entries_do_not_count_as_dead():
    store = store_for('<html><body>Hello</body></html>')
    store['observations'].append(make_observation('SITEMAP', URL+'sitemap.xml', {'status':'ok', 'entries':[{'loc':URL+'unknown'}]}))
    assert detect_crawl.check_d_crawl_07(store) == []


def test_collector_follows_sitemap_only_page(monkeypatch):
    from lib.site_observer import collect as collector
    def fetch(url, **kwargs):
        html = f'<urlset><url><loc>{URL}hidden</loc></url></urlset>' if url.endswith('sitemap.xml') else '<html><body>Page</body></html>'
        return {'status_code':200, 'html':html}
    monkeypatch.setattr(collector, 'fetch_url', fetch)
    result = collector.collect(URL, robots_fetcher=lambda _: {'status':'missing'}, render_capability={'available':False}, sleep=lambda _:None)
    fetched = {o['source_url'] for o in result['store']['observations'] if o['type']=='HTTP_FETCH'}
    assert fetched == {URL, URL+'hidden'}


def test_finite_listing_is_not_infinite_scroll_failure():
    html = '<html><body>' + '<div class="card">Item</div>'*12 + '</body></html>'
    assert detect_render.check_d_render_05(store_for('', html)) == []


def test_rendered_external_links_are_not_internal_navigation_gap():
    html = '<html><body>' + ''.join(f'<a href="https://external.example/{n}">Source</a>' for n in range(10)) + '</body></html>'
    assert detect_render.check_d_render_03(store_for('', html)) == []


def test_measured_hidden_modal_is_not_reported():
    html = '<html><body><div role="dialog" class="modal">Newsletter</div></body></html>'
    store = store_for(html, html)
    store['observations'][-1]['value']['measurements'] = {'blocking_overlay':None}
    assert detect_engagement.check_e_answer_02(store) == []


def test_brand_aliases_exclude_page_topics_and_use_explicit_alias():
    html = '<html><head><title>Technical Manual | Acme</title><script type="application/ld+json">{"@type":"Organization","name":"Acme","alternateName":"Acme Labs","url":"https://example.com/","sameAs":["https://social.example/acme"]}</script></head><body><h1>Technical Manual</h1></body></html>'
    profile = build_entity_profile.build_entity_profile(store_for(html))
    assert profile['fields']['canonical_name']['value'] == 'Acme'
    assert 'Technical Manual' not in str(profile['fields']['aliases'])
    assert 'Acme Labs' in str(profile['fields']['aliases'])
    assert profile['fields']['official_domain']['value'] == URL


def test_different_time_periods_are_not_conflicting_customer_counts():
    store = store_for('<html><body>In 2020 we served 100 customers.</body></html>')
    store['observations'].append(make_observation('HTTP_FETCH', URL+'history', {'status_code':200, 'html':'<html><body>In 2025 we served 200 customers.</body></html>'}))
    table = build_claim_table.build_claim_table(store)
    assert len([c for c in table['claims'] if c.get('key') == 'customer_count']) == 2
    assert detect_trust.check_d_trust_03(store, table) == []


def test_local_transport_failure_is_coverage_not_site_defect():
    report = run_audit.run_audit(URL, robots_fetcher=lambda _: {'status':'error','failure_kind':'transport','error':'DNS unavailable'}, render_capability={'available':False})
    assert not report['findings'] and report['coverage']


def test_lifecycle_exception_emits_valid_incomplete_report(monkeypatch):
    def fail(*args, **kwargs):
        raise RuntimeError('collector failed')
    monkeypatch.setattr(run_audit, 'collect', fail)
    report = run_audit.run_audit(URL)
    assert report['coverage'][0]['reason'] == 'AUDIT_FAILED'
    assert run_audit.validate_report_schema(report)[0]


def test_global_budget_caps_later_stages():
    tick = [0]
    budget = Budget({'total_s':10}, clock=lambda:tick[0])
    budget.start_stage('raw_crawl')
    tick[0] = 9
    budget.start_stage('render_sample')
    assert budget.stage_time_left_s('render_sample','render_sample_s') == 1


def test_process_deadline_emits_incomplete_report():
    report = run_audit.run_with_deadline('http://127.0.0.1/', {}, timeout_s=0)
    assert report['coverage'][0]['reason'] == 'BUDGET_EXHAUSTED'
    assert run_audit.validate_report_schema(report)[0]


def test_repeated_brand_title_with_different_descriptions_is_not_duplicate_summary():
    first = '<html><title>Acme</title><meta name="description" content="Our team"><body>About us.</body></html>'
    second = '<html><title>Acme</title><meta name="description" content="Contact sales"><body>Contact us.</body></html>'
    store = store_for(first)
    store['observations'].append(make_observation('HTTP_FETCH', URL+'contact', {'status_code':200,'html':second}))
    assert detect_extract.check_d_extract_02(store) == []


def test_empty_id_absence_findings_get_replayable_page_anchors():
    import validate_report
    store = store_for('<html><body>Observed page</body></html>')
    kept, dropped = validate_report.bind_evidence([{'id':'F-001','source_urls':[URL],'observation_ids':[]}],store)
    assert not dropped
    assert kept[0]['observation_ids'] == [store['observations'][0]['id']]


def packaging_fixture(tmp_path):
    root = tmp_path/'repo'
    root.mkdir()
    for name in package_submission.ROOT_FILES:
        source = ROOT/name
        destination = root/name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
    for source_name in package_submission.TEMPLATES.values():
        source = ROOT/source_name
        destination = root/source_name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
    for directory in ('lib', 'schemas', 'references', 'skills'):
        shutil.copytree(ROOT/directory, root/directory)
    return root


def test_submission_zip_is_an_explicit_deliverable_allowlist(tmp_path, monkeypatch):
    root = packaging_fixture(tmp_path)
    (root/'.pytest_cache').mkdir()
    (root/'.pytest_cache'/'cache').write_text('not submitted')
    (root/'compiled.pyc').write_bytes(b'bytecode')
    (root/'PROJECT_CONTEXT.md').write_text('repository-only context')
    (root/'handbook.pdf').write_bytes(b'preserved but not submitted')
    (root/'tests').mkdir()
    (root/'tests'/'test_extra.py').write_text('assert True')
    (root/'skills'/'audit-orchestrator'/'KNOWLEDGE.md').write_text('maintainer notes')
    (root/'model.safetensors').write_bytes(b'not selected')
    monkeypatch.setattr(package_submission, 'ROOT', root)
    output = tmp_path/'submission.zip'
    package_submission.package(output)
    with zipfile.ZipFile(output) as archive:
        names = archive.namelist()
        assert names[0] == 'LICENSE'
        assert {'marketplace.json', 'README.md', 'requirements.txt',
                'skills/audit-orchestrator/SKILL.md'} <= set(names)
        assert not any(name.startswith(('tests/', 'source-materials/')) for name in names)
        assert not any(name.endswith(('.pdf', '.pyc', '.safetensors', 'KNOWLEDGE.md')) for name in names)
        assert 'PROJECT_CONTEXT.md' not in names
        readme = archive.read('README.md').decode()
        assert 'requirements-dev.txt' not in readme
        assert 'scripts/package_submission.py' not in readme
        assert '../../tests/' not in archive.read('skills/crawl-render-audit/SKILL.md').decode()


def test_packaging_is_reproducible_and_preserves_previous_archive_on_failure(tmp_path, monkeypatch):
    root = packaging_fixture(tmp_path)
    monkeypatch.setattr(package_submission, 'ROOT', root)
    output = tmp_path/'submission.zip'
    package_submission.package(output)
    original = output.read_bytes()
    package_submission.package(output)
    assert output.read_bytes() == original
    (root/'marketplace.json').unlink()
    with pytest.raises(ValueError, match='required package file'):
        package_submission.package(output)
    assert output.read_bytes() == original


def test_failed_response_cannot_supply_proactive_identity_evidence():
    import proactive
    store = store_for('<script type="application/ld+json">{"@type":"Organization","name":"Proxy error"}</script>')
    store['observations'][0]['value']['status_code'] = 503
    assert proactive.generate_proactive_opportunities(store, []) == []


def test_report_leads_with_ranked_actions_and_preserves_proactive_rationale():
    import render_report
    report = audit('<html><title>Page</title><body>Content</body></html>')
    report['proactive_opportunities'] = [{'title':'Verify identity','opportunity':'Review official profiles.',
        'expected_mechanism':'Match the observed entity.', 'expected_effect':'Reduce ambiguity.', 'source_urls':[URL]}]
    markdown = render_report.render_markdown(report)
    assert markdown.index('## First actions') < markdown.index('## Findings')
    assert 'Match the observed entity.' in markdown and 'Reduce ambiguity.' in markdown
    assert 'Observed scope: 1 pages crawled' in markdown


def test_nested_search_html_is_a_utility_not_substantive_noindex():
    import _util
    import _engagement_util
    assert _util.is_utility_path(URL+'docs/search.html')
    assert _engagement_util.is_utility_path(URL+'docs/search.html')
    assert not _util.is_utility_path(URL+'research/search-algorithms.html')


def test_hub_route_recognizes_observed_canonical_alias_in_navigation():
    hub = URL+'guide/'
    child = hub+'topic.html'
    store = {'observations':[
        make_observation('HTTP_FETCH',hub,{'status_code':200,'html':'<html><link rel="canonical" href="index.html"><body>Guide</body></html>'}),
        make_observation('HTTP_FETCH',child,{'status_code':200,'html':'<html><body><nav><a href="index.html">Guide</a></nav><main>Topic</main></body></html>'})]}
    assert detect_engagement.check_e_continue_03(store) == []


def test_explicit_retired_version_link_is_not_a_robots_defect():
    from lib.common.robots import parse_robots
    store = store_for('<html><body><a href="/v1/">Version one (EOL)</a><a href="/current/">Current</a></body></html>')
    store['observations'].append(make_observation('ROBOTS',URL+'robots.txt',parse_robots('User-agent: *\nDisallow: /v1/\nDisallow: /current/')))
    findings = detect_crawl.check_d_crawl_01(store)
    urls = {url for f in findings for url in f['source_urls']}
    assert URL+'v1/' not in urls and URL+'current/' in urls


def test_code_percentages_are_not_claims_and_inline_citation_is_preserved():
    store = store_for('<html><body><pre>50%</pre><p>20% faster (<a href="https://research.example/study">study</a>).</p></body></html>')
    table = build_claim_table.build_claim_table(store)
    claims = [c for c in table['claims'] if c['claim_type']=='superlative_stat']
    assert len(claims)==1 and claims[0]['text']=='20%' and claims[0]['attributed']


def test_missing_optional_description_alone_is_not_a_defect():
    store = store_for('<html><title>Documented installation steps</title><body><h1>Installation</h1><p>Install the package with these steps.</p></body></html>')
    assert detect_extract.check_d_extract_02(store) == []
