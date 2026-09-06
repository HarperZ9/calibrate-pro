"""Safety contracts for the Windows color-profile management boundary."""

from __future__ import annotations

import ctypes
import dis
import os
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from calibrate_pro.profiles import profile_installer

pytestmark = pytest.mark.windows


@pytest.fixture(autouse=True)
def isolate_retained_profile_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep deliberately retained fake HANDLE owners from crossing test boundaries."""
    monkeypatch.setattr(profile_installer, "_RETAINED_PROFILE_DELETE_LEASES", [])


def interrupt_at_opcode(function: object, offset: int, interruption: BaseException) -> object:
    fired = False

    def trace(frame: object, event: str, _arg: object) -> object:
        nonlocal fired
        if event == "call" and frame.f_code is function.__code__:  # type: ignore[attr-defined]
            frame.f_trace_opcodes = True  # type: ignore[attr-defined]
            return trace
        if (
            not fired
            and event == "opcode"
            and frame.f_code is function.__code__  # type: ignore[attr-defined]
            and frame.f_lasti == offset  # type: ignore[attr-defined]
        ):
            fired = True
            sys.settrace(None)
            raise interruption
        return trace

    return trace


def test_enum_display_devices_pointer_contract_accepts_shared_struct_layouts() -> None:
    if not profile_installer.GDI_AVAILABLE:
        pytest.skip("Win32 display enumeration API unavailable")
    assert profile_installer.user32.EnumDisplayDevicesW.argtypes[2] is ctypes.c_void_p


class RecordingMscms:
    """Small native-boundary fake that records calls without touching Windows."""

    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []
        self.profile_name = "active.icc"

    def WcsAssociateColorProfileWithDevice(self, *args: object) -> bool:
        self.calls.append(("associate", *args))
        return True

    def WcsSetDefaultColorProfile(self, *args: object) -> bool:
        self.calls.append(("default", *args))
        self.profile_name = str(args[-1])
        return True

    def WcsDisassociateColorProfileFromDevice(self, *args: object) -> bool:
        self.calls.append(("disassociate", *args))
        return True

    def WcsGetDefaultColorProfile(self, *args: object) -> bool:
        self.calls.append(("get-default", *args[:-1]))
        buffer = args[-1]
        buffer.value = self.profile_name  # type: ignore[attr-defined]
        return True

    def WcsGetDefaultColorProfileSize(self, *args: object) -> bool:
        self.calls.append(("get-default-size", *args[:-1]))
        size_pointer = args[-1]
        size = (len(self.profile_name) + 1) * ctypes.sizeof(ctypes.c_wchar)
        ctypes.cast(size_pointer, ctypes.POINTER(ctypes.c_ulong)).contents.value = size
        return True

    def InstallColorProfileW(self, _machine: object, path: str) -> bool:
        self.calls.append(("install", path))
        return True

    def UninstallColorProfileW(self, _machine: object, path: str, delete: bool) -> bool:
        self.calls.append(("uninstall", path, delete))
        if delete:
            Path(path).unlink()
        return True


class EnumeratingMscms:
    """Fake the two-call WCS profile enumeration contract."""

    def __init__(
        self,
        profiles: tuple[str, ...],
        *,
        fail_size: bool = False,
        fail_enumeration: bool = False,
        reported_count: int | None = None,
    ) -> None:
        self.profiles = profiles
        self.fail_size = fail_size
        self.fail_enumeration = fail_enumeration
        self.reported_count = len(profiles) if reported_count is None else reported_count
        self.records: list[tuple[int, int, str | None]] = []

    @property
    def payload(self) -> bytes:
        if not self.profiles:
            return b""
        return ("\x00".join(self.profiles) + "\x00\x00").encode("utf-16-le")

    def _record(self, scope: int, record_pointer: object) -> None:
        record_type = profile_installer._ENUMTYPEW
        record = ctypes.cast(record_pointer, ctypes.POINTER(record_type)).contents
        self.records.append((scope, int(record.dwFields), record.pDeviceName))

    def WcsEnumColorProfilesSize(self, scope: int, record: object, size_pointer: object) -> bool:
        self._record(scope, record)
        if self.fail_size:
            return False
        size = ctypes.cast(size_pointer, ctypes.POINTER(ctypes.c_ulong))
        size.contents.value = len(self.payload)
        return True

    def WcsEnumColorProfiles(
        self,
        scope: int,
        record: object,
        buffer: object,
        size: int,
        count_pointer: object,
    ) -> bool:
        self._record(scope, record)
        if self.fail_enumeration:
            return False
        assert size == len(self.payload)
        if self.payload:
            ctypes.memmove(buffer, self.payload, len(self.payload))
        count = ctypes.cast(count_pointer, ctypes.POINTER(ctypes.c_ulong))
        count.contents.value = self.reported_count
        return True


class RegistrationStateMscms(RecordingMscms):
    """Fake native registration plus authoritative WCS enumeration state."""

    def __init__(
        self,
        profile_name: str,
        *,
        registered_after: bool,
        install_result: bool = True,
        uninstall_result: bool = True,
        install_error: BaseException | None = None,
        uninstall_error: BaseException | None = None,
    ) -> None:
        super().__init__()
        self.profile_name = profile_name
        self.registered = not registered_after
        self.registered_after = registered_after
        self.install_result = install_result
        self.uninstall_result = uninstall_result
        self.install_error = install_error
        self.uninstall_error = uninstall_error

    @property
    def payload(self) -> bytes:
        if not self.registered:
            return b""
        return f"{self.profile_name}\x00\x00".encode("utf-16-le")

    def InstallColorProfileW(self, _machine: object, path: str) -> bool:
        self.calls.append(("install", path))
        self.registered = self.registered_after
        if self.install_error is not None:
            raise self.install_error
        return self.install_result

    def UninstallColorProfileW(self, _machine: object, path: str, delete: bool) -> bool:
        self.calls.append(("uninstall", path, delete))
        self.registered = self.registered_after
        if self.uninstall_error is not None:
            raise self.uninstall_error
        return self.uninstall_result

    def WcsEnumColorProfilesSize(self, _scope: int, _record: object, size_pointer: object) -> bool:
        self.calls.append(("enum-size",))
        size = ctypes.cast(size_pointer, ctypes.POINTER(ctypes.c_ulong))
        size.contents.value = len(self.payload)
        return True

    def WcsEnumColorProfiles(
        self,
        _scope: int,
        _record: object,
        buffer: object,
        size: int,
        count_pointer: object,
    ) -> bool:
        self.calls.append(("enum",))
        assert size == len(self.payload)
        if self.payload:
            ctypes.memmove(buffer, self.payload, len(self.payload))
        count = ctypes.cast(count_pointer, ctypes.POINTER(ctypes.c_ulong))
        count.contents.value = int(self.registered)
        return True


def install_fake_mscms(
    monkeypatch: pytest.MonkeyPatch,
    color_directory: Path,
) -> RecordingMscms:
    native = RecordingMscms()
    monkeypatch.setattr(profile_installer, "MSCMS_AVAILABLE", True)
    monkeypatch.setattr(profile_installer, "mscms", native)
    monkeypatch.setattr(profile_installer, "get_profile_directory", lambda: color_directory)
    return native


def install_enumerating_mscms(
    monkeypatch: pytest.MonkeyPatch,
    profiles: tuple[str, ...],
    **changes: object,
) -> EnumeratingMscms:
    native = EnumeratingMscms(profiles, **changes)  # type: ignore[arg-type]
    monkeypatch.setattr(profile_installer, "MSCMS_AVAILABLE", True)
    monkeypatch.setattr(profile_installer, "mscms", native)
    return native


def valid_legacy_icc(marker: int = 0) -> bytes:
    """Return the smallest profile accepted by the legacy installer."""
    payload = bytearray(132)
    payload[0:4] = len(payload).to_bytes(4, "big")
    payload[36:40] = b"acsp"
    payload[-1] = marker
    return bytes(payload)


class DefaultProfileMscms:
    """In-memory implementation of the persistent WCS default-profile calls."""

    def __init__(self, profile_name: str = "active.icc") -> None:
        self.profile_name = profile_name
        self.calls: list[tuple[object, ...]] = []
        self.set_result = True
        self.get_result = True

    @property
    def profile_name_bytes(self) -> int:
        return (len(self.profile_name) + 1) * ctypes.sizeof(ctypes.c_wchar)

    def WcsGetDefaultColorProfileSize(self, *args: object) -> bool:
        self.calls.append(("get-size", *args[:-1]))
        size_pointer = args[-1]
        ctypes.cast(size_pointer, ctypes.POINTER(ctypes.c_ulong)).contents.value = self.profile_name_bytes
        return self.get_result

    def WcsGetDefaultColorProfile(self, *args: object) -> bool:
        self.calls.append(("get", *args[:-1]))
        if not self.get_result:
            return False
        buffer = args[-1]
        buffer.value = self.profile_name  # type: ignore[attr-defined]
        return True

    def WcsSetDefaultColorProfile(self, *args: object) -> bool:
        self.calls.append(("set", *args))
        if self.set_result:
            self.profile_name = str(args[-1])
        return self.set_result


def install_default_profile_mscms(
    monkeypatch: pytest.MonkeyPatch,
    profile_name: str = "active.icc",
) -> DefaultProfileMscms:
    native = DefaultProfileMscms(profile_name)
    monkeypatch.setattr(profile_installer, "MSCMS_AVAILABLE", True)
    monkeypatch.setattr(profile_installer, "mscms", native)
    return native


def test_wcs_icc_default_constants_are_named_and_correct() -> None:
    assert profile_installer.WCS_PROFILE_MANAGEMENT_SCOPE_SYSTEM_WIDE == 0
    assert profile_installer.CPT_ICC == 0
    assert profile_installer.CPST_NONE == 4


def test_wcs_signature_configurator_uses_wide_string_contracts() -> None:
    class NativeFunction:
        argtypes: list[object] | None = None
        restype: object | None = None

        def __bool__(self) -> bool:
            return False

    native = SimpleNamespace(
        InstallColorProfileW=NativeFunction(),
        UninstallColorProfileW=NativeFunction(),
        WcsAssociateColorProfileWithDevice=NativeFunction(),
        WcsDisassociateColorProfileFromDevice=NativeFunction(),
        WcsSetDefaultColorProfile=NativeFunction(),
        WcsGetDefaultColorProfile=NativeFunction(),
        WcsGetDefaultColorProfileSize=NativeFunction(),
    )
    configure = getattr(profile_installer, "_configure_wcs_default_profile_signatures", None)
    assert callable(configure)

    configure(native)

    assert native.InstallColorProfileW.argtypes == [ctypes.c_wchar_p, ctypes.c_wchar_p]
    assert native.InstallColorProfileW.restype is ctypes.c_long
    assert native.UninstallColorProfileW.argtypes == [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_long]
    assert native.UninstallColorProfileW.restype is ctypes.c_long

    assert native.WcsAssociateColorProfileWithDevice.argtypes == [
        ctypes.c_int,
        ctypes.c_wchar_p,
        ctypes.c_wchar_p,
    ]
    assert native.WcsAssociateColorProfileWithDevice.restype is ctypes.c_long
    assert native.WcsDisassociateColorProfileFromDevice.argtypes == [
        ctypes.c_int,
        ctypes.c_wchar_p,
        ctypes.c_wchar_p,
    ]
    assert native.WcsDisassociateColorProfileFromDevice.restype is ctypes.c_long

    assert native.WcsSetDefaultColorProfile.argtypes == [
        ctypes.c_int,
        ctypes.c_wchar_p,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_ulong,
        ctypes.c_wchar_p,
    ]
    assert native.WcsSetDefaultColorProfile.restype is ctypes.c_long
    assert native.WcsGetDefaultColorProfile.argtypes == [
        ctypes.c_int,
        ctypes.c_wchar_p,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_ulong,
        ctypes.c_ulong,
        ctypes.c_wchar_p,
    ]
    assert native.WcsGetDefaultColorProfile.restype is ctypes.c_long
    assert native.WcsGetDefaultColorProfileSize.argtypes == [
        ctypes.c_int,
        ctypes.c_wchar_p,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_ulong,
        ctypes.POINTER(ctypes.c_ulong),
    ]
    assert native.WcsGetDefaultColorProfileSize.restype is ctypes.c_long


def test_associate_profile_uses_icc_default_and_native_wide_strings(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profile = tmp_path / "display.icc"
    profile.write_bytes(b"profile")
    native = install_fake_mscms(monkeypatch, tmp_path)

    success, message = profile_installer.associate_profile_with_display(
        profile.name,
        r"\\.\DISPLAY1",
        make_default=True,
    )

    assert success is True, message
    expected_size = (len("display.icc") + 1) * ctypes.sizeof(ctypes.c_wchar)
    assert native.calls == [
        (
            "associate",
            profile_installer.WCS_PROFILE_MANAGEMENT_SCOPE_SYSTEM_WIDE,
            "display.icc",
            r"\\.\DISPLAY1",
        ),
        (
            "default",
            profile_installer.WCS_PROFILE_MANAGEMENT_SCOPE_SYSTEM_WIDE,
            r"\\.\DISPLAY1",
            profile_installer.CPT_ICC,
            profile_installer.CPST_NONE,
            0,
            "display.icc",
        ),
        (
            "get-default-size",
            profile_installer.WCS_PROFILE_MANAGEMENT_SCOPE_SYSTEM_WIDE,
            r"\\.\DISPLAY1",
            profile_installer.CPT_ICC,
            profile_installer.CPST_NONE,
            0,
        ),
        (
            "get-default",
            profile_installer.WCS_PROFILE_MANAGEMENT_SCOPE_SYSTEM_WIDE,
            r"\\.\DISPLAY1",
            profile_installer.CPT_ICC,
            profile_installer.CPST_NONE,
            0,
            expected_size,
        ),
    ]


def test_disassociate_profile_uses_system_scope_and_native_wide_strings(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    native = install_fake_mscms(monkeypatch, tmp_path)

    success, message = profile_installer.disassociate_profile_from_display(
        "display.icc",
        r"\\.\DISPLAY1",
    )

    assert success is True, message
    assert native.calls == [
        (
            "disassociate",
            profile_installer.WCS_PROFILE_MANAGEMENT_SCOPE_SYSTEM_WIDE,
            "display.icc",
            r"\\.\DISPLAY1",
        )
    ]


def test_get_display_profile_uses_icc_default_and_byte_sized_wide_buffer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    native = install_fake_mscms(monkeypatch, tmp_path)

    result = profile_installer.get_display_profile(r"\\.\DISPLAY1")

    assert result == "active.icc"
    assert len(native.calls) == 2
    assert native.calls[0] == (
        "get-default-size",
        profile_installer.WCS_PROFILE_MANAGEMENT_SCOPE_SYSTEM_WIDE,
        r"\\.\DISPLAY1",
        profile_installer.CPT_ICC,
        profile_installer.CPST_NONE,
        0,
    )
    call = native.calls[1]
    assert call[:6] == (
        "get-default",
        profile_installer.WCS_PROFILE_MANAGEMENT_SCOPE_SYSTEM_WIDE,
        r"\\.\DISPLAY1",
        profile_installer.CPT_ICC,
        profile_installer.CPST_NONE,
        0,
    )
    assert call[6] == (len("active.icc") + 1) * ctypes.sizeof(ctypes.c_wchar)


def test_exact_default_profile_reader_uses_sized_system_wcs_query(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    native = install_default_profile_mscms(monkeypatch, "active.icc")

    result = profile_installer.get_default_profile_for_display(r"\\.\DISPLAY1")

    assert result == "active.icc"
    common = (
        profile_installer.WCS_PROFILE_MANAGEMENT_SCOPE_SYSTEM_WIDE,
        r"\\.\DISPLAY1",
        profile_installer.CPT_ICC,
        profile_installer.CPST_NONE,
        0,
    )
    assert native.calls[0] == ("get-size", *common)
    assert native.calls[1][0:6] == ("get", *common)
    assert native.calls[1][6] == native.profile_name_bytes


@pytest.mark.parametrize(
    "native_name",
    (
        "",
        r"C:\Windows\System32\spool\drivers\color\active.icc",
        "nested/active.icc",
        "active.icc.",
        "active.icc ",
    ),
)
def test_exact_default_profile_reader_rejects_non_basename_native_evidence(
    monkeypatch: pytest.MonkeyPatch,
    native_name: str,
) -> None:
    install_default_profile_mscms(monkeypatch, native_name)

    with pytest.raises(RuntimeError, match="basename|empty|profile"):
        profile_installer.get_default_profile_for_display(r"\\.\DISPLAY1")


def test_exact_default_profile_reader_raises_on_ambiguous_native_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    native = install_default_profile_mscms(monkeypatch)
    native.get_result = False

    with pytest.raises(RuntimeError, match="default|profile|query"):
        profile_installer.get_default_profile_for_display(r"\\.\DISPLAY1")


def test_persistent_default_profile_setter_uses_system_wcs_and_exact_readback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    native = install_default_profile_mscms(monkeypatch, "old.icc")

    success, message = profile_installer.set_default_profile_for_display(
        "target.icc",
        r"\\.\DISPLAY1",
    )

    assert success is True, message
    assert native.calls[0] == (
        "set",
        profile_installer.WCS_PROFILE_MANAGEMENT_SCOPE_SYSTEM_WIDE,
        r"\\.\DISPLAY1",
        profile_installer.CPT_ICC,
        profile_installer.CPST_NONE,
        0,
        "target.icc",
    )
    assert profile_installer.get_default_profile_for_display(r"\\.\DISPLAY1") == "target.icc"


@pytest.mark.parametrize(
    "profile_name",
    (
        "",
        ".",
        "..",
        "nested/target.icc",
        r"nested\target.icc",
        "target.icc.",
        "target.icc ",
        "target.icc:stream",
        "target?.icc",
        "CON.icc",
        "control\x01.icc",
    ),
)
def test_persistent_default_profile_setter_rejects_non_exact_basename_before_native_call(
    monkeypatch: pytest.MonkeyPatch,
    profile_name: str,
) -> None:
    native = install_default_profile_mscms(monkeypatch)

    with pytest.raises((TypeError, ValueError), match="basename|profile"):
        profile_installer.set_default_profile_for_display(profile_name, r"\\.\DISPLAY1")

    assert native.calls == []


def test_persistent_default_profile_setter_propagates_cancellation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class CancellingMscms(DefaultProfileMscms):
        def WcsSetDefaultColorProfile(self, *args: object) -> bool:
            raise KeyboardInterrupt("cancelled while setting persistent default")

    native = CancellingMscms()
    monkeypatch.setattr(profile_installer, "MSCMS_AVAILABLE", True)
    monkeypatch.setattr(profile_installer, "mscms", native)

    with pytest.raises(KeyboardInterrupt, match="cancelled"):
        profile_installer.set_default_profile_for_display("target.icc", r"\\.\DISPLAY1")


@pytest.mark.parametrize(
    "profile_name",
    [
        "",
        ".",
        "..",
        "nested/display.icc",
        r"nested\display.icc",
        "display.icc:stream",
        "display?.icc",
        "NUL.icc",
        "control\x01.icc",
    ],
)
def test_uninstall_rejects_non_basename_input_before_native_delete(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    profile_name: str,
) -> None:
    (tmp_path / "nested").mkdir()
    (tmp_path / "nested" / "display.icc").write_bytes(b"profile")
    native = install_fake_mscms(monkeypatch, tmp_path)

    success, message = profile_installer.uninstall_profile(profile_name)

    assert success is False
    assert "basename" in message.casefold()
    assert native.calls == []


def test_uninstall_rejects_non_exact_string_basename(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class ProfileName(str):
        pass

    profile = tmp_path / "display.icc"
    profile.write_bytes(b"profile")
    native = install_fake_mscms(monkeypatch, tmp_path)

    success, message = profile_installer.uninstall_profile(ProfileName(profile.name))

    assert success is False
    assert "basename" in message.casefold()
    assert native.calls == []


@pytest.mark.parametrize("suffix", ["icc", "icm"])
def test_uninstall_permanently_refuses_transactional_product_cache_without_deleting(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    suffix: str,
) -> None:
    profile = tmp_path / f"calibrate-pro-{'a' * 64}.{suffix}"
    profile.write_bytes(b"shared-profile")
    native = install_fake_mscms(monkeypatch, tmp_path)

    success, message = profile_installer.uninstall_profile(profile.name)

    assert success is False
    assert "authoritative" in message.casefold() or "collector" in message.casefold()
    assert profile.read_bytes() == b"shared-profile"
    assert native.calls == []


@pytest.mark.parametrize(
    "alias_transform",
    (
        str.upper,
        lambda value: value.swapcase(),
        lambda value: value + ".",
        lambda value: value + " ",
    ),
)
def test_uninstall_refuses_win32_equivalent_transactional_cache_aliases(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    alias_transform: object,
) -> None:
    name = f"calibrate-pro-{'a' * 64}.icc"
    profile = tmp_path / name
    profile.write_bytes(b"shared-profile")
    native = install_fake_mscms(monkeypatch, tmp_path)
    alias = alias_transform(name)  # type: ignore[operator]

    success, _message = profile_installer.uninstall_profile(alias)

    assert success is False
    assert profile.read_bytes() == b"shared-profile"
    assert native.calls == []


def test_uninstall_refuses_resolved_alias_of_transactional_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profile = tmp_path / f"calibrate-pro-{'a' * 64}.icc"
    profile.write_bytes(b"shared-profile")
    alias = tmp_path / "ordinary.icc"
    try:
        alias.symlink_to(profile)
    except OSError as exc:
        pytest.skip(f"file symlinks unavailable: {exc}")
    native = install_fake_mscms(monkeypatch, tmp_path)

    success, _message = profile_installer.uninstall_profile(alias.name)

    assert success is False
    assert profile.read_bytes() == b"shared-profile"
    assert alias.exists()
    assert native.calls == []


def test_uninstall_refuses_hardlink_alias_of_transactional_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profile = tmp_path / f"calibrate-pro-{'a' * 64}.icc"
    profile.write_bytes(b"shared-profile")
    alias = tmp_path / "ordinary.icc"
    try:
        alias.hardlink_to(profile)
    except OSError as exc:
        pytest.skip(f"hard links unavailable: {exc}")
    native = install_fake_mscms(monkeypatch, tmp_path)

    success, _message = profile_installer.uninstall_profile(alias.name)

    assert success is False
    assert profile.read_bytes() == b"shared-profile"
    assert alias.read_bytes() == b"shared-profile"
    assert native.calls == []


@pytest.mark.skipif(os.name != "nt", reason="8.3 aliases are a Win32 filesystem behavior")
def test_uninstall_refuses_short_name_alias_of_transactional_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profile = tmp_path / f"calibrate-pro-{'a' * 64}.icc"
    profile.write_bytes(b"shared-profile")
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    get_short_path = kernel32.GetShortPathNameW
    get_short_path.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_ulong]
    get_short_path.restype = ctypes.c_ulong
    buffer = ctypes.create_unicode_buffer(32768)
    length = get_short_path(str(profile), buffer, len(buffer))
    if not length or length >= len(buffer):
        pytest.skip("8.3 short names are unavailable on this volume")
    short_name = Path(buffer.value).name
    if short_name.casefold() == profile.name.casefold():
        pytest.skip("this volume did not assign an alternate 8.3 name")
    native = install_fake_mscms(monkeypatch, tmp_path)

    success, _message = profile_installer.uninstall_profile(short_name)

    assert success is False
    assert profile.read_bytes() == b"shared-profile"
    assert native.calls == []


@pytest.mark.parametrize("name_transform", (lambda value: value, str.upper, lambda value: value + "."))
def test_legacy_install_never_writes_reserved_transactional_cache_name(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    name_transform: object,
) -> None:
    color_dir = tmp_path / "color"
    source_dir = tmp_path / "source"
    color_dir.mkdir()
    source_dir.mkdir()
    canonical_name = f"calibrate-pro-{'a' * 64}.icc"
    destination = color_dir / canonical_name
    destination.write_bytes(valid_legacy_icc(1))
    source_name = name_transform(canonical_name)  # type: ignore[operator]
    source = source_dir / source_name
    source.write_bytes(valid_legacy_icc(2))
    native = install_fake_mscms(monkeypatch, color_dir)

    success, _message = profile_installer.install_profile(source)

    assert success is False
    assert destination.read_bytes() == valid_legacy_icc(1)
    assert native.calls == []


def test_legacy_install_refuses_destination_resolving_to_transactional_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    color_dir = tmp_path / "color"
    source_dir = tmp_path / "source"
    color_dir.mkdir()
    source_dir.mkdir()
    destination = color_dir / f"calibrate-pro-{'a' * 64}.icc"
    destination.write_bytes(valid_legacy_icc(1))
    alias = color_dir / "ordinary.icc"
    try:
        alias.symlink_to(destination)
    except OSError as exc:
        pytest.skip(f"file symlinks unavailable: {exc}")
    source = source_dir / alias.name
    source.write_bytes(valid_legacy_icc(2))
    native = install_fake_mscms(monkeypatch, color_dir)

    success, _message = profile_installer.install_profile(source)

    assert success is False
    assert destination.read_bytes() == valid_legacy_icc(1)
    assert native.calls == []


def test_legacy_install_refuses_hardlink_destination_of_transactional_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    color_dir = tmp_path / "color"
    source_dir = tmp_path / "source"
    color_dir.mkdir()
    source_dir.mkdir()
    destination = color_dir / f"calibrate-pro-{'a' * 64}.icc"
    destination.write_bytes(valid_legacy_icc(1))
    alias = color_dir / "ordinary.icc"
    try:
        alias.hardlink_to(destination)
    except OSError as exc:
        pytest.skip(f"hard links unavailable: {exc}")
    source = source_dir / alias.name
    source.write_bytes(valid_legacy_icc(2))
    native = install_fake_mscms(monkeypatch, color_dir)

    success, _message = profile_installer.install_profile(source)

    assert success is False
    assert destination.read_bytes() == valid_legacy_icc(1)
    assert alias.read_bytes() == valid_legacy_icc(1)
    assert native.calls == []


@pytest.mark.parametrize("alias_kind", ["hardlink", "symlink"])
def test_legacy_install_rechecks_substitution_without_overwriting_product_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    alias_kind: str,
) -> None:
    color_dir = tmp_path / "color"
    source_dir = tmp_path / "source"
    color_dir.mkdir()
    source_dir.mkdir()
    product = color_dir / f"calibrate-pro-{'a' * 64}.icc"
    product.write_bytes(valid_legacy_icc(1))
    source = source_dir / "ordinary.icc"
    source.write_bytes(valid_legacy_icc(2))
    if alias_kind == "symlink":
        probe = color_dir / "symlink-probe.icc"
        try:
            probe.symlink_to(product)
            probe.unlink()
        except OSError as exc:
            pytest.skip(f"file symlinks unavailable: {exc}")
    native = install_fake_mscms(monkeypatch, color_dir)
    original_check = profile_installer._path_resolves_to_transactional_profile_cache
    check_calls = 0

    def substitute_after_precheck(path: Path) -> bool:
        nonlocal check_calls
        check_calls += 1
        result = original_check(path)
        if check_calls == 1:
            assert result is False
            if alias_kind == "hardlink":
                path.hardlink_to(product)
            else:
                path.symlink_to(product)
            return False
        return result

    monkeypatch.setattr(profile_installer, "_path_resolves_to_transactional_profile_cache", substitute_after_precheck)

    success, _message = profile_installer.install_profile(source)

    assert success is False
    assert product.read_bytes() == valid_legacy_icc(1)
    assert native.calls == []


def test_legacy_install_exclusively_creates_and_registers_an_ordinary_profile(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    color_dir = tmp_path / "color"
    source_dir = tmp_path / "source"
    color_dir.mkdir()
    source_dir.mkdir()
    source = source_dir / "ordinary.icc"
    source.write_bytes(valid_legacy_icc(9))
    native = install_fake_mscms(monkeypatch, color_dir)

    success, message = profile_installer.install_profile(source)

    destination = color_dir / source.name
    assert success is True, message
    assert destination.read_bytes() == source.read_bytes()
    assert native.calls == [("install", str(destination))]


def test_legacy_install_removes_only_its_created_file_when_registration_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    color_dir = tmp_path / "color"
    source_dir = tmp_path / "source"
    color_dir.mkdir()
    source_dir.mkdir()
    source = source_dir / "rejected.icc"
    source.write_bytes(valid_legacy_icc(7))

    class RejectingMscms(RecordingMscms):
        def InstallColorProfileW(self, _machine: object, path: str) -> bool:
            self.calls.append(("install", path))
            return False

    native = RejectingMscms()
    monkeypatch.setattr(profile_installer, "MSCMS_AVAILABLE", True)
    monkeypatch.setattr(profile_installer, "mscms", native)
    monkeypatch.setattr(profile_installer, "get_profile_directory", lambda: color_dir)

    success, _message = profile_installer.install_profile(source)

    assert success is False
    assert not (color_dir / source.name).exists()
    assert source.read_bytes() == valid_legacy_icc(7)
    assert native.calls == [("install", str(color_dir / source.name))]


def test_legacy_install_fails_without_creating_a_destination_when_mscms_is_unavailable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    color_dir = tmp_path / "color"
    source_dir = tmp_path / "source"
    color_dir.mkdir()
    source_dir.mkdir()
    source = source_dir / "unavailable.icc"
    source.write_bytes(valid_legacy_icc(13))
    monkeypatch.setattr(profile_installer, "MSCMS_AVAILABLE", False)
    monkeypatch.setattr(profile_installer, "mscms", None)
    monkeypatch.setattr(profile_installer, "get_profile_directory", lambda: color_dir)

    success, message = profile_installer.install_profile(source)

    assert success is False
    assert "unavailable" in message.casefold() or "not available" in message.casefold()
    assert not (color_dir / source.name).exists()


@pytest.mark.parametrize(
    ("install_result", "registered_after", "expected_success", "destination_exists"),
    ((True, False, False, False), (False, True, True, True)),
)
def test_legacy_install_uses_authoritative_enumeration_to_close_native_result_truth(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    install_result: bool,
    registered_after: bool,
    expected_success: bool,
    destination_exists: bool,
) -> None:
    color_dir = tmp_path / "color"
    source_dir = tmp_path / "source"
    color_dir.mkdir()
    source_dir.mkdir()
    source = source_dir / "reconciled.icc"
    source.write_bytes(valid_legacy_icc(14))
    native = RegistrationStateMscms(
        source.name,
        registered_after=registered_after,
        install_result=install_result,
    )
    monkeypatch.setattr(profile_installer, "MSCMS_AVAILABLE", True)
    monkeypatch.setattr(profile_installer, "mscms", native)
    monkeypatch.setattr(profile_installer, "get_profile_directory", lambda: color_dir)

    success, _message = profile_installer.install_profile(source)

    assert success is expected_success
    assert (color_dir / source.name).exists() is destination_exists
    assert ("enum-size",) in native.calls


@pytest.mark.parametrize(
    ("registered_after", "expected_success", "destination_exists"),
    ((False, False, False), (True, True, True)),
)
def test_legacy_install_closes_ordinary_native_errors_with_authoritative_enumeration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    registered_after: bool,
    expected_success: bool,
    destination_exists: bool,
) -> None:
    color_dir = tmp_path / "color"
    source_dir = tmp_path / "source"
    color_dir.mkdir()
    source_dir.mkdir()
    source = source_dir / "reconciled-error.icc"
    source.write_bytes(valid_legacy_icc(15))
    native = RegistrationStateMscms(
        source.name,
        registered_after=registered_after,
        install_error=RuntimeError("native install outcome interrupted"),
    )
    monkeypatch.setattr(profile_installer, "MSCMS_AVAILABLE", True)
    monkeypatch.setattr(profile_installer, "mscms", native)
    monkeypatch.setattr(profile_installer, "get_profile_directory", lambda: color_dir)

    success, _message = profile_installer.install_profile(source)

    assert success is expected_success
    assert (color_dir / source.name).exists() is destination_exists
    assert ("enum-size",) in native.calls


@pytest.mark.parametrize("interruption", [KeyboardInterrupt("pre-install cancellation"), SystemExit(56)])
def test_legacy_install_deletes_created_profile_when_cancelled_before_native_entry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    interruption: BaseException,
    unmeasured_tracing: None,
) -> None:
    color_dir = tmp_path / "color"
    source_dir = tmp_path / "source"
    color_dir.mkdir()
    source_dir.mkdir()
    source = source_dir / "pre-call.icc"
    source.write_bytes(valid_legacy_icc(10))
    native = install_fake_mscms(monkeypatch, color_dir)
    install_code = profile_installer.install_profile.__code__
    destination = color_dir / source.name
    fired = False

    def interrupt_before_native_entry(frame: object, event: str, _arg: object) -> object:
        nonlocal fired
        if (
            not fired
            and event == "line"
            and frame.f_code is install_code  # type: ignore[attr-defined]
            and destination.exists()
            and native.calls == []
        ):
            fired = True
            sys.settrace(None)
            raise interruption
        return interrupt_before_native_entry

    sys.settrace(interrupt_before_native_entry)
    try:
        with pytest.raises(type(interruption)) as caught:
            profile_installer.install_profile(source)
    finally:
        sys.settrace(None)

    assert fired is True
    assert caught.value is interruption
    assert not destination.exists()
    assert native.calls == []


@pytest.mark.parametrize("native_result", [False, True])
@pytest.mark.parametrize("interruption", [KeyboardInterrupt("post-install cancellation"), SystemExit(57)])
def test_legacy_install_publishes_native_result_before_post_native_cancellation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    native_result: bool,
    interruption: BaseException,
    unmeasured_tracing: None,
) -> None:
    color_dir = tmp_path / "color"
    source_dir = tmp_path / "source"
    color_dir.mkdir()
    source_dir.mkdir()
    source = source_dir / "post-call.icc"
    source.write_bytes(valid_legacy_icc(11))

    class ResultMscms(RecordingMscms):
        def InstallColorProfileW(self, _machine: object, path: str) -> bool:
            self.calls.append(("install", path))
            return native_result

    native = ResultMscms()
    monkeypatch.setattr(profile_installer, "MSCMS_AVAILABLE", True)
    monkeypatch.setattr(profile_installer, "mscms", native)
    monkeypatch.setattr(profile_installer, "get_profile_directory", lambda: color_dir)
    install_code = profile_installer.install_profile.__code__
    destination = color_dir / source.name
    fired = False

    def interrupt_after_native_return(frame: object, event: str, _arg: object) -> object:
        nonlocal fired
        if (
            not fired
            and event == "line"
            and frame.f_code is install_code  # type: ignore[attr-defined]
            and native.calls == [("install", str(destination))]
        ):
            fired = True
            sys.settrace(None)
            raise interruption
        return interrupt_after_native_return

    sys.settrace(interrupt_after_native_return)
    try:
        with pytest.raises(type(interruption)) as caught:
            profile_installer.install_profile(source)
    finally:
        sys.settrace(None)

    assert fired is True
    assert caught.value is interruption
    assert destination.exists() is native_result
    assert native.calls == [("install", str(destination))]


@pytest.mark.parametrize("interruption", [KeyboardInterrupt("uncertain install"), SystemExit(58)])
def test_legacy_install_retains_created_profile_when_native_entry_is_uncertain(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    interruption: BaseException,
) -> None:
    color_dir = tmp_path / "color"
    source_dir = tmp_path / "source"
    color_dir.mkdir()
    source_dir.mkdir()
    source = source_dir / "uncertain.icc"
    source.write_bytes(valid_legacy_icc(12))

    class InterruptedMscms(RecordingMscms):
        def InstallColorProfileW(self, _machine: object, path: str) -> bool:
            self.calls.append(("install", path))
            raise interruption

    native = InterruptedMscms()
    monkeypatch.setattr(profile_installer, "MSCMS_AVAILABLE", True)
    monkeypatch.setattr(profile_installer, "mscms", native)
    monkeypatch.setattr(profile_installer, "get_profile_directory", lambda: color_dir)
    destination = color_dir / source.name

    with pytest.raises(type(interruption)) as caught:
        profile_installer.install_profile(source)

    assert caught.value is interruption
    assert destination.read_bytes() == source.read_bytes()
    assert native.calls == [("install", str(destination))]


@pytest.mark.parametrize("interruption", [KeyboardInterrupt("create handoff"), SystemExit(52)])
def test_legacy_install_removes_its_created_file_when_handle_publication_is_cancelled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    interruption: BaseException,
    unmeasured_tracing: None,
) -> None:
    color_dir = tmp_path / "color"
    source_dir = tmp_path / "source"
    color_dir.mkdir()
    source_dir.mkdir()
    source = source_dir / "cancelled.icc"
    source.write_bytes(valid_legacy_icc(8))
    native = install_fake_mscms(monkeypatch, color_dir)
    context_code = profile_installer._verified_profile_delete_lease.__wrapped__.__code__
    fired = False

    def interrupt_before_publication(frame: object, event: str, _arg: object) -> object:
        nonlocal fired
        frame_locals = frame.f_locals  # type: ignore[attr-defined]
        owner = getattr(frame_locals.get("lease"), "_owner", None)
        if (
            not fired
            and event == "line"
            and frame.f_code is context_code  # type: ignore[attr-defined]
            and getattr(owner, "state", None) is profile_installer._ProfileNativeState.OPEN
            and getattr(owner, "handle", None) is not None
            and frame_locals.get("create_payload") is not None
            and frame_locals.get("body_entered") == []
        ):
            fired = True
            sys.settrace(None)
            raise interruption
        return interrupt_before_publication

    sys.settrace(interrupt_before_publication)
    try:
        with pytest.raises(type(interruption)) as caught:
            profile_installer.install_profile(source)
    finally:
        sys.settrace(None)

    assert fired is True
    assert caught.value is interruption
    assert not (color_dir / source.name).exists()
    assert native.calls == []


def test_legacy_install_removes_its_exact_partial_file_when_native_write_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    color_dir = tmp_path / "color"
    source_dir = tmp_path / "source"
    color_dir.mkdir()
    source_dir.mkdir()
    source = source_dir / "partial.icc"
    source.write_bytes(valid_legacy_icc(9))
    native = install_fake_mscms(monkeypatch, color_dir)
    original_write = profile_installer._VerifiedProfileDeleteHandle.write_bytes

    def write_partial_then_fail(
        lease: profile_installer._VerifiedProfileDeleteHandle,
        payload: bytes,
    ) -> None:
        original_write(lease, payload[:8])
        raise RuntimeError("simulated profile write failure")

    monkeypatch.setattr(profile_installer._VerifiedProfileDeleteHandle, "write_bytes", write_partial_then_fail)

    success, message = profile_installer.install_profile(source)

    assert success is False
    assert "write failure" in message
    assert not (color_dir / source.name).exists()
    assert native.calls == []


def test_uninstall_has_no_post_lease_path_swap_window(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profile = tmp_path / "ordinary.icc"
    profile.write_bytes(b"original-profile")
    native = install_fake_mscms(monkeypatch, tmp_path)

    assert not hasattr(profile_installer, "_verified_profile_mutation_lease")

    success, message = profile_installer.uninstall_profile(profile.name)

    assert success is True, message
    assert not profile.exists()
    assert native.calls == [("uninstall", str(profile), False)]


@pytest.mark.parametrize("interruption", [KeyboardInterrupt("uncertain close"), SystemExit(53)])
def test_profile_delete_handle_poisons_an_uncertain_native_close(
    interruption: BaseException,
) -> None:
    calls: list[object] = []

    class NativeFunction:
        def __call__(self, handle: object) -> bool:
            calls.append(handle)
            raise interruption

    lease = object.__new__(profile_installer._VerifiedProfileDeleteHandle)
    lease.handle = 77
    lease.delete_marked = False
    lease._close_poisoned = False
    lease.kernel32 = SimpleNamespace(CloseHandle=NativeFunction())

    with pytest.raises(type(interruption)) as caught:
        lease.close()

    assert caught.value is interruption
    assert lease.handle == 77
    assert lease._close_poisoned is True
    with pytest.raises(RuntimeError, match="poison|uncertain"):
        lease.close()
    assert calls == [77]


def test_profile_delete_handle_false_close_remains_explicitly_retryable() -> None:
    calls: list[object] = []
    results = iter((False, True))

    class NativeFunction:
        def __call__(self, handle: object) -> bool:
            calls.append(handle)
            return next(results)

    lease = object.__new__(profile_installer._VerifiedProfileDeleteHandle)
    lease.handle = 77
    lease.delete_marked = False
    lease._close_poisoned = False
    lease.kernel32 = SimpleNamespace(CloseHandle=NativeFunction())

    with pytest.raises(RuntimeError, match="close"):
        lease.close()
    assert lease.handle == 77
    assert lease._close_poisoned is False

    lease.close()

    assert lease.handle is None
    assert calls == [77, 77]


@pytest.mark.parametrize("interruption", [KeyboardInterrupt("normal cleanup dispatch"), SystemExit(54)])
def test_profile_lease_retries_close_when_normal_cleanup_dispatch_is_cancelled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    interruption: BaseException,
    unmeasured_tracing: None,
) -> None:
    class Lease:
        handle: object | None = 77
        delete_marked = False

        def validate(self, *, expected_payload: bytes | None = None) -> None:
            return None

        def close(self) -> None:
            self.handle = None
            close_calls.append(1)

    close_calls: list[int] = []
    lease = Lease()
    monkeypatch.setattr(profile_installer, "_VerifiedProfileDeleteHandle", lambda *_args, **_kwargs: lease)
    function = profile_installer._finish_verified_profile_lease_cleanup
    source_lines = Path(function.__code__.co_filename).read_text(encoding="utf-8").splitlines()
    fired = False

    def interrupt_dispatch(frame: object, event: str, _arg: object) -> object:
        nonlocal fired
        if (
            not fired
            and event == "line"
            and frame.f_code is function.__code__  # type: ignore[attr-defined]
            and "if lease is not None" in source_lines[frame.f_lineno - 1]  # type: ignore[attr-defined]
        ):
            fired = True
            sys.settrace(None)
            raise interruption
        return interrupt_dispatch

    sys.settrace(interrupt_dispatch)
    try:
        with pytest.raises(type(interruption)) as caught:
            with profile_installer._verified_profile_delete_lease(tmp_path / "normal.icc"):
                pass
    finally:
        sys.settrace(None)

    assert fired is True
    assert caught.value is interruption
    assert close_calls == [1]


def test_profile_lease_cleanup_retries_a_known_open_false_close(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Lease:
        handle: object | None = 77
        delete_marked = False
        _close_poisoned = False

        def validate(self, *, expected_payload: bytes | None = None) -> None:
            return None

        def close(self) -> None:
            close_calls.append(1)
            if len(close_calls) == 1:
                raise RuntimeError("known-open CloseHandle false")
            self.handle = None

    close_calls: list[int] = []
    lease = Lease()
    monkeypatch.setattr(profile_installer, "_VerifiedProfileDeleteHandle", lambda *_args, **_kwargs: lease)

    with profile_installer._verified_profile_delete_lease(tmp_path / "retry-close.icc"):
        pass

    assert close_calls == [1, 1]
    assert lease.handle is None


@pytest.mark.parametrize("interruption", [KeyboardInterrupt("pre-close guard"), SystemExit(60)])
def test_profile_lease_cleanup_retries_cancellation_before_close_native_guard(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    interruption: BaseException,
    unmeasured_tracing: None,
) -> None:
    class Lease:
        handle: object | None = 77
        delete_marked = False
        _close_poisoned = False

        def validate(self, *, expected_payload: bytes | None = None) -> None:
            return None

        def close(self) -> None:
            self.handle = None
            close_calls.append(1)

    close_calls: list[int] = []
    lease = Lease()
    monkeypatch.setattr(profile_installer, "_VerifiedProfileDeleteHandle", lambda *_args, **_kwargs: lease)
    close_code = Lease.close.__code__
    fired = False

    def interrupt_before_close_guard(frame: object, event: str, _arg: object) -> object:
        nonlocal fired
        if not fired and event == "line" and frame.f_code is close_code:  # type: ignore[attr-defined]
            fired = True
            sys.settrace(None)
            raise interruption
        return interrupt_before_close_guard

    sys.settrace(interrupt_before_close_guard)
    try:
        with pytest.raises(type(interruption)) as caught:
            with profile_installer._verified_profile_delete_lease(tmp_path / "retry-close.icc"):
                pass
    finally:
        sys.settrace(None)

    assert fired is True
    assert caught.value is interruption
    assert close_calls == [1]
    assert lease.handle is None


def test_profile_lease_cleanup_retains_a_persistently_open_handle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Lease:
        handle: object | None = 77
        delete_marked = False
        _close_poisoned = False

        def validate(self, *, expected_payload: bytes | None = None) -> None:
            return None

        def close(self) -> None:
            close_calls.append(1)
            raise RuntimeError("known-open CloseHandle false")

    close_calls: list[int] = []
    lease = Lease()
    retained: list[object] = []
    monkeypatch.setattr(profile_installer, "_VerifiedProfileDeleteHandle", lambda *_args, **_kwargs: lease)
    monkeypatch.setattr(profile_installer, "_RETAINED_PROFILE_DELETE_LEASES", retained, raising=False)

    with pytest.raises(RuntimeError, match="close|cleanup"):
        with profile_installer._verified_profile_delete_lease(tmp_path / "retained-close.icc"):
            pass

    assert close_calls == [1, 1]
    assert retained == [lease]


@pytest.mark.parametrize(
    ("first_failure", "expected_control_flow"),
    ((KeyboardInterrupt("pre-delete guard"), True), (RuntimeError("known no-effect delete false"), False)),
)
def test_profile_lease_cleanup_retries_retryable_delete_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    first_failure: BaseException,
    expected_control_flow: bool,
) -> None:
    class Lease:
        handle: object | None = 77
        delete_marked = False
        _delete_outcome = ["open"]
        _close_poisoned = False

        def write_bytes(self, _payload: bytes) -> None:
            return None

        def validate(self, *, expected_payload: bytes | None = None) -> None:
            return None

        def mark_delete(self, *, expected_payload: bytes | None = None) -> None:
            delete_calls.append(1)
            if len(delete_calls) == 1:
                raise first_failure
            self._delete_outcome[0] = "marked"
            self.delete_marked = True

        def close(self) -> None:
            self.handle = None

    delete_calls: list[int] = []
    lease = Lease()
    monkeypatch.setattr(profile_installer, "_VerifiedProfileDeleteHandle", lambda *_args, **_kwargs: lease)

    context = profile_installer._verified_profile_delete_lease(
        tmp_path / "retry-delete.icc",
        create_payload=b"payload",
    )
    if expected_control_flow:
        with pytest.raises(type(first_failure)) as caught:
            with context:
                raise RuntimeError("body failure")
        assert caught.value is first_failure
    else:
        with pytest.raises(RuntimeError, match="body failure"):
            with context:
                raise RuntimeError("body failure")

    assert delete_calls == [1, 1]
    assert lease.delete_marked is True
    assert lease.handle is None


def test_profile_lease_cleanup_retains_exact_handle_when_delete_remains_retryable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Lease:
        handle: object | None = 77
        delete_marked = False
        _delete_outcome = ["open"]
        _close_poisoned = False

        def write_bytes(self, _payload: bytes) -> None:
            return None

        def validate(self, *, expected_payload: bytes | None = None) -> None:
            return None

        def mark_delete(self, *, expected_payload: bytes | None = None) -> None:
            delete_calls.append(1)
            raise RuntimeError("known-open delete disposition false")

        def close(self) -> None:
            close_calls.append(1)
            self.handle = None

    delete_calls: list[int] = []
    close_calls: list[int] = []
    retained: list[object] = []
    lease = Lease()
    monkeypatch.setattr(profile_installer, "_VerifiedProfileDeleteHandle", lambda *_args, **_kwargs: lease)
    monkeypatch.setattr(profile_installer, "_RETAINED_PROFILE_DELETE_LEASES", retained)

    with pytest.raises(RuntimeError, match="body failure"):
        with profile_installer._verified_profile_delete_lease(
            tmp_path / "retained-delete.icc",
            create_payload=b"payload",
        ):
            raise RuntimeError("body failure")

    assert delete_calls == [1, 1]
    assert close_calls == []
    assert retained == [lease]
    assert lease.handle == 77


@pytest.mark.parametrize("interruption", [KeyboardInterrupt("post-yield boundary"), SystemExit(59)])
def test_profile_lease_closes_when_resumption_from_yield_is_cancelled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    interruption: BaseException,
    unmeasured_tracing: None,
) -> None:
    class Lease:
        handle: object | None = 77
        delete_marked = False

        def validate(self, *, expected_payload: bytes | None = None) -> None:
            return None

        def close(self) -> None:
            self.handle = None
            close_calls.append(1)

    close_calls: list[int] = []
    lease = Lease()
    monkeypatch.setattr(profile_installer, "_VerifiedProfileDeleteHandle", lambda *_args, **_kwargs: lease)
    function = profile_installer._verified_profile_delete_lease.__wrapped__
    body_completed = False
    fired = False

    def interrupt_on_context_resumption(frame: object, event: str, _arg: object) -> object:
        nonlocal fired
        if (
            not fired
            and body_completed
            and event == "line"
            and frame.f_code is function.__code__  # type: ignore[attr-defined]
            and close_calls == []
        ):
            fired = True
            sys.settrace(None)
            raise interruption
        return interrupt_on_context_resumption

    sys.settrace(interrupt_on_context_resumption)
    try:
        with pytest.raises(type(interruption)) as caught:
            with profile_installer._verified_profile_delete_lease(tmp_path / "normal.icc"):
                body_completed = True
    finally:
        sys.settrace(None)

    assert fired is True
    assert caught.value is interruption
    assert close_calls == [1]


@pytest.mark.parametrize("interruption", [KeyboardInterrupt("failure cleanup dispatch"), SystemExit(55)])
def test_profile_lease_runs_delete_and_close_when_failure_cleanup_dispatch_is_cancelled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    interruption: BaseException,
    unmeasured_tracing: None,
) -> None:
    class Lease:
        handle: object | None = 77
        delete_marked = False

        def write_bytes(self, _payload: bytes) -> None:
            return None

        def validate(self, *, expected_payload: bytes | None = None) -> None:
            return None

        def mark_delete(self, *, expected_payload: bytes | None = None) -> None:
            self.delete_marked = True
            delete_calls.append(1)

        def close(self) -> None:
            self.handle = None
            close_calls.append(1)

    delete_calls: list[int] = []
    close_calls: list[int] = []
    lease = Lease()
    monkeypatch.setattr(profile_installer, "_VerifiedProfileDeleteHandle", lambda *_args, **_kwargs: lease)
    function = profile_installer._finish_verified_profile_lease_cleanup
    source_lines = Path(function.__code__.co_filename).read_text(encoding="utf-8").splitlines()
    fired = False

    def interrupt_dispatch(frame: object, event: str, _arg: object) -> object:
        nonlocal fired
        if (
            not fired
            and event == "line"
            and frame.f_code is function.__code__  # type: ignore[attr-defined]
            and "if delete_created" in source_lines[frame.f_lineno - 1]  # type: ignore[attr-defined]
        ):
            fired = True
            sys.settrace(None)
            raise interruption
        return interrupt_dispatch

    sys.settrace(interrupt_dispatch)
    try:
        with pytest.raises(type(interruption)) as caught:
            with profile_installer._verified_profile_delete_lease(
                tmp_path / "failed.icc",
                create_payload=b"payload",
            ):
                raise RuntimeError("primary failure")
    finally:
        sys.settrace(None)

    assert fired is True
    assert caught.value is interruption
    assert delete_calls == [1]
    assert close_calls == [1]


@pytest.mark.parametrize("alias_kind", ["hardlink", "symlink"])
def test_uninstall_rechecks_substitution_before_native_or_delete_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    alias_kind: str,
) -> None:
    product = tmp_path / f"calibrate-pro-{'a' * 64}.icc"
    product.write_bytes(b"product-cache")
    ordinary = tmp_path / "ordinary.icc"
    ordinary.write_bytes(b"ordinary")
    if alias_kind == "symlink":
        probe = tmp_path / "symlink-probe.icc"
        try:
            probe.symlink_to(product)
            probe.unlink()
        except OSError as exc:
            pytest.skip(f"file symlinks unavailable: {exc}")
    native = install_fake_mscms(monkeypatch, tmp_path)
    original_check = profile_installer._path_resolves_to_transactional_profile_cache
    check_calls = 0

    def substitute_after_precheck(path: Path) -> bool:
        nonlocal check_calls
        check_calls += 1
        result = original_check(path)
        if check_calls == 1:
            assert result is False
            path.unlink()
            if alias_kind == "hardlink":
                path.hardlink_to(product)
            else:
                path.symlink_to(product)
            return False
        return result

    monkeypatch.setattr(profile_installer, "_path_resolves_to_transactional_profile_cache", substitute_after_precheck)

    success, _message = profile_installer.uninstall_profile(ordinary.name)

    assert success is False
    assert product.read_bytes() == b"product-cache"
    assert native.calls == []


def test_uninstall_keeps_windows_owned_delete_for_an_ordinary_basename(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profile = tmp_path / "ordinary.icc"
    profile.write_bytes(b"profile")
    native = install_fake_mscms(monkeypatch, tmp_path)

    success, message = profile_installer.uninstall_profile(profile.name)

    assert success is True, message
    assert not profile.exists()
    assert native.calls == [("uninstall", str(profile), False)]


def test_uninstall_fails_without_deleting_when_mscms_is_unavailable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profile = tmp_path / "ordinary.icc"
    profile.write_bytes(b"profile")
    monkeypatch.setattr(profile_installer, "MSCMS_AVAILABLE", False)
    monkeypatch.setattr(profile_installer, "mscms", None)
    monkeypatch.setattr(profile_installer, "get_profile_directory", lambda: tmp_path)

    success, message = profile_installer.uninstall_profile(profile.name)

    assert success is False
    assert "unavailable" in message.casefold() or "not available" in message.casefold()
    assert profile.read_bytes() == b"profile"


@pytest.mark.parametrize("interruption", [KeyboardInterrupt("post-uninstall success"), SystemExit(61)])
def test_uninstall_post_success_cancellation_disposes_the_exact_unregistered_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    interruption: BaseException,
    unmeasured_tracing: None,
) -> None:
    profile = tmp_path / "ordinary.icc"
    profile.write_bytes(b"profile")
    native = install_fake_mscms(monkeypatch, tmp_path)
    uninstall_code = profile_installer.uninstall_profile.__code__
    fired = False

    def interrupt_after_native_success(frame: object, event: str, _arg: object) -> object:
        nonlocal fired
        if (
            not fired
            and event == "line"
            and frame.f_code is uninstall_code  # type: ignore[attr-defined]
            and native.calls == [("uninstall", str(profile), False)]
        ):
            fired = True
            sys.settrace(None)
            raise interruption
        return interrupt_after_native_success

    sys.settrace(interrupt_after_native_success)
    try:
        with pytest.raises(type(interruption)) as caught:
            profile_installer.uninstall_profile(profile.name)
    finally:
        sys.settrace(None)

    assert fired is True
    assert caught.value is interruption
    assert not profile.exists()


@pytest.mark.parametrize(
    ("uninstall_result", "registered_after", "expected_success", "profile_exists"),
    ((True, True, False, True), (False, False, True, False)),
)
def test_uninstall_uses_authoritative_enumeration_before_exact_file_disposition(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    uninstall_result: bool,
    registered_after: bool,
    expected_success: bool,
    profile_exists: bool,
) -> None:
    profile = tmp_path / "ordinary.icc"
    profile.write_bytes(b"profile")
    native = RegistrationStateMscms(
        profile.name,
        registered_after=registered_after,
        uninstall_result=uninstall_result,
    )
    monkeypatch.setattr(profile_installer, "MSCMS_AVAILABLE", True)
    monkeypatch.setattr(profile_installer, "mscms", native)
    monkeypatch.setattr(profile_installer, "get_profile_directory", lambda: tmp_path)

    success, _message = profile_installer.uninstall_profile(profile.name)

    assert success is expected_success
    assert profile.exists() is profile_exists
    assert ("enum-size",) in native.calls


@pytest.mark.parametrize(
    ("registered_after", "expected_success", "profile_exists"),
    ((False, True, False), (True, False, True)),
)
def test_uninstall_closes_ordinary_native_errors_with_authoritative_enumeration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    registered_after: bool,
    expected_success: bool,
    profile_exists: bool,
) -> None:
    profile = tmp_path / "ordinary.icc"
    profile.write_bytes(b"profile")
    native = RegistrationStateMscms(
        profile.name,
        registered_after=registered_after,
        uninstall_error=RuntimeError("native uninstall outcome interrupted"),
    )
    monkeypatch.setattr(profile_installer, "MSCMS_AVAILABLE", True)
    monkeypatch.setattr(profile_installer, "mscms", native)
    monkeypatch.setattr(profile_installer, "get_profile_directory", lambda: tmp_path)

    success, _message = profile_installer.uninstall_profile(profile.name)

    assert success is expected_success
    assert profile.exists() is profile_exists
    assert ("enum-size",) in native.calls


def test_uninstall_does_not_report_success_when_exact_disposition_leaves_the_path_present(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profile = tmp_path / "ordinary.icc"
    profile.write_bytes(b"profile")
    native = install_fake_mscms(monkeypatch, tmp_path)

    class Lease:
        handle: object | None = 77
        delete_marked = False
        _delete_outcome = ["open"]
        _close_poisoned = False

        def validate(self, *, expected_payload: bytes | None = None) -> None:
            return None

        def mark_delete(self, *, expected_payload: bytes | None = None) -> None:
            self._delete_outcome[0] = "marked"
            self.delete_marked = True

        def close(self) -> None:
            self.handle = None

    lease = Lease()
    monkeypatch.setattr(profile_installer, "_VerifiedProfileDeleteHandle", lambda *_args, **_kwargs: lease)

    success, message = profile_installer.uninstall_profile(profile.name)

    assert success is False
    assert "remains" in message.casefold() or "disposition" in message.casefold()
    assert profile.read_bytes() == b"profile"
    assert native.calls == [("uninstall", str(profile), False)]


@pytest.mark.parametrize("registered_after", [False, True])
@pytest.mark.parametrize("interruption", [KeyboardInterrupt("uncertain uninstall"), SystemExit(62)])
def test_uninstall_uncertain_native_entry_deletes_only_with_authoritative_absence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    registered_after: bool,
    interruption: BaseException,
) -> None:
    profile = tmp_path / "ordinary.icc"
    profile.write_bytes(b"profile")
    native = RegistrationStateMscms(
        profile.name,
        registered_after=registered_after,
        uninstall_error=interruption,
    )
    monkeypatch.setattr(profile_installer, "MSCMS_AVAILABLE", True)
    monkeypatch.setattr(profile_installer, "mscms", native)
    monkeypatch.setattr(profile_installer, "get_profile_directory", lambda: tmp_path)

    with pytest.raises(type(interruption)) as caught:
        profile_installer.uninstall_profile(profile.name)

    assert caught.value is interruption
    assert profile.exists() is registered_after
    assert ("enum-size",) in native.calls


@pytest.mark.parametrize("interruption", [KeyboardInterrupt("delete handoff cancelled"), SystemExit(51)])
def test_handle_delete_closes_on_first_post_create_cancellation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    interruption: BaseException,
    unmeasured_tracing: None,
) -> None:
    profile = tmp_path / "ordinary.icc"
    profile.write_bytes(b"profile")
    close_calls: list[object] = []

    class NativeFunction:
        def __init__(self, callback: object) -> None:
            self.callback = callback
            self.argtypes: object = None
            self.restype: object = None

        def __call__(self, *args: object) -> object:
            return self.callback(*args)  # type: ignore[operator]

    kernel32 = SimpleNamespace(
        CreateFileW=NativeFunction(lambda *_args: 77),
        GetFileInformationByHandle=NativeFunction(lambda *_args: True),
        GetFinalPathNameByHandleW=NativeFunction(lambda *_args: 0),
        GetFileType=NativeFunction(lambda *_args: 1),
        GetFileSizeEx=NativeFunction(lambda *_args: True),
        SetFilePointerEx=NativeFunction(lambda *_args: True),
        ReadFile=NativeFunction(lambda *_args: True),
        WriteFile=NativeFunction(lambda *_args: True),
        FlushFileBuffers=NativeFunction(lambda *_args: True),
        SetFileInformationByHandle=NativeFunction(lambda *_args: True),
        CloseHandle=NativeFunction(lambda handle: close_calls.append(handle) or True),
    )
    monkeypatch.setattr(profile_installer.ctypes, "WinDLL", lambda *_args, **_kwargs: kernel32)
    context_code = profile_installer._verified_profile_delete_lease.__wrapped__.__code__
    fired = False

    def interrupt_after_create(frame: object, event: str, _arg: object) -> object:
        nonlocal fired
        frame_code = frame.f_code  # type: ignore[attr-defined]
        frame_locals = frame.f_locals  # type: ignore[attr-defined]
        if (
            not fired
            and event == "line"
            and frame_code is context_code
            and getattr(frame_locals.get("lease"), "handle", None) == 77
            and frame_locals.get("body_entered") == []
            and close_calls == []
        ):
            fired = True
            sys.settrace(None)
            raise interruption
        return interrupt_after_create

    sys.settrace(interrupt_after_create)
    try:
        with pytest.raises(type(interruption)) as caught:
            profile_installer._delete_profile_file_by_handle(profile)
    finally:
        sys.settrace(None)

    assert fired is True
    assert caught.value is interruption
    assert close_calls == [77]


def test_profile_handle_constructor_retries_a_known_open_false_close(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    unmeasured_tracing: None,
) -> None:
    profile = tmp_path / "ordinary.icc"
    profile.write_bytes(b"profile")
    close_results = iter((False, True))
    close_calls: list[object] = []

    class NativeFunction:
        def __init__(self, callback: object) -> None:
            self.callback = callback
            self.argtypes: object = None
            self.restype: object = None

        def __call__(self, *args: object) -> object:
            return self.callback(*args)  # type: ignore[operator]

    def close_handle(handle: object) -> bool:
        close_calls.append(handle)
        return next(close_results)

    kernel32 = SimpleNamespace(
        CreateFileW=NativeFunction(lambda *_args: 77),
        GetFileInformationByHandle=NativeFunction(lambda *_args: True),
        GetFinalPathNameByHandleW=NativeFunction(lambda *_args: 0),
        GetFileType=NativeFunction(lambda *_args: 1),
        GetFileSizeEx=NativeFunction(lambda *_args: True),
        SetFilePointerEx=NativeFunction(lambda *_args: True),
        ReadFile=NativeFunction(lambda *_args: True),
        WriteFile=NativeFunction(lambda *_args: True),
        FlushFileBuffers=NativeFunction(lambda *_args: True),
        SetFileInformationByHandle=NativeFunction(lambda *_args: True),
        CloseHandle=NativeFunction(close_handle),
    )
    monkeypatch.setattr(profile_installer.ctypes, "WinDLL", lambda *_args, **_kwargs: kernel32)
    context_code = profile_installer._verified_profile_delete_lease.__wrapped__.__code__
    interruption = KeyboardInterrupt("constructor publication cancelled")
    fired = False

    def interrupt_after_create(frame: object, event: str, _arg: object) -> object:
        nonlocal fired
        frame_locals = frame.f_locals  # type: ignore[attr-defined]
        if (
            not fired
            and event == "line"
            and frame.f_code is context_code  # type: ignore[attr-defined]
            and getattr(frame_locals.get("lease"), "handle", None) == 77
            and frame_locals.get("body_entered") == []
        ):
            fired = True
            sys.settrace(None)
            raise interruption
        return interrupt_after_create

    sys.settrace(interrupt_after_create)
    try:
        with pytest.raises(KeyboardInterrupt) as caught:
            profile_installer._delete_profile_file_by_handle(profile)
    finally:
        sys.settrace(None)

    assert fired is True
    assert caught.value is interruption
    assert close_calls == [77, 77]


@pytest.mark.parametrize("interruption", [KeyboardInterrupt("CreateFile store"), SystemExit(66)])
def test_profile_handle_acquisition_survives_call_to_store_fast_cancellation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    interruption: BaseException,
    unmeasured_tracing: None,
) -> None:
    """Caller-local tracing cannot interrupt the exact native worker's publication."""
    profile = tmp_path / "ordinary.icc"
    profile.write_bytes(b"profile")
    close_calls: list[object] = []
    native_threads: list[tuple[str, int]] = []
    retained: list[object] = []

    class NativeFunction:
        def __init__(self, callback: object) -> None:
            self.callback = callback
            self.argtypes: object = None
            self.restype: object = None

        def __call__(self, *args: object) -> object:
            return self.callback(*args)  # type: ignore[operator]

    kernel32 = SimpleNamespace(
        CreateFileW=NativeFunction(lambda *_args: native_threads.append(("create", threading.get_ident())) or 77),
        GetFileInformationByHandle=NativeFunction(lambda *_args: True),
        GetFinalPathNameByHandleW=NativeFunction(lambda *_args: 0),
        GetFileType=NativeFunction(lambda *_args: 1),
        GetFileSizeEx=NativeFunction(lambda *_args: True),
        SetFilePointerEx=NativeFunction(lambda *_args: True),
        ReadFile=NativeFunction(lambda *_args: True),
        WriteFile=NativeFunction(lambda *_args: True),
        FlushFileBuffers=NativeFunction(lambda *_args: True),
        SetFileInformationByHandle=NativeFunction(lambda *_args: True),
        CloseHandle=NativeFunction(
            lambda handle: native_threads.append(("close", threading.get_ident())) or close_calls.append(handle) or True
        ),
    )
    monkeypatch.setattr(profile_installer.ctypes, "WinDLL", lambda *_args, **_kwargs: kernel32)
    monkeypatch.setattr(profile_installer, "_RETAINED_PROFILE_DELETE_LEASES", retained)
    function = profile_installer._VerifiedProfileDeleteHandle._initialize

    def prime_opcode_tracing(frame: object, event: str, _arg: object) -> object:
        if event == "call" and frame.f_code is function.__code__:  # type: ignore[attr-defined]
            frame.f_trace_opcodes = True  # type: ignore[attr-defined]
        return prime_opcode_tracing

    sys.settrace(prime_opcode_tracing)
    try:
        priming_lease = profile_installer._VerifiedProfileDeleteHandle(profile, create=False)
        priming_lease.close()
    finally:
        sys.settrace(None)
    close_calls.clear()
    native_threads.clear()
    retained.clear()
    instructions = tuple(dis.get_instructions(function))
    target = next(
        instruction.offset for instruction in instructions if instruction.opname in {"RETURN_CONST", "RETURN_VALUE"}
    )
    trace = interrupt_at_opcode(function, target, interruption)

    sys.settrace(trace)
    try:
        with pytest.raises(type(interruption)) as caught:
            profile_installer._delete_profile_file_by_handle(profile)
    finally:
        sys.settrace(None)

    assert caught.value is interruption
    assert close_calls == [77] or any(getattr(lease, "handle", None) == 77 for lease in retained)
    assert [action for action, _thread in native_threads] == ["create", "close"]
    assert all(thread != threading.get_ident() for _action, thread in native_threads)


