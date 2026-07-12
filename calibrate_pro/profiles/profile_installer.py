"""
ICC Profile System Installation

Handles ICC profile installation and management on Windows:
- System profile installation via mscms.dll
- Default profile assignment per display
- Profile backup and restore
- Display enumeration and association
- Color management settings

Uses the Windows Color Management API (ICM/WCS).
"""

import ctypes
import json
import os
import re
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from ctypes import wintypes
from dataclasses import dataclass
from datetime import datetime
from enum import Enum, IntEnum
from pathlib import Path, PureWindowsPath
from typing import Any, TypeGuard

try:
    import winreg
except ImportError:  # pragma: no cover - exercised by the subprocess portability gate
    winreg = None  # type: ignore[assignment]

WCS_PROFILE_MANAGEMENT_SCOPE_SYSTEM_WIDE = 0
CPT_ICC = 0
CPST_NONE = 4
ENUM_TYPE_VERSION = 0x0300
ET_DEVICENAME = 0x00000001
_MAX_PROFILE_ENUMERATION_BYTES = 64 * 1024 * 1024
_MAX_PROFILE_NAME_BYTES = 64 * 1024
_TRANSACTIONAL_PROFILE_CACHE_RE = re.compile(r"calibrate-pro-[0-9a-f]{64}\.(?:icc|icm)\Z")
_PROFILE_REGISTRATION_ABSENT = "absent"
_PROFILE_REGISTRATION_UNCERTAIN = "uncertain"
_PROFILE_REGISTRATION_PRESENT = "present"
_PROFILE_CLEANUP_MAX_ATTEMPTS = 2
_PROFILE_RETAINED_DRAIN_CAP = 64
_PROFILE_OWNER_REGISTRY_CAP = 64
_PROFILE_NATIVE_WORKER_JOIN_SECONDS = 2.0
_INVALID_WIN32_PROFILE_NAME_CHARS = frozenset('<>:"/\\|?*')
_RESERVED_WIN32_DEVICE_NAMES = frozenset(
    {"CON", "PRN", "AUX", "NUL", *(f"COM{index}" for index in range(1, 10)), *(f"LPT{index}" for index in range(1, 10))}
)


class _ENUMTYPEW(ctypes.Structure):
    """Exact Windows ``ENUMTYPEW`` layout from the installed SDK's Icm.h."""

    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("dwVersion", wintypes.DWORD),
        ("dwFields", wintypes.DWORD),
        ("pDeviceName", wintypes.LPCWSTR),
        ("dwMediaType", wintypes.DWORD),
        ("dwDitheringMode", wintypes.DWORD),
        ("dwResolution", wintypes.DWORD * 2),
        ("dwCMMType", wintypes.DWORD),
        ("dwClass", wintypes.DWORD),
        ("dwDataColorSpace", wintypes.DWORD),
        ("dwConnectionSpace", wintypes.DWORD),
        ("dwSignature", wintypes.DWORD),
        ("dwPlatform", wintypes.DWORD),
        ("dwProfileFlags", wintypes.DWORD),
        ("dwManufacturer", wintypes.DWORD),
        ("dwModel", wintypes.DWORD),
        ("dwAttributes", wintypes.DWORD * 2),
        ("dwRenderingIntent", wintypes.DWORD),
        ("dwCreator", wintypes.DWORD),
        ("dwDeviceClass", wintypes.DWORD),
    ]


class _PROFILE_HANDLE_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("dwFileAttributes", wintypes.DWORD),
        ("ftCreationTime", wintypes.FILETIME),
        ("ftLastAccessTime", wintypes.FILETIME),
        ("ftLastWriteTime", wintypes.FILETIME),
        ("dwVolumeSerialNumber", wintypes.DWORD),
        ("nFileSizeHigh", wintypes.DWORD),
        ("nFileSizeLow", wintypes.DWORD),
        ("nNumberOfLinks", wintypes.DWORD),
        ("nFileIndexHigh", wintypes.DWORD),
        ("nFileIndexLow", wintypes.DWORD),
    ]


class _FILE_DISPOSITION_INFORMATION(ctypes.Structure):
    _fields_ = [("DeleteFile", wintypes.BOOL)]


def _configure_wcs_default_profile_signatures(api: Any) -> None:
    """Bind the exact wide-string contracts used for default ICC profiles."""
    install = getattr(api, "InstallColorProfileW", None)
    if install is not None:
        install.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
        install.restype = wintypes.BOOL
    uninstall = getattr(api, "UninstallColorProfileW", None)
    if uninstall is not None:
        uninstall.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.BOOL]
        uninstall.restype = wintypes.BOOL
    associate = getattr(api, "WcsAssociateColorProfileWithDevice", None)
    if associate is not None:
        associate.argtypes = [ctypes.c_int, wintypes.LPCWSTR, wintypes.LPCWSTR]
        associate.restype = wintypes.BOOL
    disassociate = getattr(api, "WcsDisassociateColorProfileFromDevice", None)
    if disassociate is not None:
        disassociate.argtypes = [ctypes.c_int, wintypes.LPCWSTR, wintypes.LPCWSTR]
        disassociate.restype = wintypes.BOOL
    api.WcsSetDefaultColorProfile.argtypes = [
        ctypes.c_int,
        wintypes.LPCWSTR,
        ctypes.c_int,
        ctypes.c_int,
        wintypes.DWORD,
        wintypes.LPCWSTR,
    ]
    api.WcsSetDefaultColorProfile.restype = wintypes.BOOL
    api.WcsGetDefaultColorProfile.argtypes = [
        ctypes.c_int,
        wintypes.LPCWSTR,
        ctypes.c_int,
        ctypes.c_int,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPWSTR,
    ]
    api.WcsGetDefaultColorProfile.restype = wintypes.BOOL
    get_default_size = getattr(api, "WcsGetDefaultColorProfileSize", None)
    if get_default_size is not None:
        get_default_size.argtypes = [
            ctypes.c_int,
            wintypes.LPCWSTR,
            ctypes.c_int,
            ctypes.c_int,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
        ]
        get_default_size.restype = wintypes.BOOL
    enum_size = getattr(api, "WcsEnumColorProfilesSize", None)
    enum_profiles = getattr(api, "WcsEnumColorProfiles", None)
    if enum_size is not None and enum_profiles is not None:
        enum_size.argtypes = [
            ctypes.c_int,
            ctypes.POINTER(_ENUMTYPEW),
            ctypes.POINTER(wintypes.DWORD),
        ]
        enum_size.restype = wintypes.BOOL
        enum_profiles.argtypes = [
            ctypes.c_int,
            ctypes.POINTER(_ENUMTYPEW),
            ctypes.POINTER(wintypes.BYTE),
            wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
        ]
        enum_profiles.restype = wintypes.BOOL


# =============================================================================
# Windows Color Management API Definitions
# =============================================================================

# MSCMS.dll functions
try:
    mscms = ctypes.windll.mscms
    _configure_wcs_default_profile_signatures(mscms)
    MSCMS_AVAILABLE = True
except Exception:
    mscms = None  # type: ignore[assignment]  # numpy/dynamic typing
    MSCMS_AVAILABLE = False

# GDI32 for display enumeration
try:
    gdi32 = ctypes.windll.gdi32
    user32 = ctypes.windll.user32
    GDI_AVAILABLE = True

    # DISPLAY_DEVICE structure for EnumDisplayDevicesW
    class _DISPLAY_DEVICE(ctypes.Structure):
        _fields_ = [
            ("cb", wintypes.DWORD),
            ("DeviceName", wintypes.WCHAR * 32),
            ("DeviceString", wintypes.WCHAR * 128),
            ("StateFlags", wintypes.DWORD),
            ("DeviceID", wintypes.WCHAR * 128),
            ("DeviceKey", wintypes.WCHAR * 128),
        ]

    # Set up function signatures
    user32.EnumDisplayDevicesW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        # The process has several legacy modules with layout-compatible
        # DISPLAY_DEVICE declarations. A nominal pointer type contaminates the
        # shared ctypes function object and rejects every other declaration.
        ctypes.c_void_p,
        wintypes.DWORD,
    ]
    user32.EnumDisplayDevicesW.restype = wintypes.BOOL

except Exception:
    gdi32 = None  # type: ignore[assignment]  # numpy/dynamic typing
    user32 = None  # type: ignore[assignment]  # numpy/dynamic typing
    GDI_AVAILABLE = False
    _DISPLAY_DEVICE = None  # type: ignore[assignment, misc]  # numpy/dynamic typing


# Profile scope
class ProfileScope(IntEnum):
    """Profile installation scope."""

    SYSTEM = 0  # All users (requires admin)
    USER = 1  # Current user only


# Profile association type
class ProfileAssociation(IntEnum):
    """Profile association type."""

    DEFAULT = 0  # Default profile for device
    PERCEPTUAL = 1
    RELATIVE = 2
    SATURATION = 3
    ABSOLUTE = 4


# Color profile type
class ColorProfileType(IntEnum):
    """Color profile type."""

    INPUT = 1
    DISPLAY = 2
    OUTPUT = 3
    LINK = 4
    SPACE = 5
    ABSTRACT = 6
    NAMED = 7


# =============================================================================
# Display Information
# =============================================================================


@dataclass
class DisplayDevice:
    """Information about a display device."""

    device_name: str  # e.g., "\\\\.\\DISPLAY1"
    device_string: str  # Friendly name
    device_id: str  # Hardware ID
    device_key: str  # Registry key
    is_primary: bool
    is_active: bool
    is_attached: bool
    monitor_name: str = ""
    monitor_id: str = ""

    @property
    def display_number(self) -> int:
        """Extract display number from device name."""
        try:
            return int(self.device_name.replace("\\\\.\\DISPLAY", ""))
        except ValueError:
            return 0


@dataclass
class MonitorInfo:
    """Extended monitor information."""

    device: DisplayDevice
    edid_manufacturer: str = ""
    edid_model: str = ""
    edid_serial: str = ""
    resolution: tuple[int, int] = (0, 0)
    refresh_rate: float = 0.0
    hdr_supported: bool = False
    current_profile: str | None = None


def enumerate_displays() -> list[DisplayDevice]:
    """
    Enumerate all display devices.

    Returns:
        List of DisplayDevice objects
    """
    if not GDI_AVAILABLE or _DISPLAY_DEVICE is None:
        return []

    displays = []

    device = _DISPLAY_DEVICE()
    device.cb = ctypes.sizeof(device)

    i = 0
    while user32.EnumDisplayDevicesW(None, i, ctypes.byref(device), 0):
        if device.StateFlags & 0x00000001:  # DISPLAY_DEVICE_ACTIVE
            displays.append(
                DisplayDevice(
                    device_name=device.DeviceName,
                    device_string=device.DeviceString,
                    device_id=device.DeviceID,
                    device_key=device.DeviceKey,
                    is_primary=bool(device.StateFlags & 0x00000004),
                    is_active=bool(device.StateFlags & 0x00000001),
                    is_attached=bool(device.StateFlags & 0x00000002),
                )
            )

            # Get monitor info
            monitor = _DISPLAY_DEVICE()
            monitor.cb = ctypes.sizeof(monitor)

            if user32.EnumDisplayDevicesW(device.DeviceName, 0, ctypes.byref(monitor), 0):
                displays[-1].monitor_name = monitor.DeviceString
                displays[-1].monitor_id = monitor.DeviceID

        i += 1

    return displays


def get_monitor_info(device: DisplayDevice) -> MonitorInfo:
    """
    Get extended monitor information.

    Args:
        device: DisplayDevice object

    Returns:
        MonitorInfo with extended details
    """
    info = MonitorInfo(device=device)

    # Get current mode
    class DEVMODEW(ctypes.Structure):
        _fields_ = [
            ("dmDeviceName", wintypes.WCHAR * 32),
            ("dmSpecVersion", wintypes.WORD),
            ("dmDriverVersion", wintypes.WORD),
            ("dmSize", wintypes.WORD),
            ("dmDriverExtra", wintypes.WORD),
            ("dmFields", wintypes.DWORD),
            ("dmPositionX", wintypes.LONG),
            ("dmPositionY", wintypes.LONG),
            ("dmDisplayOrientation", wintypes.DWORD),
            ("dmDisplayFixedOutput", wintypes.DWORD),
            ("dmColor", wintypes.SHORT),
            ("dmDuplex", wintypes.SHORT),
            ("dmYResolution", wintypes.SHORT),
            ("dmTTOption", wintypes.SHORT),
            ("dmCollate", wintypes.SHORT),
            ("dmFormName", wintypes.WCHAR * 32),
            ("dmLogPixels", wintypes.WORD),
            ("dmBitsPerPel", wintypes.DWORD),
            ("dmPelsWidth", wintypes.DWORD),
            ("dmPelsHeight", wintypes.DWORD),
            ("dmDisplayFlags", wintypes.DWORD),
            ("dmDisplayFrequency", wintypes.DWORD),
        ]

    if GDI_AVAILABLE:
        devmode = DEVMODEW()
        devmode.dmSize = ctypes.sizeof(devmode)

        if user32.EnumDisplaySettingsW(device.device_name, -1, ctypes.byref(devmode)):  # ENUM_CURRENT_SETTINGS
            info.resolution = (devmode.dmPelsWidth, devmode.dmPelsHeight)
            info.refresh_rate = float(devmode.dmDisplayFrequency)

    # Get current profile
    info.current_profile = get_display_profile(device.device_name)

    return info


