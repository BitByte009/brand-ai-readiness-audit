"""Strict format/project-graph regressions and real offline CLI portability checks."""
import importlib
import json
import os
from pathlib import Path
import subprocess
import sys
import zipfile

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]
import validate_marketplace as validator
from scripts import package_submission


def write_skill(root, name, extra=""):
    path = root / "skills" / name
    path.mkdir(parents=True, exist_ok=True)
    (path / "SKILL.md").write_text(f"---\nname: {name}\ndescription: Analyze {name} when explicitly requested.\nallowed-tools: Bash Read\n---\n\n# {name}\n\n## When to use\nAnalyze {name}.\n\n## Inputs\nLocal input.\n\n## Procedure\nRead and analyze.\n\n## Outputs\nAnalysis.\n\n## Tool requirements\nLocal read access.\n" + extra)
    return path


@pytest.fixture
def package(tmp_path):
    root = tmp_path / "package"
    write_skill(root, "entry", "\n[Worker](../worker/SKILL.md)\n")
    write_skill(root, "worker")
    manifest = {"name": "test-marketplace", "version": "1.0", "description": "Test composition", "skills": [
        {"id": "entry", "path": "skills/entry", "entrypoint": True},
        {"id": "worker", "path": "skills/worker"}]}
    (root / "marketplace.json").write_text(json.dumps(manifest))
    return root


def change_manifest(root, change):
    path = root / "marketplace.json"
    data = json.loads(path.read_text())
    change(data)
    path.write_text(json.dumps(data))


def test_repository_and_minimal_composition_pass(package):
    assert validator.validate_marketplace(ROOT) == []
    assert validator.validate_marketplace(package) == []


def test_built_submission_validates_from_its_extracted_root(tmp_path):
    archive_path = tmp_path / "submission.zip"
    package_submission.package(archive_path)
    extracted = tmp_path / "extracted"
    with zipfile.ZipFile(archive_path) as archive:
        archive.extractall(extracted)
    assert validator.validate_marketplace(extracted) == []
    names = {path.relative_to(extracted).as_posix() for path in extracted.rglob("*") if path.is_file()}
    assert not any(name.startswith(("tests/", "design-docs/", "source-materials/")) for name in names)
    assert not any(name.endswith((".pdf", "KNOWLEDGE.md")) for name in names)


@pytest.mark.parametrize("change", [
    lambda m: m["skills"][0].pop("entrypoint"),
    lambda m: m["skills"][1].update(entrypoint=True),
    lambda m: m["skills"][0].update(entrypoint="true"),
    lambda m: m["skills"].append(dict(m["skills"][1])),
    lambda m: m["skills"][1].update(id="different"),
    lambda m: m["skills"][1].update(path="../outside"),
    lambda m: m["skills"][1].update(path="skills/missing"),
])
def test_rejects_invalid_manifest_graph(package, change):
    change_manifest(package, change)
    assert validator.validate_marketplace(package)
    assert validator.main(["--root", str(package)]) == 1


@pytest.mark.parametrize("replacement", [
    "name: entry\nname: entry\ndescription: Duplicate key",
    "name: Wrong-Name\ndescription: Wrong name",
    "name: entry\ndescription: ''",
    "name: entry\ndescription: [not, a, string]",
    "name: entry\ndescription: Bad tools\nallowed-tools: [Bash, Read]",
    "name: entry\ndescription: Bad tools\nallowed-tools: Bash, Read",
    "name: entry\ndescription: Bad metadata\nmetadata:\n  version: 1",
    "name: entry\ndescription: Bad field\nunknown-field: true",
    "name: entry\ndescription: Too long\ncompatibility: " + "x" * 501,
    "name: entry\ndescription: " + "x" * 1025,
    "[broken yaml",
])
def test_rejects_bad_frontmatter(package, replacement):
    path = package / "skills/entry/SKILL.md"
    old = path.read_text()
    body = old.split("---", 2)[2]
    path.write_text("---\n" + replacement + "\n---" + body)
    assert validator.validate_marketplace(package)


def test_valid_optional_metadata_is_supported(package):
    path = package / "skills/entry/SKILL.md"
    path.write_text(path.read_text().replace("allowed-tools: Bash Read", 'allowed-tools: Bash Read\ncompatibility: Python 3.12\nmetadata:\n  version: "1"'))
    assert validator.validate_marketplace(package) == []


def test_official_validation_cannot_silently_skip_missing_tool(package, monkeypatch):
    monkeypatch.setitem(sys.modules, "skills_ref", None)
    assert any("not installed" in e for e in validator.validate_marketplace(package, official=True))


def test_missing_instructions_and_duplicate_bodies_are_rejected(package):
    first = package / "skills/entry/SKILL.md"
    second = package / "skills/worker/SKILL.md"
    second.write_text(first.read_text().replace("name: entry", "name: worker"))
    assert any("duplicate skill instructions" in e for e in validator.validate_marketplace(package))
    second.write_text("---\nname: worker\ndescription: No procedure\n---\n")
    assert any("body contract" in e for e in validator.validate_marketplace(package))


def test_shared_reference_links_are_checked(package):
    references = package / "references"
    references.mkdir()
    (references / "runtime.md").write_text("[Missing dependency](../missing.txt)")
    assert any("broken resource" in e for e in validator.validate_marketplace(package))


