"""Fail-closed tests for binary-origin provenance verification."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
VERIFIER = ROOT / "scripts" / "verify_binary_provenance.py"


class _Response:
    def __init__(self, payload: bytes, final_url: str) -> None:
        self.payload = payload
        self.final_url = final_url

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self, _size: int = -1) -> bytes:
        payload, self.payload = self.payload, b""
        return payload

    def geturl(self) -> str:
        return self.final_url


def _load():
    from scripts import verify_binary_provenance

    return verify_binary_provenance


def _lock(payload: bytes) -> dict[str, object]:
    return {
        "schema_version": 1,
        "components": [
            {
                "name": "widget-wheel-1.0",
                "version": "1.0",
                "artifact_url": "https://files.example.test/widget.whl",
                "sha256": hashlib.sha256(payload).hexdigest(),
                "license": "MIT",
                "allowed_final_hosts": ["files.example.test"],
            }
        ],
    }


def test_binary_verifier_hashes_and_cleans_unique_directory(tmp_path: Path) -> None:
    module = _load()
    payload = b"locked wheel bytes"
    lock_path = tmp_path / "lock.json"
    lock_path.write_text(json.dumps(_lock(payload)), encoding="utf-8")
    result = module.verify_binary_provenance(
        lock_path,
        opener=lambda _request: _Response(payload, "https://files.example.test/widget.whl"),
        temp_parent=tmp_path,
    )
    assert result == [{"name": "widget-wheel-1.0", "sha256": hashlib.sha256(payload).hexdigest()}]
    assert list(tmp_path.glob("calibrate-binary-proof-*")) == []


def test_binary_verifier_rejects_hash_and_redirect_mismatch(tmp_path: Path) -> None:
    module = _load()
    lock_path = tmp_path / "lock.json"
    lock_path.write_text(json.dumps(_lock(b"expected")), encoding="utf-8")
    with pytest.raises(ValueError, match="SHA-256"):
        module.verify_binary_provenance(
            lock_path,
            opener=lambda _request: _Response(b"wrong", "https://files.example.test/widget.whl"),
            temp_parent=tmp_path,
        )
    with pytest.raises(ValueError, match="redirect host"):
        module.verify_binary_provenance(
            lock_path,
            opener=lambda _request: _Response(b"expected", "https://evil.example/widget.whl"),
            temp_parent=tmp_path,
        )