# =============================================================================
# Profile Installation
# =============================================================================


def get_profile_directory() -> Path:
    """Get the system color profile directory."""
    import os

    # Get Windows system directory
    system_root = os.environ.get("SystemRoot", r"C:\Windows")
    color_dir = Path(system_root) / "System32" / "spool" / "drivers" / "color"

    if color_dir.exists():
        return color_dir

    # Fallback locations
    fallbacks = [
        Path(r"C:\Windows\System32\spool\drivers\color"),
        Path(r"C:\WINDOWS\system32\spool\drivers\color"),
    ]

    for fallback in fallbacks:
        if fallback.exists():
            return fallback

    # Return default even if not exists
    return Path(r"C:\Windows\System32\spool\drivers\color")


def _invoke_install_color_profile(profile_path: Path, registration_state: list[str]) -> bool:
    """Publish InstallColorProfileW's result on the same trace line as native entry."""
    return (registration_state.__setitem__(0, _PROFILE_REGISTRATION_UNCERTAIN), registration_state.__setitem__(0, _PROFILE_REGISTRATION_PRESENT if bool(mscms.InstallColorProfileW(None, str(profile_path))) else _PROFILE_REGISTRATION_ABSENT), registration_state[0] == _PROFILE_REGISTRATION_PRESENT)[2]  # type: ignore[func-returns-value]  # fmt: skip


def _invoke_uninstall_color_profile(profile_path: Path, registration_state: list[str]) -> bool:
    """Publish UninstallColorProfileW's result on the same trace line as native entry."""
    return (registration_state.__setitem__(0, _PROFILE_REGISTRATION_UNCERTAIN), registration_state.__setitem__(0, _PROFILE_REGISTRATION_ABSENT if bool(mscms.UninstallColorProfileW(None, str(profile_path), False)) else _PROFILE_REGISTRATION_PRESENT), registration_state[0] == _PROFILE_REGISTRATION_ABSENT)[2]  # type: ignore[func-returns-value]  # fmt: skip


def _authoritative_profile_enumeration_available() -> bool:
    return bool(
        MSCMS_AVAILABLE
        and mscms is not None
        and callable(getattr(mscms, "WcsEnumColorProfilesSize", None))
        and callable(getattr(mscms, "WcsEnumColorProfiles", None))
    )


def _publish_authoritative_registration_state(profile_name: str, registration_state: list[str]) -> None:
    (registration_state.__setitem__(0, _PROFILE_REGISTRATION_UNCERTAIN), _profiles := _enumerate_system_profiles(None), registration_state.__setitem__(0, _PROFILE_REGISTRATION_PRESENT if any(name.casefold() == profile_name.casefold() for name in _profiles) else _PROFILE_REGISTRATION_ABSENT))  # type: ignore[func-returns-value]  # fmt: skip


def _reconcile_profile_registration_if_available(profile_name: str, registration_state: list[str]) -> bool:
    if not _authoritative_profile_enumeration_available():
        return False
    _publish_authoritative_registration_state(profile_name, registration_state)
    return True


def _reconcile_profile_registration_after_native_error(
    profile_name: str,
    registration_state: list[str],
    native_error: BaseException,
) -> bool:
    try:
        return _reconcile_profile_registration_if_available(profile_name, registration_state)
    except BaseException as reconciliation_error:
        if isinstance(native_error, Exception) and not isinstance(reconciliation_error, Exception):
            _add_exception_note(
                reconciliation_error,
                f"profile native mutation also failed: {_exception_detail(native_error)}",
            )
            raise reconciliation_error from native_error
        _add_exception_note(
            native_error,
            f"authoritative profile reconciliation also failed: {_exception_detail(reconciliation_error)}",
        )
        return False


def install_profile(profile_path: str | Path, scope: ProfileScope = ProfileScope.SYSTEM) -> tuple[bool, str]:
    """
    Install ICC profile to system.

    Args:
        profile_path: Path to ICC profile
        scope: Installation scope (SYSTEM or USER)

    Returns:
        (success, message)
    """
    profile_path = Path(profile_path)

    if not profile_path.exists():
        return False, f"Profile not found: {profile_path}"
    profile_name = profile_path.name
    if not _is_exact_profile_basename(profile_name):
        return False, "Profile filename must be an exact Win32 basename"
    if _is_transactional_profile_cache_name(profile_name):
        return False, "The transactional product profile cache namespace is reserved"

    # Validate profile
    try:
        data = profile_path.read_bytes()
        if len(data) < 128 or data[36:40] != b"acsp":
            return False, "Invalid ICC profile"
    except Exception as e:
        return False, f"Cannot read profile: {e}"

    if not MSCMS_AVAILABLE or mscms is None:
        return False, "Windows color management profile registration API is unavailable"

    # Create and hold one delete-capable native handle through registration so
    # failure cleanup can affect only the exact object created here.
    color_dir = get_profile_directory()
    dest_path = color_dir / profile_name
    if _path_resolves_to_transactional_profile_cache(dest_path):
        return False, "The install destination resolves to the transactional product profile cache"

    registration_state = [_PROFILE_REGISTRATION_ABSENT]
    try:
        with _verified_profile_delete_lease(
            dest_path,
            create_payload=data,
            delete_on_body_error=lambda: registration_state[0] == _PROFILE_REGISTRATION_ABSENT,
        ) as lease:
            try:
                _invoke_install_color_profile(dest_path, registration_state)
            except BaseException as native_error:
                reconciled = _reconcile_profile_registration_after_native_error(
                    profile_name,
                    registration_state,
                    native_error,
                )
                if not isinstance(native_error, Exception) or not reconciled:
                    raise
            _reconcile_profile_registration_if_available(profile_name, registration_state)
            if registration_state[0] == _PROFILE_REGISTRATION_ABSENT:
                lease.mark_delete(expected_payload=data)
            elif registration_state[0] == _PROFILE_REGISTRATION_PRESENT:
                lease.validate(expected_payload=data)
            else:
                raise RuntimeError("profile registration state remained uncertain after native mutation")
    except FileExistsError:
        return False, "Install destination already exists; legacy profile installation never overwrites"
    except PermissionError:
        return False, "Permission denied. Run as administrator for system-wide installation."
    except Exception as e:
        return False, f"Color management error: {e}"
    if registration_state[0] != _PROFILE_REGISTRATION_PRESENT:
        return False, "Windows color management did not retain the profile as registered"

    return True, f"Profile installed: {dest_path}"


def register_profile(profile_path: str | Path) -> tuple[bool, str]:
    """Register an already materialized profile without copying or overwriting it."""
    profile_path = Path(profile_path)
    if not profile_path.is_file():
        return False, f"Profile not found: {profile_path}"
    if not MSCMS_AVAILABLE:
        return False, "Color management API not available"
    try:
        result = mscms.InstallColorProfileW(None, str(profile_path))
    except Exception as exc:
        return False, f"Color management registration error: {exc}"
    if not result:
        return False, "Windows color management rejected profile registration"
    return True, f"Profile registered: {profile_path}"


def _is_exact_profile_basename(value: object) -> bool:
    if type(value) is not str or not value or value in {".", ".."}:
        return False
    if value.rstrip(" .") != value or PureWindowsPath(value).name != value:
        return False
    if any(ord(character) < 32 or character in _INVALID_WIN32_PROFILE_NAME_CHARS for character in value):
        return False
    if value.split(".", 1)[0].upper() in _RESERVED_WIN32_DEVICE_NAMES:
        return False
    try:
        return len(value.encode("utf-16-le")) <= 510
    except UnicodeEncodeError:
        return False


def _require_exact_device_name(device_name: object) -> str:
    if type(device_name) is not str or not device_name.strip() or "\x00" in device_name:
        raise ValueError("device_name must be a non-empty exact string")
    return device_name


def _is_transactional_profile_cache_name(value: object) -> bool:
    if type(value) is not str:
        return False
    return _TRANSACTIONAL_PROFILE_CACHE_RE.fullmatch(value.rstrip(" .").casefold()) is not None


def _path_resolves_to_transactional_profile_cache(path: Path) -> bool:
    if _is_transactional_profile_cache_name(path.name):
        return True
    try:
        # ``strict=False`` also follows a dangling reparse-point target, so a
        # legacy copy cannot create a reserved cache entry through that alias.
        resolved_name = path.resolve(strict=False).name
    except (OSError, RuntimeError):
        return True
    if _is_transactional_profile_cache_name(resolved_name):
        return True
    try:
        if not path.exists():
            return False
    except (OSError, RuntimeError):
        # Existing-path identity uncertainty must not authorize a destructive
        # or overwriting legacy operation.
        return True
    try:
        siblings = tuple(path.parent.iterdir())
    except OSError:
        return True
    for sibling in siblings:
        if not _is_transactional_profile_cache_name(sibling.name):
            continue
        try:
            if path.samefile(sibling):
                return True
        except OSError:
            return True
    return False


def _exception_detail(exc: BaseException) -> str:
    return str(exc).strip() or type(exc).__name__


def _add_exception_note(exc: BaseException, note: str) -> None:
    add_note = getattr(exc, "add_note", None)
    if callable(add_note):
        add_note(note)


def _normalize_profile_handle_path(path: str) -> str:
    if path.startswith("\\\\?\\UNC\\"):
        path = "\\\\" + path[8:]
    elif path.startswith("\\\\?\\"):
        path = path[4:]
    return os.path.normcase(os.path.normpath(os.path.abspath(path)))


class _ProfileNativeState(Enum):
    PENDING = "pending"
    ENTERED = "entered"
    OPEN = "open"
    CLOSED = "closed"
    FAILED = "failed"
    UNCERTAIN = "uncertain"


class _ProfileOwnerClaim(Enum):
    PENDING = "pending"
    ACTIVE = "active"
    RETAINED = "retained"
    CLAIMED = "claimed"


class _ProfileNativeAction(Enum):
    ACQUIRE = "acquire"
    DELETE = "delete"
    CLOSE = "close"


_PROFILE_OWNER_REGISTRY_LOCK = threading.RLock()
_PROFILE_OWNER_REGISTRY_CHANGED = threading.Condition(_PROFILE_OWNER_REGISTRY_LOCK)


@dataclass(frozen=True)
class _ProfileNativeAttempt:
    """One immutable native action isolated from caller-thread cancellation.

    Tracing is not suppressed. Same-process code that injects inside this worker,
    including through ``sys.monitoring``, is trusted and outside this boundary:
    interruption between a native return and Python publication has no honest way
    to reconstruct the native result.
    """

    token: object
    action: _ProfileNativeAction
    done: threading.Event
    started: threading.Event
    worker: threading.Thread


@dataclass
class _ProfileOwnerState:
    handle: object | None = None
    state: _ProfileNativeState = _ProfileNativeState.PENDING
    claim: _ProfileOwnerClaim = _ProfileOwnerClaim.PENDING
    action: _ProfileNativeAction = _ProfileNativeAction.ACQUIRE
    attempt: _ProfileNativeAttempt | None = None
    claimant: object | None = None
    terminal_cleanup_token: object | None = None
    error: BaseException | None = None
    delete_marked: bool = False
    delete_last_error: int = 0
    cleanup_delete_requested: bool = False
    close_poisoned: bool = False


_RETAINED_PROFILE_DELETE_LEASES: list[Any] = []


