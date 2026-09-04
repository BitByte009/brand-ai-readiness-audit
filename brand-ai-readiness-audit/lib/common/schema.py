"""JSON Schema loading and validation for report and observation shapes.

Inputs:  document, schema (or a well-known schema name)
Outputs: (is_valid, error_messages)
Nature:  deterministic

Never raises on an invalid document -- the whole point of validating the
final report mechanically (PROJECT_CONTEXT.md D-9: a schema-valid report is
always emitted) is defeated if a validation bug can itself crash the run.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Tuple

import jsonschema

MARKETPLACE_ROOT = Path(__file__).resolve().parents[2]
SCHEMAS_DIR = MARKETPLACE_ROOT / "schemas"

_SCHEMA_CACHE: Dict[str, Dict[str, Any]] = {}


def load_schema(name_or_path: str) -> Dict[str, Any]:
    """Load a schema by filename under schemas/ (e.g. "report.schema.json")
    or by an absolute path. Cached by resolved path."""
    path = Path(name_or_path)
    if not path.is_absolute():
        path = SCHEMAS_DIR / path
    key = str(path)
    if key not in _SCHEMA_CACHE:
        _SCHEMA_CACHE[key] = json.loads(path.read_text(encoding="utf-8"))
    return _SCHEMA_CACHE[key]


def validate_document(document: Any, schema: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """Validate `document` against `schema`, collecting every error rather
    than stopping at the first (so a caller can see the full picture, and so
    dropping one bad finding doesn't require re-running validation)."""
    validator = jsonschema.Draft202012Validator(schema)
    errors = [f"{'/'.join(str(p) for p in err.path) or '<root>'}: {err.message}" for err in validator.iter_errors(document)]
    return (not errors, errors)


def validate_report(report: Dict[str, Any]) -> Tuple[bool, List[str]]:
    return validate_document(report, load_schema("report.schema.json"))


def validate_observation(observation: Dict[str, Any]) -> Tuple[bool, List[str]]:
    return validate_document(observation, load_schema("observation.schema.json"))


def main() -> int:
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
