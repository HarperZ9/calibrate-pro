"""Download and hash every binary-origin artifact recorded for a release."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.request import Request, build_opener

if __package__:
    from .verify_source_provenance import (
        _NAME,
        _SHA256,
        _AllowlistedRedirectHandler,
        _https_host,
        _normalise_host,
    )
else:  # pragma: no cover - exercised by the release script boundary
    from verify_source_provenance import (
        _NAME,
        _SHA256,
        _AllowlistedRedirectHandler,
        _https_host,
        _normalise_host,
    )

_TEMP_PREFIX = "calibrate-binary-proof-"
_CHUNK_SIZE = 1024 * 1024
_MAX_ARTIFACT_BYTES = 512 * 1024 * 1024


def _validate_lock(raw: object) -> list[dict[str, Any]]:
    if not isinstance(raw, dict) or raw.get("schema_version") != 1:
        raise ValueError("binary provenance lock must be a schema-1 JSON object")
    components = raw.get("components")
    if not isinstance(components, list) or not components:
        raise ValueError("binary provenance components must be a non-empty list")

    validated: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, candidate in enumerate(components):
        if not isinstance(candidate, dict):
            raise ValueError(f"component {index} must be a JSON object")
        name = candidate.get("name")
        version = candidate.get("version")
        artifact_url = candidate.get("artifact_url")
        digest = candidate.get("sha256")
        license_name = candidate.get("license")
        allowed_raw = candidate.get("allowed_final_hosts")
        if not isinstance(name, str) or not _NAME.fullmatch(name):
            raise ValueError(f"component {index} has an invalid name")
        if name in seen:
            raise ValueError(f"duplicate binary component name: {name}")
        seen.add(name)
        if not isinstance(version, str) or not version.strip():
            raise ValueError(f"{name}: version must be non-empty")
        if not isinstance(artifact_url, str):
            raise ValueError(f"{name}: artifact_url must be a string")
        artifact_host = _https_host(artifact_url, label=f"{name} artifact_url")
        if not isinstance(digest, str) or not _SHA256.fullmatch(digest):
            raise ValueError(f"{name}: sha256 must be 64 lowercase hexadecimal characters")
        if not isinstance(license_name, str) or not license_name.strip():
            raise ValueError(f"{name}: license must be non-empty")
        if (
            not isinstance(allowed_raw, list)
            or not allowed_raw
            or not all(isinstance(host, str) for host in allowed_raw)
        ):
            raise ValueError(f"{name}: allowed_final_hosts must be a non-empty string list")
        allowed_hosts = {_normalise_host(host) for host in allowed_raw}
        if len(allowed_hosts) != len(allowed_raw):
            raise ValueError(f"{name}: allowed_final_hosts contains duplicates")
        if artifact_host not in allowed_hosts:
            raise ValueError(f"{name}: recorded artifact host is not allowed")
        validated.append(
            {
                "name": name,
                "version": version,
                "artifact_url": artifact_url,
                "sha256": digest,
                "license": license_name,
                "allowed_final_hosts": allowed_hosts,
            }
        )
    return validated


def _safe_remove(work_dir: Path, parent: Path) -> None:
    if work_dir.parent != parent or not work_dir.name.startswith(_TEMP_PREFIX):
        raise RuntimeError(f"refusing unsafe binary-verification cleanup: {work_dir}")
    if work_dir.exists():
        if not work_dir.is_dir() or work_dir.is_symlink():
            raise RuntimeError(f"refusing altered binary-verification cleanup target: {work_dir}")
        shutil.rmtree(work_dir)


def verify_binary_provenance(
    lock_path: Path,
    *,
    opener: Callable[[Request], Any] | None = None,
    temp_parent: Path | None = None,
) -> list[dict[str, str]]:
    """Verify all locked binary origins and return their observed hashes."""
    raw = json.loads(Path(lock_path).read_text(encoding="utf-8"))
    components = _validate_lock(raw)
    parent = (Path(temp_parent) if temp_parent is not None else Path(tempfile.gettempdir())).resolve(strict=True)
    if not parent.is_dir():
        raise ValueError(f"temporary parent is not a directory: {parent}")
    work_dir = Path(tempfile.mkdtemp(prefix=_TEMP_PREFIX, dir=parent)).resolve(strict=True)
    if work_dir.parent != parent or not work_dir.name.startswith(_TEMP_PREFIX):
        raise RuntimeError(f"temporary directory escaped its parent: {work_dir}")

    verified: list[dict[str, str]] = []
    try:
        for index, component in enumerate(components):
            allowed_hosts = component["allowed_final_hosts"]
            active_opener = opener or build_opener(_AllowlistedRedirectHandler(allowed_hosts)).open
            request = Request(
                component["artifact_url"],
                headers={"User-Agent": "Calibrate-Pro-binary-provenance/1"},
            )
            target = work_dir / f"{index:02d}-{component['name']}.artifact"
            observed = hashlib.sha256()
            observed_bytes = 0
            with active_opener(request) as response:
                final_host = _https_host(response.geturl(), label=f"{component['name']} final URL")
                if final_host not in allowed_hosts:
                    raise ValueError(f"{component['name']}: redirect host is not recorded: {final_host}")
                with target.open("xb") as destination:
                    while True:
                        chunk = response.read(_CHUNK_SIZE)
                        if not chunk:
                            break
                        observed_bytes += len(chunk)
                        if observed_bytes > _MAX_ARTIFACT_BYTES:
                            raise ValueError(f"{component['name']}: artifact exceeds size ceiling")
                        observed.update(chunk)
                        destination.write(chunk)
            digest = observed.hexdigest()
            if digest != component["sha256"]:
                raise ValueError(
                    f"{component['name']}: SHA-256 mismatch: expected {component['sha256']}, observed {digest}"
                )
            verified.append({"name": component["name"], "sha256": digest})
        return verified
    finally:
        _safe_remove(work_dir, parent)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "lock_path",
        nargs="?",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "packaging" / "binary-provenance.lock.json",
    )
    args = parser.parse_args(argv)
    try:
        verified = verify_binary_provenance(args.lock_path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        parser.exit(1, f"binary provenance verification failed: {exc}\n")
    print(json.dumps({"verified": verified}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
