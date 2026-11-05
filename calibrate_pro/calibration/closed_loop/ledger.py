"""A hash-chained record of every loop step.

Each entry carries the digest of the one before it, so removing, reordering or
editing an entry changes every digest after it. The seal is the last digest.
This makes the record tamper-evident to anyone who recomputes it; it does not
prove who wrote it.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

GENESIS = "0" * 64


def canonical(payload: Any) -> str:
    """Serialize a payload deterministically for hashing."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _digest(previous: str, kind: str, payload: dict[str, Any]) -> str:
    text = canonical({"previous": previous, "kind": kind, "payload": payload})
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class Ledger:
    """Append-only step record with a running SHA-256 chain."""

    def __init__(self) -> None:
        self._entries: list[dict[str, Any]] = []

    @property
    def seal(self) -> str:
        return self._entries[-1]["digest"] if self._entries else GENESIS

    def append(self, kind: str, payload: dict[str, Any]) -> str:
        digest = _digest(self.seal, kind, payload)
        self._entries.append({"kind": kind, "payload": payload, "previous": self.seal, "digest": digest})
        return digest

    def entries(self) -> tuple[dict[str, Any], ...]:
        return tuple(dict(entry) for entry in self._entries)


def verify_chain(entries: tuple[dict[str, Any], ...]) -> bool:
    """Recompute every digest and answer whether the chain is intact."""
    previous = GENESIS
    for entry in entries:
        if entry["previous"] != previous:
            return False
        if _digest(previous, entry["kind"], entry["payload"]) != entry["digest"]:
            return False
        previous = entry["digest"]
    return True


__all__ = ["GENESIS", "Ledger", "canonical", "verify_chain"]