@pytest.mark.parametrize("interruption", [KeyboardInterrupt("delete pre-entry"), SystemExit(67)])
def test_profile_delete_disposition_retries_instruction_cancellation_before_native_call(
    monkeypatch: pytest.MonkeyPatch,
    interruption: BaseException,
    unmeasured_tracing: None,
) -> None:
    native_calls: list[object] = []
    close_calls: list[object] = []

    class NativeFunction:
        def __call__(self, *args: object) -> bool:
            native_calls.append(args)
            return True

    class CloseFunction:
        def __call__(self, handle: object) -> bool:
            close_calls.append(handle)
            return True

    lease = object.__new__(profile_installer._VerifiedProfileDeleteHandle)
    lease.handle = 77
    lease.delete_marked = False
    lease._delete_outcome = ["open"]
    lease._delete_on_body_error = None
    lease._close_poisoned = False
    lease.kernel32 = SimpleNamespace(
        SetFileInformationByHandle=NativeFunction(),
        CloseHandle=CloseFunction(),
    )
    lease.validate = lambda **_kwargs: None  # type: ignore[method-assign]
    function = profile_installer._start_profile_native_attempt
    target = next(
        instruction.offset
        for instruction in dis.get_instructions(function)
        if instruction.opname in {"LOAD_ATTR", "LOAD_METHOD"} and instruction.argval == "start"
    )
    trace = interrupt_at_opcode(function, target, interruption)
    cleanup_errors: list[BaseException] = []

    sys.settrace(trace)
    try:
        profile_installer._finish_verified_profile_lease_cleanup(
            lease,
            delete_created=True,
            cleanup_errors=cleanup_errors,
        )
    finally:
        sys.settrace(None)

    assert interruption in cleanup_errors
    assert len(native_calls) == 1
    assert lease.delete_marked is True
    assert close_calls == [77]