@pytest.mark.parametrize("payload", ['{"name":"a","name":"b"}', '{"name":NaN}', '[]', '{'])
def test_rejects_non_strict_json(package, payload):
    (package / "marketplace.json").write_text(payload)
    assert validator.validate_marketplace(package)


def test_rejects_orphan_skill_and_unreachable_worker(package):
    write_skill(package, "orphan")
    path = package / "skills/entry/SKILL.md"
    path.write_text(path.read_text().replace("[Worker](../worker/SKILL.md)", ""))
    errors = validator.validate_marketplace(package)
    assert any("unlisted skill" in e for e in errors)
    assert any("not reachable" in e for e in errors)


def test_rejects_broken_and_escaping_links_and_orphan_resources(package):
    path = package / "skills/entry/SKILL.md"
    path.write_text(path.read_text() + "\n[Missing](references/missing.md)\n[Escape](../../../outside.md)\n")
    references = path.parent / "references"
    references.mkdir()
    (references / "unlinked.md").write_text("Unreachable instructions")
    scripts = path.parent / "scripts"
    scripts.mkdir()
    (scripts / "unlinked.py").write_text("def unused(): return 1\n")
    errors = validator.validate_marketplace(package)
    assert any("broken resource" in e for e in errors)
    assert any("escapes package" in e for e in errors)
    assert any("orphan reference" in e for e in errors)
    assert any("orphan script" in e for e in errors)


def test_rejects_symlinked_skill(package, tmp_path):
    target = write_skill(tmp_path / "external", "linked")
    (package / "skills/linked").symlink_to(target, target_is_directory=True)
    change_manifest(package, lambda m: m["skills"].append({"id": "linked", "path": "skills/linked"}))
    assert any("unsafe skill path" in e for e in validator.validate_marketplace(package))


def test_imported_helper_is_not_orphan_but_duplicate_scripts_fail(package):
    skill = package / "skills/entry"
    (skill / "scripts").mkdir()
    (skill / "scripts/run.py").write_text("from helper import work\n")
    (skill / "scripts/helper.py").write_text("def work(): return 1\n")
    path = skill / "SKILL.md"
    path.write_text(path.read_text() + "\n[Run](scripts/run.py)\n")
    assert validator.validate_marketplace(package) == []
    (skill / "scripts/copy.py").write_text("def work(): return 1\n")
    assert any("identical script copies" in e for e in validator.validate_marketplace(package))


def test_checks_schema_and_package_size(package, monkeypatch):
    (package / "schemas").mkdir()
    (package / "schemas/bad.json").write_text('{"type":"not-a-type"}')
    monkeypatch.setattr(validator, "MAX_PACKAGE_BYTES", 1)
    errors = validator.validate_marketplace(package)
    assert any("invalid JSON Schema" in e for e in errors)
    assert any("50 MB" in e for e in errors)


CLI_SCRIPTS = sorted(p for p in (ROOT / "skills").glob("*/scripts/*.py") if "argparse.ArgumentParser(" in p.read_text())


@pytest.mark.parametrize("script", CLI_SCRIPTS, ids=lambda p: p.stem)
def test_documented_cli_imports_from_unrelated_directory(script, tmp_path):
    # Preserve dependency locations but remove the project root/current directory
    # from PYTHONPATH: bootstrapping must be owned by the executable, not pytest.
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    env["PYTHONPATH"] = os.pathsep.join(p for p in env.get("PYTHONPATH", "").split(os.pathsep)
        if p and Path(p).resolve() != ROOT)
    result = subprocess.run([sys.executable, str(script), "--help"], cwd=tmp_path,
        env=env, text=True, capture_output=True, timeout=15)
    assert result.returncode == 0, result.stderr
    assert "usage:" in result.stdout


def test_shared_mechanics_are_imports_not_copied_implementations():
    from lib.common import observations, findings, extract, pages
    for folder, module_name in [("crawl-render-audit", "_util"), ("entity-semantic-audit", "_entity_util"),
                                ("trust-freshness-audit", "_trust_util"), ("engagement-audit", "_engagement_util")]:
        sys.path.insert(0, str(ROOT / "skills" / folder / "scripts"))
        module = importlib.import_module(module_name)
        assert module.iter_type is observations.iter_type
        assert module.http_fetches is observations.http_fetches
        assert module.make_finding is findings.make_finding
        assert module.affected_block is findings.affected_block
        if hasattr(module, "effective_pages"): assert module.effective_pages is pages.effective_pages
        if hasattr(module, "title_segments"): assert module.title_segments is extract.title_segments


def test_scoring_cli_passes_store_metadata(tmp_path, monkeypatch, capsys):
    sys.path.insert(0, str(ROOT / "skills/evidence-prioritization/scripts"))
    score = importlib.import_module("score")
    findings = tmp_path / "findings.json"
    store = tmp_path / "store.json"
    findings.write_text("[]")
    store.write_text('{"target":{"requested_url":"https://example.com/"}}')
    received = []
    monkeypatch.setattr(score, "prioritize_findings", lambda f, s: received.append((f, s)) or {"findings": []})
    assert score.main(["--findings", str(findings), "--store", str(store)]) == 0
    assert received == [([], json.loads(store.read_text()))]
    assert json.loads(capsys.readouterr().out) == {"findings": []}
