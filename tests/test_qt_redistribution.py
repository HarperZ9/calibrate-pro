"""Third-party notice and corresponding-source release gates."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
from types import ModuleType
from urllib.parse import urlsplit

import pytest

ROOT = Path(__file__).resolve().parents[1]
NOTICE_DIR = ROOT / "THIRD_PARTY_LICENSES"
LOCK_PATH = ROOT / "packaging" / "source-provenance.lock.json"
BINARY_LOCK_PATH = ROOT / "packaging" / "binary-provenance.lock.json"
VERIFIER_PATH = ROOT / "scripts" / "verify_source_provenance.py"

REQUIRED_NOTICES = {
    "README.md",
    "LGPL-3.0-only.txt",
    "Qt-for-Python-NOTICE.txt",
    "QT_SOURCE_OFFER.txt",
    "LGPL_RELINKING.md",
    "Python-3.12.10.txt",
    "Build-Color-1.0.2.txt",
    "Build-UI-2.0.0.txt",
    "QtPy-2.4.3.txt",
    "NumPy-2.5.1.txt",
    "SciPy-1.18.0.txt",
    "OpenBLAS.txt",
    "hidapi-0.15.0.txt",
    "PyInstaller-6.21.0.txt",
    "Packaging-26.2.txt",
    "CPython-3.12.10-Windows-Externals-NOTICE.txt",
    "Microsoft-Visual-Cpp-Runtime-NOTICE.txt",
    "Qt-6.11.1-THIRD-PARTY-NOTICES.txt",
}
REQUIRED_SOURCES = {
    "cpython-3.12.10",
    "build-color-1.0.2",
    "build-ui-2.0.0",
    "qtpy-2.4.3",
    "numpy-2.5.1",
    "scipy-1.18.0",
    "hidapi-0.15.0",
    "pyinstaller-6.21.0",
    "pyside-setup-6.11.1",
    "qtbase-6.11.1",
    "packaging-26.2",
    "bzip2-1.0.8",
    "expat-2.6.3",
    "hacl-star-bb3d0dc8d9d15a5cd51094d5b69e70aa09005ff0",
    "libb2-0.98.1",
    "libffi-3.4.4",
    "mpdecimal-2.5.1",
    "openssl-3.0.16",
    "xz-5.2.5",
    "openblas-scipy-0.3.31.22.0",
    "openblas-libs-scipy-0.3.31.22.0",
    "openblas-numpy-0.3.33.112.0",
    "openblas-libs-numpy-0.3.33.112.0",
    "minhook-1.3.3",
    "msys2-mingw-packages-minhook-1.3.3-2",
    "dwm-lut-3.8",
    "windows-display-api-1.3.0.13",
}
REQUIRED_BINARY_RECEIPTS = {
    "cpython-3.12.10-amd64-installer",
    "cpython-3.12.10-amd64-spdx",
    "pyinstaller-6.21.0-win-amd64-wheel",
    "hidapi-0.15.0-cp312-win-amd64-wheel",
    "numpy-2.5.1-cp312-win-amd64-wheel",
    "scipy-1.18.0-cp312-win-amd64-wheel",
    "pyside6-essentials-6.11.1-win-amd64-wheel",
    "shiboken6-6.11.1-win-amd64-wheel",
    "dwm-lut-3.8-win-amd64-release",
    "msys2-minhook-1.3.3-2-any-package",
}
LOCKED_NOTICE_SHA256 = {
    "Build-Color-1.0.2.txt": "5d4abfef8a42cb0b1762662ae9745b01cd729991e60c2fee83d6ea8ee752cb6d",
    "Build-UI-2.0.0.txt": "5d4abfef8a42cb0b1762662ae9745b01cd729991e60c2fee83d6ea8ee752cb6d",
    "QtPy-2.4.3.txt": "59ec4225bd380e349a82e6482437ff9475eeb1c2e676a2d1185bb53315d45bf9",
    "NumPy-2.5.1.txt": "dc97d59562c75c04557f1e9a68f3eae326699eb119d569cd4ed6a4eafe5f9abb",
    "SciPy-1.18.0.txt": "c803fb373fe0f3b038f3f841bf706d63e076ffc554ec889cdeb258e5b29802bb",
    "OpenBLAS.txt": "190b5a9c8d9723fe958ad33916bd7346d96fab3c5ea90832bb02d854f620fcff",
    "hidapi-0.15.0.txt": "80d50f6bc0fb4bbaf657f1ac79084725c2ff58d9d7736de19808914c65703ce1",
    "PyInstaller-6.21.0.txt": "dcf75fdb959db1e3b41c0f8505069d2ece781b5ec6b3d0a4d30975cfc6580245",
    "Python-3.12.10.txt": "3b2f81fe21d181c499c59a256c8e1968455d6689d269aa85373bfb6af41da3bf",
}


def _load_verifier() -> ModuleType:
    assert VERIFIER_PATH.is_file()
    spec = importlib.util.spec_from_file_location("verify_source_provenance", VERIFIER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _normalised_payload(path: Path) -> bytes:
    return path.read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n")


def test_required_notice_files_are_committed_and_nonempty() -> None:
    assert NOTICE_DIR.is_dir()
    names = {path.name for path in NOTICE_DIR.iterdir() if path.is_file()}
    assert names >= REQUIRED_NOTICES
    for name in REQUIRED_NOTICES:
        assert (NOTICE_DIR / name).read_text(encoding="utf-8").strip()


def test_lgpl_payload_is_verbatim_gnu_lgpl_v3() -> None:
    payload = _normalised_payload(NOTICE_DIR / "LGPL-3.0-only.txt")
    text = payload.decode("utf-8")
    assert text.startswith("                   GNU LESSER GENERAL PUBLIC LICENSE\n")
    assert "Version 3, 29 June 2007" in text
    assert text.rstrip().endswith("Library.")
    assert hashlib.sha256(payload).hexdigest() == "e3a994d82e644b03a792a930f574002658412f62407f5fee083f2555c5f23118"


def test_versioned_notice_payloads_are_exactly_locked() -> None:
    for name, expected in LOCKED_NOTICE_SHA256.items():
        assert hashlib.sha256(_normalised_payload(NOTICE_DIR / name)).hexdigest() == expected


def test_source_provenance_is_complete_and_fail_closed() -> None:
    data = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    assert data["schema_version"] == 1
    assert data["modifications"] == []
    components = data["components"]
    names = {component["name"] for component in components}
    assert names >= REQUIRED_SOURCES
    assert len(names) == len(components)
    for component in components:
        assert component["version"]
        assert component["source_url"].startswith("https://")
        assert len(component["sha256"]) == 64
        int(component["sha256"], 16)
        assert component["license"]
        assert component["allowed_final_hosts"]
        assert urlsplit(component["source_url"]).hostname in component["allowed_final_hosts"]


def test_binary_provenance_is_complete_and_references_locked_sources() -> None:
    source_data = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    source_names = {component["name"] for component in source_data["components"]}
    data = json.loads(BINARY_LOCK_PATH.read_text(encoding="utf-8"))

    assert data["schema_version"] == 1
    components = data["components"]
    names = {component["name"] for component in components}
    assert names >= REQUIRED_BINARY_RECEIPTS
    assert len(names) == len(components)
    for component in components:
        assert component["version"]
        assert component["artifact_type"] in {"exe", "spdx-json", "wheel", "zip", "pkg.tar.zst"}
        assert component["artifact_url"].startswith("https://")
        assert component["filename"]
        assert len(component["sha256"]) == 64
        int(component["sha256"], 16)
        assert component["allowed_final_hosts"]
        assert urlsplit(component["artifact_url"]).hostname in component["allowed_final_hosts"]
        assert component["source_components"]
        assert set(component["source_components"]) <= source_names


def test_new_notice_payloads_identify_exact_evidence() -> None:
    packaging_notice = (NOTICE_DIR / "Packaging-26.2.txt").read_text(encoding="utf-8")
    assert "Apache License" in packaging_notice
    assert "Copyright (c) Donald Stufft and individual contributors." in packaging_notice

    cpython_notice = (
        NOTICE_DIR / "CPython-3.12.10-Windows-Externals-NOTICE.txt"
    ).read_text(encoding="utf-8")
    for name in ("bzip2 1.0.8", "Expat 2.6.3", "HACL*", "libb2 0.98.1", "libffi 3.4.4", "mpdecimal 2.5.1", "OpenSSL 3.0.16", "XZ Utils 5.2.5"):
        assert name in cpython_notice
    assert "1905207f988375b65dccbe3a1aafb22cc96b03f7826a4867c1b34006c214e571" in cpython_notice

    msvc_notice = (NOTICE_DIR / "Microsoft-Visual-Cpp-Runtime-NOTICE.txt").read_text(
        encoding="utf-8"
    )
    assert "Microsoft Visual C++ Runtime" in msvc_notice
    assert "not corresponding source" in msvc_notice

    qt_notice = (NOTICE_DIR / "Qt-6.11.1-THIRD-PARTY-NOTICES.txt").read_text(
        encoding="utf-8"
    )
    assert "Qt Base 6.11.1" in qt_notice
    assert "qt_attribution.json" in qt_notice


def test_source_offer_and_lgpl_notices_cover_the_provenance_lock() -> None:
    data = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    offer = (NOTICE_DIR / "QT_SOURCE_OFFER.txt").read_text(encoding="utf-8")
    for component in data["components"]:
        assert component["source_url"] in offer
        assert component["sha256"] in offer

    qt_notice = (NOTICE_DIR / "Qt-for-Python-NOTICE.txt").read_text(encoding="utf-8")
    for required in ("PySide6 6.11.1", "shiboken6 6.11.1", "Qt 6.11.1", "LGPL-3.0-only"):
        assert required in qt_notice

    readme = (NOTICE_DIR / "README.md").read_text(encoding="utf-8").lower()
    relinking = (NOTICE_DIR / "LGPL_RELINKING.md").read_text(encoding="utf-8").lower()
    assert "do not replace" in readme
    assert "reverse engineering" in readme
    assert "onedir" in relinking
    assert "replace" in relinking


class _Response:
    def __init__(self, payload: bytes, final_url: str) -> None:
        self._payload = payload
        self._final_url = final_url

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self, _size: int = -1) -> bytes:
        payload, self._payload = self._payload, b""
        return payload

    def geturl(self) -> str:
        return self._final_url


def _lock(payload: bytes, *, allowed_final_hosts: list[str] | None = None) -> dict[str, object]:
    return {
        "schema_version": 1,
        "modifications": [],
        "components": [
            {
                "name": "fixture-1.0",
                "version": "1.0",
                "source_url": "https://sources.example.test/fixture.tar.gz",
                "sha256": hashlib.sha256(payload).hexdigest(),
                "license": "MIT",
                "allowed_final_hosts": allowed_final_hosts or ["sources.example.test"],
            }
        ],
    }


def test_verifier_hashes_download_and_removes_only_its_unique_temp_dir(tmp_path: Path) -> None:
    module = _load_verifier()
    payload = b"authoritative source archive"
    lock_path = tmp_path / "lock.json"
    lock_path.write_text(json.dumps(_lock(payload)), encoding="utf-8")
    sentinel = tmp_path / "keep.txt"
    sentinel.write_text("keep", encoding="utf-8")

    result = module.verify_source_provenance(
        lock_path,
        opener=lambda _request: _Response(payload, "https://sources.example.test/fixture.tar.gz"),
        temp_parent=tmp_path,
    )

    assert result == [{"name": "fixture-1.0", "sha256": hashlib.sha256(payload).hexdigest()}]
    assert sentinel.read_text(encoding="utf-8") == "keep"
    assert [path for path in tmp_path.iterdir() if path.is_dir()] == []


def test_verifier_rejects_unrecorded_redirect_host_and_still_cleans_temp(tmp_path: Path) -> None:
    module = _load_verifier()
    payload = b"source"
    lock_path = tmp_path / "lock.json"
    lock_path.write_text(json.dumps(_lock(payload)), encoding="utf-8")

    with pytest.raises(ValueError, match="redirect|host"):
        module.verify_source_provenance(
            lock_path,
            opener=lambda _request: _Response(payload, "https://mirror.invalid/fixture.tar.gz"),
            temp_parent=tmp_path,
        )

    assert [path for path in tmp_path.iterdir() if path.is_dir()] == []


def test_verifier_rejects_hash_mismatch_and_still_cleans_temp(tmp_path: Path) -> None:
    module = _load_verifier()
    expected = b"expected"
    lock_path = tmp_path / "lock.json"
    lock_path.write_text(json.dumps(_lock(expected)), encoding="utf-8")

    with pytest.raises(ValueError, match="SHA-256"):
        module.verify_source_provenance(
            lock_path,
            opener=lambda _request: _Response(b"tampered", "https://sources.example.test/fixture.tar.gz"),
            temp_parent=tmp_path,
        )

    assert [path for path in tmp_path.iterdir() if path.is_dir()] == []