class _VerifiedProfileDeleteHandle:
    """One exact Win32 object held from verification through optional disposition."""

    _DELETE = 0x00010000
    _GENERIC_READ = 0x80000000
    _GENERIC_WRITE = 0x40000000
    _FILE_READ_ATTRIBUTES = 0x00000080
    _FILE_SHARE_READ = 0x00000001
    _CREATE_NEW = 1
    _OPEN_EXISTING = 3
    _FILE_ATTRIBUTE_DIRECTORY = 0x00000010
    _FILE_ATTRIBUTE_REPARSE_POINT = 0x00000400
    _FILE_ATTRIBUTE_NORMAL = 0x00000080
    _FILE_FLAG_OPEN_REPARSE_POINT = 0x00200000
    _FILE_TYPE_DISK = 0x0001
    _FILE_DISPOSITION_INFO = 4
    _MAX_PROFILE_BYTES = 64 * 1024 * 1024

    def __init__(self, path: Path, *, create: bool) -> None:
        self._initialize(path, create=create)

    def _owner_state(self) -> _ProfileOwnerState:
        owner = getattr(self, "_owner", None)
        if owner is None:
            owner = _ProfileOwnerState(claim=_ProfileOwnerClaim.RETAINED)
            self._owner = owner
        return owner

    @property
    def handle(self) -> object | None:
        with _PROFILE_OWNER_REGISTRY_CHANGED:
            return self._owner_state().handle

    @handle.setter
    def handle(self, value: object | None) -> None:
        with _PROFILE_OWNER_REGISTRY_CHANGED:
            owner = self._owner_state()
            owner.handle = value
            if value is None:
                owner.state = _ProfileNativeState.CLOSED
            elif owner.state in {_ProfileNativeState.PENDING, _ProfileNativeState.CLOSED, _ProfileNativeState.FAILED}:
                owner.state = _ProfileNativeState.OPEN
            _PROFILE_OWNER_REGISTRY_CHANGED.notify_all()

    @property
    def delete_marked(self) -> bool:
        with _PROFILE_OWNER_REGISTRY_CHANGED:
            return self._owner_state().delete_marked

    @delete_marked.setter
    def delete_marked(self, value: bool) -> None:
        with _PROFILE_OWNER_REGISTRY_CHANGED:
            self._owner_state().delete_marked = value
            _PROFILE_OWNER_REGISTRY_CHANGED.notify_all()

    @property
    def _close_poisoned(self) -> bool:
        with _PROFILE_OWNER_REGISTRY_CHANGED:
            return self._owner_state().close_poisoned

    @_close_poisoned.setter
    def _close_poisoned(self, value: bool) -> None:
        with _PROFILE_OWNER_REGISTRY_CHANGED:
            self._owner_state().close_poisoned = value
            _PROFILE_OWNER_REGISTRY_CHANGED.notify_all()

    @property
    def _cleanup_delete_requested(self) -> bool:
        with _PROFILE_OWNER_REGISTRY_CHANGED:
            return self._owner_state().cleanup_delete_requested

    @_cleanup_delete_requested.setter
    def _cleanup_delete_requested(self, value: bool) -> None:
        with _PROFILE_OWNER_REGISTRY_CHANGED:
            self._owner_state().cleanup_delete_requested = value
            _PROFILE_OWNER_REGISTRY_CHANGED.notify_all()

    @property
    def _lease_state(self) -> str:
        with _PROFILE_OWNER_REGISTRY_CHANGED:
            return self._owner_state().claim.value

    @_lease_state.setter
    def _lease_state(self, value: str) -> None:
        with _PROFILE_OWNER_REGISTRY_CHANGED:
            legacy_claims = {
                "pending": _ProfileOwnerClaim.PENDING,
                "active": _ProfileOwnerClaim.ACTIVE,
                "cleanup": _ProfileOwnerClaim.CLAIMED,
                "retained": _ProfileOwnerClaim.RETAINED,
            }
            self._owner_state().claim = legacy_claims[value]
            _PROFILE_OWNER_REGISTRY_CHANGED.notify_all()

    @property
    def _acquired_handle(self) -> object | None:
        return self.handle

    @_acquired_handle.setter
    def _acquired_handle(self, value: object | None) -> None:
        self.handle = value

    @property
    def _acquisition_outcome(self) -> str:
        with _PROFILE_OWNER_REGISTRY_CHANGED:
            owner = self._owner_state()
            return "pre-entry" if owner.state is _ProfileNativeState.PENDING else owner.state.value

    @property
    def _delete_outcome(self) -> list[str]:
        with _PROFILE_OWNER_REGISTRY_CHANGED:
            owner = self._owner_state()
            if owner.delete_marked:
                return ["marked"]
            if owner.action is _ProfileNativeAction.DELETE and owner.state is _ProfileNativeState.PENDING:
                return ["pre-entry"]
            return [owner.state.value]

    @_delete_outcome.setter
    def _delete_outcome(self, value: list[str]) -> None:
        with _PROFILE_OWNER_REGISTRY_CHANGED:
            owner = self._owner_state()
            outcome = value[0]
            owner.delete_marked = outcome == "marked"
            owner.state = (
                _ProfileNativeState.OPEN
                if outcome == "marked"
                else _ProfileNativeState.PENDING
                if outcome == "pre-entry"
                else _ProfileNativeState(outcome)
            )
            owner.action = _ProfileNativeAction.DELETE
            _PROFILE_OWNER_REGISTRY_CHANGED.notify_all()

    def _initialize(self, path: Path, *, create: bool) -> None:
        self.path = path
        self.kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._owner = _ProfileOwnerState(cleanup_delete_requested=create)
        self._delete_on_body_error: Callable[[], bool] | None = None
        api = self.kernel32
        api.CreateFileW.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            ctypes.c_void_p,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.HANDLE,
        ]
        api.CreateFileW.restype = wintypes.HANDLE
        api.GetFileInformationByHandle.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(_PROFILE_HANDLE_INFORMATION),
        ]
        api.GetFileInformationByHandle.restype = wintypes.BOOL
        api.GetFinalPathNameByHandleW.argtypes = [
            wintypes.HANDLE,
            wintypes.LPWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
        ]
        api.GetFinalPathNameByHandleW.restype = wintypes.DWORD
        api.GetFileType.argtypes = [wintypes.HANDLE]
        api.GetFileType.restype = wintypes.DWORD
        api.GetFileSizeEx.argtypes = [wintypes.HANDLE, ctypes.POINTER(ctypes.c_longlong)]
        api.GetFileSizeEx.restype = wintypes.BOOL
        api.SetFilePointerEx.argtypes = [wintypes.HANDLE, ctypes.c_longlong, ctypes.c_void_p, wintypes.DWORD]
        api.SetFilePointerEx.restype = wintypes.BOOL
        api.ReadFile.argtypes = [
            wintypes.HANDLE,
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
            ctypes.c_void_p,
        ]
        api.ReadFile.restype = wintypes.BOOL
        api.WriteFile.argtypes = [
            wintypes.HANDLE,
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
            ctypes.c_void_p,
        ]
        api.WriteFile.restype = wintypes.BOOL
        api.FlushFileBuffers.argtypes = [wintypes.HANDLE]
        api.FlushFileBuffers.restype = wintypes.BOOL
        api.SetFileInformationByHandle.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            wintypes.DWORD,
        ]
        api.SetFileInformationByHandle.restype = wintypes.BOOL
        api.CloseHandle.argtypes = [wintypes.HANDLE]
        api.CloseHandle.restype = wintypes.BOOL

        access = self._DELETE | self._GENERIC_READ | self._FILE_READ_ATTRIBUTES
        if create:
            access |= self._GENERIC_WRITE
        creation = self._CREATE_NEW if create else self._OPEN_EXISTING
        invalid_handle = ctypes.c_void_p(-1).value
        attempt: _ProfileNativeAttempt | None = None
        start_requested = False
        try:
            attempt = _reserve_profile_delete_lease(
                self,
                access=access,
                creation=creation,
                invalid_handle=invalid_handle,
            )
            start_requested = True
            _start_profile_native_attempt(self, attempt)
            _await_profile_native_attempt(self, attempt)
        except BaseException as primary_error:
            cleanup_errors: list[BaseException] = []
            with _PROFILE_OWNER_REGISTRY_CHANGED:
                published_attempt = attempt if attempt is not None else self._owner.attempt
                state = self._owner.state
                handle = self._owner.handle
                if _profile_lease_is_registered_locked(self) and state in {
                    _ProfileNativeState.PENDING,
                    _ProfileNativeState.ENTERED,
                }:
                    self._owner.claim = _ProfileOwnerClaim.RETAINED
                    self._owner.claimant = None
                    _PROFILE_OWNER_REGISTRY_CHANGED.notify_all()
            if start_requested and published_attempt is not None:
                try:
                    _reconcile_profile_native_attempt(self, published_attempt)
                except BaseException as acquisition_cleanup_error:
                    cleanup_errors.append(acquisition_cleanup_error)
                with _PROFILE_OWNER_REGISTRY_CHANGED:
                    state = self._owner.state
                    handle = self._owner.handle
            if handle not in (None, 0, invalid_handle) and state is _ProfileNativeState.OPEN:
                _finish_verified_profile_lease_cleanup(
                    self,
                    delete_created=create,
                    cleanup_errors=cleanup_errors,
                )
                cancellation = next(
                    (error for error in cleanup_errors if not isinstance(error, Exception)),
                    None,
                )
                if isinstance(primary_error, Exception) and cancellation is not None:
                    _add_exception_note(
                        cancellation,
                        f"profile handle construction also failed: {_exception_detail(primary_error)}",
                    )
                    raise cancellation from primary_error
                for recorded_error in cleanup_errors:
                    _add_exception_note(
                        primary_error,
                        f"profile handle construction cleanup also failed: {_exception_detail(recorded_error)}",
                    )
            elif state is _ProfileNativeState.FAILED:
                _release_retained_profile_delete_lease(self)
            raise

        with _PROFILE_OWNER_REGISTRY_CHANGED:
            if self._owner.state is _ProfileNativeState.OPEN and self._owner.handle not in (None, 0, invalid_handle):
                return
            error = self._owner.error or RuntimeError(
                "profile mutation handle acquisition ended without a valid handle"
            )
            if self._owner.state is _ProfileNativeState.FAILED:
                _retire_profile_delete_lease_locked(self)
        raise error

    def _acquire_handle_worker(
        self,
        token: object,
        done: threading.Event,
        access: int,
        creation: int,
        invalid_handle: int | None,
    ) -> None:
        with _PROFILE_OWNER_REGISTRY_CHANGED:
            if not _profile_attempt_matches_locked(self, token, _ProfileNativeAction.ACQUIRE):
                done.set()
                _PROFILE_OWNER_REGISTRY_CHANGED.notify_all()
                return
            self._owner.state = _ProfileNativeState.ENTERED
            _PROFILE_OWNER_REGISTRY_CHANGED.notify_all()
        try:
            handle = self.kernel32.CreateFileW(
                str(self.path),
                access,
                self._FILE_SHARE_READ,
                None,
                creation,
                self._FILE_ATTRIBUTE_NORMAL | self._FILE_FLAG_OPEN_REPARSE_POINT,
                None,
            )
            if not handle or handle == invalid_handle:
                error = ctypes.get_last_error()
                if creation == self._CREATE_NEW and error in {80, 183}:
                    raise FileExistsError(f"profile destination already exists: {self.path}")
                if error == 5:
                    raise PermissionError(f"profile handle access denied: {self.path}")
                raise RuntimeError(f"profile mutation handle could not open: {ctypes.WinError(error)}")
        except BaseException as acquisition_error:
            with _PROFILE_OWNER_REGISTRY_CHANGED:
                if _profile_attempt_matches_locked(self, token, _ProfileNativeAction.ACQUIRE):
                    self._owner.error = acquisition_error
                    self._owner.state = _ProfileNativeState.FAILED
        else:
            with _PROFILE_OWNER_REGISTRY_CHANGED:
                if _profile_attempt_matches_locked(self, token, _ProfileNativeAction.ACQUIRE):
                    self._owner.handle = handle
                    self._owner.error = None
                    self._owner.state = _ProfileNativeState.OPEN
        finally:
            terminal_attempt: _ProfileNativeAttempt | None = None
            with _PROFILE_OWNER_REGISTRY_CHANGED:
                done.set()
                if (
                    self._owner.attempt is not None
                    and self._owner.attempt.token is token
                    and self._owner.terminal_cleanup_token is token
                ):
                    terminal_attempt = self._owner.attempt
                _PROFILE_OWNER_REGISTRY_CHANGED.notify_all()
            if terminal_attempt is not None:
                _launch_profile_terminal_cleanup(self, terminal_attempt)

    def _require_handle(self) -> object:
        if self.handle is None:
            raise RuntimeError("profile mutation handle is closed")
        return self.handle

    def write_bytes(self, payload: bytes) -> None:
        handle = self._require_handle()
        if type(payload) is not bytes or len(payload) > self._MAX_PROFILE_BYTES:
            raise RuntimeError("profile payload is outside the supported exact-byte range")
        if payload:
            buffer = (ctypes.c_ubyte * len(payload)).from_buffer_copy(payload)
            written = wintypes.DWORD()
            if not self.kernel32.WriteFile(handle, buffer, len(payload), ctypes.byref(written), None):
                raise RuntimeError(f"profile write failed: {ctypes.WinError(ctypes.get_last_error())}")
            if written.value != len(payload):
                raise RuntimeError("profile write produced a short write")
        if not self.kernel32.FlushFileBuffers(handle):
            raise RuntimeError(f"profile flush failed: {ctypes.WinError(ctypes.get_last_error())}")

    def read_bytes(self) -> bytes:
        handle = self._require_handle()
        size = ctypes.c_longlong()
        if not self.kernel32.GetFileSizeEx(handle, ctypes.byref(size)):
            raise RuntimeError(f"profile size read failed: {ctypes.WinError(ctypes.get_last_error())}")
        if not 0 <= size.value <= self._MAX_PROFILE_BYTES:
            raise RuntimeError("profile size is outside the supported range")
        if not self.kernel32.SetFilePointerEx(handle, 0, None, 0):
            raise RuntimeError(f"profile seek failed: {ctypes.WinError(ctypes.get_last_error())}")
        if size.value == 0:
            return b""
        buffer = (ctypes.c_ubyte * size.value)()
        read = wintypes.DWORD()
        if not self.kernel32.ReadFile(handle, buffer, size.value, ctypes.byref(read), None):
            raise RuntimeError(f"profile read failed: {ctypes.WinError(ctypes.get_last_error())}")
        if read.value != size.value:
            raise RuntimeError("profile read produced a short read")
        return bytes(buffer)

    def validate(self, *, expected_payload: bytes | None = None) -> None:
        handle = self._require_handle()
        if self.kernel32.GetFileType(handle) != self._FILE_TYPE_DISK:
            raise RuntimeError("profile mutation target is not a disk file")
        information = _PROFILE_HANDLE_INFORMATION()
        if not self.kernel32.GetFileInformationByHandle(handle, ctypes.byref(information)):
            raise RuntimeError(f"profile mutation identity failed: {ctypes.WinError(ctypes.get_last_error())}")
        attributes = int(information.dwFileAttributes)
        if attributes & self._FILE_ATTRIBUTE_REPARSE_POINT:
            raise RuntimeError("profile mutation target is a reparse point")
        if attributes & self._FILE_ATTRIBUTE_DIRECTORY:
            raise RuntimeError("profile mutation target is not a regular file")
        if int(information.nNumberOfLinks) != 1:
            raise RuntimeError("profile mutation target is not a private single-link file")
        required = int(self.kernel32.GetFinalPathNameByHandleW(handle, None, 0, 0))
        if required <= 0:
            raise RuntimeError(f"profile final path query failed: {ctypes.WinError(ctypes.get_last_error())}")
        buffer = ctypes.create_unicode_buffer(required + 1)
        written = int(self.kernel32.GetFinalPathNameByHandleW(handle, buffer, len(buffer), 0))
        if written <= 0 or written >= len(buffer):
            raise RuntimeError(f"profile final path read failed: {ctypes.WinError(ctypes.get_last_error())}")
        if _normalize_profile_handle_path(buffer.value) != _normalize_profile_handle_path(str(self.path)):
            raise RuntimeError("profile mutation handle does not resolve to the exact requested path")
        if _path_resolves_to_transactional_profile_cache(self.path):
            raise RuntimeError("profile mutation target resolves to the transactional product cache")
        if expected_payload is not None and self.read_bytes() != expected_payload:
            raise RuntimeError("profile mutation bytes changed from the exact expected payload")

    def _delete_disposition_worker(
        self,
        token: object,
        done: threading.Event,
        disposition: _FILE_DISPOSITION_INFORMATION,
    ) -> None:
        with _PROFILE_OWNER_REGISTRY_CHANGED:
            if not _profile_attempt_matches_locked(self, token, _ProfileNativeAction.DELETE):
                done.set()
                _PROFILE_OWNER_REGISTRY_CHANGED.notify_all()
                return
            self._owner.state = _ProfileNativeState.ENTERED
            _PROFILE_OWNER_REGISTRY_CHANGED.notify_all()
        try:
            marked = bool(
                self.kernel32.SetFileInformationByHandle(
                    self._require_handle(),
                    self._FILE_DISPOSITION_INFO,
                    ctypes.byref(disposition),
                    ctypes.sizeof(disposition),
                )
            )
        except BaseException as delete_error:
            with _PROFILE_OWNER_REGISTRY_CHANGED:
                if _profile_attempt_matches_locked(self, token, _ProfileNativeAction.DELETE):
                    self._owner.error = delete_error
                    self._owner.state = _ProfileNativeState.UNCERTAIN
        else:
            with _PROFILE_OWNER_REGISTRY_CHANGED:
                if _profile_attempt_matches_locked(self, token, _ProfileNativeAction.DELETE):
                    self._owner.error = None
                    self._owner.delete_last_error = 0 if marked else ctypes.get_last_error()
                    self._owner.delete_marked = marked
                    self._owner.state = _ProfileNativeState.OPEN
        finally:
            terminal_attempt: _ProfileNativeAttempt | None = None
            with _PROFILE_OWNER_REGISTRY_CHANGED:
                done.set()
                if (
                    self._owner.attempt is not None
                    and self._owner.attempt.token is token
                    and self._owner.terminal_cleanup_token is token
                ):
                    terminal_attempt = self._owner.attempt
                _PROFILE_OWNER_REGISTRY_CHANGED.notify_all()
            if terminal_attempt is not None:
                _launch_profile_terminal_cleanup(self, terminal_attempt)

    def _close_handle_worker(self, token: object, done: threading.Event) -> None:
        with _PROFILE_OWNER_REGISTRY_CHANGED:
            if not _profile_attempt_matches_locked(self, token, _ProfileNativeAction.CLOSE):
                done.set()
                _PROFILE_OWNER_REGISTRY_CHANGED.notify_all()
                return
            self._owner.state = _ProfileNativeState.ENTERED
            handle = self._owner.handle
            _PROFILE_OWNER_REGISTRY_CHANGED.notify_all()
        try:
            closed = bool(self.kernel32.CloseHandle(handle))
        except BaseException as close_error:
            with _PROFILE_OWNER_REGISTRY_CHANGED:
                if _profile_attempt_matches_locked(self, token, _ProfileNativeAction.CLOSE):
                    self._owner.error = close_error
                    self._owner.close_poisoned = True
                    self._owner.state = _ProfileNativeState.UNCERTAIN
        else:
            with _PROFILE_OWNER_REGISTRY_CHANGED:
                if _profile_attempt_matches_locked(self, token, _ProfileNativeAction.CLOSE):
                    self._owner.error = None
                    self._owner.state = _ProfileNativeState.CLOSED if closed else _ProfileNativeState.OPEN
                    if closed:
                        self._owner.handle = None
        finally:
            terminal_attempt: _ProfileNativeAttempt | None = None
            with _PROFILE_OWNER_REGISTRY_CHANGED:
                done.set()
                if (
                    self._owner.attempt is not None
                    and self._owner.attempt.token is token
                    and self._owner.terminal_cleanup_token is token
                ):
                    terminal_attempt = self._owner.attempt
                _PROFILE_OWNER_REGISTRY_CHANGED.notify_all()
            if terminal_attempt is not None:
                _launch_profile_terminal_cleanup(self, terminal_attempt)

    def _invoke_delete_disposition(self, disposition: _FILE_DISPOSITION_INFORMATION) -> bool:
        _retain_profile_delete_lease(self)
        while True:
            with _PROFILE_OWNER_REGISTRY_CHANGED:
                owner = self._owner
                if owner.state is _ProfileNativeState.CLOSED or owner.handle is None:
                    raise RuntimeError("profile mutation handle is closed")
                if owner.state is _ProfileNativeState.UNCERTAIN:
                    raise owner.error or RuntimeError("profile native outcome is uncertain")
                if owner.state in {_ProfileNativeState.PENDING, _ProfileNativeState.ENTERED}:
                    attempt = owner.attempt
                    if attempt is None:
                        raise RuntimeError("profile native attempt was not published")
                else:
                    attempt = _new_profile_native_attempt_locked(
                        self,
                        _ProfileNativeAction.DELETE,
                        disposition=disposition,
                    )
            _reconcile_profile_native_attempt(self, attempt)
            if attempt.action is _ProfileNativeAction.DELETE:
                break
        with _PROFILE_OWNER_REGISTRY_CHANGED:
            if self._owner.error is not None:
                raise self._owner.error
            return self._owner.delete_marked

    def mark_delete(self, *, expected_payload: bytes | None = None) -> None:
        with _PROFILE_OWNER_REGISTRY_CHANGED:
            in_flight = (
                self._owner.attempt
                if self._owner.state in {_ProfileNativeState.PENDING, _ProfileNativeState.ENTERED}
                else None
            )
        if in_flight is not None:
            _reconcile_profile_native_attempt(self, in_flight)
        with _PROFILE_OWNER_REGISTRY_CHANGED:
            if self._owner.delete_marked:
                return
            if self._owner.state is _ProfileNativeState.CLOSED or self._owner.handle is None:
                raise RuntimeError("profile mutation handle is closed")
            if self._owner.state is _ProfileNativeState.UNCERTAIN:
                raise RuntimeError("profile delete disposition is poisoned because the native outcome is uncertain")
        self.validate(expected_payload=expected_payload)
        disposition = _FILE_DISPOSITION_INFORMATION(True)
        if not self._invoke_delete_disposition(disposition):
            with _PROFILE_OWNER_REGISTRY_CHANGED:
                error = self._owner.delete_last_error
            raise RuntimeError(f"profile delete disposition failed: {ctypes.WinError(error)}")

    def close(self) -> None:
        cleanup_error = _close_profile_handle(self)
        if cleanup_error is not None:
            raise cleanup_error


