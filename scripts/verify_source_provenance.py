"""Download and verify every source archive recorded for a release.

The verifier deliberately accepts only HTTPS URLs, exact SHA-256 digests, and
literal redirect hosts recorded in the lock.  Its download directory is unique
to each invocation and the cleanup guard refuses to remove any other path.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

_TEMP_PREFIX = "calibrate-source-proof-"
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_HOST = re.compile(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?\Z")
_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+-]*\Z")
_CHUNK_SIZE = 1024 * 1024


def _normalise_host(host: str) -> str:
    normalised = host.rstrip(".").lower()
    if not _HOST.fullmatch(normalised) or ".." in normalised:
        raise ValueError(f"invalid recorded host: {host!r}")
    return normalised


def _https_host(url: str, *, label: str) -> str:
    parsed = urlsplit(url)
    if parsed.scheme.lower() != "https" or not parsed.hostname:
        raise ValueError(f"{label} must be an absolute HTTPS URL: {url!r}")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError(f"{label} must not contain credentials: {url!r}")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError(f"{label} contains an invalid port: {url!r}") from exc
    if port not in (None, 443):
        raise ValueError(f"{label} must use the standard HTTPS port: {url!r}")
    return _normalise_host(parsed.hostname)


def _validate_lock(raw: object) -> list[dict[str, Any]]:
    if not isinstance(raw, dict):
        raise ValueError("source provenance lock must be a JSON object")
    if raw.get("schema_version") != 1:
        raise ValueError("source provenance lock schema_version must be 1")
    if raw.get("modifications") != []:
        raise ValueError("source provenance modifications must be the empty list")
    components = raw.get("components")
    if not isinstance(components, list) or not components:
        raise ValueError("source provenance components must be a non-empty list")

    validated: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, candidate in enumerate(components):
        if not isinstance(candidate, dict):
            raise ValueError(f"component {index} must be a JSON object")
        name = candidate.get("name")
        version = candidate.get("version")
        source_url = candidate.get("source_url")
        digest = candidate.get("sha256")
        license_name = candidate.get("license")
        allowed_raw = candidate.get("allowed_final_hosts")
        if not isinstance(name, str) or not _NAME.fullmatch(name):
            raise ValueError(f"component {index} has an invalid name")
        if name in seen:
            raise ValueError(f"duplicate source component name: {name}")
        seen.add(name)
        if not isinstance(version, str) or not version.strip():
            raise ValueError(f"{name}: version must be non-empty")
        if not isinstance(source_url, str):
            raise ValueError(f"{name}: source_url must be a string")
        source_host = _https_host(source_url, label=f"{name} source_url")
        if not isinstance(digest, str) or not _SHA256.fullmatch(digest):
            raise ValueError(f"{name}: sha256 must be 64 lowercase hexadecimal characters")
        if not isinstance(license_name, str) or not license_name.strip():
            raise ValueError(f"{name}: license must be non-empty")
        if not isinstance(allowed_raw, list) or not allowed_raw:
            raise ValueError(f"{name}: allowed_final_hosts must be a non-empty list")
        if not all(isinstance(host, str) for host in allowed_raw):
            raise ValueError(f"{name}: allowed_final_hosts entries must be strings")
        allowed_hosts = {_normalise_host(host) for host in allowed_raw}
        if len(allowed_hosts) != len(allowed_raw):
            raise ValueError(f"{name}: allowed_final_hosts contains duplicates")
        if source_host not in allowed_hosts:
            raise ValueError(f"{name}: recorded source host is not allowed")
        validated.append(
            {
                "name": name,
                "version": version,
                "source_url": source_url,
                "sha256": digest,
                "license": license_name,
                "allowed_final_hosts": allowed_hosts,
            }
        )
    return validated


class _AllowlistedRedirectHandler(HTTPRedirectHandler):
    def __init__(self, allowed_hosts: set[str]) -> None:
        super().__init__()
        self._allowed_hosts = allowed_hosts

    def redirect_request(
        self,
        request: Request,
        file_pointer: Any,
        code: int,
        message: str,
        headers: Any,
        new_url: str,
    ) -> Request | None:
        absolute_url = urljoin(request.full_url, new_url)
        host = _https_host(absolute_url, label="redirect URL")
        if host not in self._allowed_hosts:
            raise ValueError(f"redirect host is not recorded: {host}")
        return super().redirect_request(request, file_pointer, code, message, headers, absolute_url)


def _safe_remove(work_dir: Path, parent: Path) -> None:
    if work_dir.parent != parent or not work_dir.name.startswith(_TEMP_PREFIX):
        raise RuntimeError(f"refusing unsafe source-verification cleanup: {work_dir}")
    if work_dir.exists():
        if not work_dir.is_dir() or work_dir.is_symlink():
            raise RuntimeError(f"refusing altered source-verification cleanup target: {work_dir}")
        shutil.rmtree(work_dir)


def verify_source_provenance(
    lock_path: Path,
    *,
    opener: Callable[[Request], Any] | None = None,
    temp_parent: Path | None = None,
) -> list[dict[str, str]]:
    """Verify all recorded archives and return their observed hashes."""

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
            active_opener = opener
            if active_opener is None:
                active_opener = build_opener(_AllowlistedRedirectHandler(allowed_hosts)).open
            request = Request(
                component["source_url"],
                headers={"User-Agent": "Calibrate-Pro-source-provenance/1"},
            )
            target = work_dir / f"{index:02d}-{component['name']}.source"
            observed = hashlib.sha256()
            with active_opener(request) as response:
                final_url = response.geturl()
                final_host = _https_host(final_url, label=f"{component['name']} final URL")
                if final_host not in allowed_hosts:
                    raise ValueError(f"{component['name']}: redirect host is not recorded: {final_host}")
                with target.open("xb") as destination:
                    while True:
                        chunk = response.read(_CHUNK_SIZE)
                        if not chunk:
                            break
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
        default=Path(__file__).resolve().parents[1] / "packaging" / "source-provenance.lock.json",
    )
    args = parser.parse_args(argv)
    try:
        verified = verify_source_provenance(args.lock_path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        parser.exit(1, f"source provenance verification failed: {exc}\n")
    print(json.dumps({"verified": verified}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