def test_profile_close_waits_for_the_exact_delete_disposition_worker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profile = tmp_path / "delete-worker.icc"
    profile.write_bytes(b"profile")
    mutation_started = threading.Event()
    release_mutation = threading.Event()
    close_entered = threading.Event()
    native_calls: list[str] = []
    retained: list[object] = []

    class NativeFunction:
        def __init__(self, callback: object) -> None:
            self.callback = callback
            self.argtypes: object = None
            self.restype: object = None

        def __call__(self, *args: object) -> object:
            return self.callback(*args)  # type: ignore[operator]

    def close_handle(_handle: object) -> bool:
        native_calls.append("close")
        close_entered.set()
        return True

    kernel32 = SimpleNamespace(
        CreateFileW=NativeFunction(lambda *_args: 77),
        GetFileInformationByHandle=NativeFunction(lambda *_args: True),
        GetFinalPathNameByHandleW=NativeFunction(lambda *_args: 0),
        GetFileType=NativeFunction(lambda *_args: 1),
        GetFileSizeEx=NativeFunction(lambda *_args: True),
        SetFilePointerEx=NativeFunction(lambda *_args: True),
        ReadFile=NativeFunction(lambda *_args: True),
        WriteFile=NativeFunction(lambda *_args: True),
        FlushFileBuffers=NativeFunction(lambda *_args: True),
        SetFileInformationByHandle=NativeFunction(lambda *_args: native_calls.append("delete") or True),
        CloseHandle=NativeFunction(close_handle),
    )
    monkeypatch.setattr(profile_installer.ctypes, "WinDLL", lambda *_args, **_kwargs: kernel32)
    monkeypatch.setattr(profile_installer, "_RETAINED_PROFILE_DELETE_LEASES", retained)
    lease = profile_installer._VerifiedProfileDeleteHandle(profile, create=False)
    original_worker = profile_installer._VerifiedProfileDeleteHandle._delete_disposition_worker

    def delayed_worker(
        owner: profile_installer._VerifiedProfileDeleteHandle,
        token: object,
        done: threading.Event,
        disposition: object,
    ) -> None:
        mutation_started.set()
        assert release_mutation.wait(timeout=2)
        original_worker(owner, token, done, disposition)  # type: ignore[arg-type]

    monkeypatch.setattr(
        profile_installer._VerifiedProfileDeleteHandle,
        "_delete_disposition_worker",
        delayed_worker,
    )
    invoke_errors: list[BaseException] = []
    cleanup_errors: list[BaseException] = []

    def invoke_delete() -> None:
        try:
            lease._invoke_delete_disposition(profile_installer._FILE_DISPOSITION_INFORMATION(True))
        except BaseException as error:
            invoke_errors.append(error)

    def cleanup() -> None:
        profile_installer._finish_verified_profile_lease_cleanup(
            lease,
            delete_created=False,
            cleanup_errors=cleanup_errors,
        )

    mutation_caller = threading.Thread(target=invoke_delete)
    cleanup_caller = threading.Thread(target=cleanup)
    mutation_caller.start()
    assert mutation_started.wait(timeout=1)
    cleanup_caller.start()
    try:
        assert not close_entered.wait(timeout=0.2)
    finally:
        release_mutation.set()
    mutation_caller.join(timeout=2)
    cleanup_caller.join(timeout=2)

    assert not mutation_caller.is_alive()
    assert not cleanup_caller.is_alive()
    assert invoke_errors == []
    assert cleanup_errors == []
    assert native_calls == ["delete", "close"]
    assert lease.handle is None
    assert retained == []