_VERIFIED_PROFILE_DELETE_HANDLE_TYPE = _VerifiedProfileDeleteHandle


def _is_synchronized_profile_lease(lease: object) -> TypeGuard[_VerifiedProfileDeleteHandle]:
    return isinstance(lease, _VERIFIED_PROFILE_DELETE_HANDLE_TYPE) and hasattr(lease, "_owner")


def _profile_lease_is_registered_locked(lease: object) -> bool:
    return any(retained is lease for retained in _RETAINED_PROFILE_DELETE_LEASES)


def _retire_profile_delete_lease_locked(lease: object) -> None:
    _RETAINED_PROFILE_DELETE_LEASES[:] = [
        retained for retained in _RETAINED_PROFILE_DELETE_LEASES if retained is not lease
    ]
    if _is_synchronized_profile_lease(lease):
        lease._owner.claimant = None
        lease._owner.terminal_cleanup_token = None
    _PROFILE_OWNER_REGISTRY_CHANGED.notify_all()


def _retire_closed_profile_leases_locked() -> None:
    for lease in tuple(_RETAINED_PROFILE_DELETE_LEASES):
        if _is_synchronized_profile_lease(lease):
            if lease._owner.state is _ProfileNativeState.CLOSED:
                _retire_profile_delete_lease_locked(lease)
        elif getattr(lease, "handle", None) is None:
            _retire_profile_delete_lease_locked(lease)


def _reserve_profile_delete_lease(
    lease: _VerifiedProfileDeleteHandle,
    *,
    access: int = 0,
    creation: int = 0,
    invalid_handle: int | None = None,
) -> _ProfileNativeAttempt:
    try:
        with _PROFILE_OWNER_REGISTRY_CHANGED:
            _retire_closed_profile_leases_locked()
            if _profile_lease_is_registered_locked(lease):
                attempt = lease._owner.attempt
                if attempt is None:
                    attempt = _new_profile_native_attempt_locked(
                        lease,
                        _ProfileNativeAction.ACQUIRE,
                        access=access,
                        creation=creation,
                        invalid_handle=invalid_handle,
                    )
                return attempt
            if len(_RETAINED_PROFILE_DELETE_LEASES) >= _PROFILE_OWNER_REGISTRY_CAP:
                raise RuntimeError("profile owner registry capacity is exhausted")
            lease._owner.claim = _ProfileOwnerClaim.PENDING
            lease._owner.state = _ProfileNativeState.PENDING
            lease._owner.action = _ProfileNativeAction.ACQUIRE
            lease._owner.attempt = None
            lease._owner.claimant = None
            lease._owner.error = None
            attempt = _new_profile_native_attempt_locked(
                lease,
                _ProfileNativeAction.ACQUIRE,
                access=access,
                creation=creation,
                invalid_handle=invalid_handle,
            )
            _RETAINED_PROFILE_DELETE_LEASES.append(lease)
            _PROFILE_OWNER_REGISTRY_CHANGED.notify_all()
            return attempt
    except BaseException:
        with _PROFILE_OWNER_REGISTRY_CHANGED:
            if _profile_lease_is_registered_locked(lease):
                lease._owner.claim = _ProfileOwnerClaim.RETAINED
                lease._owner.claimant = None
                _PROFILE_OWNER_REGISTRY_CHANGED.notify_all()
        raise


def _retain_profile_delete_lease(lease: _VerifiedProfileDeleteHandle) -> None:
    with _PROFILE_OWNER_REGISTRY_CHANGED:
        _retire_closed_profile_leases_locked()
        if _is_synchronized_profile_lease(lease) and lease._owner.state is _ProfileNativeState.CLOSED:
            return
        if _profile_lease_is_registered_locked(lease):
            return
        if len(_RETAINED_PROFILE_DELETE_LEASES) >= _PROFILE_OWNER_REGISTRY_CAP:
            raise RuntimeError("profile owner registry capacity is exhausted")
        _RETAINED_PROFILE_DELETE_LEASES.append(lease)
        _PROFILE_OWNER_REGISTRY_CHANGED.notify_all()


