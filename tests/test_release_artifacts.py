"""Final-byte and fail-closed tests for Windows release artifact tooling."""

from __future__ import annotations

import hashlib
import json
import os
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

import scripts.release_artifacts as release_artifacts
from calibrate_pro import __version__
from scripts.product_version import PORTABLE_NAME, SDIST_NAME
from scripts.release_artifacts import (
    audit_analysis_toc,
    audit_staged_tree,
    finalize,
    package,
    probe_authenticode,
    stage,
    write_reproducible_zip,
    write_sha256s,
)

EPOCH = 315532800


@pytest.mark.skipif(os.name != "nt", reason="Authenticode is a Windows-only release boundary")
def test_probe_authenticode_passes_target_and_handles_missing_certificates(tmp_path: Path) -> None:
    unsigned = tmp_path / "unsigned.exe"
    unsigned.write_bytes(b"MZ\x00\x00")

    signature = probe_authenticode(unsigned)

    assert set(signature) == {
        "SignerSubject",
        "SignerThumbprint",
        "Status",
        "TimestampThumbprint",
    }
    assert isinstance(signature["Status"], str)
    assert signature["Status"]
    assert signature["SignerThumbprint"] is None
    assert signature["SignerSubject"] is None
    assert signature["TimestampThumbprint"] is None


def test_probe_authenticode_uses_inbox_security_module_and_sanitizes_module_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "unsigned.exe"
    target.write_bytes(b"MZ\x00\x00")
    captured: dict[str, object] = {}

    def fake_run(command: list[str], **kwargs: object) -> object:
        captured["command"] = command
        captured["environment"] = kwargs["env"]
        return SimpleNamespace(
            stdout=json.dumps(
                {
                    "Status": "NotSigned",
                    "SignerThumbprint": None,
                    "SignerSubject": None,
                    "TimestampThumbprint": None,
                }
            )
        )

    monkeypatch.setenv("PSModulePath", "poisoned-by-parent-shell")
    monkeypatch.setattr(release_artifacts.subprocess, "run", fake_run)

    probe_authenticode(target)

    command = captured["command"]
    environment = captured["environment"]
    assert isinstance(command, list)
    assert isinstance(environment, dict)
    assert "$PSHOME" in command[-1]
    assert "Microsoft.PowerShell.Security.psd1" in command[-1]
    assert "PSModulePath" not in environment