def test_profile_delete_cannot_replace_an_in_flight_close_attempt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profile = tmp_path / "close-first.icc"
    profile.write_bytes(b"profile")
    close_entered = threading.Event()
    release_close = threading.Event()
    delete_entered = threading.Event()
    retained: list[object] = []

    class NativeFunction:
        def __init__(self, callback: object) -> None:
            self.callback = callback
            self.argtypes: object = None
            self.restype: object = None

        def __call__(self, *args: object) -> object:
            return self.callback(*args)  # type: ignore[operator]

    def close_handle(_handle: object) -> bool:
        close_entered.set()
        assert release_close.wait(timeout=2)
        return True

    kernel32 = SimpleNamespace(
        CreateFileW=NativeFunction(lambda *_args: 77),
        GetFileInformationByHandle=NativeFunction(lambda *_args: True),
        GetFinalPathNameByHandleW=NativeFunction(lambda *_args: 0),
        GetFileType=NativeFunction(lambda *_args: 1),
        GetFileSizeEx=NativeFunction(lambda *_args: True),
        SetFilePointerEx=NativeFunction(lambda *_args: True),
        ReadFile=NativeFunction(lambda *_args: True),
        WriteFile=NativeFunction(lambda *_args: True),
        FlushFileBuffers=NativeFunction(lambda *_args: True),
        SetFileInformationByHandle=NativeFunction(lambda *_args: delete_entered.set() or True),
        CloseHandle=NativeFunction(close_handle),
    )
    monkeypatch.setattr(profile_installer.ctypes, "WinDLL", lambda *_args, **_kwargs: kernel32)
    monkeypatch.setattr(profile_installer, "_RETAINED_PROFILE_DELETE_LEASES", retained)
    lease = profile_installer._VerifiedProfileDeleteHandle(profile, create=False)
    close_errors: list[BaseException] = []
    delete_errors: list[BaseException] = []

    def close() -> None:
        try:
            lease.close()
        except BaseException as error:
            close_errors.append(error)

    def delete() -> None:
        try:
            lease._invoke_delete_disposition(profile_installer._FILE_DISPOSITION_INFORMATION(True))
        except BaseException as error:
            delete_errors.append(error)

    close_caller = threading.Thread(target=close)
    delete_caller = threading.Thread(target=delete)
    close_caller.start()
    assert close_entered.wait(timeout=1)
    delete_caller.start()
    try:
        delete_was_blocked = not delete_entered.wait(timeout=0.2)
    finally:
        release_close.set()
        close_caller.join(timeout=2)
        delete_caller.join(timeout=2)

    assert delete_was_blocked
    assert not close_caller.is_alive()
    assert not delete_caller.is_alive()
    assert close_errors == []
    assert len(delete_errors) == 1
    assert isinstance(delete_errors[0], RuntimeError)
    assert lease.handle is None
    assert retained == []


