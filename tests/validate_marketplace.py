"""Offline structural gate; official skill format plus explicit project rules.

Agent Skills does not standardize marketplace.json or require particular body
headings. Manifest schema, body sections, resource reachability and size checks
below are this marketplace's additional contract. Semantic purpose/decomposition
still require review. Install requirements-dev.txt; use --official to additionally
run the independently installed skills-ref reference validator (never auto-install).
"""
import argparse
import ast
from collections import defaultdict
import json
from pathlib import Path
import re
import unicodedata
from urllib.parse import unquote, urlsplit

import jsonschema
import yaml

ROOT = Path(__file__).resolve().parents[1]
ALLOWED_FIELDS = {"name", "description", "license", "compatibility", "metadata", "allowed-tools"}
SECTIONS = {"when to use", "inputs", "procedure", "outputs", "tool requirements"}
LINK = re.compile(r"\[[^\]\n]*\]\(([^\s)]+)\)")
MAX_PACKAGE_BYTES = 50_000_000


def unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate key: {key}")
        result[key] = value
    return result


class UniqueLoader(yaml.SafeLoader):
    pass


def unique_mapping(loader, node):
    return unique_pairs((loader.construct_object(k, deep=True), loader.construct_object(v, deep=True)) for k, v in node.value)


UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, unique_mapping)


def read_json(path):
    def reject_constant(value):
        raise ValueError(f"non-JSON numeric constant: {value}")
    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique_pairs, parse_constant=reject_constant)


def read_skill(path):
    text = path.read_text(encoding="utf-8")
    match = re.match(r"\A---\r?\n(.*?)\r?\n---(?:\r?\n|\Z)", text, re.S)
    if not match:
        raise ValueError("missing or unclosed YAML frontmatter")
    frontmatter = yaml.load(match.group(1), Loader=UniqueLoader)
    if not isinstance(frontmatter, dict):
        raise ValueError("frontmatter must be a mapping")
    return frontmatter, text[match.end():]


def validate_skill(path):
    try:
        meta, body = read_skill(path / "SKILL.md")
    except (OSError, ValueError, TypeError, yaml.YAMLError) as exc:
        return [str(exc)]
    errors = []
    if set(meta) - ALLOWED_FIELDS:
        errors.append("unsupported frontmatter fields")
    name = meta.get("name")
    if not isinstance(name, str) or not name or len(name) > 64:
        errors.append("name must be a nonempty string of at most 64 characters")
    elif (name != unicodedata.normalize("NFKC", name) or name != name.lower()
          or name != path.name or name.startswith("-") or name.endswith("-")
          or "--" in name or not all(c.isalnum() or c == "-" for c in name)):
        errors.append("invalid name or directory-name mismatch")
    for field, limit in (("description", 1024), ("compatibility", 500)):
        if field == "description" or field in meta:
            value = meta.get(field)
            if not isinstance(value, str) or not value.strip() or len(value) > limit:
                errors.append(f"{field} must be a nonempty string of at most {limit} characters")
    if "license" in meta and (not isinstance(meta["license"], str) or not meta["license"].strip()):
        errors.append("license must be a nonempty string")
    if "metadata" in meta and (not isinstance(meta["metadata"], dict) or not all(
            isinstance(k, str) and isinstance(v, str) for k, v in meta["metadata"].items())):
        errors.append("metadata must map strings to strings")
    if "allowed-tools" in meta:
        value = meta["allowed-tools"]
        if not isinstance(value, str) or not value.strip() or "," in value:
            errors.append("allowed-tools must be a space-separated string, not a list or comma-separated tokens")
    headings = {h.strip().lower() for h in re.findall(r"^##\s+(.+)$", body, re.M)}
    if not body.strip() or SECTIONS - headings:
        errors.append("project body contract missing sections: " + ", ".join(sorted(SECTIONS - headings)))
    if len((path / "SKILL.md").read_text().splitlines()) >= 500:
        errors.append("project size guidance: keep SKILL.md under 500 lines")
    return errors


def local_links(path, root, errors):
    result = set()
    for link in LINK.findall(path.read_text(encoding="utf-8")):
        parsed = urlsplit(link)
        if parsed.scheme or parsed.netloc or not parsed.path:
            continue
        target = (path.parent / unquote(parsed.path)).resolve()
        if not target.is_relative_to(root):
            errors.append(f"{path.relative_to(root)}: link escapes package: {link}")
        elif not target.exists():
            errors.append(f"{path.relative_to(root)}: broken resource link: {link}")
        else:
            result.add(target)
    return result


