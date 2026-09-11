"""Build and verify the handbook deliverable ZIP from an explicit allowlist."""

import argparse
import ast
import json
import os
from pathlib import Path, PurePosixPath
import re
import tempfile
from urllib.parse import unquote, urlsplit
import zipfile


ROOT = Path(__file__).resolve().parents[1]
MAX_PACKAGE_BYTES = 50_000_000
FIXED_TIMESTAMP = (2026, 1, 1, 0, 0, 0)
ROOT_FILES = (
    "marketplace.json",
    "LICENSE",
    "requirements.txt",
    "SAFETY_AUDIT.md",
)
TEMPLATES = {
    "README.md": "scripts/submission_README.md",
    "references/skill-runtime.md": "scripts/submission_skill-runtime.md",
}
MODEL_SUFFIXES = {".pt", ".pth", ".onnx", ".safetensors", ".ckpt"}
LINK = re.compile(r"\[[^\]\n]*\]\(([^\s)]+)\)")


def _transform_skill(text):
    """Remove repository-only links from the staged copy, not the source file."""
    text = text.replace(
        "[project context](../../PROJECT_CONTEXT.md) decision D-6.",
        "the package's single-collection contract.",
    )
    lines = text.splitlines(keepends=True)
    result = []
    skipping_tests = False
    for line in lines:
        if line.rstrip() == "## Tests":
            skipping_tests = True
            continue
        if skipping_tests and line.startswith("Shared output semantics:"):
            skipping_tests = False
        if not skipping_tests:
            result.append(line)
    return "".join(result)


def _source_members(root):
    """Return (archive name, source path, optional transform) allowlist entries."""
    root = Path(root).resolve()
    entries = []
    for name in ROOT_FILES:
        entries.append((name, root / name, None))
    for archive_name, source_name in TEMPLATES.items():
        entries.append((archive_name, root / source_name, None))

    for path in sorted((root / "lib").rglob("*.py")):
        entries.append((path.relative_to(root).as_posix(), path, None))
    for path in sorted((root / "schemas").glob("*.json")):
        entries.append((path.relative_to(root).as_posix(), path, None))
    for path in sorted((root / "references").glob("*.md")):
        if path.name != "skill-runtime.md":
            entries.append((path.relative_to(root).as_posix(), path, None))
    for path in sorted((root / "skills").glob("*/SKILL.md")):
        entries.append((path.relative_to(root).as_posix(), path, _transform_skill))
    for pattern in ("*/references/*.md", "*/scripts/*.py"):
        for path in sorted((root / "skills").glob(pattern)):
            entries.append((path.relative_to(root).as_posix(), path, None))
    return entries


def _snapshot(root):
    members = []
    names = set()
    folded = set()
    for name, path, transform in _source_members(root):
        posix = PurePosixPath(name)
        if posix.is_absolute() or ".." in posix.parts or name != posix.as_posix():
            raise ValueError(f"unsafe archive path: {name}")
        if name in names or name.casefold() in folded:
            raise ValueError(f"duplicate archive path: {name}")
        if not path.is_file() or path.is_symlink():
            raise ValueError(f"required package file missing or unsupported: {path}")
        data = path.read_bytes()
        if transform:
            data = transform(data.decode("utf-8")).encode("utf-8")
        if path.suffix.lower() in MODEL_SUFFIXES:
            raise ValueError(f"model weights must not be submitted: {path}")
        members.append((name, data))
        names.add(name)
        folded.add(name.casefold())
    return sorted(members)


def _validate_manifest(files):
    try:
        manifest = json.loads(files["marketplace.json"])
        skills = manifest["skills"]
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid marketplace manifest: {exc}") from exc
    if not isinstance(skills, list) or not skills:
        raise ValueError("marketplace manifest must list at least one skill")
    entrypoints = [entry for entry in skills if entry.get("entrypoint") is True]
    if len(entrypoints) != 1:
        raise ValueError("marketplace manifest must designate exactly one entrypoint")
    for entry in skills:
        skill_path = entry.get("path")
        if not isinstance(skill_path, str) or f"{skill_path}/SKILL.md" not in files:
            raise ValueError(f"manifest skill is absent from package: {skill_path!r}")


def _validate_links(files):
    names = set(files)
    for name, data in files.items():
        if not name.endswith(".md"):
            continue
        for link in LINK.findall(data.decode("utf-8")):
            parsed = urlsplit(link)
            if parsed.scheme or parsed.netloc or not parsed.path:
                continue
            target = PurePosixPath(name).parent / unquote(parsed.path)
            normalized = []
            for part in target.parts:
                if part in ("", "."):
                    continue
                if part == "..":
                    if not normalized:
                        raise ValueError(f"link escapes package in {name}: {link}")
                    normalized.pop()
                else:
                    normalized.append(part)
            target_name = PurePosixPath(*normalized).as_posix()
            if target_name not in names and not any(item.startswith(target_name.rstrip("/") + "/") for item in names):
                raise ValueError(f"broken package link in {name}: {link}")


def _validate_files(members):
    files = dict(members)
    required = {"marketplace.json", "README.md", "LICENSE", "requirements.txt"}
    missing = sorted(required - files.keys())
    if missing:
        raise ValueError(f"required package files missing: {', '.join(missing)}")
    if sum(map(len, files.values())) > MAX_PACKAGE_BYTES:
        raise ValueError("uncompressed submission exceeds conservative 50 MB gate")
    _validate_manifest(files)
    _validate_links(files)
    for name, data in files.items():
        if name.endswith(".json"):
            try:
                json.loads(data)
            except (TypeError, ValueError, json.JSONDecodeError) as exc:
                raise ValueError(f"invalid JSON in {name}: {exc}") from exc
        if name.endswith(".py"):
            try:
                ast.parse(data.decode("utf-8"), filename=name)
            except (SyntaxError, UnicodeError) as exc:
                raise ValueError(f"invalid Python: {name}: {exc}") from exc


def _validate_archive(candidate, members):
    with zipfile.ZipFile(candidate) as archive:
        if archive.namelist() != [name for name, _ in members]:
            raise ValueError("archive contents differ from allowlist")
        if archive.testzip() is not None:
            raise ValueError("invalid submission archive")
        archived = [(name, archive.read(name)) for name in archive.namelist()]
    if archived != members:
        raise ValueError("archive bytes differ from source snapshot")


def package(output):
    """Write only a fully validated candidate, preserving an old ZIP on failure."""
    output = Path(output).resolve()
    members = _snapshot(ROOT)
    _validate_files(members)
    output.parent.mkdir(parents=True, exist_ok=True)
    descriptor, candidate_name = tempfile.mkstemp(
        prefix=".submission-", suffix=".zip", dir=output.parent
    )
    os.close(descriptor)
    candidate = Path(candidate_name)
    try:
        with zipfile.ZipFile(candidate, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            for name, data in members:
                info = zipfile.ZipInfo(name, date_time=FIXED_TIMESTAMP)
                info.compress_type = zipfile.ZIP_DEFLATED
                info.create_system = 3
                info.external_attr = 0o100644 << 16
                archive.writestr(info, data)
        if candidate.stat().st_size > MAX_PACKAGE_BYTES:
            raise ValueError("submission exceeds 50 MB")
        _validate_archive(candidate, members)
        os.replace(candidate, output)
    finally:
        candidate.unlink(missing_ok=True)
    return len(members), output.stat().st_size


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT / "dist/submission.zip")
    args = parser.parse_args()
    count, size = package(args.out)
    print(f"{args.out}: {count} files, {size:,} bytes; validated allowlist at ZIP root")