def _write_json(path: Path, payload: object) -> Path:
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def synthetic_valid_stage(tmp_path: Path) -> tuple[Path, Path, dict[str, Path]]:
    staged = tmp_path / "staged"
    internal = staged / "_internal"
    internal.mkdir(parents=True)
    (staged / "CalibratePro.exe").write_bytes(b"gui")
    (staged / "CalibrateProCLI.exe").write_bytes(b"cli")
    (internal / "python312.dll").write_bytes(b"MZpython")
    (internal / "base_library.zip").write_bytes(b"stdlib")

    notices = tmp_path / "notices"
    notices.mkdir()
    (notices / "Python.txt").write_text("Python notice\n", encoding="utf-8")
    (notices / "PyInstaller.txt").write_text("PyInstaller notice\n", encoding="utf-8")
    (tmp_path / "LICENSE").write_text("Calibrate Pro license\n", encoding="utf-8")

    component_policy = _write_json(
        tmp_path / "components.json",
        {
            "schema_version": 2,
            "default": "reject",
            "path_mode": "literal-posix",
            "components": [
                {
                    "id": "calibrate-pro",
                    "owner": "calibrate-pro",
                    "version": __version__,
                    "license": "LicenseRef-FSL-1.1-MIT",
                    "notice_paths": ["LICENSE"],
                    "provenance": [{"kind": "release_source", "name": SDIST_NAME}],
                },
                {
                    "id": "cpython",
                    "owner": "python",
                    "version": "3.12.10",
                    "license": "PSF-2.0",
                    "notice_paths": ["THIRD_PARTY_LICENSES/Python.txt"],
                    "provenance": [
                        {"kind": "source", "name": "cpython-3.12.10"},
                        {"kind": "binary", "name": "cpython-3.12.10-win64"},
                    ],
                },
                {
                    "id": "pyinstaller-bootloader",
                    "owner": "pyinstaller",
                    "version": "6.21.0",
                    "license": "GPL-2.0-or-later WITH Bootloader-exception",
                    "notice_paths": ["THIRD_PARTY_LICENSES/PyInstaller.txt"],
                    "provenance": [
                        {"kind": "source", "name": "pyinstaller-6.21.0"},
                        {"kind": "binary", "name": "pyinstaller-6.21.0-wheel"},
                    ],
                },
            ],
            "artifacts": [
                {
                    "paths": ["CalibratePro.exe", "CalibrateProCLI.exe"],
                    "component_ids": ["calibrate-pro", "pyinstaller-bootloader"],
                },
                {
                    "paths": ["_internal/python312.dll", "_internal/base_library.zip"],
                    "component_ids": ["cpython"],
                },
            ],
        },
    )
    qt_policy = _write_json(
        tmp_path / "qt.json",
        {
            "schema_version": 2,
            "default": "reject",
            "path_mode": "literal-posix",
            "artifacts": [],
        },
    )
    module_policy = _write_json(
        tmp_path / "modules.json",
        {
            "schema_version": 1,
            "default": "reject",
            "first_party_exact": ["calibrate_pro.frozen_main"],
            "optional_first_party_exact": [],
            "distribution_roots": [],
        },
    )
    source_policy = _write_json(
        tmp_path / "sources.json",
        {
            "schema_version": 1,
            "modifications": [],
            "components": [
                {"name": "cpython-3.12.10"},
                {"name": "pyinstaller-6.21.0"},
            ],
        },
    )
    binary_policy = _write_json(
        tmp_path / "binaries.json",
        {
            "schema_version": 1,
            "components": [
                {"name": "cpython-3.12.10-win64"},
                {"name": "pyinstaller-6.21.0-wheel"},
            ],
        },
    )
    analysis_toc = tmp_path / "Analysis-00.toc"
    analysis_toc.write_text(
        repr([("calibrate_pro.frozen_main", "calibrate_pro/frozen_main.py", "PYMODULE-1")]),
        encoding="utf-8",
    )
    release = tmp_path / "release"
    policies = {
        "analysis_toc": analysis_toc,
        "component_policy": component_policy,
        "qt_policy": qt_policy,
        "module_policy": module_policy,
        "source_policy": source_policy,
        "binary_policy": binary_policy,
        "notice_dir": notices,
    }
    return staged, release, policies


def test_reproducible_zip_has_stable_bytes_and_safe_top_level(tmp_path: Path) -> None:
    staged = tmp_path / "staged"
    staged.mkdir()
    (staged / "z.txt").write_text("z", encoding="utf-8")
    (staged / "a.txt").write_text("a", encoding="utf-8")
    first = tmp_path / "first.zip"
    second = tmp_path / "second.zip"

    first_hash = write_reproducible_zip(staged, first, epoch=EPOCH)
    second_hash = write_reproducible_zip(staged, second, epoch=EPOCH)

    assert first_hash == second_hash
    assert first.read_bytes() == second.read_bytes()
    with zipfile.ZipFile(first) as archive:
        assert archive.namelist() == ["CalibratePro/a.txt", "CalibratePro/z.txt"]


def test_package_inventory_and_zip_use_post_sign_bytes(tmp_path: Path) -> None:
    staged, release, policies = synthetic_valid_stage(tmp_path)
    exe = staged / "CalibratePro.exe"
    exe.write_bytes(b"unsigned")
    stage(staged, release, **policies)
    exe.write_bytes(b"signed-final-bytes")
    package(staged, release, epoch=EPOCH, **policies)
    inventory = json.loads((release / "staged-inventory.json").read_text(encoding="utf-8"))
    record = next(item for item in inventory["files"] if item["path"] == "CalibratePro.exe")
    assert record["sha256"] == hashlib.sha256(b"signed-final-bytes").hexdigest()
    assert [component["id"] for component in record["components"]] == [
        "calibrate-pro",
        "pyinstaller-bootloader",
    ]
    assert record["qt_component_ids"] == []
    with zipfile.ZipFile(release / PORTABLE_NAME) as archive:
        assert archive.read("CalibratePro/CalibratePro.exe") == b"signed-final-bytes"