@pytest.mark.parametrize("interruption", [KeyboardInterrupt("profile claim handoff"), SystemExit(72)])
def test_profile_claim_guard_rolls_back_cancellation_before_body(
    monkeypatch: pytest.MonkeyPatch,
    interruption: BaseException,
    unmeasured_tracing: None,
) -> None:
    lease = object.__new__(profile_installer._VerifiedProfileDeleteHandle)
    lease.handle = 77
    lease.delete_marked = False
    lease._delete_outcome = ["open"]
    retained: list[object] = [lease]
    token = object()
    body_entered: list[bool] = []
    monkeypatch.setattr(profile_installer, "_RETAINED_PROFILE_DELETE_LEASES", retained)

    def claim_then_enter_body() -> None:
        with profile_installer._claim_profile_delete_lease(lease, token) as claim:
            assert claim.acquired
            body_entered.append(True)

    def prime_opcode_tracing(frame: object, event: str, _arg: object) -> object:
        if event == "call" and frame.f_code is claim_then_enter_body.__code__:  # type: ignore[attr-defined]
            frame.f_trace_opcodes = True  # type: ignore[attr-defined]
        return prime_opcode_tracing

    sys.settrace(prime_opcode_tracing)
    try:
        claim_then_enter_body()
    finally:
        sys.settrace(None)
    body_entered.clear()

    def interrupt_before_body(frame: object, event: str, _arg: object) -> object:
        if (
            event == "line"
            and frame.f_code is claim_then_enter_body.__code__  # type: ignore[attr-defined]
            and lease._owner.claim is profile_installer._ProfileOwnerClaim.CLAIMED
            and body_entered == []
        ):
            sys.settrace(None)
            raise interruption
        return interrupt_before_body

    sys.settrace(interrupt_before_body)
    try:
        with pytest.raises(type(interruption)) as caught:
            claim_then_enter_body()
    finally:
        sys.settrace(None)

    assert caught.value is interruption
    assert body_entered == []
    assert lease._owner.claim is profile_installer._ProfileOwnerClaim.RETAINED
    assert lease._owner.claimant is None
    assert retained == [lease]