def _release_retained_profile_delete_lease(lease: _VerifiedProfileDeleteHandle) -> None:
    with _PROFILE_OWNER_REGISTRY_CHANGED:
        _retire_profile_delete_lease_locked(lease)


def _profile_attempt_matches_locked(
    lease: _VerifiedProfileDeleteHandle,
    token: object,
    action: _ProfileNativeAction,
) -> bool:
    attempt = lease._owner.attempt
    return attempt is not None and attempt.token is token and lease._owner.action is action


def _new_profile_native_attempt_locked(
    lease: _VerifiedProfileDeleteHandle,
    action: _ProfileNativeAction,
    *,
    access: int = 0,
    creation: int = 0,
    invalid_handle: int | None = None,
    disposition: _FILE_DISPOSITION_INFORMATION | None = None,
) -> _ProfileNativeAttempt:
    current = lease._owner.attempt
    if lease._owner.state in {_ProfileNativeState.PENDING, _ProfileNativeState.ENTERED} and current is not None:
        if current.action is action:
            return current
        raise RuntimeError("profile native action cannot replace an in-flight attempt")
    if lease._owner.state is _ProfileNativeState.ENTERED:
        if current is None:
            raise RuntimeError("profile native state has no immutable attempt")
    token = object()
    done = threading.Event()
    started = threading.Event()
    if action is _ProfileNativeAction.ACQUIRE:
        worker = threading.Thread(
            target=lease._acquire_handle_worker,
            args=(token, done, access, creation, invalid_handle),
            daemon=True,
        )
    elif action is _ProfileNativeAction.DELETE:
        if disposition is None:
            raise RuntimeError("profile delete disposition attempt requires an immutable disposition")
        worker = threading.Thread(
            target=lease._delete_disposition_worker,
            args=(token, done, disposition),
            daemon=True,
        )
    else:
        worker = threading.Thread(
            target=lease._close_handle_worker,
            args=(token, done),
            daemon=True,
        )
    attempt = _ProfileNativeAttempt(token=token, action=action, done=done, started=started, worker=worker)
    lease._owner.action = action
    lease._owner.attempt = attempt
    lease._owner.state = _ProfileNativeState.PENDING
    lease._owner.error = None
    _PROFILE_OWNER_REGISTRY_CHANGED.notify_all()
    return attempt


def _start_profile_native_attempt(
    lease: _VerifiedProfileDeleteHandle,
    attempt: _ProfileNativeAttempt,
) -> None:
    try:
        with _PROFILE_OWNER_REGISTRY_CHANGED:
            if lease._owner.attempt is not attempt:
                raise RuntimeError("profile native attempt ownership changed before start")
            if attempt.started.is_set() or attempt.done.is_set() or attempt.worker.ident is not None:
                return
            attempt.worker.start()
            attempt.started.set()
            _PROFILE_OWNER_REGISTRY_CHANGED.notify_all()
    except BaseException as start_error:
        try:
            _await_profile_native_attempt(lease, attempt)
        except BaseException as reconciliation_error:
            _add_exception_note(
                start_error,
                f"profile native start reconciliation also failed: {_exception_detail(reconciliation_error)}",
            )
        raise


def _await_profile_native_attempt(
    lease: _VerifiedProfileDeleteHandle,
    attempt: _ProfileNativeAttempt,
) -> bool:
    with _PROFILE_OWNER_REGISTRY_CHANGED:
        started = attempt.started.is_set() or attempt.done.is_set() or attempt.worker.ident is not None
    if not started:
        return False
    attempt.worker.join(timeout=_PROFILE_NATIVE_WORKER_JOIN_SECONDS)
    if attempt.worker.is_alive():
        raise RuntimeError("profile native worker did not terminate within the bounded wait")
    if not attempt.done.is_set():
        raise RuntimeError("profile native worker exited without publishing a terminal state")
    return True


def _reconcile_profile_native_attempt(
    lease: _VerifiedProfileDeleteHandle,
    attempt: _ProfileNativeAttempt,
) -> None:
    if not _await_profile_native_attempt(lease, attempt):
        _start_profile_native_attempt(lease, attempt)
    if not _await_profile_native_attempt(lease, attempt):
        raise RuntimeError("profile native attempt remained unstarted during reconciliation")


def _await_profile_acquisition(lease: _VerifiedProfileDeleteHandle) -> None:
    if not _is_synchronized_profile_lease(lease):
        return
    with _PROFILE_OWNER_REGISTRY_CHANGED:
        attempt = lease._owner.attempt if lease._owner.action is _ProfileNativeAction.ACQUIRE else None
    if attempt is not None:
        _reconcile_profile_native_attempt(lease, attempt)


def _await_profile_delete_worker(lease: _VerifiedProfileDeleteHandle) -> None:
    if not _is_synchronized_profile_lease(lease):
        return
    with _PROFILE_OWNER_REGISTRY_CHANGED:
        attempt = lease._owner.attempt if lease._owner.action is _ProfileNativeAction.DELETE else None
    if attempt is not None:
        _reconcile_profile_native_attempt(lease, attempt)


def _publish_acquired_profile_handle(lease: _VerifiedProfileDeleteHandle) -> None:
    del lease


def _profile_delete_outcome(lease: _VerifiedProfileDeleteHandle) -> str:
    if _is_synchronized_profile_lease(lease):
        with _PROFILE_OWNER_REGISTRY_CHANGED:
            owner = lease._owner
            if owner.delete_marked:
                return "marked"
            if owner.action is _ProfileNativeAction.DELETE and owner.state is _ProfileNativeState.PENDING:
                return "pre-entry"
            return owner.state.value
    outcome = getattr(lease, "_delete_outcome", None)
    if isinstance(outcome, list) and outcome:
        return str(outcome[0])
    return "marked" if lease.delete_marked else "open"


class _ProfileClaimGuard:
    def __init__(
        self,
        lease: _VerifiedProfileDeleteHandle,
        token: object,
        *,
        cleanup_handoff: bool = False,
    ) -> None:
        self.lease = lease
        self.token = token
        self._cleanup_handoff = cleanup_handoff
        self._acquired = False
        self._evaluated = False
        self._rollback_claim = _ProfileOwnerClaim.RETAINED

    def __enter__(self) -> "_ProfileClaimGuard":
        return self

    @property
    def acquired(self) -> bool:
        if not self._evaluated:
            try:
                self._acquire()
            except BaseException:
                self._rollback()
                raise
            self._evaluated = True
        return self._acquired

    def _acquire(self) -> None:
        try:
            with _PROFILE_OWNER_REGISTRY_CHANGED:
                while True:
                    owner = self.lease._owner
                    if owner.state is _ProfileNativeState.CLOSED:
                        _retire_profile_delete_lease_locked(self.lease)
                        return
                    if not _profile_lease_is_registered_locked(self.lease):
                        if owner.handle is None:
                            return
                        if len(_RETAINED_PROFILE_DELETE_LEASES) >= _PROFILE_OWNER_REGISTRY_CAP:
                            raise RuntimeError("profile owner registry capacity is exhausted")
                        _RETAINED_PROFILE_DELETE_LEASES.append(self.lease)
                    if owner.claim is not _ProfileOwnerClaim.CLAIMED:
                        self._rollback_claim = owner.claim
                        publication_complete = False
                        try:
                            owner.claimant = self.token
                            owner.claim = _ProfileOwnerClaim.CLAIMED
                            self._acquired = True
                            publication_complete = True
                        finally:
                            if not publication_complete and owner.claimant is self.token:
                                self._rollback_locked(owner)
                        _PROFILE_OWNER_REGISTRY_CHANGED.notify_all()
                        return
                    if owner.claimant is self.token:
                        self._acquired = True
                        return
                    notified = _PROFILE_OWNER_REGISTRY_CHANGED.wait(timeout=_PROFILE_NATIVE_WORKER_JOIN_SECONDS)
                    if not notified and owner.claim is _ProfileOwnerClaim.CLAIMED:
                        raise RuntimeError("profile cleanup claim did not resolve within the bounded wait")
        except BaseException:
            self._rollback()
            raise

    def __exit__(self, *_args: object) -> None:
        self._rollback()

    def _rollback(self) -> None:
        with _PROFILE_OWNER_REGISTRY_CHANGED:
            self._rollback_locked(self.lease._owner)

    def _rollback_locked(self, owner: _ProfileOwnerState) -> None:
        if owner.claimant is not self.token:
            return
        if self._cleanup_handoff and _profile_lease_is_registered_locked(self.lease):
            if owner.state is _ProfileNativeState.CLOSED or (
                owner.state is _ProfileNativeState.FAILED and owner.handle is None
            ):
                _retire_profile_delete_lease_locked(self.lease)
                return
            attempt = owner.attempt
            if (
                owner.terminal_cleanup_token is None
                and owner.state in {_ProfileNativeState.PENDING, _ProfileNativeState.ENTERED}
                and attempt is not None
                and (attempt.started.is_set() or attempt.done.is_set() or attempt.worker.ident is not None)
            ):
                _arm_profile_terminal_cleanup_locked(self.lease, attempt)
                return
            owner.claim = _ProfileOwnerClaim.RETAINED
        else:
            owner.claim = self._rollback_claim
        owner.claimant = None
        _PROFILE_OWNER_REGISTRY_CHANGED.notify_all()


def _claim_profile_delete_lease(
    lease: _VerifiedProfileDeleteHandle,
    claim_token: object,
    *,
    cleanup_handoff: bool = False,
) -> _ProfileClaimGuard:
    return _ProfileClaimGuard(lease, claim_token, cleanup_handoff=cleanup_handoff)


def _release_profile_cleanup_claim(
    lease: _VerifiedProfileDeleteHandle,
    claim: _ProfileOwnerClaim,
) -> None:
    with _PROFILE_OWNER_REGISTRY_CHANGED:
        if lease._owner.state is _ProfileNativeState.CLOSED:
            _retire_profile_delete_lease_locked(lease)
            return
        lease._owner.claim = claim
        lease._owner.claimant = None
        _PROFILE_OWNER_REGISTRY_CHANGED.notify_all()


def _close_profile_handle(
    lease: _VerifiedProfileDeleteHandle,
    *,
    claim_token: object | None = None,
) -> BaseException | None:
    token = claim_token if claim_token is not None else object()
    try:
        with _claim_profile_delete_lease(lease, token) as claim:
            if not claim.acquired:
                return None
            return _close_claimed_profile_handle(lease)
    except BaseException as claim_error:
        return claim_error


def _close_claimed_profile_handle(lease: _VerifiedProfileDeleteHandle) -> BaseException | None:
    errors: list[BaseException] = []
    with _PROFILE_OWNER_REGISTRY_CHANGED:
        owner = lease._owner
        if owner.close_poisoned:
            _release_profile_cleanup_claim(lease, _ProfileOwnerClaim.RETAINED)
            return RuntimeError("profile mutation handle close is poisoned because the native outcome is uncertain")
        in_flight = owner.attempt if owner.state in {_ProfileNativeState.PENDING, _ProfileNativeState.ENTERED} else None
    if in_flight is not None:
        try:
            _reconcile_profile_native_attempt(lease, in_flight)
        except BaseException as wait_error:
            errors.append(wait_error)

    with _PROFILE_OWNER_REGISTRY_CHANGED:
        owner = lease._owner
        if owner.state in {_ProfileNativeState.PENDING, _ProfileNativeState.ENTERED}:
            attempt = owner.attempt
            if attempt is not None and (
                attempt.started.is_set() or attempt.done.is_set() or attempt.worker.ident is not None
            ):
                _arm_profile_terminal_cleanup_locked(lease, attempt)
            else:
                _release_profile_cleanup_claim(lease, _ProfileOwnerClaim.RETAINED)
            return errors[-1] if errors else RuntimeError("profile native mutation remains in flight")
        if owner.action is _ProfileNativeAction.DELETE and owner.state is _ProfileNativeState.UNCERTAIN:
            _release_profile_cleanup_claim(lease, _ProfileOwnerClaim.RETAINED)
            return owner.error or RuntimeError("profile delete disposition native outcome is uncertain")
        if owner.handle is None or owner.state is _ProfileNativeState.CLOSED:
            owner.state = _ProfileNativeState.CLOSED
            _retire_profile_delete_lease_locked(lease)
            return next((error for error in errors if not isinstance(error, Exception)), None)
        attempt = _new_profile_native_attempt_locked(lease, _ProfileNativeAction.CLOSE)

    try:
        _start_profile_native_attempt(lease, attempt)
        _await_profile_native_attempt(lease, attempt)
    except BaseException as close_error:
        errors.append(close_error)
        try:
            _reconcile_profile_native_attempt(lease, attempt)
        except BaseException as reconciliation_error:
            errors.append(reconciliation_error)

    with _PROFILE_OWNER_REGISTRY_CHANGED:
        owner = lease._owner
        control_error = next((error for error in errors if not isinstance(error, Exception)), None)
        if owner.state is _ProfileNativeState.CLOSED:
            _retire_profile_delete_lease_locked(lease)
            return control_error
        if owner.state in {_ProfileNativeState.PENDING, _ProfileNativeState.ENTERED}:
            claim = _ProfileOwnerClaim.RETAINED
        else:
            claim = _ProfileOwnerClaim.RETAINED
        owner.claim = claim
        owner.claimant = None
        _PROFILE_OWNER_REGISTRY_CHANGED.notify_all()
        native_error = owner.error

    if native_error is not None:
        return native_error
    if control_error is not None:
        return control_error
    return RuntimeError(f"profile mutation handle close failed: {ctypes.WinError(ctypes.get_last_error())}")