def test_stage_copies_runtime_notices_and_policies_below_meipass(tmp_path: Path) -> None:
    staged, release, policies = synthetic_valid_stage(tmp_path)

    stage(staged, release, **policies)

    for root in (staged, staged / "_internal"):
        assert (root / "LICENSE").read_text(encoding="utf-8") == "Calibrate Pro license\n"
        assert (root / "THIRD_PARTY_LICENSES" / "Python.txt").is_file()
    assert (staged / "_internal" / "packaging" / "components-win64.json").is_file()
    assert (staged / "_internal" / "packaging" / "qt-components.json").is_file()
    assert (staged / "_internal" / "packaging" / "frozen-modules.json").is_file()
    staged_source = json.loads(
        (staged / "_internal" / "THIRD_PARTY_LICENSES" / "source-provenance.json").read_text(encoding="utf-8")
    )
    expected_source = json.loads(Path(policies["source_policy"]).read_text(encoding="utf-8"))
    assert staged_source == expected_source
    staged_binary = json.loads(
        (staged / "_internal" / "THIRD_PARTY_LICENSES" / "binary-provenance.json").read_text(encoding="utf-8")
    )
    expected_binary = json.loads(Path(policies["binary_policy"]).read_text(encoding="utf-8"))
    assert staged_binary == expected_binary
    assert (staged / "_internal" / "packaging" / "binary-provenance.lock.json").is_file()


def test_finalize_without_installer_hashes_every_completed_release_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    staged, release, policies = synthetic_valid_stage(tmp_path)
    package(staged, release, epoch=EPOCH, **policies)
    (release / "build-receipt.json").write_text('{"schema_version":1}\n', encoding="utf-8")
    monkeypatch.setattr(
        "scripts.release_artifacts.probe_authenticode",
        lambda path: {
            "Status": "NotSigned",
            "SignerThumbprint": None,
            "SignerSubject": None,
            "TimestampThumbprint": None,
        },
    )

    finalize(staged, release, installer=None)

    checksum_lines = (release / "SHA256SUMS.txt").read_text(encoding="utf-8").splitlines()
    names = {line.split("  ", 1)[1] for line in checksum_lines}
    assert "build-receipt.json" in names
    assert "signature-inventory.json" in names
    assert PORTABLE_NAME in names


def test_finalize_requires_expected_valid_timestamped_signer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    staged, release, policies = synthetic_valid_stage(tmp_path)
    package(staged, release, epoch=EPOCH, **policies)
    monkeypatch.setattr(
        "scripts.release_artifacts.probe_authenticode",
        lambda path: {
            "Status": "NotSigned",
            "SignerThumbprint": None,
            "SignerSubject": None,
            "TimestampThumbprint": None,
        },
    )

    with pytest.raises(RuntimeError, match="Valid|signature"):
        finalize(staged, release, installer=None, expected_signer_thumbprint="A1B2")


def test_unknown_distribution_or_native_binary_fails_closed(tmp_path: Path) -> None:
    staged, _, policies = synthetic_valid_stage(tmp_path)
    unknown = staged / "_internal" / "unknown-native.dll"
    unknown.write_bytes(b"MZunknown")
    with pytest.raises(RuntimeError, match="unknown-native.dll"):
        audit_staged_tree(staged, **policies)


def test_composite_multi_source_and_binary_only_components_are_preserved(tmp_path: Path) -> None:
    staged, _, policies = synthetic_valid_stage(tmp_path)
    component_path = Path(policies["component_policy"])
    component_data = json.loads(component_path.read_text(encoding="utf-8"))
    component_data["components"].append(
        {
            "id": "windows-runtime",
            "owner": "microsoft",
            "version": "14.44",
            "license": "LicenseRef-Microsoft-VC-Runtime",
            "notice_paths": ["THIRD_PARTY_LICENSES/Microsoft.txt"],
            "provenance": [
                {"kind": "binary", "name": "msvc-runtime-14.44"},
            ],
        }
    )
    component_data["artifacts"][1]["component_ids"].append("windows-runtime")
    _write_json(component_path, component_data)
    binary_path = Path(policies["binary_policy"])
    binary_data = json.loads(binary_path.read_text(encoding="utf-8"))
    binary_data["components"].append({"name": "msvc-runtime-14.44"})
    _write_json(binary_path, binary_data)
    notice_dir = Path(policies["notice_dir"])
    (notice_dir / "Microsoft.txt").write_text("Microsoft runtime notice\n", encoding="utf-8")

    receipt = audit_staged_tree(staged, **policies)

    python_record = next(item for item in receipt["classified"] if item["path"] == "_internal/python312.dll")
    assert [component["id"] for component in python_record["components"]] == ["cpython", "windows-runtime"]
    assert python_record["components"][0]["provenance"] == [
        {"kind": "source", "name": "cpython-3.12.10"},
        {"kind": "binary", "name": "cpython-3.12.10-win64"},
    ]
    assert python_record["components"][1]["provenance"] == [{"kind": "binary", "name": "msvc-runtime-14.44"}]