@pytest.mark.parametrize("interruption", [KeyboardInterrupt("profile guard return"), SystemExit(76)])
def test_profile_claim_guard_return_cancellation_cannot_strand_claim(
    monkeypatch: pytest.MonkeyPatch,
    interruption: BaseException,
    unmeasured_tracing: None,
) -> None:
    lease = object.__new__(profile_installer._VerifiedProfileDeleteHandle)
    lease.handle = 77
    lease.delete_marked = False
    lease._delete_outcome = ["open"]
    retained: list[object] = [lease]
    monkeypatch.setattr(profile_installer, "_RETAINED_PROFILE_DELETE_LEASES", retained)
    guard = profile_installer._claim_profile_delete_lease(lease, object())
    function = type(guard).__enter__

    priming_guard = profile_installer._claim_profile_delete_lease(lease, object())

    def prime_opcode_tracing(frame: object, event: str, _arg: object) -> object:
        if event == "call" and frame.f_code is function.__code__:  # type: ignore[attr-defined]
            frame.f_trace_opcodes = True  # type: ignore[attr-defined]
        return prime_opcode_tracing

    sys.settrace(prime_opcode_tracing)
    try:
        priming_guard.__enter__()
    finally:
        sys.settrace(None)
        priming_guard.__exit__(None, None, None)
    returns = [
        instruction.offset for instruction in dis.get_instructions(function) if instruction.opname.startswith("RETURN")
    ]
    sys.settrace(interrupt_at_opcode(function, returns[-1], interruption))
    try:
        with pytest.raises(type(interruption)) as caught:
            guard.__enter__()
    finally:
        sys.settrace(None)

    assert caught.value is interruption
    assert lease._owner.claim is profile_installer._ProfileOwnerClaim.RETAINED
    assert lease._owner.claimant is None
    assert retained == [lease]


@pytest.mark.parametrize("assignment", ["claimant", "claim"])
def test_profile_claim_publication_cancellation_rolls_back_from_shared_token(
    monkeypatch: pytest.MonkeyPatch,
    assignment: str,
    unmeasured_tracing: None,
) -> None:
    close_calls: list[object] = []

    class CloseFunction:
        def __call__(self, handle: object) -> bool:
            close_calls.append(handle)
            return True

    lease = object.__new__(profile_installer._VerifiedProfileDeleteHandle)
    lease.handle = 77
    lease.delete_marked = False
    lease._delete_outcome = ["open"]
    lease._close_poisoned = False
    lease.kernel32 = SimpleNamespace(CloseHandle=CloseFunction())
    retained: list[object] = [lease]
    monkeypatch.setattr(profile_installer, "_RETAINED_PROFILE_DELETE_LEASES", retained)
    monkeypatch.setattr(profile_installer, "_PROFILE_NATIVE_WORKER_JOIN_SECONDS", 0.01)
    guard = profile_installer._claim_profile_delete_lease(lease, object())
    function = type(guard)._acquire

    def prime_opcode_tracing(frame: object, event: str, _arg: object) -> object:
        if event == "call" and frame.f_code is function.__code__:  # type: ignore[attr-defined]
            frame.f_trace_opcodes = True  # type: ignore[attr-defined]
        return prime_opcode_tracing

    priming_guard = profile_installer._claim_profile_delete_lease(lease, object())
    sys.settrace(prime_opcode_tracing)
    try:
        with priming_guard as claim:
            assert claim.acquired
    finally:
        sys.settrace(None)
    instructions = tuple(dis.get_instructions(function))
    store_index = next(
        index
        for index, instruction in enumerate(instructions)
        if instruction.opname == "STORE_ATTR" and instruction.argval == assignment
    )
    interruption = KeyboardInterrupt(f"profile {assignment} publication")
    sys.settrace(interrupt_at_opcode(function, instructions[store_index + 1].offset, interruption))
    try:
        with pytest.raises(KeyboardInterrupt) as caught:
            with guard as claim:
                assert claim.acquired
    finally:
        sys.settrace(None)

    assert caught.value is interruption
    assert lease._owner.claim is profile_installer._ProfileOwnerClaim.RETAINED
    assert lease._owner.claimant is None
    assert profile_installer._close_profile_handle(lease) is None
    assert close_calls == [77]
    assert retained == []


def test_retained_profile_handle_drain_retries_bound_handle_and_removes_owner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Lease:
        handle: object | None = 77
        delete_marked = False
        _delete_outcome = ["open"]
        _delete_on_body_error = None
        _close_poisoned = False
        close_success = False

        def validate(self, *, expected_payload: bytes | None = None) -> None:
            return None

        def close(self) -> None:
            close_calls.append(1)
            if not self.close_success:
                raise RuntimeError("known-open CloseHandle false")
            self.handle = None

    retained: list[object] = []
    close_calls: list[int] = []
    lease = Lease()
    monkeypatch.setattr(profile_installer, "_VerifiedProfileDeleteHandle", lambda *_args, **_kwargs: lease)
    monkeypatch.setattr(profile_installer, "_RETAINED_PROFILE_DELETE_LEASES", retained)

    with pytest.raises(RuntimeError, match="close|cleanup"):
        with profile_installer._verified_profile_delete_lease(tmp_path / "drain.icc"):
            pass
    assert retained == [lease]
    lease.close_success = True
    drain = getattr(profile_installer, "_drain_retained_profile_delete_leases", None)

    assert callable(drain)
    drain()

    assert retained == []
    assert lease.handle is None