def _should_delete_profile_on_error(
    primary_error: BaseException | None,
    create_payload: bytes | None,
    lease: _VerifiedProfileDeleteHandle | None,
    body_entered: list[bool],
    delete_on_body_error: Callable[[], bool] | None,
) -> bool:
    if primary_error is None or lease is None or lease.delete_marked:
        return False
    if not body_entered:
        return create_payload is not None
    if delete_on_body_error is None:
        delete_on_body_error = getattr(lease, "_delete_on_body_error", None)
    if delete_on_body_error is not None:
        return delete_on_body_error()
    return create_payload is not None


def _finish_synchronized_profile_lease_cleanup(
    lease: _VerifiedProfileDeleteHandle,
    *,
    delete_created: bool,
    cleanup_errors: list[BaseException],
    claim_token: object | None,
) -> None:
    token = claim_token if claim_token is not None else object()
    with _PROFILE_OWNER_REGISTRY_CHANGED:
        lease._owner.cleanup_delete_requested = delete_created
        _PROFILE_OWNER_REGISTRY_CHANGED.notify_all()
    for cleanup_number, cleanup_token in enumerate((token, object())):
        try:
            with _claim_profile_delete_lease(lease, cleanup_token, cleanup_handoff=True) as claim:
                if not claim.acquired:
                    return
                _finish_claimed_profile_lease_cleanup(
                    lease,
                    delete_created=delete_created,
                    cleanup_errors=cleanup_errors,
                    claim_token=cleanup_token,
                )
        except BaseException as claim_error:
            cleanup_errors.append(claim_error)
            with _PROFILE_OWNER_REGISTRY_CHANGED:
                owner = lease._owner
                recoverable_owner = (
                    _profile_lease_is_registered_locked(lease)
                    and owner.terminal_cleanup_token is None
                    and (
                        (owner.state is _ProfileNativeState.OPEN and owner.handle is not None)
                        or (
                            owner.state in {_ProfileNativeState.PENDING, _ProfileNativeState.ENTERED}
                            and owner.attempt is not None
                        )
                    )
                )
            if cleanup_number == 0 and recoverable_owner:
                continue
        return


def _finish_claimed_profile_lease_cleanup(
    lease: _VerifiedProfileDeleteHandle,
    *,
    delete_created: bool,
    cleanup_errors: list[BaseException],
    claim_token: object,
) -> None:
    with _PROFILE_OWNER_REGISTRY_CHANGED:
        lease._owner.cleanup_delete_requested = delete_created
        in_flight = (
            lease._owner.attempt
            if lease._owner.state in {_ProfileNativeState.PENDING, _ProfileNativeState.ENTERED}
            else None
        )
    if in_flight is not None:
        try:
            _reconcile_profile_native_attempt(lease, in_flight)
        except BaseException as wait_error:
            cleanup_errors.append(wait_error)

    with _PROFILE_OWNER_REGISTRY_CHANGED:
        if lease._owner.state in {_ProfileNativeState.PENDING, _ProfileNativeState.ENTERED}:
            attempt = lease._owner.attempt
            if attempt is not None and (
                attempt.started.is_set() or attempt.done.is_set() or attempt.worker.ident is not None
            ):
                _arm_profile_terminal_cleanup_locked(lease, attempt)
            else:
                _release_profile_cleanup_claim(lease, _ProfileOwnerClaim.RETAINED)
            if not cleanup_errors:
                cleanup_errors.append(RuntimeError("profile native mutation remains in flight"))
            return
        if lease._owner.state is _ProfileNativeState.FAILED and lease._owner.handle is None:
            _retire_profile_delete_lease_locked(lease)
            if lease._owner.error is not None:
                cleanup_errors.append(lease._owner.error)
            return

    if delete_created and not lease.delete_marked:
        delete_errors: list[BaseException] = []
        for _attempt_number in range(_PROFILE_CLEANUP_MAX_ATTEMPTS):
            with _PROFILE_OWNER_REGISTRY_CHANGED:
                if lease._owner.delete_marked:
                    break
                if (
                    lease._owner.action is _ProfileNativeAction.DELETE
                    and lease._owner.state is _ProfileNativeState.UNCERTAIN
                ):
                    break
            try:
                lease.mark_delete()
            except BaseException as delete_error:
                delete_errors.append(delete_error)
            with _PROFILE_OWNER_REGISTRY_CHANGED:
                if lease._owner.delete_marked:
                    break
                if lease._owner.state in {_ProfileNativeState.PENDING, _ProfileNativeState.ENTERED}:
                    attempt = lease._owner.attempt
                else:
                    attempt = None
            if attempt is not None:
                try:
                    _reconcile_profile_native_attempt(lease, attempt)
                except BaseException as wait_error:
                    delete_errors.append(wait_error)

        if lease.delete_marked:
            cleanup_errors.extend(error for error in delete_errors if not isinstance(error, Exception))
        else:
            cleanup_errors.extend(delete_errors)
            if not delete_errors:
                cleanup_errors.append(RuntimeError("profile delete disposition remained unconfirmed"))
            with _PROFILE_OWNER_REGISTRY_CHANGED:
                attempt = lease._owner.attempt
                if (
                    lease._owner.state in {_ProfileNativeState.PENDING, _ProfileNativeState.ENTERED}
                    and attempt is not None
                    and (attempt.started.is_set() or attempt.done.is_set() or attempt.worker.ident is not None)
                ):
                    _arm_profile_terminal_cleanup_locked(lease, attempt)
                else:
                    _release_profile_cleanup_claim(lease, _ProfileOwnerClaim.RETAINED)
            return

    close_errors: list[BaseException] = []
    for _attempt_number in range(_PROFILE_CLEANUP_MAX_ATTEMPTS):
        close_error = _close_profile_handle(lease, claim_token=claim_token)
        if close_error is not None:
            close_errors.append(close_error)
        with _PROFILE_OWNER_REGISTRY_CHANGED:
            closed = lease._owner.state is _ProfileNativeState.CLOSED or lease._owner.handle is None
            poisoned = lease._owner.close_poisoned
        if closed or poisoned:
            break
    if closed:
        cleanup_errors.extend(error for error in close_errors if not isinstance(error, Exception))
    else:
        cleanup_errors.extend(close_errors)
        if not close_errors:
            cleanup_errors.append(RuntimeError("profile mutation handle remained open after cleanup"))


def _finish_verified_profile_lease_cleanup(
    lease: _VerifiedProfileDeleteHandle | None,
    *,
    delete_created: bool,
    cleanup_errors: list[BaseException],
    claim_token: object | None = None,
) -> None:
    if lease is not None and _is_synchronized_profile_lease(lease):
        _finish_synchronized_profile_lease_cleanup(
            lease,
            delete_created=delete_created,
            cleanup_errors=cleanup_errors,
            claim_token=claim_token,
        )
        return
    if lease is not None:
        lease._lease_state = "cleanup"
        try:
            _await_profile_acquisition(lease)
        except BaseException as acquisition_error:
            cleanup_errors.append(acquisition_error)
        _publish_acquired_profile_handle(lease)
        lease._cleanup_delete_requested = delete_created

    delete_remains_retryable = False
    if delete_created and lease is not None and not lease.delete_marked:
        delete_errors: list[BaseException] = []
        for _attempt in range(_PROFILE_CLEANUP_MAX_ATTEMPTS):
            outcome = _profile_delete_outcome(lease)
            if outcome == "entered":
                try:
                    _await_profile_delete_worker(lease)
                except BaseException as delete_wait_error:
                    delete_errors.append(delete_wait_error)
                outcome = _profile_delete_outcome(lease)
            if outcome == "marked":
                lease.delete_marked = True
                break
            if outcome == "uncertain":
                break
            try:
                lease.mark_delete()
            except BaseException as delete_error:
                delete_errors.append(delete_error)
            outcome = _profile_delete_outcome(lease)
            if lease.delete_marked or outcome == "marked":
                lease.delete_marked = True
                break
            if outcome == "uncertain":
                break
        if lease.delete_marked:
            cleanup_errors.extend(error for error in delete_errors if not isinstance(error, Exception))
        else:
            cleanup_errors.extend(delete_errors)
            if not delete_errors:
                cleanup_errors.append(RuntimeError("profile delete disposition remained unconfirmed"))
            if (
                _profile_delete_outcome(lease) in {"pre-entry", "open", "entered", "uncertain"}
                and getattr(lease, "handle", None) is not None
            ):
                _retain_profile_delete_lease(lease)
                delete_remains_retryable = True

    if lease is not None and getattr(lease, "handle", None) is not None and not delete_remains_retryable:
        close_errors: list[BaseException] = []
        for _attempt in range(_PROFILE_CLEANUP_MAX_ATTEMPTS):
            try:
                lease.close()
            except BaseException as close_error:
                close_errors.append(close_error)
            if getattr(lease, "handle", None) is None:
                break
            if bool(getattr(lease, "_close_poisoned", False)):
                break
        if getattr(lease, "handle", None) is None:
            _release_retained_profile_delete_lease(lease)
            cleanup_errors.extend(error for error in close_errors if not isinstance(error, Exception))
        else:
            _retain_profile_delete_lease(lease)
            cleanup_errors.extend(close_errors)
            if not close_errors:
                cleanup_errors.append(RuntimeError("profile mutation handle remained open after cleanup"))
    if lease is not None and getattr(lease, "handle", None) is not None:
        lease._lease_state = "retained"


def _arm_profile_terminal_cleanup_locked(
    lease: _VerifiedProfileDeleteHandle,
    attempt: _ProfileNativeAttempt,
) -> None:
    if lease._owner.attempt is not attempt:
        raise RuntimeError("profile terminal cleanup cannot arm a replaced attempt")
    lease._owner.terminal_cleanup_token = attempt.token
    lease._owner.claim = _ProfileOwnerClaim.RETAINED
    lease._owner.claimant = None
    _PROFILE_OWNER_REGISTRY_CHANGED.notify_all()


def _launch_profile_terminal_cleanup(
    lease: _VerifiedProfileDeleteHandle,
    attempt: _ProfileNativeAttempt,
) -> None:
    callback = threading.Thread(
        target=_run_profile_terminal_cleanup,
        args=(lease, attempt),
        daemon=True,
    )
    try:
        callback.start()
    except BaseException as callback_error:
        with _PROFILE_OWNER_REGISTRY_CHANGED:
            if lease._owner.error is None:
                lease._owner.error = RuntimeError(
                    f"profile terminal cleanup callback failed to start: {callback_error}"
                )
            _PROFILE_OWNER_REGISTRY_CHANGED.notify_all()


def _run_profile_terminal_cleanup(
    lease: _VerifiedProfileDeleteHandle,
    attempt: _ProfileNativeAttempt,
) -> None:
    attempt.worker.join()
    with _PROFILE_OWNER_REGISTRY_CHANGED:
        owner = lease._owner
        if owner.terminal_cleanup_token is not attempt.token:
            return
        owner.terminal_cleanup_token = None
        if owner.state is _ProfileNativeState.CLOSED or (
            owner.state is _ProfileNativeState.FAILED and owner.handle is None
        ):
            _retire_profile_delete_lease_locked(lease)
            return
        if owner.state is not _ProfileNativeState.OPEN:
            _PROFILE_OWNER_REGISTRY_CHANGED.notify_all()
            return
        owner.claim = _ProfileOwnerClaim.RETAINED
        owner.claimant = None
        delete_created = owner.cleanup_delete_requested
        _PROFILE_OWNER_REGISTRY_CHANGED.notify_all()
    cleanup_errors: list[BaseException] = []
    _finish_verified_profile_lease_cleanup(
        lease,
        delete_created=delete_created,
        cleanup_errors=cleanup_errors,
    )