@pytest.mark.parametrize(
    ("bad_path", "message"),
    [
        ("_internal/*.dll", "wildcard|literal"),
        ("../outside.dll", "traversal|literal"),
        ("/absolute.dll", "absolute|literal"),
        (r"_internal\\python312.dll", "POSIX|backslash|literal"),
    ],
)
def test_component_policy_rejects_non_literal_paths(tmp_path: Path, bad_path: str, message: str) -> None:
    staged, _, policies = synthetic_valid_stage(tmp_path)
    policy_path = Path(policies["component_policy"])
    data = json.loads(policy_path.read_text(encoding="utf-8"))
    data["artifacts"][1]["paths"][0] = bad_path
    _write_json(policy_path, data)

    with pytest.raises(RuntimeError, match=message):
        audit_staged_tree(staged, **policies)


def test_component_policy_rejects_dead_components(tmp_path: Path) -> None:
    staged, _, policies = synthetic_valid_stage(tmp_path)
    policy_path = Path(policies["component_policy"])
    data = json.loads(policy_path.read_text(encoding="utf-8"))
    data["components"].append(
        {
            "id": "dead",
            "owner": "nobody",
            "version": "0",
            "license": "MIT",
            "notice_paths": ["LICENSE"],
            "provenance": [{"kind": "source", "name": "cpython-3.12.10"}],
        }
    )
    _write_json(policy_path, data)

    with pytest.raises(RuntimeError, match="dead|unreferenced"):
        audit_staged_tree(staged, **policies)


def test_component_policy_rejects_legacy_top_level_pattern_fields(tmp_path: Path) -> None:
    staged, _, policies = synthetic_valid_stage(tmp_path)
    policy_path = Path(policies["component_policy"])
    data = json.loads(policy_path.read_text(encoding="utf-8"))
    data["legacy_patterns"] = [{"pattern": "*.dll"}]
    _write_json(policy_path, data)

    with pytest.raises(RuntimeError, match="unknown|legacy_patterns"):
        audit_staged_tree(staged, **policies)


def test_component_notice_paths_are_limited_to_license_roots(tmp_path: Path) -> None:
    staged, _, policies = synthetic_valid_stage(tmp_path)
    policy_path = Path(policies["component_policy"])
    data = json.loads(policy_path.read_text(encoding="utf-8"))
    data["components"][0]["notice_paths"] = ["CalibratePro.exe"]
    _write_json(policy_path, data)

    with pytest.raises(RuntimeError, match="notice|LICENSE|THIRD_PARTY_LICENSES"):
        audit_staged_tree(staged, **policies)


def test_component_policy_rejects_casefold_path_collisions(tmp_path: Path) -> None:
    staged, _, policies = synthetic_valid_stage(tmp_path)
    policy_path = Path(policies["component_policy"])
    data = json.loads(policy_path.read_text(encoding="utf-8"))
    data["artifacts"].append({"paths": ["calibratepro.exe"], "component_ids": ["calibrate-pro"]})
    _write_json(policy_path, data)

    with pytest.raises(RuntimeError, match="collision|duplicate"):
        audit_staged_tree(staged, **policies)


def test_component_policy_requires_every_declared_path_to_exist(tmp_path: Path) -> None:
    staged, _, policies = synthetic_valid_stage(tmp_path)
    policy_path = Path(policies["component_policy"])
    data = json.loads(policy_path.read_text(encoding="utf-8"))
    data["artifacts"][1]["paths"].append("_internal/missing.dll")
    _write_json(policy_path, data)

    with pytest.raises(RuntimeError, match="missing.dll|does not exist"):
        audit_staged_tree(staged, **policies)