def test_pending_profile_lease_cannot_be_drained_before_constructor_activation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profile = tmp_path / "pending.icc"
    profile.write_bytes(b"profile")
    close_calls: list[object] = []
    retained: list[object] = []
    acquisition_reconciled = threading.Event()
    release_constructor = threading.Event()
    constructed: list[object] = []
    errors: list[BaseException] = []

    class NativeFunction:
        def __init__(self, callback: object) -> None:
            self.callback = callback
            self.argtypes: object = None
            self.restype: object = None

        def __call__(self, *args: object) -> object:
            return self.callback(*args)  # type: ignore[operator]

    kernel32 = SimpleNamespace(
        CreateFileW=NativeFunction(lambda *_args: 77),
        GetFileInformationByHandle=NativeFunction(lambda *_args: True),
        GetFinalPathNameByHandleW=NativeFunction(lambda *_args: 0),
        GetFileType=NativeFunction(lambda *_args: 1),
        GetFileSizeEx=NativeFunction(lambda *_args: True),
        SetFilePointerEx=NativeFunction(lambda *_args: True),
        ReadFile=NativeFunction(lambda *_args: True),
        WriteFile=NativeFunction(lambda *_args: True),
        FlushFileBuffers=NativeFunction(lambda *_args: True),
        SetFileInformationByHandle=NativeFunction(lambda *_args: True),
        CloseHandle=NativeFunction(lambda handle: close_calls.append(handle) or True),
    )
    monkeypatch.setattr(profile_installer.ctypes, "WinDLL", lambda *_args, **_kwargs: kernel32)
    monkeypatch.setattr(profile_installer, "_RETAINED_PROFILE_DELETE_LEASES", retained)
    original_await = profile_installer._await_profile_native_attempt
    constructor_thread: threading.Thread

    def pause_after_acquisition(lease: object, attempt: object) -> bool:
        reconciled = original_await(lease, attempt)  # type: ignore[arg-type]
        if (
            threading.current_thread() is constructor_thread
            and getattr(attempt, "action", None) is profile_installer._ProfileNativeAction.ACQUIRE
        ):
            acquisition_reconciled.set()
            assert release_constructor.wait(timeout=2)
        return reconciled

    monkeypatch.setattr(profile_installer, "_await_profile_native_attempt", pause_after_acquisition)

    def construct_and_close() -> None:
        try:
            lease = profile_installer._VerifiedProfileDeleteHandle(profile, create=False)
            constructed.append(lease)
            lease.close()
        except BaseException as error:
            errors.append(error)

    constructor_thread = threading.Thread(target=construct_and_close)
    constructor_thread.start()
    assert acquisition_reconciled.wait(timeout=1)
    try:
        profile_installer._drain_retained_profile_delete_leases()
        assert close_calls == []
    finally:
        release_constructor.set()
        constructor_thread.join(timeout=2)

    assert not constructor_thread.is_alive()
    assert errors == []
    assert len(constructed) == 1
    assert close_calls == [77]
    assert retained == []


@pytest.mark.parametrize("interruption", [KeyboardInterrupt("profile ingress handoff"), SystemExit(74)])
def test_cancelled_profile_ingress_publishes_attempt_and_drain_retires_ghost(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    interruption: BaseException,
    unmeasured_tracing: None,
) -> None:
    profile = tmp_path / "ingress.icc"
    retained: list[object] = []
    native_calls: list[str] = []

    class NativeFunction:
        def __init__(self, callback: object) -> None:
            self.callback = callback
            self.argtypes: object = None
            self.restype: object = None

        def __call__(self, *args: object) -> object:
            return self.callback(*args)  # type: ignore[operator]

    kernel32 = SimpleNamespace(
        CreateFileW=NativeFunction(lambda *_args: native_calls.append("create") or 77),
        GetFileInformationByHandle=NativeFunction(lambda *_args: True),
        GetFinalPathNameByHandleW=NativeFunction(lambda *_args: 0),
        GetFileType=NativeFunction(lambda *_args: 1),
        GetFileSizeEx=NativeFunction(lambda *_args: True),
        SetFilePointerEx=NativeFunction(lambda *_args: True),
        ReadFile=NativeFunction(lambda *_args: True),
        WriteFile=NativeFunction(lambda *_args: True),
        FlushFileBuffers=NativeFunction(lambda *_args: True),
        SetFileInformationByHandle=NativeFunction(lambda *_args: True),
        CloseHandle=NativeFunction(lambda *_args: True),
    )
    monkeypatch.setattr(profile_installer.ctypes, "WinDLL", lambda *_args, **_kwargs: kernel32)
    monkeypatch.setattr(profile_installer, "_RETAINED_PROFILE_DELETE_LEASES", retained)
    function = profile_installer._reserve_profile_delete_lease

    def prime_opcode_tracing(frame: object, event: str, _arg: object) -> object:
        if event == "call" and frame.f_code is function.__code__:  # type: ignore[attr-defined]
            frame.f_trace_opcodes = True  # type: ignore[attr-defined]
        return prime_opcode_tracing

    priming_lease = object.__new__(profile_installer._VerifiedProfileDeleteHandle)
    priming_lease._owner = profile_installer._ProfileOwnerState()
    sys.settrace(prime_opcode_tracing)
    try:
        function(priming_lease)
    finally:
        sys.settrace(None)
        profile_installer._release_retained_profile_delete_lease(priming_lease)
    returns = [
        instruction.offset for instruction in dis.get_instructions(function) if instruction.opname.startswith("RETURN")
    ]
    target = returns[-2]
    lease = object.__new__(profile_installer._VerifiedProfileDeleteHandle)
    sys.settrace(interrupt_at_opcode(function, target, interruption))
    try:
        with pytest.raises(type(interruption)) as caught:
            lease._initialize(profile, create=True)
    finally:
        sys.settrace(None)

    assert caught.value is interruption
    assert lease._owner.attempt is not None
    assert lease._owner.attempt.worker.ident is None
    assert lease._owner.claim is profile_installer._ProfileOwnerClaim.RETAINED
    assert lease.handle is None
    profile_installer._drain_retained_profile_delete_leases()
    assert retained == []
    assert native_calls == []


def test_late_created_profile_acquisition_auto_deletes_after_incomplete_drain(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profile = tmp_path / "late-created.icc"
    retained: list[object] = []
    create_entered = threading.Event()
    release_create = threading.Event()
    deleted = threading.Event()
    closed = threading.Event()
    native_calls: list[tuple[str, object]] = []

    class NativeFunction:
        def __init__(self, callback: object) -> None:
            self.callback = callback
            self.argtypes: object = None
            self.restype: object = None

        def __call__(self, *args: object) -> object:
            return self.callback(*args)  # type: ignore[operator]

    def create_file(*_args: object) -> int:
        create_entered.set()
        assert release_create.wait(timeout=2)
        native_calls.append(("create", 77))
        return 77

    def mark_delete(handle: object, *_args: object) -> bool:
        native_calls.append(("delete", handle))
        deleted.set()
        return True

    def close_handle(handle: object) -> bool:
        native_calls.append(("close", handle))
        closed.set()
        return True

    kernel32 = SimpleNamespace(
        CreateFileW=NativeFunction(create_file),
        GetFileInformationByHandle=NativeFunction(lambda *_args: True),
        GetFinalPathNameByHandleW=NativeFunction(lambda *_args: 0),
        GetFileType=NativeFunction(lambda *_args: 1),
        GetFileSizeEx=NativeFunction(lambda *_args: True),
        SetFilePointerEx=NativeFunction(lambda *_args: True),
        ReadFile=NativeFunction(lambda *_args: True),
        WriteFile=NativeFunction(lambda *_args: True),
        FlushFileBuffers=NativeFunction(lambda *_args: True),
        SetFileInformationByHandle=NativeFunction(mark_delete),
        CloseHandle=NativeFunction(close_handle),
    )
    monkeypatch.setattr(profile_installer.ctypes, "WinDLL", lambda *_args, **_kwargs: kernel32)
    monkeypatch.setattr(profile_installer, "_RETAINED_PROFILE_DELETE_LEASES", retained)
    monkeypatch.setattr(profile_installer, "_PROFILE_NATIVE_WORKER_JOIN_SECONDS", 0.01)
    lease = object.__new__(profile_installer._VerifiedProfileDeleteHandle)
    lease.validate = lambda **_kwargs: None  # type: ignore[method-assign]
    caller_errors: list[BaseException] = []

    def acquire() -> None:
        try:
            lease._initialize(profile, create=True)
        except BaseException as error:
            caller_errors.append(error)

    caller = threading.Thread(target=acquire)
    caller.start()
    assert create_entered.wait(timeout=1)
    caller.join(timeout=1)
    assert not caller.is_alive()
    assert len(caller_errors) == 1
    try:
        with pytest.raises(RuntimeError, match="incomplete|terminal|running"):
            profile_installer._drain_retained_profile_delete_leases()
    finally:
        release_create.set()
    assert deleted.wait(timeout=2)
    assert closed.wait(timeout=2)
    with profile_installer._PROFILE_OWNER_REGISTRY_CHANGED:
        assert profile_installer._PROFILE_OWNER_REGISTRY_CHANGED.wait_for(
            lambda: lease not in retained,
            timeout=2,
        )
    assert native_calls == [("create", 77), ("delete", 77), ("close", 77)]


def test_profile_boundary_arms_late_create_cleanup_without_a_later_drain(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profile = tmp_path / "boundary-late-created.icc"
    retained: list[object] = []
    create_entered = threading.Event()
    release_create = threading.Event()
    deleted = threading.Event()
    closed = threading.Event()
    native_calls: list[tuple[str, object]] = []

    class NativeFunction:
        def __init__(self, callback: object) -> None:
            self.callback = callback
            self.argtypes: object = None
            self.restype: object = None

        def __call__(self, *args: object) -> object:
            return self.callback(*args)  # type: ignore[operator]

    def create_file(*_args: object) -> int:
        create_entered.set()
        assert release_create.wait(timeout=2)
        native_calls.append(("create", 77))
        return 77

    def mark_delete(handle: object, *_args: object) -> bool:
        native_calls.append(("delete", handle))
        deleted.set()
        return True

    def close_handle(handle: object) -> bool:
        native_calls.append(("close", handle))
        closed.set()
        return True

    kernel32 = SimpleNamespace(
        CreateFileW=NativeFunction(create_file),
        GetFileInformationByHandle=NativeFunction(lambda *_args: True),
        GetFinalPathNameByHandleW=NativeFunction(lambda *_args: 0),
        GetFileType=NativeFunction(lambda *_args: 1),
        GetFileSizeEx=NativeFunction(lambda *_args: True),
        SetFilePointerEx=NativeFunction(lambda *_args: True),
        ReadFile=NativeFunction(lambda *_args: True),
        WriteFile=NativeFunction(lambda *_args: True),
        FlushFileBuffers=NativeFunction(lambda *_args: True),
        SetFileInformationByHandle=NativeFunction(mark_delete),
        CloseHandle=NativeFunction(close_handle),
    )
    monkeypatch.setattr(profile_installer.ctypes, "WinDLL", lambda *_args, **_kwargs: kernel32)
    monkeypatch.setattr(profile_installer, "_RETAINED_PROFILE_DELETE_LEASES", retained)
    monkeypatch.setattr(profile_installer, "_PROFILE_NATIVE_WORKER_JOIN_SECONDS", 0.01)
    monkeypatch.setattr(
        profile_installer._VerifiedProfileDeleteHandle,
        "validate",
        lambda *_args, **_kwargs: None,
    )
    caller_errors: list[BaseException] = []

    def enter_boundary() -> None:
        try:
            with profile_installer._verified_profile_delete_lease(
                profile,
                create_payload=b"profile",
            ):
                raise AssertionError("late acquisition must not enter the profile body")
        except BaseException as error:
            caller_errors.append(error)

    caller = threading.Thread(target=enter_boundary)
    caller.start()
    assert create_entered.wait(timeout=1)
    caller.join(timeout=1)
    assert not caller.is_alive()
    assert len(caller_errors) == 1
    try:
        with profile_installer._PROFILE_OWNER_REGISTRY_CHANGED:
            assert len(retained) == 1
            lease = retained[0]
            assert lease._owner.attempt is not None
            assert lease._owner.terminal_cleanup_token is lease._owner.attempt.token
    finally:
        release_create.set()
    assert deleted.wait(timeout=2)
    assert closed.wait(timeout=2)
    with profile_installer._PROFILE_OWNER_REGISTRY_CHANGED:
        assert profile_installer._PROFILE_OWNER_REGISTRY_CHANGED.wait_for(lambda: retained == [], timeout=2)
    assert native_calls == [("create", 77), ("delete", 77), ("close", 77)]


def _created_profile_cleanup_kernel(native_calls: list[tuple[str, object]]) -> object:
    class NativeFunction:
        def __init__(self, callback: object) -> None:
            self.callback = callback
            self.argtypes: object = None
            self.restype: object = None

        def __call__(self, *args: object) -> object:
            return self.callback(*args)  # type: ignore[operator]

    def write_file(
        _handle: object,
        _buffer: object,
        size: int,
        written: object,
        _overlapped: object,
    ) -> bool:
        written._obj.value = size  # type: ignore[attr-defined]
        return True

    return SimpleNamespace(
        CreateFileW=NativeFunction(lambda *_args: native_calls.append(("create", 77)) or 77),
        GetFileInformationByHandle=NativeFunction(lambda *_args: True),
        GetFinalPathNameByHandleW=NativeFunction(lambda *_args: 0),
        GetFileType=NativeFunction(lambda *_args: 1),
        GetFileSizeEx=NativeFunction(lambda *_args: True),
        SetFilePointerEx=NativeFunction(lambda *_args: True),
        ReadFile=NativeFunction(lambda *_args: True),
        WriteFile=NativeFunction(write_file),
        FlushFileBuffers=NativeFunction(lambda *_args: True),
        SetFileInformationByHandle=NativeFunction(
            lambda handle, *_args: native_calls.append(("delete", handle)) or True
        ),
        CloseHandle=NativeFunction(lambda handle: native_calls.append(("close", handle)) or True),
    )


@pytest.mark.parametrize("interruption", [KeyboardInterrupt("claimed profile cleanup entry"), SystemExit(79)])
def test_created_profile_boundary_reclaims_cleanup_after_claimed_helper_control_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    interruption: BaseException,
) -> None:
    profile = tmp_path / "claimed-entry.icc"
    native_calls: list[tuple[str, object]] = []
    retained: list[object] = []
    cleanup_entries: list[tuple[object, object | None]] = []
    body_error = RuntimeError("profile body failure")
    kernel32 = _created_profile_cleanup_kernel(native_calls)
    original_finish = profile_installer._finish_claimed_profile_lease_cleanup
    monkeypatch.setattr(profile_installer.ctypes, "WinDLL", lambda *_args, **_kwargs: kernel32)
    monkeypatch.setattr(profile_installer, "_RETAINED_PROFILE_DELETE_LEASES", retained)
    monkeypatch.setattr(
        profile_installer._VerifiedProfileDeleteHandle,
        "validate",
        lambda *_args, **_kwargs: None,
    )

    def interrupt_first_cleanup(
        lease: object,
        *,
        delete_created: bool,
        cleanup_errors: list[BaseException],
        claim_token: object,
    ) -> None:
        cleanup_entries.append((lease, lease._owner.claimant))  # type: ignore[attr-defined]
        if len(cleanup_entries) == 1:
            raise interruption
        original_finish(
            lease,  # type: ignore[arg-type]
            delete_created=delete_created,
            cleanup_errors=cleanup_errors,
            claim_token=claim_token,
        )

    monkeypatch.setattr(
        profile_installer,
        "_finish_claimed_profile_lease_cleanup",
        interrupt_first_cleanup,
    )

    with pytest.raises(type(interruption)) as caught:
        with profile_installer._verified_profile_delete_lease(
            profile,
            create_payload=b"profile",
        ):
            raise body_error

    assert caught.value is interruption
    assert len(cleanup_entries) == 2
    assert cleanup_entries[0][0] is cleanup_entries[1][0]
    assert cleanup_entries[0][1] is not cleanup_entries[1][1]
    assert native_calls == [("create", 77), ("delete", 77), ("close", 77)]
    assert retained == []


@pytest.mark.parametrize("interruption", [KeyboardInterrupt("profile delete publication"), SystemExit(80)])
def test_created_profile_boundary_starts_exact_delete_attempt_after_publication_control_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    interruption: BaseException,
) -> None:
    profile = tmp_path / "delete-publication.icc"
    native_calls: list[tuple[str, object]] = []
    retained: list[object] = []
    published_attempts: list[object] = []
    body_error = RuntimeError("profile body failure")
    kernel32 = _created_profile_cleanup_kernel(native_calls)
    original_publish = profile_installer._new_profile_native_attempt_locked
    monkeypatch.setattr(profile_installer.ctypes, "WinDLL", lambda *_args, **_kwargs: kernel32)
    monkeypatch.setattr(profile_installer, "_RETAINED_PROFILE_DELETE_LEASES", retained)
    monkeypatch.setattr(
        profile_installer._VerifiedProfileDeleteHandle,
        "validate",
        lambda *_args, **_kwargs: None,
    )

    def publish_then_interrupt(lease: object, action: object, **kwargs: object) -> object:
        attempt = original_publish(lease, action, **kwargs)  # type: ignore[arg-type]
        if action is profile_installer._ProfileNativeAction.DELETE and not published_attempts:
            published_attempts.append(attempt)
            raise interruption
        return attempt

    monkeypatch.setattr(profile_installer, "_new_profile_native_attempt_locked", publish_then_interrupt)

    with pytest.raises(type(interruption)) as caught:
        with profile_installer._verified_profile_delete_lease(
            profile,
            create_payload=b"profile",
        ):
            raise body_error

    assert caught.value is interruption
    assert len(published_attempts) == 1
    published = published_attempts[0]
    assert published.started.is_set()  # type: ignore[attr-defined]
    assert published.done.is_set()  # type: ignore[attr-defined]
    assert native_calls == [("create", 77), ("delete", 77), ("close", 77)]
    assert retained == []