def _drain_retained_profile_delete_leases(
    *,
    exclude: _VerifiedProfileDeleteHandle | None = None,
) -> None:
    errors: list[str] = []
    control_errors: list[BaseException] = []
    cleanup_candidates: list[_VerifiedProfileDeleteHandle] = []
    pending_attempts: list[tuple[_VerifiedProfileDeleteHandle, _ProfileNativeAttempt]] = []
    retained_count = 0
    with _PROFILE_OWNER_REGISTRY_CHANGED:
        _retire_closed_profile_leases_locked()
        for lease in tuple(_RETAINED_PROFILE_DELETE_LEASES):
            if lease is exclude:
                continue
            if _is_synchronized_profile_lease(lease):
                owner = lease._owner
                if owner.claim is not _ProfileOwnerClaim.RETAINED:
                    continue
                retained_count += 1
                if owner.state is _ProfileNativeState.FAILED and owner.handle is None:
                    _retire_profile_delete_lease_locked(lease)
                    continue
                if len(cleanup_candidates) + len(pending_attempts) >= _PROFILE_RETAINED_DRAIN_CAP:
                    continue
                if owner.state in {_ProfileNativeState.PENDING, _ProfileNativeState.ENTERED}:
                    attempt = owner.attempt
                    if attempt is None:
                        errors.append("profile transitional owner has no immutable attempt")
                        continue
                    if (
                        owner.state is _ProfileNativeState.PENDING
                        and owner.handle is None
                        and attempt.worker.ident is None
                        and not attempt.started.is_set()
                        and not attempt.done.is_set()
                    ):
                        _retire_profile_delete_lease_locked(lease)
                        continue
                    _arm_profile_terminal_cleanup_locked(lease, attempt)
                    pending_attempts.append((lease, attempt))
                elif owner.state is _ProfileNativeState.OPEN:
                    cleanup_candidates.append(lease)
                elif owner.state is _ProfileNativeState.UNCERTAIN:
                    errors.append("profile native owner outcome is uncertain")
                continue
            if getattr(lease, "_lease_state", "retained") in {"active", "cleanup", "pending"}:
                continue
            retained_count += 1
            if len(cleanup_candidates) < _PROFILE_RETAINED_DRAIN_CAP:
                cleanup_candidates.append(lease)
        _PROFILE_OWNER_REGISTRY_CHANGED.notify_all()

    incomplete = False
    for lease, attempt in pending_attempts:
        try:
            _reconcile_profile_native_attempt(lease, attempt)
        except BaseException as pending_error:
            incomplete = True
            detail = (
                f"profile cleanup incomplete while exact native worker is running: {_exception_detail(pending_error)}"
            )
            if isinstance(pending_error, Exception):
                errors.append(detail)
            else:
                control_errors.append(pending_error)
            continue
        cleanup_candidates.append(lease)

    for lease in cleanup_candidates:
        lease_errors: list[BaseException] = []
        _finish_verified_profile_lease_cleanup(
            lease,
            delete_created=bool(getattr(lease, "_cleanup_delete_requested", False)),
            cleanup_errors=lease_errors,
        )

        control_errors.extend(error for error in lease_errors if not isinstance(error, Exception))
        with _PROFILE_OWNER_REGISTRY_CHANGED:
            remains_registered = _profile_lease_is_registered_locked(lease)
        if remains_registered:
            if lease_errors:
                errors.extend(_exception_detail(error) for error in lease_errors)
            else:
                errors.append("retained profile handle ownership remains unresolved")

    with _PROFILE_OWNER_REGISTRY_CHANGED:
        _retire_closed_profile_leases_locked()
        remaining = []
        for lease in _RETAINED_PROFILE_DELETE_LEASES:
            if lease is exclude:
                continue
            if _is_synchronized_profile_lease(lease):
                if lease._owner.claim in {
                    _ProfileOwnerClaim.RETAINED,
                    _ProfileOwnerClaim.CLAIMED,
                } and lease._owner.state in {
                    _ProfileNativeState.PENDING,
                    _ProfileNativeState.ENTERED,
                    _ProfileNativeState.OPEN,
                    _ProfileNativeState.UNCERTAIN,
                }:
                    remaining.append(lease)
            elif getattr(lease, "handle", None) is not None and getattr(lease, "_lease_state", "retained") not in {
                "active",
                "cleanup",
                "pending",
            }:
                remaining.append(lease)
    if retained_count > _PROFILE_RETAINED_DRAIN_CAP:
        errors.append("profile retained-owner drain cap exceeded")
    if control_errors:
        control_error = control_errors[0]
        details = "; ".join(errors)
        add_note = getattr(control_error, "add_note", None)
        if details and callable(add_note):
            add_note(f"profile retained-owner drain also reported: {details}")
        raise control_error
    if incomplete or remaining:
        details = "; ".join(errors) or "retained profile handle ownership remains unresolved"
        raise RuntimeError(details)


@contextmanager
def _verified_profile_delete_lease(
    path: Path,
    *,
    create_payload: bytes | None = None,
    delete_on_body_error: Callable[[], bool] | None = None,
) -> Iterator[_VerifiedProfileDeleteHandle]:
    lease: _VerifiedProfileDeleteHandle | None = None
    primary_error: BaseException | None = None
    cleanup_errors: list[BaseException] = []
    body_entered: list[bool] = []
    try:
        _drain_retained_profile_delete_leases()
        try:
            if _VerifiedProfileDeleteHandle is _VERIFIED_PROFILE_DELETE_HANDLE_TYPE:
                lease = object.__new__(_VERIFIED_PROFILE_DELETE_HANDLE_TYPE)
                lease._initialize(path, create=create_payload is not None)
                with _PROFILE_OWNER_REGISTRY_CHANGED:
                    if lease._owner.state is not _ProfileNativeState.OPEN:
                        raise RuntimeError("profile acquisition did not publish an open owner")
                    lease._owner.claim = _ProfileOwnerClaim.ACTIVE
                    _PROFILE_OWNER_REGISTRY_CHANGED.notify_all()
            else:
                lease = _VerifiedProfileDeleteHandle(path, create=create_payload is not None)
                lease._lease_state = "active"
            _retain_profile_delete_lease(lease)
            if create_payload is not None:
                lease.write_bytes(create_payload)
            lease.validate(expected_payload=create_payload)
            body_entered.append(True)
            yield lease
        except BaseException as exc:
            primary_error = exc
        finally:
            delete_created = _should_delete_profile_on_error(
                primary_error,
                create_payload,
                lease,
                body_entered,
                delete_on_body_error,
            )
            _finish_verified_profile_lease_cleanup(
                lease,
                delete_created=delete_created,
                cleanup_errors=cleanup_errors,
            )
    except BaseException as boundary_error:
        if primary_error is None:
            primary_error = boundary_error
        else:
            cleanup_errors.append(boundary_error)
        delete_created = _should_delete_profile_on_error(
            primary_error,
            create_payload,
            lease,
            body_entered,
            delete_on_body_error,
        )
        _finish_verified_profile_lease_cleanup(
            lease,
            delete_created=delete_created,
            cleanup_errors=cleanup_errors,
        )

    if lease is not None and not _is_synchronized_profile_lease(lease) and getattr(lease, "handle", None) is not None:
        lease._lease_state = "retained"

    try:
        _drain_retained_profile_delete_leases(exclude=lease)
    except BaseException as drain_error:
        cleanup_errors.append(drain_error)

    cancellation = next((error for error in cleanup_errors if not isinstance(error, Exception)), None)
    if primary_error is not None and not isinstance(primary_error, Exception):
        cancellation = primary_error
    if cancellation is not None:
        if primary_error is not None and primary_error is not cancellation:
            _add_exception_note(cancellation, f"profile mutation also failed: {_exception_detail(primary_error)}")
        for error in cleanup_errors:
            if error is not cancellation:
                _add_exception_note(cancellation, f"additional profile cleanup failure: {_exception_detail(error)}")
        raise cancellation
    if primary_error is not None:
        for error in cleanup_errors:
            _add_exception_note(primary_error, f"profile cleanup also failed: {_exception_detail(error)}")
        raise primary_error
    if cleanup_errors:
        details = "; ".join(_exception_detail(error) for error in cleanup_errors)
        raise RuntimeError(f"profile cleanup failed: {details}") from cleanup_errors[0]


def _delete_profile_file_by_handle(path: Path) -> None:
    """Delete only the exact regular single-link object held from validation to disposition."""
    with _verified_profile_delete_lease(path) as lease:
        lease.mark_delete()
    if path.exists():
        raise RuntimeError("profile delete disposition completed but the path still exists")


def _enumerate_system_profiles(device_name: str | None) -> tuple[str, ...]:
    """Return closed Windows enumeration evidence or raise on uncertainty."""
    if not MSCMS_AVAILABLE or mscms is None:
        raise RuntimeError("Windows color profile enumeration is unavailable")
    if device_name is not None and (type(device_name) is not str or not device_name.strip()):
        raise ValueError("device_name must be a non-empty exact string")

    record = _ENUMTYPEW()
    record.dwSize = ctypes.sizeof(record)
    record.dwVersion = ENUM_TYPE_VERSION
    record.dwFields = ET_DEVICENAME if device_name is not None else 0
    record.pDeviceName = device_name

    size = wintypes.DWORD()
    if not mscms.WcsEnumColorProfilesSize(
        WCS_PROFILE_MANAGEMENT_SCOPE_SYSTEM_WIDE,
        ctypes.byref(record),
        ctypes.byref(size),
    ):
        raise RuntimeError("Windows color profile enumeration size query failed")
    if size.value == 0:
        return ()
    wchar_size = ctypes.sizeof(ctypes.c_wchar)
    if size.value < 2 * wchar_size or size.value > _MAX_PROFILE_ENUMERATION_BYTES or size.value % wchar_size != 0:
        raise RuntimeError("Windows color profile enumeration returned an invalid buffer size")

    buffer = (wintypes.BYTE * size.value)()
    count = wintypes.DWORD()
    if not mscms.WcsEnumColorProfiles(
        WCS_PROFILE_MANAGEMENT_SCOPE_SYSTEM_WIDE,
        ctypes.byref(record),
        buffer,
        size.value,
        ctypes.byref(count),
    ):
        raise RuntimeError("Windows color profile enumeration failed")
    try:
        decoded = bytes(buffer).decode("utf-16-le", errors="strict")
    except UnicodeError as exc:
        raise RuntimeError("Windows color profile enumeration returned invalid UTF-16 evidence") from exc
    if not decoded.endswith("\x00\x00"):
        raise RuntimeError("Windows color profile enumeration returned an unterminated MULTI_SZ")
    names = tuple(decoded[:-2].split("\x00")) if decoded[:-2] else ()
    if any(not name for name in names) or len(names) != count.value:
        raise RuntimeError("Windows color profile enumeration count did not match its MULTI_SZ evidence")
    return names


def is_profile_installed(profile_name: str) -> bool:
    """Return whether Windows' system-wide profile enumeration names the profile."""
    if not _is_exact_profile_basename(profile_name):
        raise ValueError("profile_name must be an exact basename")
    expected = profile_name.casefold()
    return any(name.casefold() == expected for name in _enumerate_system_profiles(None))


def is_profile_associated_with_display(profile_name: str, device_name: str) -> bool:
    """Return whether Windows enumerates the profile for the exact system display."""
    if not _is_exact_profile_basename(profile_name):
        raise ValueError("profile_name must be an exact basename")
    expected = profile_name.casefold()
    return any(name.casefold() == expected for name in _enumerate_system_profiles(device_name))