def test_component_policy_requires_base_library_zip(tmp_path: Path) -> None:
    staged, _, policies = synthetic_valid_stage(tmp_path)
    policy_path = Path(policies["component_policy"])
    data = json.loads(policy_path.read_text(encoding="utf-8"))
    data["artifacts"][1]["paths"].remove("_internal/base_library.zip")
    _write_json(policy_path, data)

    with pytest.raises(RuntimeError, match="base_library.zip"):
        audit_staged_tree(staged, **policies)


def test_qt_policy_matches_only_explicit_qt_component_ids(tmp_path: Path) -> None:
    staged, _, policies = synthetic_valid_stage(tmp_path)
    qt_dir = staged / "_internal" / "PySide6"
    qt_dir.mkdir()
    (qt_dir / "Qt6Core.dll").write_bytes(b"MZqt")
    (qt_dir / "msvcp140.dll").write_bytes(b"MZmsvc")
    notices = Path(policies["notice_dir"])
    (notices / "Qt.txt").write_text("Qt notice\n", encoding="utf-8")
    (notices / "Microsoft.txt").write_text("Microsoft notice\n", encoding="utf-8")
    source_path = Path(policies["source_policy"])
    source_data = json.loads(source_path.read_text(encoding="utf-8"))
    source_data["components"].append({"name": "qtbase-6.11.1"})
    _write_json(source_path, source_data)
    binary_path = Path(policies["binary_policy"])
    binary_data = json.loads(binary_path.read_text(encoding="utf-8"))
    binary_data["components"].extend([{"name": "pyside6-6.11.1-wheel"}, {"name": "msvc-runtime-14.44"}])
    _write_json(binary_path, binary_data)
    component_path = Path(policies["component_policy"])
    component_data = json.loads(component_path.read_text(encoding="utf-8"))
    component_data["components"].extend(
        [
            {
                "id": "qtbase",
                "owner": "qt",
                "version": "6.11.1",
                "license": "LGPL-3.0-only",
                "notice_paths": ["THIRD_PARTY_LICENSES/Qt.txt"],
                "provenance": [
                    {"kind": "source", "name": "qtbase-6.11.1"},
                    {"kind": "binary", "name": "pyside6-6.11.1-wheel"},
                ],
                "qt_component": True,
            },
            {
                "id": "msvc-runtime",
                "owner": "microsoft",
                "version": "14.44",
                "license": "LicenseRef-Microsoft-VC-Runtime",
                "notice_paths": ["THIRD_PARTY_LICENSES/Microsoft.txt"],
                "provenance": [{"kind": "binary", "name": "msvc-runtime-14.44"}],
            },
        ]
    )
    component_data["artifacts"].extend(
        [
            {
                "paths": ["_internal/PySide6/Qt6Core.dll"],
                "component_ids": ["qtbase", "msvc-runtime"],
            },
            {
                "paths": ["_internal/PySide6/msvcp140.dll"],
                "component_ids": ["msvc-runtime"],
            },
        ]
    )
    _write_json(component_path, component_data)
    qt_path = Path(policies["qt_policy"])
    qt_data = json.loads(qt_path.read_text(encoding="utf-8"))
    qt_data["artifacts"].append({"paths": ["_internal/PySide6/Qt6Core.dll"], "component_ids": ["qtbase"]})
    _write_json(qt_path, qt_data)

    receipt = audit_staged_tree(staged, **policies)

    qt_record = next(item for item in receipt["classified"] if item["path"].endswith("Qt6Core.dll"))
    msvc_record = next(item for item in receipt["classified"] if item["path"].endswith("msvcp140.dll"))
    assert qt_record["qt_component_ids"] == ["qtbase"]
    assert msvc_record["qt_component_ids"] == []


def test_qt_policy_rejects_paths_not_backed_by_qt_component(tmp_path: Path) -> None:
    staged, _, policies = synthetic_valid_stage(tmp_path)
    qt_path = Path(policies["qt_policy"])
    qt_data = json.loads(qt_path.read_text(encoding="utf-8"))
    qt_data["artifacts"].append({"paths": ["_internal/python312.dll"], "component_ids": ["cpython"]})
    _write_json(qt_path, qt_data)

    with pytest.raises(RuntimeError, match="Qt|qt"):
        audit_staged_tree(staged, **policies)