@pytest.mark.parametrize(
    ("initial_interruption", "recovery_interruption"),
    [
        (KeyboardInterrupt("initial profile cleanup"), SystemExit(83)),
        (SystemExit(84), KeyboardInterrupt("recovery profile cleanup")),
    ],
)
def test_created_profile_boundary_double_cleanup_control_errors_demote_only_stale_lease_for_drain(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    initial_interruption: BaseException,
    recovery_interruption: BaseException,
) -> None:
    profile = tmp_path / "double-cleanup.icc"
    native_calls: list[tuple[str, object]] = []
    retained: list[object] = []
    cleanup_entries: list[tuple[object, object | None]] = []
    body_error = RuntimeError("profile body failure")
    kernel32 = _created_profile_cleanup_kernel(native_calls)
    original_finish = profile_installer._finish_claimed_profile_lease_cleanup
    newer_lease = object.__new__(profile_installer._VerifiedProfileDeleteHandle)
    newer_lease._owner = profile_installer._ProfileOwnerState(
        handle=88,
        state=profile_installer._ProfileNativeState.OPEN,
        claim=profile_installer._ProfileOwnerClaim.ACTIVE,
    )
    blocked_lease = object.__new__(profile_installer._VerifiedProfileDeleteHandle)
    blocked_lease._owner = profile_installer._ProfileOwnerState(
        handle=99,
        state=profile_installer._ProfileNativeState.OPEN,
        claim=profile_installer._ProfileOwnerClaim.ACTIVE,
    )
    monkeypatch.setattr(profile_installer.ctypes, "WinDLL", lambda *_args, **_kwargs: kernel32)
    monkeypatch.setattr(profile_installer, "_RETAINED_PROFILE_DELETE_LEASES", retained)
    monkeypatch.setattr(profile_installer, "_PROFILE_OWNER_REGISTRY_CAP", 2)
    monkeypatch.setattr(
        profile_installer._VerifiedProfileDeleteHandle,
        "validate",
        lambda *_args, **_kwargs: None,
    )

    def interrupt_both_cleanup_claims(
        lease: object,
        *,
        delete_created: bool,
        cleanup_errors: list[BaseException],
        claim_token: object,
    ) -> None:
        cleanup_entries.append((lease, lease._owner.claimant))  # type: ignore[attr-defined]
        if len(cleanup_entries) == 1:
            raise initial_interruption
        if len(cleanup_entries) == 2:
            retained.append(newer_lease)
            raise recovery_interruption
        original_finish(
            lease,  # type: ignore[arg-type]
            delete_created=delete_created,
            cleanup_errors=cleanup_errors,
            claim_token=claim_token,
        )

    monkeypatch.setattr(
        profile_installer,
        "_finish_claimed_profile_lease_cleanup",
        interrupt_both_cleanup_claims,
    )

    with pytest.raises(type(initial_interruption)) as caught:
        with profile_installer._verified_profile_delete_lease(
            profile,
            create_payload=b"profile",
        ):
            raise body_error

    assert caught.value is initial_interruption
    assert len(cleanup_entries) == 2
    stale_lease = cleanup_entries[0][0]
    assert cleanup_entries[1][0] is stale_lease
    assert cleanup_entries[0][1] is not cleanup_entries[1][1]
    assert stale_lease._owner.claim is profile_installer._ProfileOwnerClaim.RETAINED  # type: ignore[attr-defined]
    assert stale_lease._owner.state is profile_installer._ProfileNativeState.OPEN  # type: ignore[attr-defined]
    assert stale_lease._owner.claimant is None  # type: ignore[attr-defined]
    assert stale_lease._owner.terminal_cleanup_token is None  # type: ignore[attr-defined]
    assert newer_lease._owner.claim is profile_installer._ProfileOwnerClaim.ACTIVE
    assert retained == [stale_lease, newer_lease]
    with pytest.raises(RuntimeError, match="capacity"):
        profile_installer._retain_profile_delete_lease(blocked_lease)

    profile_installer._drain_retained_profile_delete_leases()
    profile_installer._drain_retained_profile_delete_leases()

    assert native_calls == [("create", 77), ("delete", 77), ("close", 77)]
    assert newer_lease._owner.claim is profile_installer._ProfileOwnerClaim.ACTIVE
    assert newer_lease.handle == 88
    assert retained == [newer_lease]
    profile_installer._retain_profile_delete_lease(blocked_lease)
    profile_installer._release_retained_profile_delete_lease(blocked_lease)
    assert retained == [newer_lease]


def test_retained_profile_handle_drain_does_not_close_an_active_lease(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Lease:
        handle: object | None = 77
        delete_marked = False
        _lease_state = "active"

        def close(self) -> None:
            close_calls.append(1)
            self.handle = None

    close_calls: list[int] = []
    lease = Lease()
    retained: list[object] = [lease]
    monkeypatch.setattr(profile_installer, "_RETAINED_PROFILE_DELETE_LEASES", retained)

    profile_installer._drain_retained_profile_delete_leases()

    assert close_calls == []
    assert retained == [lease]
    lease._lease_state = "retained"
    profile_installer._drain_retained_profile_delete_leases()
    assert close_calls == [1]
    assert retained == []


@pytest.mark.parametrize("interruption", [KeyboardInterrupt("drain close cancelled"), SystemExit(69)])
def test_retained_profile_handle_drain_preserves_control_after_successful_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    interruption: BaseException,
) -> None:
    class Lease:
        handle: object | None = 77
        delete_marked = False
        _close_poisoned = False
        phase = "retain"

        def validate(self, *, expected_payload: bytes | None = None) -> None:
            return None

        def close(self) -> None:
            close_calls.append(1)
            if self.phase == "retain":
                raise RuntimeError("known-open CloseHandle false")
            if len(close_calls) == 3:
                raise interruption
            self.handle = None

    retained: list[object] = []
    close_calls: list[int] = []
    lease = Lease()
    monkeypatch.setattr(profile_installer, "_VerifiedProfileDeleteHandle", lambda *_args, **_kwargs: lease)
    monkeypatch.setattr(profile_installer, "_RETAINED_PROFILE_DELETE_LEASES", retained)

    with pytest.raises(RuntimeError, match="close|cleanup"):
        with profile_installer._verified_profile_delete_lease(tmp_path / "drain-control.icc"):
            pass
    lease.phase = "drain"

    with pytest.raises(type(interruption)) as caught:
        profile_installer._drain_retained_profile_delete_leases()

    assert caught.value is interruption
    assert close_calls == [1, 1, 1, 1]
    assert retained == []
    assert lease.handle is None


def test_successful_created_profile_retention_clears_rollback_before_later_drain(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Lease:
        handle: object | None = 77
        delete_marked = False
        _delete_outcome = ["open"]
        _close_poisoned = False
        _cleanup_delete_requested = True
        close_success = False

        def write_bytes(self, _payload: bytes) -> None:
            return None

        def validate(self, *, expected_payload: bytes | None = None) -> None:
            return None

        def mark_delete(self, *, expected_payload: bytes | None = None) -> None:
            delete_calls.append(1)
            raise AssertionError("successful profile must not be rolled back by a later drain")

        def close(self) -> None:
            close_calls.append(1)
            if not self.close_success:
                raise RuntimeError("known-open CloseHandle false")
            self.handle = None

    retained: list[object] = []
    close_calls: list[int] = []
    delete_calls: list[int] = []
    lease = Lease()
    monkeypatch.setattr(profile_installer, "_VerifiedProfileDeleteHandle", lambda *_args, **_kwargs: lease)
    monkeypatch.setattr(profile_installer, "_RETAINED_PROFILE_DELETE_LEASES", retained)

    with pytest.raises(RuntimeError, match="close|cleanup"):
        with profile_installer._verified_profile_delete_lease(
            tmp_path / "successful-created.icc",
            create_payload=b"profile",
        ):
            pass

    assert lease._cleanup_delete_requested is False
    lease.close_success = True
    profile_installer._drain_retained_profile_delete_leases()

    assert delete_calls == []
    assert retained == []
    assert lease.handle is None


def test_is_profile_installed_uses_os_enumeration_not_color_file_existence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "present-only-on-disk.icc").write_bytes(b"profile")
    monkeypatch.setattr(profile_installer, "get_profile_directory", lambda: tmp_path)
    native = install_enumerating_mscms(monkeypatch, ("registered.icc",))

    assert profile_installer.is_profile_installed("registered.icc") is True
    assert profile_installer.is_profile_installed("present-only-on-disk.icc") is False
    assert all(record[1:] == (0, None) for record in native.records)


def test_is_profile_associated_uses_exact_device_enumeration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    native = install_enumerating_mscms(monkeypatch, ("target.icc", "other.icc"))

    assert (
        profile_installer.is_profile_associated_with_display(
            "target.icc",
            r"\\.\DISPLAY1",
        )
        is True
    )
    assert all(
        record
        == (
            profile_installer.WCS_PROFILE_MANAGEMENT_SCOPE_SYSTEM_WIDE,
            profile_installer.ET_DEVICENAME,
            r"\\.\DISPLAY1",
        )
        for record in native.records
    )


@pytest.mark.parametrize("failure", ["size", "enumeration"])
def test_profile_enumeration_errors_fail_closed_without_becoming_false(
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    install_enumerating_mscms(
        monkeypatch,
        ("target.icc",),
        fail_size=failure == "size",
        fail_enumeration=failure == "enumeration",
    )

    with pytest.raises(RuntimeError, match="enumerat"):
        profile_installer.is_profile_installed("target.icc")


def test_profile_enumeration_rejects_inconsistent_native_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_enumerating_mscms(
        monkeypatch,
        ("target.icc",),
        reported_count=2,
    )

    with pytest.raises(RuntimeError, match="count|evidence"):
        profile_installer.is_profile_installed("target.icc")


@pytest.mark.parametrize("interruption", [KeyboardInterrupt("enumeration cancelled"), SystemExit(63)])
def test_authoritative_reconciliation_publishes_uncertainty_before_enumeration(
    monkeypatch: pytest.MonkeyPatch,
    interruption: BaseException,
) -> None:
    registration_state = [profile_installer._PROFILE_REGISTRATION_ABSENT]

    def interrupt_enumeration(_device_name: str | None) -> tuple[str, ...]:
        assert registration_state == [profile_installer._PROFILE_REGISTRATION_UNCERTAIN]
        raise interruption

    monkeypatch.setattr(profile_installer, "_enumerate_system_profiles", interrupt_enumeration)

    with pytest.raises(type(interruption)) as caught:
        profile_installer._publish_authoritative_registration_state("target.icc", registration_state)

    assert caught.value is interruption
    assert registration_state == [profile_installer._PROFILE_REGISTRATION_UNCERTAIN]