def validate_marketplace(root=ROOT, official=False):
    root = Path(root).resolve()
    errors = []
    try:
        manifest = read_json(root / "marketplace.json")
        schema_path = root / "schemas/marketplace.schema.json"
        # Tiny validator fixtures intentionally omit schemas; real extracted
        # packages validate against their own shipped schema, never ROOT's.
        schema = read_json(schema_path if schema_path.is_file() else ROOT / "schemas/marketplace.schema.json")
        jsonschema.Draft202012Validator.check_schema(schema)
        for error in jsonschema.Draft202012Validator(schema).iter_errors(manifest):
            errors.append(f"manifest/{'/'.join(map(str, error.path))}: {error.message}")
    except (OSError, ValueError, jsonschema.SchemaError) as exc:
        return [f"manifest: {exc}"]
    if errors:
        return errors
    entries = manifest["skills"]
    ids, paths, graph = set(), set(), {}
    bodies = defaultdict(list)
    official_validate = None
    if official:
        try:
            from skills_ref import validate as official_validate
        except ImportError:
            errors.append("--official requested but skills-ref is not installed")
    for entry in entries:
        path = (root / entry["path"]).resolve()
        if Path(entry["path"]).is_absolute() or ".." in Path(entry["path"]).parts or not path.is_relative_to(root):
            errors.append(f"unsafe skill path: {entry['path']}")
            continue
        if entry["id"] in ids or path in paths:
            errors.append(f"duplicate skill id/path: {entry['id']}")
        ids.add(entry["id"])
        paths.add(path)
        if entry["id"] != path.name:
            errors.append(f"manifest id/directory mismatch: {entry['id']}")
        errors.extend(f"{entry['id']}: {e}" for e in validate_skill(path))
        if official_validate:
            try:
                errors.extend(f"official/{entry['id']}: {e}" for e in official_validate(path))
            except Exception as exc:
                errors.append(f"official/{entry['id']}: validation failed: {exc}")
        skill_md = path / "SKILL.md"
        if skill_md.is_file():
            try:
                _, body = read_skill(skill_md)
                if body.strip(): bodies[body.strip()].append(entry["id"])
            except (OSError, ValueError, TypeError, yaml.YAMLError):
                pass  # already diagnosed by validate_skill
            graph[path] = {p.parent for p in local_links(skill_md, root, errors) if p.name == "SKILL.md"}
            # Every instruction resource must be discoverable directly (progressive disclosure).
            linked = local_links(skill_md, root, [])
            for resource in (path / "references").glob("*.md"):
                if resource.resolve() not in linked:
                    errors.append(f"{entry['id']}: orphan reference: {resource.name}")
            scripts = {p.stem: p.resolve() for p in (path / "scripts").glob("*.py")}
            pending_scripts = [p for p in linked if p in scripts.values()]
            used_scripts = set()
            while pending_scripts:
                script = pending_scripts.pop()
                if script in used_scripts: continue
                used_scripts.add(script)
                try:
                    tree = ast.parse(script.read_text())
                    for node in ast.walk(tree):
                        names = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module] if isinstance(node, ast.ImportFrom) else []
                        pending_scripts.extend(scripts[n] for n in names if n in scripts)
                except (SyntaxError, UnicodeError):
                    pass  # syntax errors reported below
            for script in sorted(set(scripts.values()) - used_scripts):
                errors.append(f"{entry['id']}: orphan script (neither linked nor imported): {script.name}")
    for same in bodies.values():
        if len(same) > 1:
            errors.append(f"duplicate skill instructions require review: {same}")
    discovered = {p.parent.resolve() for p in root.rglob("SKILL.md")}
    for orphan in sorted(discovered - paths):
        errors.append(f"unlisted skill: {orphan.relative_to(root)}")
    for directory in (root / "skills").iterdir() if (root / "skills").is_dir() else []:
        if directory.is_dir() and not directory.name.startswith((".", "__")) and directory.resolve() not in paths:
            errors.append(f"orphan skill directory: {directory.name}")
    entrypoint = next(entry for entry in entries if entry.get("entrypoint") is True)
    pending, reached = [(root / entrypoint["path"]).resolve()], set()
    while pending:
        path = pending.pop()
        if path in reached: continue
        reached.add(path)
        pending.extend(graph.get(path, set()) - reached)
    for path in sorted(paths - reached):
        errors.append(f"skill not reachable from entrypoint instructions: {path.name}")
    duplicates = defaultdict(list)
    size = 0
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            errors.append(f"package symlink not supported: {path.relative_to(root)}")
            continue
        if not path.is_file(): continue
        size += path.stat().st_size
        if path.suffix == ".md" and path.relative_to(root).parts[0] in {"skills", "references"} and path.name != "SKILL.md":
            local_links(path, root, errors)
        if path.suffix == ".py" and "skills" in path.relative_to(root).parts:
            try:
                ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            except (SyntaxError, UnicodeError) as exc:
                errors.append(f"invalid Python: {path.relative_to(root)}: {exc}")
            duplicates[path.read_bytes()].append(path.relative_to(root))
    for same in duplicates.values():
        if len(same) > 1:
            errors.append(f"identical script copies require review: {same}")
    for schema_path in sorted((root / "schemas").glob("*.json")):
        try:
            schema = read_json(schema_path)
            jsonschema.validators.validator_for(schema).check_schema(schema)
        except (OSError, ValueError, jsonschema.SchemaError) as exc:
            errors.append(f"invalid JSON Schema {schema_path.name}: {exc}")
    if size > MAX_PACKAGE_BYTES:
        errors.append(f"uncompressed package exceeds conservative 50 MB gate: {size} bytes")
    return sorted(set(errors))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--official", action="store_true")
    args = parser.parse_args(argv)
    errors = validate_marketplace(args.root, args.official)
    if errors:
        print("FAIL\n" + "\n".join(errors))
        return 1
    print("PASS: manifest, skill contracts, references, composition, scripts, schemas and package size" + ("; skills-ref passed" if args.official else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
