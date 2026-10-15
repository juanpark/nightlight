"""Identifiers: prefixed ULIDs for new records, derived ids where retries must find the same record."""

import hashlib
import json

from ulid import ULID


def new_id(prefix: str) -> str:
    return f"{prefix}_{ULID()}"


def canonical_params(params: dict) -> str:
    return json.dumps(params, sort_keys=True, separators=(",", ":"))


def proposal_key(generation: int, turn_id: str, device_id: str, svc_id: str | None, action_type: str,
                 params: dict) -> str:
    raw = f"{generation}|{turn_id}|{device_id}|{svc_id}|{action_type}|{canonical_params(params)}"
    return hashlib.sha256(raw.encode()).hexdigest()


def action_id(key: str) -> str:
    return "act_" + key[:26]


def continuation_turn_id(action_id_: str) -> str:
    return f"cont_{action_id_}"
