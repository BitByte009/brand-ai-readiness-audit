"""Observation store: stable IDs, append-only storage, and evidence resolution."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Dict, List, Optional


def iter_type(store: Dict[str, Any], observation_type: str) -> List[Dict[str, Any]]:
    return [obs for obs in store.get("observations", []) if obs.get("type") == observation_type]


def single(store: Dict[str, Any], observation_type: str) -> Optional[Dict[str, Any]]:
    matches = iter_type(store, observation_type)
    return matches[0] if matches else None


def http_fetches(store: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Requested URL to observation; latest observation wins on duplicate URLs."""
    return {obs["source_url"]: obs for obs in iter_type(store, "HTTP_FETCH")}


def renders(store: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    return {obs["source_url"]: obs for obs in iter_type(store, "RENDER")}


def page_classifications(store: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    return {obs["source_url"]: obs for obs in iter_type(store, "PAGE_CLASSIFICATION")}


def probes(store: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    return {obs["source_url"]: obs for obs in iter_type(store, "PROBE")}


def _normalize_type(type_name: str) -> str:
    return re.sub(r"[^A-Z0-9]+", "-", str(type_name).upper()).strip("-") or "OBS"


def make_observation(observation_type: str, source_url: str, value: Any) -> Dict[str, Any]:
    """Build a deterministic observation with a stable, source-scoped ID.

    Observation identity includes the observation type and source URL as well
    as the payload. Two pages produced from the same template can have
    byte-identical values without being the same observation, and must remain
    independently resolvable in the evidence store.
    """
    identity = {
        "type": str(observation_type),
        "source_url": str(source_url),
        "value": value,
    }
    payload = json.dumps(identity, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    digest = hashlib.sha1(payload.encode("utf-8")).hexdigest()[:16]
    observation_id = f"OBS-{_normalize_type(observation_type)}-{digest}"
    return {"id": observation_id, "type": observation_type, "source_url": source_url, "value": value}


class ObservationStore:
    """Append-only observation registry used by the audit orchestrator."""

    def __init__(self) -> None:
        self._records: Dict[str, Dict[str, Any]] = {}

    def add(self, observation: Dict[str, Any]) -> Dict[str, Any]:
        observation_id = observation.get("id")
        if not observation_id:
            raise ValueError("Observation missing id")
        self._records[observation_id] = observation
        return observation

    def resolve(self, observation_id: str) -> Optional[Dict[str, Any]]:
        return self._records.get(observation_id)

    def all(self) -> List[Dict[str, Any]]:
        return list(self._records.values())


def main() -> int:
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