def test_unknown_pure_site_packages_root_fails_closed(tmp_path: Path) -> None:
    _, _, policies = synthetic_valid_stage(tmp_path)
    toc = Path(policies["analysis_toc"])
    toc.write_text(
        repr(
            [
                ("calibrate_pro.frozen_main", "site-packages/calibrate_pro/frozen_main.py", "PYSOURCE"),
                ("surprise.module", "site-packages/surprise/module.py", "PYSOURCE"),
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="surprise|distribution"):
        audit_analysis_toc(toc, policies["module_policy"])


def test_site_packages_gate_uses_toc_path_root_not_claimed_module_name(tmp_path: Path) -> None:
    _, _, policies = synthetic_valid_stage(tmp_path)
    module_path = Path(policies["module_policy"])
    module_data = json.loads(module_path.read_text(encoding="utf-8"))
    module_data["distribution_roots"] = ["numpy"]
    _write_json(module_path, module_data)
    toc = Path(policies["analysis_toc"])
    toc.write_text(
        repr(
            [
                ("calibrate_pro.frozen_main", "site-packages/calibrate_pro/frozen_main.py", "PYSOURCE"),
                ("numpy.module", "site-packages/surprise/module.py", "PYSOURCE"),
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="surprise|distribution"):
        audit_analysis_toc(toc, module_path)


def test_upx_and_forbidden_toc_modules_fail_closed(tmp_path: Path) -> None:
    staged, _, policies = synthetic_valid_stage(tmp_path)
    (staged / "CalibratePro.exe").write_bytes(b"MZ---UPX!---")
    with pytest.raises(RuntimeError, match="UPX"):
        audit_staged_tree(staged, **policies)

    toc = policies["analysis_toc"]
    toc.write_text(repr([("PyQt6.QtCore", "x", "PYMODULE")]), encoding="utf-8")
    with pytest.raises(RuntimeError, match="PyQt6"):
        audit_analysis_toc(toc, policies["module_policy"])
    toc.write_text(repr([("build_color.gui", "x", "PYMODULE")]), encoding="utf-8")
    with pytest.raises(RuntimeError, match="build_color.gui"):
        audit_analysis_toc(toc, policies["module_policy"])


@pytest.mark.parametrize(
    "relative",
    [
        "_internal/api-ms-win-core-file-l1-1-0.dll",
        "_internal/charset_normalizer/md.cp312-win_amd64.pyd",
        "_internal/numpy/f2py/rules.py",
        "_internal/PySide6/opengl32sw.dll",
        "_internal/PySide6/plugins/imageformats/qpdf.dll",
        "_internal/PySide6/translations/qt_en.qm",
    ],
)
def test_pruned_runtime_families_remain_forbidden_even_if_declared(
    tmp_path: Path,
    relative: str,
) -> None:
    staged, _, policies = synthetic_valid_stage(tmp_path)
    target = staged.joinpath(*relative.split("/"))
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"forbidden")
    component_path = policies["component_policy"]
    component_policy = json.loads(component_path.read_text(encoding="utf-8"))
    component_policy["artifacts"].append({"paths": [relative], "component_ids": ["cpython"]})
    component_path.write_text(json.dumps(component_policy), encoding="utf-8")

    with pytest.raises(RuntimeError, match="forbidden staged path"):
        audit_staged_tree(staged, **policies)


def test_analysis_receipt_contains_no_absolute_build_path(tmp_path: Path) -> None:
    _, _, policies = synthetic_valid_stage(tmp_path)

    receipt = audit_analysis_toc(policies["analysis_toc"], policies["module_policy"])

    assert receipt["analysis_toc"] == "Analysis-00.toc"


def test_sha256s_excludes_itself_and_is_sorted(tmp_path: Path) -> None:
    release = tmp_path / "release"
    release.mkdir()
    (release / "z.bin").write_bytes(b"z")
    (release / "a.bin").write_bytes(b"a")
    write_sha256s(release)
    lines = (release / "SHA256SUMS.txt").read_text(encoding="utf-8").splitlines()
    assert lines == sorted(lines, key=lambda line: line.split("  ", 1)[1])
    assert not any(line.endswith("SHA256SUMS.txt") for line in lines)


def test_release_directory_cannot_be_inside_staged_tree(tmp_path: Path) -> None:
    staged, _, policies = synthetic_valid_stage(tmp_path)
    with pytest.raises(ValueError, match="release directory"):
        stage(staged, staged / "release", **policies)