def get_default_profile_for_display(device_name: str) -> str:
    """Return the exact persistent system-wide WCS default profile basename or raise."""
    device_name = _require_exact_device_name(device_name)
    if not MSCMS_AVAILABLE or mscms is None:
        raise RuntimeError("Windows color management default-profile API is unavailable")
    get_size = getattr(mscms, "WcsGetDefaultColorProfileSize", None)
    if not callable(get_size):
        raise RuntimeError("Windows color management default-profile size API is unavailable")

    size = wintypes.DWORD()
    try:
        size_result = get_size(
            WCS_PROFILE_MANAGEMENT_SCOPE_SYSTEM_WIDE,
            device_name,
            CPT_ICC,
            CPST_NONE,
            0,
            ctypes.byref(size),
        )
    except Exception as exc:
        raise RuntimeError(f"Windows default color profile size query failed: {exc}") from exc
    if not size_result:
        raise RuntimeError("Windows default color profile size query failed")
    wchar_size = ctypes.sizeof(ctypes.c_wchar)
    if size.value < wchar_size or size.value > _MAX_PROFILE_NAME_BYTES or size.value % wchar_size != 0:
        raise RuntimeError("Windows default color profile returned an invalid buffer size")

    buffer = ctypes.create_unicode_buffer(size.value // wchar_size)
    try:
        get_result = mscms.WcsGetDefaultColorProfile(
            WCS_PROFILE_MANAGEMENT_SCOPE_SYSTEM_WIDE,
            device_name,
            CPT_ICC,
            CPST_NONE,
            0,
            size.value,
            buffer,
        )
    except Exception as exc:
        raise RuntimeError(f"Windows default color profile query failed: {exc}") from exc
    if not get_result:
        raise RuntimeError("Windows default color profile query failed")
    profile_name = buffer.value
    if not _is_exact_profile_basename(profile_name):
        raise RuntimeError("Windows default color profile was not an exact non-empty basename")
    return profile_name


def set_default_profile_for_display(profile_name: str, device_name: str) -> tuple[bool, str]:
    """Persist and read back the system-wide WCS default ICC profile for a display."""
    if not _is_exact_profile_basename(profile_name):
        raise ValueError("profile_name must be an exact Win32 basename")
    device_name = _require_exact_device_name(device_name)
    if not MSCMS_AVAILABLE or mscms is None:
        return False, "Windows color management default-profile API is unavailable"
    try:
        result = mscms.WcsSetDefaultColorProfile(
            WCS_PROFILE_MANAGEMENT_SCOPE_SYSTEM_WIDE,
            device_name,
            CPT_ICC,
            CPST_NONE,
            0,
            profile_name,
        )
    except Exception as exc:
        return False, f"Windows default color profile update failed: {exc}"
    if not result:
        return False, "Windows rejected the persistent default color profile update"
    try:
        selected = get_default_profile_for_display(device_name)
    except Exception as exc:
        return False, f"Default color profile changed but readback failed: {exc}"
    if selected.casefold() != profile_name.casefold():
        return False, f"Default color profile readback selected {selected!r}, not {profile_name!r}"
    return True, f"Persistent default color profile set to {profile_name} for {device_name}"


def uninstall_profile(profile_name: str) -> tuple[bool, str]:
    """
    Uninstall ICC profile from system.

    Args:
        profile_name: Profile filename (e.g., "calibration.icc")

    Returns:
        (success, message)
    """
    if not _is_exact_profile_basename(profile_name):
        return False, "Profile name must be an exact basename"
    if _is_transactional_profile_cache_name(profile_name):
        return (
            False,
            "Transactional product profile cache deletion requires a separately designed authoritative collector",
        )

    if not MSCMS_AVAILABLE or mscms is None:
        return False, "Windows color management profile uninstall API is unavailable"

    color_dir = get_profile_directory()
    profile_path = color_dir / profile_name
    if _path_resolves_to_transactional_profile_cache(profile_path):
        return (
            False,
            "Resolved transactional product profile cache deletion requires a separately designed authoritative collector",
        )

    if not profile_path.exists():
        return False, f"Profile not found: {profile_name}"

    # One delete-capable handle remains bound across unregister, revalidation,
    # disposition, and close, so a pathname replacement can never be deleted.
    registration_state = [_PROFILE_REGISTRATION_PRESENT]
    try:
        with _verified_profile_delete_lease(profile_path) as lease:
            lease._delete_on_body_error = lambda: registration_state[0] == _PROFILE_REGISTRATION_ABSENT
            try:
                _invoke_uninstall_color_profile(profile_path, registration_state)
            except BaseException as native_error:
                reconciled = _reconcile_profile_registration_after_native_error(
                    profile_name,
                    registration_state,
                    native_error,
                )
                if not isinstance(native_error, Exception) or not reconciled:
                    raise
            _reconcile_profile_registration_if_available(profile_name, registration_state)
            if registration_state[0] != _PROFILE_REGISTRATION_ABSENT:
                return False, "Windows color management still reports the profile as registered"
            lease.mark_delete()
    except PermissionError:
        return False, "Permission denied. Run as administrator."
    except Exception as e:
        return False, f"Failed to delete profile safely: {e}"

    if profile_path.exists():
        return False, "Profile was unregistered but the exact file disposition remains incomplete"
    return True, f"Profile uninstalled: {profile_name}"


# =============================================================================
# Profile Association
# =============================================================================


def associate_profile_with_display(profile_name: str, device_name: str, make_default: bool = True) -> tuple[bool, str]:
    """
    Associate ICC profile with a display.

    Args:
        profile_name: Profile filename
        device_name: Display device name (e.g., "\\\\.\\DISPLAY1")
        make_default: Set as default profile

    Returns:
        (success, message)
    """
    if not MSCMS_AVAILABLE:
        return False, "Color management API not available"
    if not _is_exact_profile_basename(profile_name):
        return False, "Profile name must be an exact Win32 basename"
    try:
        device_name = _require_exact_device_name(device_name)
    except ValueError as exc:
        return False, str(exc)
    if type(make_default) is not bool:
        return False, "make_default must be an exact boolean"

    color_dir = get_profile_directory()
    profile_path = color_dir / profile_name

    if not profile_path.exists():
        return False, f"Profile not found: {profile_name}"

    try:
        # Associate profile with device
        result = mscms.WcsAssociateColorProfileWithDevice(
            WCS_PROFILE_MANAGEMENT_SCOPE_SYSTEM_WIDE,
            profile_name,
            device_name,
        )

        if not result:
            return False, "Failed to associate profile"

        if make_default:
            default_success, default_message = set_default_profile_for_display(profile_name, device_name)
            if not default_success:
                return False, default_message

        return True, f"Profile {profile_name} associated with {device_name}"

    except Exception as e:
        return False, f"Association error: {e}"


def disassociate_profile_from_display(profile_name: str, device_name: str) -> tuple[bool, str]:
    """
    Remove profile association from display.

    Args:
        profile_name: Profile filename
        device_name: Display device name

    Returns:
        (success, message)
    """
    if not MSCMS_AVAILABLE:
        return False, "Color management API not available"
    if not _is_exact_profile_basename(profile_name):
        return False, "Profile name must be an exact Win32 basename"
    try:
        device_name = _require_exact_device_name(device_name)
    except ValueError as exc:
        return False, str(exc)

    try:
        result = mscms.WcsDisassociateColorProfileFromDevice(
            WCS_PROFILE_MANAGEMENT_SCOPE_SYSTEM_WIDE,
            profile_name,
            device_name,
        )

        if result:
            return True, "Profile disassociated"
        else:
            return False, "Failed to disassociate profile"

    except Exception as e:
        return False, f"Error: {e}"


def get_display_profile(device_name: str) -> str | None:
    """
    Get the default profile for a display.

    Args:
        device_name: Display device name

    Returns:
        Profile filename or None
    """
    try:
        return get_default_profile_for_display(device_name)
    except Exception:
        pass

    return None


def get_associated_profiles(device_name: str) -> list[str]:
    """
    Get all profiles associated with a display.

    Args:
        device_name: Display device name

    Returns:
        List of profile filenames
    """
    profiles = []
    if winreg is None:
        return profiles

    # Read from registry
    try:
        key_path = r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\ICM\ProfileAssociations\Display"
        key_path += "\\" + device_name.replace("\\", "_")

        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_path) as key:
            i = 0
            while True:
                try:
                    name, value, _ = winreg.EnumValue(key, i)
                    if value:
                        profiles.append(value)
                    i += 1
                except OSError:
                    break

    except Exception:
        pass

    return profiles


# =============================================================================
# Profile Backup and Restore
# =============================================================================


@dataclass
class ProfileBackup:
    """Profile backup data."""

    timestamp: str
    profiles: dict[str, str]  # display_name -> profile_name
    profile_data: dict[str, bytes]  # profile_name -> bytes

    def to_dict(self) -> dict:
        """Convert to dictionary (profiles only, not bytes)."""
        return {"timestamp": self.timestamp, "profiles": self.profiles}


def backup_profiles(backup_dir: str | Path, include_data: bool = True) -> tuple[bool, str]:
    """
    Backup current display profile assignments.

    Args:
        backup_dir: Directory for backup
        include_data: Include profile files in backup

    Returns:
        (success, message)
    """
    backup_dir = Path(backup_dir)
    backup_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_name = f"profile_backup_{timestamp}"

    profiles = {}
    profile_data = {}

    # Get current assignments
    for display in enumerate_displays():
        profile = get_display_profile(display.device_name)
        if profile:
            profiles[display.device_name] = profile

            if include_data:
                color_dir = get_profile_directory()
                profile_path = color_dir / profile

                if profile_path.exists():
                    profile_data[profile] = profile_path.read_bytes()

    # Save backup
    backup_info = {"timestamp": timestamp, "profiles": profiles}

    info_path = backup_dir / f"{backup_name}.json"
    info_path.write_text(json.dumps(backup_info, indent=2))

    if include_data:
        data_dir = backup_dir / backup_name
        data_dir.mkdir(exist_ok=True)

        for name, data in profile_data.items():
            (data_dir / name).write_bytes(data)

    return True, f"Backup created: {backup_name}"


def restore_profiles(backup_path: str | Path, restore_data: bool = True) -> tuple[bool, str]:
    """
    Restore profile assignments from backup.

    Args:
        backup_path: Path to backup JSON file
        restore_data: Also restore profile files

    Returns:
        (success, message)
    """
    backup_path = Path(backup_path)

    if not backup_path.exists():
        return False, f"Backup not found: {backup_path}"

    try:
        backup_info = json.loads(backup_path.read_text())
    except Exception as e:
        return False, f"Cannot read backup: {e}"

    profiles = backup_info.get("profiles", {})
    backup_name = backup_path.stem
    data_dir = backup_path.parent / backup_name

    restored = 0
    errors = []

    for device_name, profile_name in profiles.items():
        # Restore profile file if needed
        if restore_data and data_dir.exists():
            profile_file = data_dir / profile_name
            if profile_file.exists():
                success, msg = install_profile(profile_file)
                if not success:
                    errors.append(msg)
                    continue

        # Associate profile
        success, msg = associate_profile_with_display(profile_name, device_name)
        if success:
            restored += 1
        else:
            errors.append(msg)

    if errors:
        return False, f"Restored {restored} profiles with errors: {'; '.join(errors)}"

    return True, f"Restored {restored} profile assignments"


def list_installed_profiles() -> list[str]:
    """
    List all installed ICC profiles.

    Returns:
        List of profile filenames
    """
    color_dir = get_profile_directory()

    profiles = []

    for ext in ["*.icc", "*.icm"]:
        profiles.extend([p.name for p in color_dir.glob(ext)])

    return sorted(profiles)


# =============================================================================
# Profile Loader (VCGT/Gamma Ramp)
# =============================================================================


def load_profile_vcgt(profile_path: str | Path, display_id: int = 0) -> tuple[bool, str]:
    """
    Load VCGT from profile and apply to display gamma ramp.

    Args:
        profile_path: Path to ICC profile
        display_id: Display index

    Returns:
        (success, message)
    """
    from calibrate_pro.profiles.vcgt import GammaRampController, extract_vcgt_from_profile

    vcgt = extract_vcgt_from_profile(profile_path)

    if vcgt is None:
        return False, "No VCGT tag in profile"

    controller = GammaRampController()

    if not controller.is_available:
        return False, "Gamma ramp controller not available"

    if controller.set_gamma_ramp(vcgt, display_id):
        return True, "VCGT applied to display"
    else:
        return False, "Failed to apply gamma ramp"


def reset_display_gamma(display_id: int = 0) -> tuple[bool, str]:
    """
    Reset display to linear gamma ramp.

    Args:
        display_id: Display index

    Returns:
        (success, message)
    """
    from calibrate_pro.profiles.vcgt import GammaRampController

    controller = GammaRampController()

    if not controller.is_available:
        return False, "Gamma ramp controller not available"

    if controller.reset_gamma_ramp(display_id):
        return True, "Display gamma reset to linear"
    else:
        return False, "Failed to reset gamma"


# =============================================================================
# Convenience Functions
# =============================================================================


def quick_calibrate_display(
    profile_path: str | Path, display_id: int = 0, make_default: bool = True, apply_vcgt: bool = True
) -> tuple[bool, str]:
    """
    Quick display calibration: install profile, set as default, apply VCGT.

    Args:
        profile_path: Path to ICC profile
        display_id: Display index
        make_default: Set as default profile
        apply_vcgt: Apply VCGT immediately

    Returns:
        (success, message)
    """
    messages = []

    # Get display device name
    displays = enumerate_displays()

    if display_id >= len(displays):
        return False, f"Display {display_id} not found"

    device = displays[display_id]

    # Install profile
    success, msg = install_profile(profile_path)
    messages.append(msg)

    if not success:
        return False, "; ".join(messages)

    # Get profile name
    profile_name = Path(profile_path).name

    # Associate with display
    if make_default:
        success, msg = associate_profile_with_display(profile_name, device.device_name, make_default=True)
        messages.append(msg)

    # Apply VCGT
    if apply_vcgt:
        success, msg = load_profile_vcgt(profile_path, display_id)
        messages.append(msg)

    return True, "; ".join(messages)


def get_display_calibration_status() -> list[dict]:
    """
    Get calibration status for all displays.

    Returns:
        List of display status dictionaries
    """
    status = []

    for display in enumerate_displays():
        info = get_monitor_info(display)

        entry = {
            "device_name": display.device_name,
            "display_name": display.device_string,
            "monitor_name": display.monitor_name,
            "is_primary": display.is_primary,
            "resolution": info.resolution,
            "refresh_rate": info.refresh_rate,
            "current_profile": info.current_profile,
            "calibrated": info.current_profile is not None,
            "hdr_supported": info.hdr_supported,
        }

        status.append(entry)

    return status
