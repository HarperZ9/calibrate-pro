"""Durable diagnostic journal boundary for the functional-recovery layer."""

from __future__ import annotations

import ctypes
import errno
import getpass
import hashlib
import hmac
import json
import math
import ntpath
import os
import posixpath
import re
import secrets
import stat
import threading
import time
import zipfile
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from ctypes import wintypes
from dataclasses import dataclass, replace
from dataclasses import fields as dataclass_fields
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Literal, NoReturn, Protocol

if TYPE_CHECKING:
    import fcntl as _fcntl
    import msvcrt as _msvcrt
else:
    try:  # Windows product path; imported conservatively elsewhere.
        import msvcrt as _msvcrt
    except ImportError:  # pragma: no cover - exercised by non-Windows CI.
        _msvcrt = None

    try:  # Optional parity for development and CI hosts.
        import fcntl as _fcntl
    except ImportError:  # pragma: no cover - exercised on Windows.
        _fcntl = None

if TYPE_CHECKING:
    from calibrate_pro.application.outcomes import ActionError as ActionErrorOutcome
    from calibrate_pro.application.outcomes import ActionOutcome
    from calibrate_pro.application.outcomes import ActionSuccess as ActionSuccessOutcome
    from calibrate_pro.workflow import WorkflowStage


DIAGNOSTIC_JOURNAL_MAX_BYTES = 1_048_576
DIAGNOSTIC_RECEIPT_RECORD_MAX_BYTES = 65_536
DIAGNOSTIC_ARCHIVE_BASENAMES = tuple(
    f"diagnostics.{generation}.jsonl" for generation in range(1, 6)
)
_DIAGNOSTIC_BUNDLE_BASENAMES = tuple(
    sorted(("diagnostics.jsonl", *DIAGNOSTIC_ARCHIVE_BASENAMES))
)

_JOURNAL_LOCK = threading.RLock()
_PRIVATE_SALT_LOCK = threading.RLock()
_ROOT_COORDINATORS_LOCK = threading.RLock()
_ROOT_LOCK_BASENAME = ".diagnostics.lock"
_ROOT_LOCK_TIMEOUT_SECONDS = 1.0
_RESERVATION_STAGE_BYTES = DIAGNOSTIC_JOURNAL_MAX_BYTES
_MAX_LIVE_RESERVATIONS = 8
_MAX_RESERVATION_IDENTITY_BYTES = 512
_MAX_TERMINAL_RESERVATION_KEYS = 1_024
_RESERVATION_RE = re.compile(r"\.diagnostics\.reserve\.[0-9a-f]{32}\.tmp\Z")
_ZERO_CHUNK = bytes(65_536)
_APPEND_TEMP_BASENAME = ".diagnostics.append.tmp"
_ROTATION_TEMP_BASENAMES = tuple(
    f".diagnostics.rotate.{generation}.tmp" for generation in range(6)
)
_BUNDLE_TEMP_RE = re.compile(
    r"\.calibrate-pro-diagnostic-bundle\.(?P<pid>[1-9][0-9]{0,19})\."
    r"[0-9a-f]{32}\.tmp\Z"
)
_BUNDLE_TOKEN_RE = re.compile(r"[A-Za-z0-9_-]{1,256}\Z")

REDACTION_MARKER = "[REDACTED]"
REDACTED_PATH_MARKER = "[REDACTED_PATH]"
REDACTED_DEVICE_MARKER = "[REDACTED_DEVICE]"
INVALID_UTF8_REDACTION_MARKER = "[REDACTED_INVALID_UTF8]"

_CANONICAL_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
_SAFE_MARKER_BASENAME_PATTERN = r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}"
_RECOGNIZED_REDACTION_MARKER_RE = re.compile(
    rf"\[REDACTED(?:_PATH(?::{_SAFE_MARKER_BASENAME_PATTERN})?"
    r"|_DEVICE|_INVALID_UTF8)?\]"
)
_DYNAMIC_PATH_MARKER_RE = re.compile(
    r"\[REDACTED_PATH:(?P<basename>[^\]\r\n]*)\]"
)

_PRIVATE_KEY_RE = re.compile(
    r"-----BEGIN [^-\r\n]*PRIVATE KEY-----.*?-----END [^-\r\n]*PRIVATE KEY-----",
    re.IGNORECASE | re.DOTALL,
)
_BEARER_RE = re.compile(r"\bBearer\s+[^\s;,]+", re.IGNORECASE)
_SYNTHETIC_TOKEN_RE = re.compile(
    r"(?<!\w)(?:sk-[A-Za-z0-9_-]{12,}|gh[pousr]_[A-Za-z0-9]{12,}|"
    r"xox[baprs]-[A-Za-z0-9-]{12,}|AKIA[A-Z0-9]{12,}|"
    r"eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,})(?!\w)",
    re.IGNORECASE,
)
_CREDENTIAL_KEY_PATTERN = (
    r"password|passwd|api[ _-]?key|access[ _-]?token|"
    r"confirmation[ _-]?token|token|secret"
)
_CREDENTIAL_RE = re.compile(
    rf"(?P<prefix>(?:(?P<key_quote>[\"'])(?:{_CREDENTIAL_KEY_PATTERN})"
    rf"(?P=key_quote)|(?:{_CREDENTIAL_KEY_PATTERN}))\s*[:=]\s*)"
    r"(?:(?P<double_quote>\")(?P<double_value>(?:\\[^\r\n]|[^\"\\\r\n])*)\""
    r"|(?P<single_quote>')(?P<single_value>(?:\\[^\r\n]|[^'\\\r\n])*)'"
    r"|(?P<unquoted_value>[^;,\r\n]+))",
    re.IGNORECASE,
)
_EDID_RE = re.compile(
    r"\b(?P<key>raw[ _-]?edid|edid(?:[ _-]?(?:hex|blob))?)\s*[:=]\s*[^;,\r\n]+",
    re.IGNORECASE,
)
_SERIAL_RE = re.compile(
    r"\b(?P<key>device[ _-]?serial|serial(?:[ _-]?number)?)\s*[:=]\s*[^;,\r\n]+",
    re.IGNORECASE,
)
_DEVICE_PATH_RE = re.compile(
    r"(?:(?:\\\\[?.]\\)?(?:DISPLAY|MONITOR|USB|HID))[#\\][^\s;,\"']+",
    re.IGNORECASE,
)
_LABELED_DEVICE_INSTANCE_RE = re.compile(
    r"\b(?P<label>pnp(?:[ _-]?(?:instance|path|id))?"
    r"|device(?:[ _-]?(?:instance|path|id))?)"
    r"(?P<separator>\s*[:=]\s*)[^;,\r\n]+",
    re.IGNORECASE,
)
_LABELED_ABSOLUTE_PATH_RE = re.compile(
    r"\b(?P<label>path|unc|root|home|file|folder|directory|export)"
    r"(?P<separator>\s*[:=]\s*)"
    r"(?P<path>(?:[A-Za-z]:[\\/]|\\\\|/)[^;,\r\n]+)",
    re.IGNORECASE,
)
_QUOTED_ABSOLUTE_PATH_RE = re.compile(
    r"(?P<quote>[\"'])(?P<path>(?:[A-Za-z]:[\\/]|\\\\|/)[^\"']+)(?P=quote)",
)
_WINDOWS_ABSOLUTE_PATH_RE = re.compile(
    r"(?<![\w])(?:[A-Za-z]:[\\/])[^\s;,\"'<>|]+",
)
_POSIX_ABSOLUTE_PATH_RE = re.compile(
    r"(?<![\w])/(?:[^\s;,\"'/]+/)*[^\s;,\"'/]+",
)

_EXACT_STRING_FIELDS = (
    "timestamp_utc",
    "correlation_id",
    "product_version",
    "runtime_mode",
    "platform_version",
    "action_id",
    "workflow_stage",
    "outcome",
)
_OPTIONAL_STRING_FIELDS = (
    "exception_type",
    "error_code",
    "technical_category",
    "redacted_message",
    "display_pseudonym",
    "plan_sha256",
    "recovery_guarantee",
    "export_basename",
    "export_sha256",
)
_PAIR_TUPLE_FIELDS = ("capability_flags", "apply_phase_flags")
_DISPLAY_PSEUDONYM_DOMAIN = b"calibrate-pro/display-pseudonym/v1\0"
_PRIVATE_SALT_BYTES = 32

_TOKEN_QUERY = 0x0008
_TOKEN_USER_CLASS = 1
_SDDL_REVISION_1 = 1
_OWNER_SECURITY_INFORMATION = 0x00000001
_DACL_SECURITY_INFORMATION = 0x00000004
_SE_FILE_OBJECT = 1
_GENERIC_READ = 0x80000000
_GENERIC_WRITE = 0x40000000
_READ_CONTROL = 0x00020000
_CREATE_NEW = 1
_OPEN_EXISTING = 3
_FILE_ATTRIBUTE_DIRECTORY = 0x00000010
_FILE_ATTRIBUTE_HIDDEN = 0x00000002
_FILE_ATTRIBUTE_ARCHIVE = 0x00000020
_FILE_ATTRIBUTE_NOT_CONTENT_INDEXED = 0x00002000
_FILE_ATTRIBUTE_REPARSE_POINT = 0x00000400
_FILE_FLAG_OPEN_REPARSE_POINT = 0x00200000
_FILE_TYPE_DISK = 1
_ERROR_FILE_EXISTS = 80
_ERROR_ALREADY_EXISTS = 183
_ERROR_SHARING_VIOLATION = 32
_ERROR_LOCK_VIOLATION = 33
_ERROR_INVALID_PARAMETER = 87
_INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
_SYNCHRONIZE = 0x00100000
_WAIT_OBJECT_0 = 0x00000000
_PRIVATE_SALT_ALLOWED_FILE_ATTRIBUTES = (
    _FILE_ATTRIBUTE_HIDDEN
    | _FILE_ATTRIBUTE_ARCHIVE
    | _FILE_ATTRIBUTE_NOT_CONTENT_INDEXED
)


class _SecurityAttributes(ctypes.Structure):
    _fields_ = [
        ("nLength", wintypes.DWORD),
        ("lpSecurityDescriptor", ctypes.c_void_p),
        ("bInheritHandle", wintypes.BOOL),
    ]


class _SidAndAttributes(ctypes.Structure):
    _fields_ = [("Sid", ctypes.c_void_p), ("Attributes", wintypes.DWORD)]


class _TokenUser(ctypes.Structure):
    _fields_ = [("User", _SidAndAttributes)]


class _ByHandleFileInformation(ctypes.Structure):
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


@dataclass(frozen=True)
class _WindowsSaltFileMetadata:
    file_type: int
    file_attributes: int
    link_count: int
    byte_length: int
_OPTIONAL_SHA256_FIELDS = ("display_pseudonym", "plan_sha256", "export_sha256")


@dataclass(frozen=True)
class JournalRecord:
    timestamp_utc: str
    correlation_id: str
    product_version: str
    runtime_mode: Literal["source", "frozen", "fake_acceptance"]
    platform_version: str
    action_id: str
    workflow_stage: str
    capability_flags: tuple[tuple[str, bool], ...]
    outcome: Literal["success", "failure"]
    exception_type: str | None
    error_code: str | None
    technical_category: str | None
    redacted_message: str | None
    display_pseudonym: str | None
    plan_sha256: str | None
    asset_sha256: tuple[str, ...]
    apply_phase_flags: tuple[tuple[str, bool], ...]
    recovery_guarantee: str | None
    export_basename: str | None
    export_sha256: str | None


@dataclass(frozen=True, slots=True)
class BundleMemberPreview:
    basename: str
    byte_length: int
    sha256: str


@dataclass(frozen=True, slots=True)
class BundlePreview:
    token: str
    members: tuple[BundleMemberPreview, ...]
    expires_utc: str


@dataclass(frozen=True, slots=True)
class DiagnosticBundleReceipt:
    published_path: Path
    bundle_sha256: str
    byte_length: int
    member_hashes: tuple[tuple[str, str], ...]
    readback_verified: bool


class DiagnosticRedactor:
    """Deterministically remove sensitive scalar content before persistence."""

    def __init__(
        self,
        *,
        username: str | None = None,
        home: str | os.PathLike[str] | None = None,
        environment: Mapping[str, str] | None = None,
    ) -> None:
        resolved_username = getpass.getuser() if username is None else username
        resolved_home = os.path.expanduser("~") if home is None else os.fspath(home)
        resolved_environment = os.environ if environment is None else environment
        self._username = resolved_username.strip() if type(resolved_username) is str else ""
        identity_values = {
            value
            for value in (resolved_username, resolved_home)
            if type(value) is str and value.strip()
        }
        environment_values = {
            value
            for value in resolved_environment.values()
            if type(value) is str and self._is_meaningful_environment_value(value)
        }
        self._sensitive_values = tuple(
            sorted(
                identity_values | environment_values,
                key=len,
                reverse=True,
            )
        )
        sensitive_patterns = []
        for sensitive_value in self._sensitive_values:
            pattern = re.escape(sensitive_value)
            if sensitive_value == self._username:
                pattern = rf"(?<!\w){pattern}(?!\w)"
            sensitive_patterns.append(f"(?:{pattern})")
        self._sensitive_pattern: re.Pattern[str] | None = (
            re.compile("|".join(sensitive_patterns), re.IGNORECASE)
            if sensitive_patterns
            else None
        )

    @staticmethod
    def _is_meaningful_environment_value(value: str) -> bool:
        stripped = value.strip()
        return len(stripped) >= 8 and stripped.casefold() not in {
            "windows_nt",
            "true",
            "false",
        }

    def redact(self, value: str) -> str:
        """Return a redacted copy of one exact string scalar."""
        if type(value) is not str:
            raise TypeError("value must be an exact str")
        prepared = _DYNAMIC_PATH_MARKER_RE.sub(self._sanitize_path_marker, value)
        prepared = _CREDENTIAL_RE.sub(self._redact_credential, prepared)
        prepared = _LABELED_DEVICE_INSTANCE_RE.sub(
            self._redact_labeled_device,
            prepared,
        )
        prepared = _LABELED_ABSOLUTE_PATH_RE.sub(
            self._redact_labeled_path,
            prepared,
        )
        redacted_parts: list[str] = []
        position = 0
        for marker in _RECOGNIZED_REDACTION_MARKER_RE.finditer(prepared):
            redacted_parts.append(
                self._redact_unprotected(prepared[position : marker.start()])
            )
            redacted_parts.append(marker.group(0))
            position = marker.end()
        redacted_parts.append(self._redact_unprotected(prepared[position:]))
        return "".join(redacted_parts)

    def _redact_unprotected(self, value: str) -> str:
        if not value:
            return value
        stripped = value.strip()
        if re.match(r"^(?:[A-Za-z]:[\\/]|\\\\|/)", stripped):
            return self._path_marker(stripped)
        redacted = (
            self._sensitive_pattern.sub(REDACTION_MARKER, value)
            if self._sensitive_pattern is not None
            else value
        )
        redacted = _PRIVATE_KEY_RE.sub(REDACTION_MARKER, redacted)
        redacted = _BEARER_RE.sub(f"Bearer {REDACTION_MARKER}", redacted)
        redacted = _SYNTHETIC_TOKEN_RE.sub(REDACTION_MARKER, redacted)
        redacted = _EDID_RE.sub(
            lambda match: f"{match.group('key')}={REDACTION_MARKER}",
            redacted,
        )
        redacted = _SERIAL_RE.sub(
            lambda match: f"{match.group('key')}={REDACTION_MARKER}",
            redacted,
        )
        redacted = _DEVICE_PATH_RE.sub(REDACTED_DEVICE_MARKER, redacted)
        redacted = _QUOTED_ABSOLUTE_PATH_RE.sub(self._redact_quoted_path, redacted)
        redacted = _WINDOWS_ABSOLUTE_PATH_RE.sub(self._redact_path, redacted)
        redacted = _POSIX_ABSOLUTE_PATH_RE.sub(self._redact_path, redacted)
        return redacted

    def redact_bytes(self, value: bytes) -> bytes:
        """Redact UTF-8 bytes, replacing malformed input without retaining it."""
        if type(value) is not bytes:
            raise TypeError("value must be exact bytes")
        try:
            decoded = value.decode("utf-8", errors="strict")
        except UnicodeDecodeError:
            return INVALID_UTF8_REDACTION_MARKER.encode("utf-8")
        return self.redact(decoded).encode("utf-8")

    def _redact_quoted_path(self, match: re.Match[str]) -> str:
        return self._path_marker(match.group("path"))

    @staticmethod
    def _redact_credential(match: re.Match[str]) -> str:
        quote = '"' if match.group("double_quote") else "'" if match.group("single_quote") else ""
        return f"{match.group('prefix')}{quote}{REDACTION_MARKER}{quote}"

    @staticmethod
    def _redact_labeled_device(match: re.Match[str]) -> str:
        return (
            f"{match.group('label')}{match.group('separator')}"
            f"{REDACTED_DEVICE_MARKER}"
        )

    def _sanitize_path_marker(self, match: re.Match[str]) -> str:
        basename = match.group("basename")
        if (
            re.fullmatch(_SAFE_MARKER_BASENAME_PATTERN, basename) is None
            or self._redact_unprotected(basename) != basename
        ):
            return REDACTED_PATH_MARKER
        return match.group(0)

    def _redact_labeled_path(self, match: re.Match[str]) -> str:
        return (
            f"{match.group('label')}{match.group('separator')}"
            f"{self._path_marker(match.group('path').strip())}"
        )

    def _redact_path(self, match: re.Match[str]) -> str:
        return self._path_marker(match.group(0))

    def _path_marker(self, value: str) -> str:
        value = value.strip()
        basename = (
            ntpath.basename(value.rstrip("\\/"))
            if re.match(r"^(?:[A-Za-z]:[\\/]|\\\\)", value)
            else posixpath.basename(value.rstrip("/"))
        )
        if (
            not basename
            or basename in {".", ".."}
            or re.fullmatch(_SAFE_MARKER_BASENAME_PATTERN, basename) is None
            or any(
                sensitive.casefold() in basename.casefold()
                for sensitive in self._sensitive_values
            )
        ):
            return REDACTED_PATH_MARKER
        return f"[REDACTED_PATH:{basename}]"


class JournalSink(Protocol):
    def preflight(self, action_id: str, correlation_id: str) -> ActionOutcome[None]: ...

    def append_and_sync(self, record: JournalRecord) -> ActionOutcome[None]: ...


class CancellableJournalSink(Protocol):
    """Optional reservation cleanup capability for receipt-required actions."""

    def cancel_preflight(self, action_id: str, correlation_id: str) -> None: ...


class PrivateSaltStore(Protocol):
    """Capability that returns only security-verified private salt bytes."""

    def load_or_create_verified_salt(self) -> bytes | None: ...


class _WindowsPrivateSaltBackend(Protocol):
    def load_or_create_verified(
        self,
        path: Path,
        candidate_salt: bytes,
    ) -> bytes | None: ...


class WindowsPrivateSaltStore:
    """Fail-closed access to a current-user-only Windows salt file."""

    def __init__(
        self,
        path: Path | None = None,
        *,
        random_bytes: Callable[[int], bytes] = secrets.token_bytes,
        backend: _WindowsPrivateSaltBackend | None = None,
    ) -> None:
        resolved_path = resolve_private_salt_path() if path is None else Path(path)
        if not resolved_path.is_absolute():
            raise ValueError("private salt path must be absolute")
        self.path = resolved_path
        self._random_bytes = random_bytes
        self._backend = backend

    def load_or_create_verified_salt(self) -> bytes | None:
        try:
            candidate = self._random_bytes(_PRIVATE_SALT_BYTES)
        except Exception:
            return None
        if type(candidate) is not bytes or len(candidate) != _PRIVATE_SALT_BYTES:
            return None
        with _PRIVATE_SALT_LOCK:
            backend = self._backend
            if backend is None:
                if os.name != "nt":
                    return None
                try:
                    backend = _CtypesWindowsPrivateSaltBackend()
                except Exception:
                    return None
            try:
                salt = backend.load_or_create_verified(self.path, candidate)
            except Exception:
                return None
        if type(salt) is not bytes or len(salt) != _PRIVATE_SALT_BYTES:
            return None
        return salt


def _private_salt_descriptor_is_exact(actual_sddl: str, expected_sddl: str) -> bool:
    """Accept only the canonical protected single-current-user descriptor."""
    return type(actual_sddl) is str and type(expected_sddl) is str and actual_sddl == expected_sddl


def _private_salt_file_metadata_is_safe(metadata: _WindowsSaltFileMetadata) -> bool:
    return (
        type(metadata) is _WindowsSaltFileMetadata
        and metadata.file_type == _FILE_TYPE_DISK
        and metadata.file_attributes & ~_PRIVATE_SALT_ALLOWED_FILE_ATTRIBUTES == 0
        and metadata.link_count == 1
        and metadata.byte_length == _PRIVATE_SALT_BYTES
    )


def _wait_for_private_salt_handle(
    open_attempt: Callable[[], tuple[int | None, int]],
    *,
    monotonic: Callable[[], float],
    sleeper: Callable[[float], None],
    timeout_seconds: float,
    retry_interval_seconds: float,
) -> int | None:
    if (
        type(timeout_seconds) not in {int, float}
        or type(retry_interval_seconds) not in {int, float}
        or not math.isfinite(timeout_seconds)
        or not math.isfinite(retry_interval_seconds)
        or timeout_seconds <= 0
        or retry_interval_seconds <= 0
    ):
        return None
    try:
        deadline = monotonic() + timeout_seconds
        maximum_attempts = math.ceil(timeout_seconds / retry_interval_seconds) + 1
        for _attempt in range(maximum_attempts):
            handle, error = open_attempt()
            if handle is not None:
                return handle
            if error not in {_ERROR_SHARING_VIOLATION, _ERROR_LOCK_VIOLATION}:
                return None
            remaining = deadline - monotonic()
            if remaining <= 0:
                return None
            sleeper(min(retry_interval_seconds, remaining))
    except Exception:
        return None
    return None


class _CtypesWindowsPrivateSaltBackend:
    """Win32 implementation that verifies and reads through one exclusive handle."""

    def __init__(
        self,
        *,
        monotonic: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
        reopen_timeout_seconds: float = 2.0,
        retry_interval_seconds: float = 0.01,
    ) -> None:
        if os.name != "nt":
            raise OSError("Windows private salt APIs are unavailable")
        self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
        self._monotonic = monotonic
        self._sleeper = sleeper
        self._reopen_timeout_seconds = reopen_timeout_seconds
        self._retry_interval_seconds = retry_interval_seconds
        self._configure_signatures()

    def load_or_create_verified(self, path: Path, candidate_salt: bytes) -> bytes | None:
        if type(candidate_salt) is not bytes or len(candidate_salt) != _PRIVATE_SALT_BYTES:
            return None
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            current_sid = self._current_user_sid()
            requested_sddl = f"O:{current_sid}D:P(A;;FA;;;{current_sid})"
            security_descriptor = self._security_descriptor_from_sddl(requested_sddl)
            try:
                expected_sddl = self._security_descriptor_to_sddl(security_descriptor)
                self._create_if_absent(path, candidate_salt, security_descriptor)
            finally:
                self._local_free(security_descriptor)
            return self._open_verify_and_read(path, expected_sddl)
        except Exception:
            return None

    def _configure_signatures(self) -> None:
        handle_pointer = ctypes.POINTER(wintypes.HANDLE)
        void_pointer_pointer = ctypes.POINTER(ctypes.c_void_p)

        self._kernel32.GetCurrentProcess.argtypes = []
        self._kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        self._kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        self._kernel32.CloseHandle.restype = wintypes.BOOL
        self._kernel32.LocalFree.argtypes = [ctypes.c_void_p]
        self._kernel32.LocalFree.restype = ctypes.c_void_p
        self._kernel32.CreateFileW.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            ctypes.POINTER(_SecurityAttributes),
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.HANDLE,
        ]
        self._kernel32.CreateFileW.restype = wintypes.HANDLE
        self._kernel32.WriteFile.argtypes = [
            wintypes.HANDLE,
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
            ctypes.c_void_p,
        ]
        self._kernel32.WriteFile.restype = wintypes.BOOL
        self._kernel32.ReadFile.argtypes = [
            wintypes.HANDLE,
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
            ctypes.c_void_p,
        ]
        self._kernel32.ReadFile.restype = wintypes.BOOL
        self._kernel32.FlushFileBuffers.argtypes = [wintypes.HANDLE]
        self._kernel32.FlushFileBuffers.restype = wintypes.BOOL
        self._kernel32.GetFileType.argtypes = [wintypes.HANDLE]
        self._kernel32.GetFileType.restype = wintypes.DWORD
        self._kernel32.GetFileInformationByHandle.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(_ByHandleFileInformation),
        ]
        self._kernel32.GetFileInformationByHandle.restype = wintypes.BOOL
        self._kernel32.DeleteFileW.argtypes = [wintypes.LPCWSTR]
        self._kernel32.DeleteFileW.restype = wintypes.BOOL

        self._advapi32.OpenProcessToken.argtypes = [
            wintypes.HANDLE,
            wintypes.DWORD,
            handle_pointer,
        ]
        self._advapi32.OpenProcessToken.restype = wintypes.BOOL
        self._advapi32.GetTokenInformation.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
        ]
        self._advapi32.GetTokenInformation.restype = wintypes.BOOL
        self._advapi32.ConvertSidToStringSidW.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(wintypes.LPWSTR),
        ]
        self._advapi32.ConvertSidToStringSidW.restype = wintypes.BOOL
        self._advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            void_pointer_pointer,
            ctypes.POINTER(wintypes.DWORD),
        ]
        self._advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW.restype = (
            wintypes.BOOL
        )
        self._advapi32.ConvertSecurityDescriptorToStringSecurityDescriptorW.argtypes = [
            ctypes.c_void_p,
            wintypes.DWORD,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.LPWSTR),
            ctypes.POINTER(wintypes.DWORD),
        ]
        self._advapi32.ConvertSecurityDescriptorToStringSecurityDescriptorW.restype = (
            wintypes.BOOL
        )
        self._advapi32.GetSecurityInfo.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            wintypes.DWORD,
            void_pointer_pointer,
            void_pointer_pointer,
            void_pointer_pointer,
            void_pointer_pointer,
            void_pointer_pointer,
        ]
        self._advapi32.GetSecurityInfo.restype = wintypes.DWORD

    def _current_user_sid(self) -> str:
        token = wintypes.HANDLE()
        if not self._advapi32.OpenProcessToken(
            self._kernel32.GetCurrentProcess(),
            _TOKEN_QUERY,
            ctypes.byref(token),
        ):
            raise OSError("Windows token query failed")
        try:
            required = wintypes.DWORD()
            self._advapi32.GetTokenInformation(
                token,
                _TOKEN_USER_CLASS,
                None,
                0,
                ctypes.byref(required),
            )
            if required.value == 0:
                raise OSError("Windows token identity size query failed")
            buffer = ctypes.create_string_buffer(required.value)
            if not self._advapi32.GetTokenInformation(
                token,
                _TOKEN_USER_CLASS,
                buffer,
                required.value,
                ctypes.byref(required),
            ):
                raise OSError("Windows token identity query failed")
            token_user = ctypes.cast(buffer, ctypes.POINTER(_TokenUser)).contents
            string_pointer = wintypes.LPWSTR()
            if not self._advapi32.ConvertSidToStringSidW(
                token_user.User.Sid,
                ctypes.byref(string_pointer),
            ):
                raise OSError("Windows SID conversion failed")
            try:
                value = string_pointer.value
                if not value:
                    raise OSError("Windows SID conversion was inconclusive")
                return value
            finally:
                self._local_free(ctypes.cast(string_pointer, ctypes.c_void_p))
        finally:
            self._kernel32.CloseHandle(token)

    def _security_descriptor_from_sddl(self, sddl: str) -> ctypes.c_void_p:
        descriptor = ctypes.c_void_p()
        if not self._advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW(
            sddl,
            _SDDL_REVISION_1,
            ctypes.byref(descriptor),
            None,
        ):
            raise OSError("Windows private descriptor creation failed")
        if not descriptor.value:
            raise OSError("Windows private descriptor creation was inconclusive")
        return descriptor

    def _security_descriptor_to_sddl(self, descriptor: ctypes.c_void_p) -> str:
        string_pointer = wintypes.LPWSTR()
        if not self._advapi32.ConvertSecurityDescriptorToStringSecurityDescriptorW(
            descriptor,
            _SDDL_REVISION_1,
            _OWNER_SECURITY_INFORMATION | _DACL_SECURITY_INFORMATION,
            ctypes.byref(string_pointer),
            None,
        ):
            raise OSError("Windows private descriptor verification failed")
        try:
            value = string_pointer.value
            if not value:
                raise OSError("Windows private descriptor verification was inconclusive")
            return value
        finally:
            self._local_free(ctypes.cast(string_pointer, ctypes.c_void_p))

    def _create_if_absent(
        self,
        path: Path,
        candidate_salt: bytes,
        security_descriptor: ctypes.c_void_p,
    ) -> None:
        security_attributes = _SecurityAttributes(
            nLength=ctypes.sizeof(_SecurityAttributes),
            lpSecurityDescriptor=security_descriptor,
            bInheritHandle=False,
        )
        handle = self._kernel32.CreateFileW(
            os.fspath(path),
            _GENERIC_READ | _GENERIC_WRITE | _READ_CONTROL,
            0,
            ctypes.byref(security_attributes),
            _CREATE_NEW,
            _FILE_ATTRIBUTE_HIDDEN
            | _FILE_ATTRIBUTE_NOT_CONTENT_INDEXED
            | _FILE_FLAG_OPEN_REPARSE_POINT,
            None,
        )
        if self._is_invalid_handle(handle):
            error = ctypes.get_last_error()
            if error in {_ERROR_FILE_EXISTS, _ERROR_ALREADY_EXISTS}:
                return
            raise OSError("Windows private salt creation failed")
        completed = False
        try:
            buffer = ctypes.create_string_buffer(candidate_salt, _PRIVATE_SALT_BYTES)
            written = wintypes.DWORD()
            if not self._kernel32.WriteFile(
                handle,
                buffer,
                _PRIVATE_SALT_BYTES,
                ctypes.byref(written),
                None,
            ) or written.value != _PRIVATE_SALT_BYTES:
                raise OSError("Windows private salt write failed")
            if not self._kernel32.FlushFileBuffers(handle):
                raise OSError("Windows private salt synchronization failed")
            completed = True
        finally:
            self._kernel32.CloseHandle(handle)
            if not completed:
                self._kernel32.DeleteFileW(os.fspath(path))

    def _open_verify_and_read(self, path: Path, expected_sddl: str) -> bytes | None:
        def open_attempt() -> tuple[int | None, int]:
            candidate_handle = self._kernel32.CreateFileW(
                os.fspath(path),
                _GENERIC_READ | _READ_CONTROL,
                0,
                None,
                _OPEN_EXISTING,
                _FILE_FLAG_OPEN_REPARSE_POINT,
                None,
            )
            if self._is_invalid_handle(candidate_handle):
                return None, ctypes.get_last_error()
            return candidate_handle, 0

        handle = _wait_for_private_salt_handle(
            open_attempt,
            monotonic=self._monotonic,
            sleeper=self._sleeper,
            timeout_seconds=self._reopen_timeout_seconds,
            retry_interval_seconds=self._retry_interval_seconds,
        )
        if handle is None:
            return None
        try:
            metadata = self._file_metadata(handle)
            if not _private_salt_file_metadata_is_safe(metadata):
                return None
            actual_sddl = self._security_sddl_for_handle(handle)
            if not _private_salt_descriptor_is_exact(actual_sddl, expected_sddl):
                return None
            buffer = ctypes.create_string_buffer(_PRIVATE_SALT_BYTES)
            read = wintypes.DWORD()
            if not self._kernel32.ReadFile(
                handle,
                buffer,
                _PRIVATE_SALT_BYTES,
                ctypes.byref(read),
                None,
            ) or read.value != _PRIVATE_SALT_BYTES:
                return None
            return bytes(buffer.raw[:_PRIVATE_SALT_BYTES])
        finally:
            self._kernel32.CloseHandle(handle)

    def _file_metadata(self, handle: int) -> _WindowsSaltFileMetadata:
        file_type = int(self._kernel32.GetFileType(handle))
        information = _ByHandleFileInformation()
        if not self._kernel32.GetFileInformationByHandle(
            handle,
            ctypes.byref(information),
        ):
            raise OSError("Windows private salt metadata query failed")
        return _WindowsSaltFileMetadata(
            file_type=file_type,
            file_attributes=int(information.dwFileAttributes),
            link_count=int(information.nNumberOfLinks),
            byte_length=(int(information.nFileSizeHigh) << 32)
            | int(information.nFileSizeLow),
        )

    def _security_sddl_for_handle(self, handle: int) -> str:
        descriptor = ctypes.c_void_p()
        status = self._advapi32.GetSecurityInfo(
            handle,
            _SE_FILE_OBJECT,
            _OWNER_SECURITY_INFORMATION | _DACL_SECURITY_INFORMATION,
            None,
            None,
            None,
            None,
            ctypes.byref(descriptor),
        )
        if status != 0 or not descriptor.value:
            raise OSError("Windows private salt security query failed")
        try:
            return self._security_descriptor_to_sddl(descriptor)
        finally:
            self._local_free(descriptor)

    def _local_free(self, value: ctypes.c_void_p) -> None:
        if value and value.value:
            self._kernel32.LocalFree(value)

    @staticmethod
    def _is_invalid_handle(handle: int | None) -> bool:
        return handle is None or handle == _INVALID_HANDLE_VALUE


class DisplayPseudonymizer:
    """Derive non-reversible per-install display identifiers in memory."""

    def __init__(self, salt_store: PrivateSaltStore | None) -> None:
        self._salt_store = salt_store

    @classmethod
    def for_current_user(cls) -> DisplayPseudonymizer:
        store = WindowsPrivateSaltStore() if os.name == "nt" else None
        return cls(store)

    def pseudonymize(self, raw_identifier: str) -> str | None:
        if type(raw_identifier) is not str:
            raise TypeError("raw_identifier must be an exact str")
        if not raw_identifier.strip():
            return None
        try:
            identifier_bytes = raw_identifier.encode("utf-8", errors="strict")
        except UnicodeEncodeError:
            return None
        if self._salt_store is None:
            return None
        try:
            salt = self._salt_store.load_or_create_verified_salt()
        except Exception:
            return None
        if type(salt) is not bytes or len(salt) != _PRIVATE_SALT_BYTES:
            return None
        return hmac.new(
            salt,
            _DISPLAY_PSEUDONYM_DOMAIN + identifier_bytes,
            hashlib.sha256,
        ).hexdigest()


def resolve_diagnostic_root() -> Path:
    """Resolve the production journal root without a working-directory fallback."""
    value = os.environ.get("LOCALAPPDATA")
    if value is None or not value.strip():
        raise ValueError("LOCALAPPDATA must be a non-empty absolute path")
    root = Path(value)
    if not root.is_absolute():
        raise ValueError("LOCALAPPDATA must be a non-empty absolute path")
    return root / "Build Universe" / "Calibrate Pro" / "Diagnostics"


def resolve_private_salt_path() -> Path:
    """Resolve private pseudonym state outside the diagnostics inventory."""
    return resolve_diagnostic_root().parent / "Private" / "display-pseudonym.salt"


@dataclass(slots=True)
class _JournalReservation:
    action_id: str
    correlation_id: str
    path: Path
    file_descriptor: int


class _RootCoordinator:
    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.reservations: dict[tuple[str, str], _JournalReservation] = {}
        self.terminal_keys: dict[tuple[str, str], None] = {}

    def mark_terminal(self, key: tuple[str, str]) -> None:
        self.terminal_keys[key] = None
        while len(self.terminal_keys) > _MAX_TERMINAL_RESERVATION_KEYS:
            del self.terminal_keys[next(iter(self.terminal_keys))]


_ROOT_COORDINATORS: dict[str, _RootCoordinator] = {}


def _canonical_root_key(root: Path) -> str:
    return os.path.normcase(os.path.abspath(os.fspath(root)))


def _coordinator_for(root: Path) -> _RootCoordinator:
    key = _canonical_root_key(root)
    with _ROOT_COORDINATORS_LOCK:
        coordinator = _ROOT_COORDINATORS.get(key)
        if coordinator is None:
            coordinator = _RootCoordinator()
            _ROOT_COORDINATORS[key] = coordinator
        return coordinator


def _lock_file_descriptor_once(file_descriptor: int) -> Literal["acquired", "busy", "ambiguous"]:
    try:
        os.lseek(file_descriptor, 0, os.SEEK_SET)
        if _msvcrt is not None:
            _msvcrt.locking(file_descriptor, _msvcrt.LK_NBLCK, 1)
        elif _fcntl is not None:
            _fcntl.flock(file_descriptor, _fcntl.LOCK_EX | _fcntl.LOCK_NB)
        else:
            return "ambiguous"
    except OSError as error:
        if error.errno in {errno.EACCES, errno.EAGAIN, errno.EDEADLK}:
            return "busy"
        return "ambiguous"
    return "acquired"


def _lock_file_descriptor(file_descriptor: int) -> None:
    deadline = time.monotonic() + _ROOT_LOCK_TIMEOUT_SECONDS
    while True:
        status = _lock_file_descriptor_once(file_descriptor)
        if status == "acquired":
            return
        if status == "ambiguous":
            raise OSError("diagnostic lock state is unavailable")
        if time.monotonic() >= deadline:
            raise TimeoutError("diagnostic lock acquisition timed out")
        time.sleep(0.01)


def _unlock_file_descriptor(file_descriptor: int) -> None:
    os.lseek(file_descriptor, 0, os.SEEK_SET)
    if _msvcrt is not None:
        _msvcrt.locking(file_descriptor, _msvcrt.LK_UNLCK, 1)
    elif _fcntl is not None:
        _fcntl.flock(file_descriptor, _fcntl.LOCK_UN)


@contextmanager
def _cross_process_root_lock(root: Path):  # type: ignore[no-untyped-def]
    lock_path = root / _ROOT_LOCK_BASENAME
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_BINARY", 0)
    file_descriptor = os.open(os.fspath(lock_path), flags, 0o600)
    acquired = False
    try:
        if os.fstat(file_descriptor).st_size == 0:
            os.ftruncate(file_descriptor, 1)
        _lock_file_descriptor(file_descriptor)
        acquired = True
        yield
    finally:
        if acquired:
            try:
                _unlock_file_descriptor(file_descriptor)
            except OSError:
                pass
        os.close(file_descriptor)


def _validate_reservation_identity(action_id: str, correlation_id: str) -> None:
    for field_name, value in (("action_id", action_id), ("correlation_id", correlation_id)):
        if type(value) is not str or not value:
            raise TypeError(f"{field_name} must be a non-empty exact str")
        try:
            encoded = value.encode("utf-8", errors="strict")
        except UnicodeEncodeError as error:
            raise TypeError(f"{field_name} must contain valid UTF-8 text") from error
        if len(encoded) > _MAX_RESERVATION_IDENTITY_BYTES:
            raise ValueError(f"{field_name} exceeds the reservation identity bound")


class DiagnosticJournal:
    """Append-only UTF-8 JSON Lines implementation of :class:`JournalSink`."""

    def __init__(
        self,
        root: Path | None = None,
        *,
        redactor: DiagnosticRedactor | None = None,
    ) -> None:
        resolved_root = resolve_diagnostic_root() if root is None else Path(root)
        if not resolved_root.is_absolute():
            raise ValueError("diagnostic journal root must be absolute")
        self._redactor = DiagnosticRedactor() if redactor is None else redactor
        self._root = resolved_root
        self._coordinator = _coordinator_for(resolved_root)
        self.path = resolved_root / "diagnostics.jsonl"
        self.archive_paths = tuple(resolved_root / name for name in DIAGNOSTIC_ARCHIVE_BASENAMES)
        self._append_temp_path = resolved_root / _APPEND_TEMP_BASENAME
        self._rotation_temp_paths = tuple(
            resolved_root / name for name in _ROTATION_TEMP_BASENAMES
        )

    def preflight(self, action_id: str, correlation_id: str) -> ActionOutcome[None]:
        stage = _fallback_stage()
        try:
            _validate_reservation_identity(action_id, correlation_id)
            with self._exclusive_root():
                self._recover_stale_state()
                key = (action_id, correlation_id)
                if key in self._coordinator.reservations:
                    raise FileExistsError("diagnostic reservation identity already exists")
                live_count = self._reap_abandoned_reservations()
                if live_count >= _MAX_LIVE_RESERVATIONS:
                    raise OSError("diagnostic reservation capacity is exhausted")
                current_size = self.path.stat().st_size if self.path.exists() else 0
                reserved_after = (live_count + 1) * DIAGNOSTIC_RECEIPT_RECORD_MAX_BYTES
                if current_size + reserved_after > DIAGNOSTIC_JOURNAL_MAX_BYTES:
                    self._rotate()
                    current_size = self.path.stat().st_size if self.path.exists() else 0
                if current_size + reserved_after > DIAGNOSTIC_JOURNAL_MAX_BYTES:
                    raise OSError("diagnostic reservation does not fit the active journal")
                self._sync_active()
                reservation = self._create_reservation(action_id, correlation_id)
                self._coordinator.reservations[key] = reservation
                self._coordinator.terminal_keys.pop(key, None)
        except Exception:
            return _diagnostic_error(
                action_id=action_id,
                correlation_id=correlation_id,
                stage=stage,
                code="DIAGNOSTIC_JOURNAL_UNAVAILABLE",
                summary="The diagnostic journal is unavailable.",
            )
        return ActionSuccess(
            action_id=action_id,
            correlation_id=correlation_id,
            stage=stage,
            value=None,
        )

    def append_and_sync(self, record: JournalRecord) -> ActionOutcome[None]:
        if type(record) is not JournalRecord:
            _validate_record(record)
        reservation: _JournalReservation | None = None
        if type(record.action_id) is str and type(record.correlation_id) is str:
            candidate_key = (record.action_id, record.correlation_id)
            with self._coordinator.lock:
                reservation = self._coordinator.reservations.get(candidate_key)
        if reservation is not None:
            return self._append_reserved_and_sync(record, reservation)

        _validate_record(record)
        stage = _stage_from_value(record.workflow_stage)
        line = _encode_record(record, self._redactor)
        encoded_line = line.encode("utf-8")
        encoded_size = len(encoded_line)
        key = (record.action_id, record.correlation_id)
        with self._coordinator.lock:
            reservation = self._coordinator.reservations.get(key)
            partial_match = any(
                reserved_action == record.action_id or reserved_correlation == record.correlation_id
                for reserved_action, reserved_correlation in self._coordinator.reservations
            )
            terminal = key in self._coordinator.terminal_keys
        if partial_match or terminal:
            return _diagnostic_error(
                action_id=record.action_id,
                correlation_id=record.correlation_id,
                stage=stage,
                code="DIAGNOSTIC_RESERVATION_MISMATCH",
                summary="The diagnostic reservation identity does not match.",
                retryable=False,
                next_action="Start the action again with a new correlation identifier.",
            )
        if encoded_size > DIAGNOSTIC_JOURNAL_MAX_BYTES:
            return _diagnostic_error(
                action_id=record.action_id,
                correlation_id=record.correlation_id,
                stage=stage,
                code="DIAGNOSTIC_RECORD_TOO_LARGE",
                summary="The encoded diagnostic record exceeds the journal byte limit.",
                retryable=False,
                next_action="Reduce the diagnostic record size and retry.",
            )
        try:
            with self._exclusive_root():
                current_reservation = self._coordinator.reservations.get(key)
                current_partial_match = any(
                    reserved_action == record.action_id
                    or reserved_correlation == record.correlation_id
                    for reserved_action, reserved_correlation in self._coordinator.reservations
                )
                current_terminal = key in self._coordinator.terminal_keys
                if (
                    current_reservation is not None
                    or current_partial_match
                    or current_terminal
                ):
                    return _diagnostic_error(
                        action_id=record.action_id,
                        correlation_id=record.correlation_id,
                        stage=stage,
                        code="DIAGNOSTIC_RESERVATION_MISMATCH",
                        summary="The diagnostic reservation identity does not match.",
                        retryable=False,
                        next_action=(
                            "Start the action again with a new correlation identifier."
                        ),
                    )
                self._recover_stale_state()
                live_count = self._reap_abandoned_reservations()
                current_size = self.path.stat().st_size if self.path.exists() else 0
                liability = live_count * DIAGNOSTIC_RECEIPT_RECORD_MAX_BYTES
                if current_size + encoded_size + liability > DIAGNOSTIC_JOURNAL_MAX_BYTES:
                    self._rotate()
                    current_size = self.path.stat().st_size if self.path.exists() else 0
                if current_size + encoded_size + liability > DIAGNOSTIC_JOURNAL_MAX_BYTES:
                    raise OSError("normal append would consume reserved journal capacity")
                self._append_atomically(encoded_line)
        except Exception:
            return _diagnostic_error(
                action_id=record.action_id,
                correlation_id=record.correlation_id,
                stage=stage,
                code="DIAGNOSTIC_JOURNAL_WRITE_FAILED",
                summary="The diagnostic record could not be synchronized.",
            )
        return ActionSuccess(
            action_id=record.action_id,
            correlation_id=record.correlation_id,
            stage=stage,
            value=None,
        )

    @contextmanager
    def _exclusive_root(self) -> Iterator[None]:
        with _JOURNAL_LOCK, self._coordinator.lock:
            self._root.mkdir(parents=True, exist_ok=True)
            with _cross_process_root_lock(self._root):
                yield

    def _create_reservation(
        self,
        action_id: str,
        correlation_id: str,
    ) -> _JournalReservation:
        file_descriptor: int | None = None
        path: Path | None = None
        locked = False
        try:
            flags = (
                os.O_RDWR
                | os.O_CREAT
                | os.O_EXCL
                | getattr(os, "O_BINARY", 0)
            )
            for _attempt in range(16):
                candidate = self._root / f".diagnostics.reserve.{secrets.token_hex(16)}.tmp"
                try:
                    file_descriptor = os.open(os.fspath(candidate), flags, 0o600)
                except FileExistsError:
                    continue
                path = candidate
                break
            if file_descriptor is None or path is None:
                raise FileExistsError("could not allocate a unique diagnostic reservation")
            _write_all(file_descriptor, b"\0")
            _lock_file_descriptor(file_descriptor)
            locked = True
            os.lseek(file_descriptor, 1, os.SEEK_SET)
            remaining = _RESERVATION_STAGE_BYTES - 1
            while remaining:
                chunk = _ZERO_CHUNK if remaining >= len(_ZERO_CHUNK) else bytes(remaining)
                _write_all(file_descriptor, chunk)
                remaining -= len(chunk)
            os.fsync(file_descriptor)
            return _JournalReservation(
                action_id=action_id,
                correlation_id=correlation_id,
                path=path,
                file_descriptor=file_descriptor,
            )
        except BaseException:
            if file_descriptor is not None:
                if locked:
                    try:
                        _unlock_file_descriptor(file_descriptor)
                    except OSError:
                        pass
                try:
                    os.close(file_descriptor)
                except OSError:
                    pass
            if path is not None:
                _best_effort_unlink(path)
            raise

    def _reap_abandoned_reservations(self) -> int:
        own_paths: set[str] = set()
        for reservation in self._coordinator.reservations.values():
            if reservation.path.stat().st_size != _RESERVATION_STAGE_BYTES:
                raise OSError("live diagnostic reservation has an invalid size")
            own_paths.add(_canonical_root_key(reservation.path))
        live_count = len(own_paths)
        for candidate in sorted(self._root.glob(".diagnostics.reserve.*.tmp")):
            if _RESERVATION_RE.fullmatch(candidate.name) is None:
                continue
            if _canonical_root_key(candidate) in own_paths:
                continue
            file_descriptor: int | None = None
            try:
                flags = os.O_RDWR | getattr(os, "O_BINARY", 0)
                file_descriptor = os.open(os.fspath(candidate), flags)
                stage_size = os.fstat(file_descriptor).st_size
                if stage_size == 0:
                    os.ftruncate(file_descriptor, 1)
                lock_status = _lock_file_descriptor_once(file_descriptor)
                if lock_status == "acquired":
                    _unlock_file_descriptor(file_descriptor)
                    os.close(file_descriptor)
                    file_descriptor = None
                    os.unlink(candidate)
                elif lock_status == "busy":
                    if stage_size != _RESERVATION_STAGE_BYTES:
                        raise OSError("live diagnostic reservation has an invalid size")
                    live_count += 1
                else:
                    raise OSError("diagnostic reservation lock state is ambiguous")
            except FileNotFoundError:
                pass
            finally:
                if file_descriptor is not None:
                    try:
                        os.close(file_descriptor)
                    except OSError:
                        pass
        return live_count

    def cancel_preflight(self, action_id: str, correlation_id: str) -> None:
        key = (action_id, correlation_id)
        try:
            with self._exclusive_root():
                reservation = self._coordinator.reservations.get(key)
                if reservation is not None:
                    self._release_reservation(reservation, delete_stage=True)
        except Exception:
            with self._coordinator.lock:
                reservation = self._coordinator.reservations.get(key)
                if reservation is not None:
                    self._release_reservation(reservation, delete_stage=True)

    def _append_reserved_and_sync(
        self,
        record: JournalRecord,
        reservation: _JournalReservation,
    ) -> ActionOutcome[None]:
        stage = _fallback_stage()
        record_validated = False
        bound_failure: ActionOutcome[None] | None = None
        try:
            _validate_record(record)
            record_validated = True
            stage = _stage_from_value(record.workflow_stage)
            encoded_line = _encode_record(record, self._redactor).encode("utf-8")
            if len(encoded_line) > DIAGNOSTIC_RECEIPT_RECORD_MAX_BYTES:
                encoded_line = _encode_record(
                    _bounded_reservation_failure_record(record),
                    self._redactor,
                ).encode("utf-8")
                if len(encoded_line) > DIAGNOSTIC_RECEIPT_RECORD_MAX_BYTES:
                    raise AssertionError(
                        "bounded diagnostic fallback exceeds its reservation"
                    )
                bound_failure = _diagnostic_error(
                    action_id=record.action_id,
                    correlation_id=record.correlation_id,
                    stage=stage,
                    code="DIAGNOSTIC_RECORD_BOUND_EXCEEDED",
                    summary="The reserved diagnostic record exceeds its byte bound.",
                    retryable=False,
                    next_action="Start the action again after reviewing diagnostics.",
                )
            with self._exclusive_root():
                key = (record.action_id, record.correlation_id)
                if self._coordinator.reservations.get(key) is not reservation:
                    raise OSError("diagnostic reservation is no longer live")
                prior = self.path.read_bytes() if self.path.exists() else b""
                if len(prior) + len(encoded_line) > DIAGNOSTIC_JOURNAL_MAX_BYTES:
                    raise OSError("reserved diagnostic record no longer fits")
                os.lseek(reservation.file_descriptor, 0, os.SEEK_SET)
                _write_all(reservation.file_descriptor, prior)
                _write_all(reservation.file_descriptor, encoded_line)
                os.fsync(reservation.file_descriptor)
                os.ftruncate(reservation.file_descriptor, len(prior) + len(encoded_line))
                os.fsync(reservation.file_descriptor)
                _unlock_file_descriptor(reservation.file_descriptor)
                os.close(reservation.file_descriptor)
                reservation.file_descriptor = -1
                os.replace(reservation.path, self.path)
                self._release_reservation(reservation, delete_stage=False)
        except Exception:
            with self._coordinator.lock:
                self._release_reservation(reservation, delete_stage=True)
            if not record_validated:
                raise
            return _diagnostic_error(
                action_id=record.action_id,
                correlation_id=record.correlation_id,
                stage=stage,
                code="DIAGNOSTIC_JOURNAL_WRITE_FAILED",
                summary="The diagnostic record could not be synchronized.",
            )
        except BaseException:
            with self._coordinator.lock:
                self._release_reservation(reservation, delete_stage=True)
            raise
        if bound_failure is not None:
            return bound_failure
        return ActionSuccess(
            action_id=record.action_id,
            correlation_id=record.correlation_id,
            stage=stage,
            value=None,
        )

    def _release_reservation(
        self,
        reservation: _JournalReservation,
        *,
        delete_stage: bool,
    ) -> None:
        key = (reservation.action_id, reservation.correlation_id)
        if reservation.file_descriptor >= 0:
            try:
                _unlock_file_descriptor(reservation.file_descriptor)
            except OSError:
                pass
            try:
                os.close(reservation.file_descriptor)
            except OSError:
                pass
            reservation.file_descriptor = -1
        if delete_stage:
            _best_effort_unlink(reservation.path)
        if self._coordinator.reservations.get(key) is reservation:
            del self._coordinator.reservations[key]
        self._coordinator.mark_terminal(key)

    def _rotate(self) -> None:
        self._recover_stale_state()
        original_paths = (self.path, *self.archive_paths)
        for generation in range(5, 0, -1):
            source = original_paths[generation]
            if source.exists():
                os.replace(source, self._rotation_temp_paths[generation])
        if self.path.exists():
            os.replace(self.path, self._rotation_temp_paths[0])
        self._finish_rotation()

    def _recover_stale_state(self) -> None:
        self._recover_rotation()
        self._prune_excess_archives()
        if self._append_temp_path.exists():
            os.unlink(self._append_temp_path)

    def _prune_excess_archives(self) -> None:
        for candidate in sorted(self._root.glob("diagnostics.*.jsonl")):
            parts = candidate.name.split(".")
            if len(parts) == 3 and parts[1].isdigit() and int(parts[1]) > 5:
                os.unlink(candidate)

    def _recover_rotation(self) -> None:
        if not any(path.exists() for path in self._rotation_temp_paths):
            return
        if self.path.exists():
            for generation in range(1, 6):
                temporary = self._rotation_temp_paths[generation]
                if temporary.exists():
                    os.replace(temporary, self.archive_paths[generation - 1])
            return
        self._finish_rotation()

    def _finish_rotation(self) -> None:
        for generation in range(4, -1, -1):
            temporary = self._rotation_temp_paths[generation]
            if temporary.exists():
                os.replace(temporary, self.archive_paths[generation])
        oldest = self._rotation_temp_paths[5]
        if oldest.exists():
            os.unlink(oldest)
        self._sync_active()

    def _append_atomically(self, encoded_line: bytes) -> None:
        prior = self.path.read_bytes() if self.path.exists() else b""
        file_descriptor: int | None = None
        try:
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
            file_descriptor = os.open(os.fspath(self._append_temp_path), flags, 0o600)
            _write_all(file_descriptor, prior)
            _write_all(file_descriptor, encoded_line)
            os.fsync(file_descriptor)
        except Exception:
            if file_descriptor is not None:
                os.close(file_descriptor)
                file_descriptor = None
            _best_effort_unlink(self._append_temp_path)
            raise
        finally:
            if file_descriptor is not None:
                os.close(file_descriptor)
        try:
            os.replace(self._append_temp_path, self.path)
        except Exception:
            _best_effort_unlink(self._append_temp_path)
            raise

    def _sync_active(self) -> None:
        with self.path.open("a", encoding="utf-8", newline="") as stream:
            stream.flush()
            os.fsync(stream.fileno())


class FolderOpener(Protocol):
    def __call__(self, folder: Path) -> None: ...


@dataclass(frozen=True, slots=True)
class _DiagnosticBundleSnapshot:
    raw_members: tuple[BundleMemberPreview, ...]
    public_members: tuple[BundleMemberPreview, ...]


@dataclass(frozen=True, slots=True)
class _DiagnosticBundleGrant:
    token: str
    expires_monotonic: float
    snapshot: _DiagnosticBundleSnapshot


def _default_bundle_token() -> str:
    return secrets.token_urlsafe(32)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _is_finite_number(value: object) -> bool:
    if not isinstance(value, (int, float)) or type(value) not in {int, float}:
        return False
    try:
        return math.isfinite(float(value))
    except (OverflowError, TypeError, ValueError):
        return False


def _is_valid_bundle_token(value: object) -> bool:
    return type(value) is str and _BUNDLE_TOKEN_RE.fullmatch(value) is not None


def _process_is_alive(process_id: int) -> bool:
    """Return False only when the process is proven to have exited."""

    if type(process_id) is not int or process_id <= 0 or process_id == os.getpid():
        return True
    if os.name == "nt":
        try:
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            open_process = kernel32.OpenProcess
            open_process.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
            open_process.restype = wintypes.HANDLE
            wait_for_single_object = kernel32.WaitForSingleObject
            wait_for_single_object.argtypes = [wintypes.HANDLE, wintypes.DWORD]
            wait_for_single_object.restype = wintypes.DWORD
            close_handle = kernel32.CloseHandle
            close_handle.argtypes = [wintypes.HANDLE]
            close_handle.restype = wintypes.BOOL

            handle = open_process(_SYNCHRONIZE, False, process_id)
            if not handle:
                return ctypes.get_last_error() != _ERROR_INVALID_PARAMETER
            try:
                wait_result = wait_for_single_object(handle, 0)
            finally:
                close_handle(handle)
            return wait_result != _WAIT_OBJECT_0
        except Exception:
            return True

    try:
        os.kill(process_id, 0)
    except ProcessLookupError:
        return False
    except (OSError, OverflowError):
        return True
    return True


def _raise_bundle_failure(
    code: str,
    summary: str,
    *,
    retryable: bool = True,
    next_action: str | None = "Create a new diagnostic bundle preview and retry.",
    effect_state: Literal["none", "local_write_published"] = "none",
    published_artifact: tuple[str, str] | None = None,
) -> NoReturn:
    from calibrate_pro.application.outcomes import ActionFailure

    raise ActionFailure(
        code=code,
        summary=summary,
        retryable=retryable,
        next_action=next_action,
        category="diagnostics",
        effect_state=effect_state,
        published_artifact=published_artifact,
    )


class DiagnosticBundleManager:
    """Own one fail-closed, in-memory diagnostic bundle preview grant."""

    def __init__(
        self,
        journal: DiagnosticJournal,
        *,
        redactor: DiagnosticRedactor | None = None,
        token_factory: Callable[[], str] = _default_bundle_token,
        monotonic: Callable[[], float] = time.monotonic,
        utc_now: Callable[[], datetime] = _utc_now,
        ttl_seconds: float = 300.0,
        folder_opener: FolderOpener | None = None,
        process_is_alive: Callable[[int], bool] = _process_is_alive,
    ) -> None:
        if type(journal) is not DiagnosticJournal:
            raise TypeError("journal must be an exact DiagnosticJournal")
        if not _is_finite_number(ttl_seconds) or ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be finite and positive")
        self._journal = journal
        self._redactor = journal._redactor if redactor is None else redactor
        self._token_factory = token_factory
        self._monotonic = monotonic
        self._utc_now = utc_now
        self._ttl_seconds = float(ttl_seconds)
        self._folder_opener = folder_opener
        self._process_is_alive = process_is_alive
        self._grant: _DiagnosticBundleGrant | None = None

    @property
    def folder(self) -> Path:
        """Where the journal this manager reads is kept.

        Naming the folder is not reaching into it. A surface prints this so an
        operator whose platform cannot open a window still knows where to look,
        and the three declared actions remain the only way anything is read.
        """
        return self._journal._root

    def preview(self) -> BundlePreview:
        with _JOURNAL_LOCK:
            self._grant = None
            snapshot = self._snapshot()
            try:
                token = self._token_factory()
                now_monotonic = self._monotonic()
                now_utc = self._utc_now()
            except Exception:
                _raise_bundle_failure(
                    "DIAGNOSTIC_BUNDLE_PREVIEW_FAILED",
                    "The diagnostic bundle preview could not be created.",
                )
            if not _is_valid_bundle_token(token):
                _raise_bundle_failure(
                    "DIAGNOSTIC_BUNDLE_PREVIEW_FAILED",
                    "The diagnostic bundle preview could not be created.",
                )
            if (
                not _is_finite_number(now_monotonic)
                or type(now_utc) is not datetime
                or now_utc.utcoffset() != timedelta(0)
            ):
                _raise_bundle_failure(
                    "DIAGNOSTIC_BUNDLE_PREVIEW_FAILED",
                    "The diagnostic bundle preview could not be created.",
                )
            try:
                deadline = float(now_monotonic) + self._ttl_seconds
                if not _is_finite_number(deadline):
                    raise OverflowError("diagnostic bundle deadline is not finite")
                expires = now_utc + timedelta(seconds=self._ttl_seconds)
            except Exception:
                _raise_bundle_failure(
                    "DIAGNOSTIC_BUNDLE_PREVIEW_FAILED",
                    "The diagnostic bundle preview could not be created.",
                )
            grant = _DiagnosticBundleGrant(
                token=token,
                expires_monotonic=deadline,
                snapshot=snapshot,
            )
            preview = BundlePreview(
                token=token,
                members=snapshot.public_members,
                expires_utc=expires.isoformat().replace("+00:00", "Z"),
            )
            self._grant = grant
            return preview

    def preview_is_live(self, token: str) -> bool:
        with _JOURNAL_LOCK:
            grant = self._grant
            if (
                grant is None
                or not _is_valid_bundle_token(token)
                or not hmac.compare_digest(token, grant.token)
            ):
                return False
            try:
                now = self._monotonic()
            except Exception:
                self._grant = None
                return False
            if not _is_finite_number(now) or now >= grant.expires_monotonic:
                self._grant = None
                return False
            try:
                current = self._snapshot()
            except Exception:
                self._grant = None
                return False
            if current != grant.snapshot:
                self._grant = None
                return False
            return True

    def create(self, token: str, destination: Path) -> DiagnosticBundleReceipt:
        with _JOURNAL_LOCK:
            grant = self._grant
            if (
                grant is None
                or not _is_valid_bundle_token(token)
                or not hmac.compare_digest(token, grant.token)
            ):
                _raise_bundle_failure(
                    "DIAGNOSTIC_BUNDLE_TOKEN_INVALID",
                    "The diagnostic bundle preview token is invalid.",
                    retryable=False,
                )
            try:
                now = self._monotonic()
            except Exception:
                self._grant = None
                _raise_bundle_failure(
                    "DIAGNOSTIC_BUNDLE_PREVIEW_EXPIRED",
                    "The diagnostic bundle preview has expired.",
                )
            if not _is_finite_number(now) or now >= grant.expires_monotonic:
                self._grant = None
                _raise_bundle_failure(
                    "DIAGNOSTIC_BUNDLE_PREVIEW_EXPIRED",
                    "The diagnostic bundle preview has expired.",
                )
            current, public_payloads = self._snapshot_and_payloads()
            if current != grant.snapshot:
                self._grant = None
                _raise_bundle_failure(
                    "DIAGNOSTIC_BUNDLE_PREVIEW_STALE",
                    "The diagnostic journal changed after the bundle preview.",
                )
            if not isinstance(destination, Path) or not destination.is_absolute() or not destination.name:
                _raise_bundle_failure(
                    "DIAGNOSTIC_BUNDLE_DESTINATION_INVALID",
                    "The diagnostic bundle destination must be an absolute file path.",
                    retryable=False,
                    next_action="Choose an absolute destination and retry.",
                )
            if self._path_entry_exists(destination):
                _raise_bundle_failure(
                    "DIAGNOSTIC_BUNDLE_DESTINATION_EXISTS",
                    "The diagnostic bundle destination already exists.",
                    retryable=False,
                    next_action="Choose a new destination and retry.",
                )
            self._grant = None
            self._cleanup_owned_temps(destination.parent)
            return self._publish(destination, public_payloads)

    def open_folder(self, action_id: str) -> None:
        if type(action_id) is not str or action_id != "diagnostics.folder.open":
            _raise_bundle_failure(
                "DIAGNOSTIC_FOLDER_ACTION_INVALID",
                "The diagnostics folder action is invalid.",
                retryable=False,
                next_action=None,
            )
        opener = self._folder_opener
        if opener is None:
            _raise_bundle_failure(
                "DIAGNOSTIC_FOLDER_OPEN_UNAVAILABLE",
                "The diagnostics folder cannot be opened in this environment.",
            )
        try:
            opener(self._journal._root)
        except Exception:
            _raise_bundle_failure(
                "DIAGNOSTIC_FOLDER_OPEN_FAILED",
                "The diagnostics folder could not be opened.",
            )

    def _snapshot(self) -> _DiagnosticBundleSnapshot:
        snapshot, _payloads = self._snapshot_and_payloads()
        return snapshot

    def _snapshot_and_payloads(
        self,
    ) -> tuple[_DiagnosticBundleSnapshot, tuple[tuple[str, bytes], ...]]:
        raw_members: list[BundleMemberPreview] = []
        public_members: list[BundleMemberPreview] = []
        public_payloads: list[tuple[str, bytes]] = []
        for basename in _DIAGNOSTIC_BUNDLE_BASENAMES:
            path = self._journal._root / basename
            try:
                raw_payload = self._read_source_once(path)
            except FileNotFoundError:
                continue
            except Exception as error:
                from calibrate_pro.application.outcomes import ActionFailure

                if isinstance(error, ActionFailure):
                    raise
                _raise_bundle_failure(
                    "DIAGNOSTIC_BUNDLE_SOURCE_UNAVAILABLE",
                    "A diagnostic bundle source could not be read.",
                )
            public_payload = self._redactor.redact_bytes(raw_payload)
            raw_members.append(
                BundleMemberPreview(
                    basename=basename,
                    byte_length=len(raw_payload),
                    sha256=hashlib.sha256(raw_payload).hexdigest(),
                )
            )
            public_members.append(
                BundleMemberPreview(
                    basename=basename,
                    byte_length=len(public_payload),
                    sha256=hashlib.sha256(public_payload).hexdigest(),
                )
            )
            public_payloads.append((basename, public_payload))
        if not raw_members:
            _raise_bundle_failure(
                "DIAGNOSTIC_BUNDLE_EMPTY",
                "There are no diagnostic journal files to bundle.",
            )
        return (
            _DiagnosticBundleSnapshot(tuple(raw_members), tuple(public_members)),
            tuple(public_payloads),
        )

    def _read_source_once(self, path: Path) -> bytes:
        metadata = os.lstat(path)
        if not stat.S_ISREG(metadata.st_mode):
            _raise_bundle_failure(
                "DIAGNOSTIC_BUNDLE_SOURCE_INVALID",
                "A diagnostic bundle source is not a regular file.",
                retryable=False,
            )
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
        file_descriptor: int | None = None
        try:
            file_descriptor = os.open(path, flags)
            before = os.fstat(file_descriptor)
            if not self._same_source(metadata, before):
                _raise_bundle_failure(
                    "DIAGNOSTIC_BUNDLE_SOURCE_CHANGED",
                    "The diagnostic bundle inventory changed while it was opened.",
                )
            chunks: list[bytes] = []
            while True:
                chunk = os.read(file_descriptor, 65_536)
                if not chunk:
                    break
                chunks.append(chunk)
            after = os.fstat(file_descriptor)
            payload = b"".join(chunks)
            if not self._same_source(before, after) or len(payload) != before.st_size:
                _raise_bundle_failure(
                    "DIAGNOSTIC_BUNDLE_SOURCE_CHANGED",
                    "The diagnostic bundle inventory changed while it was read.",
                )
            return payload
        finally:
            if file_descriptor is not None:
                os.close(file_descriptor)

    @staticmethod
    def _same_source(first: os.stat_result, second: os.stat_result) -> bool:
        return (
            stat.S_ISREG(first.st_mode)
            and stat.S_ISREG(second.st_mode)
            and first.st_ino != 0
            and first.st_dev == second.st_dev
            and first.st_ino == second.st_ino
            and stat.S_IFMT(first.st_mode) == stat.S_IFMT(second.st_mode)
            and first.st_size == second.st_size
            and first.st_mtime_ns == second.st_mtime_ns
        )

    @staticmethod
    def _path_entry_exists(path: Path) -> bool:
        try:
            return os.path.lexists(os.fspath(path))
        except Exception:
            return True

    def _cleanup_owned_temps(self, parent: Path) -> None:
        try:
            candidates = tuple(parent.iterdir())
        except Exception:
            _raise_bundle_failure(
                "DIAGNOSTIC_BUNDLE_CREATE_FAILED",
                "The diagnostic bundle could not be created.",
            )
        for candidate in candidates:
            match = _BUNDLE_TEMP_RE.fullmatch(candidate.name)
            if match is None:
                continue
            process_id = int(match.group("pid"))
            try:
                process_alive = self._process_is_alive(process_id)
            except Exception:
                continue
            # Ambiguous liveness, inaccessible processes, and PID reuse are
            # retained. Cleanup is intentionally limited to proven-dead owners.
            if process_alive is not False:
                continue
            try:
                metadata = candidate.lstat()
                if stat.S_ISREG(metadata.st_mode):
                    os.unlink(candidate)
            except FileNotFoundError:
                continue
            except Exception:
                _raise_bundle_failure(
                    "DIAGNOSTIC_BUNDLE_CREATE_FAILED",
                    "The diagnostic bundle could not be created.",
                )

    def _publish(
        self,
        destination: Path,
        public_payloads: tuple[tuple[str, bytes], ...],
    ) -> DiagnosticBundleReceipt:
        temporary_path: Path | None = None
        file_descriptor: int | None = None
        try:
            temporary_path, file_descriptor = self._open_temporary(destination.parent)
            stream = os.fdopen(file_descriptor, "w+b")
            file_descriptor = None
            with stream:
                with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_STORED) as archive:
                    archive.comment = b""
                    for basename, payload in public_payloads:
                        info = zipfile.ZipInfo(basename, date_time=(1980, 1, 1, 0, 0, 0))
                        info.compress_type = zipfile.ZIP_STORED
                        info.create_system = 3
                        info.external_attr = (stat.S_IFREG | 0o600) << 16
                        info.extra = b""
                        info.comment = b""
                        archive.writestr(info, payload)
                stream.flush()
                os.fsync(stream.fileno())
            byte_length, bundle_sha256 = self._verify_zip(temporary_path, public_payloads)
            if self._path_entry_exists(destination):
                _raise_bundle_failure(
                    "DIAGNOSTIC_BUNDLE_DESTINATION_EXISTS",
                    "The diagnostic bundle destination already exists.",
                    retryable=False,
                    next_action="Choose a new destination and retry.",
                )
            published = False
            try:
                if os.name == "nt":
                    # Same-directory Windows rename is atomic and fails if the
                    # destination appeared after the final existence check.
                    os.rename(temporary_path, destination)
                    published = True
                else:
                    # A same-directory hard link publishes atomically without
                    # clobbering, then the temporary name is removed.
                    os.link(temporary_path, destination, follow_symlinks=False)
                    published = True
                    os.unlink(temporary_path)
            except FileExistsError:
                if not published:
                    _raise_bundle_failure(
                        "DIAGNOSTIC_BUNDLE_DESTINATION_EXISTS",
                        "The diagnostic bundle destination already exists.",
                        retryable=False,
                        next_action="Choose a new destination and retry.",
                    )
                _raise_bundle_failure(
                    "DIAGNOSTIC_BUNDLE_READBACK_FAILED",
                    "The diagnostic bundle was published but could not be confirmed.",
                    retryable=False,
                    next_action="Preserve the published bundle and review diagnostics.",
                    effect_state="local_write_published",
                    published_artifact=(destination.name, bundle_sha256),
                )
            except Exception:
                if published or self._published_matches(
                    destination,
                    public_payloads,
                    byte_length,
                    bundle_sha256,
                ):
                    _raise_bundle_failure(
                        "DIAGNOSTIC_BUNDLE_READBACK_FAILED",
                        "The diagnostic bundle was published but could not be confirmed.",
                        retryable=False,
                        next_action="Preserve the published bundle and review diagnostics.",
                        effect_state="local_write_published",
                        published_artifact=(destination.name, bundle_sha256),
                    )
                _raise_bundle_failure(
                    "DIAGNOSTIC_BUNDLE_CREATE_FAILED",
                    "The diagnostic bundle could not be published.",
                )
            temporary_path = None
            if not self._published_matches(
                destination,
                public_payloads,
                byte_length,
                bundle_sha256,
            ):
                _raise_bundle_failure(
                    "DIAGNOSTIC_BUNDLE_READBACK_FAILED",
                    "The diagnostic bundle was published but failed readback verification.",
                    retryable=False,
                    next_action="Preserve the published bundle and review diagnostics.",
                    effect_state="local_write_published",
                    published_artifact=(destination.name, bundle_sha256),
                )
            return DiagnosticBundleReceipt(
                published_path=destination,
                bundle_sha256=bundle_sha256,
                byte_length=byte_length,
                member_hashes=tuple(
                    (basename, hashlib.sha256(payload).hexdigest())
                    for basename, payload in public_payloads
                ),
                readback_verified=True,
            )
        except Exception as error:
            from calibrate_pro.application.outcomes import ActionFailure

            if isinstance(error, ActionFailure):
                raise
            _raise_bundle_failure(
                "DIAGNOSTIC_BUNDLE_CREATE_FAILED",
                "The diagnostic bundle could not be created.",
            )
        finally:
            if file_descriptor is not None:
                os.close(file_descriptor)
            if temporary_path is not None:
                _best_effort_unlink(temporary_path)

    @staticmethod
    def _open_temporary(parent: Path) -> tuple[Path, int]:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
        for _attempt in range(32):
            basename = (
                f".calibrate-pro-diagnostic-bundle.{os.getpid()}."
                f"{secrets.token_hex(16)}.tmp"
            )
            if _BUNDLE_TEMP_RE.fullmatch(basename) is None:
                continue
            path = parent / basename
            try:
                return path, os.open(path, flags, 0o600)
            except FileExistsError:
                continue
        _raise_bundle_failure(
            "DIAGNOSTIC_BUNDLE_CREATE_FAILED",
            "The diagnostic bundle temporary file could not be reserved.",
        )

    @staticmethod
    def _verify_zip(
        path: Path,
        public_payloads: tuple[tuple[str, bytes], ...],
    ) -> tuple[int, str]:
        expected_names = tuple(basename for basename, _payload in public_payloads)
        with zipfile.ZipFile(path, "r") as archive:
            infos = archive.infolist()
            if tuple(info.filename for info in infos) != expected_names or archive.comment != b"":
                raise ValueError("diagnostic bundle inventory mismatch")
            if archive.testzip() is not None:
                raise ValueError("diagnostic bundle CRC mismatch")
            for info, (basename, payload) in zip(infos, public_payloads, strict=True):
                if (
                    info.filename != basename
                    or info.is_dir()
                    or info.compress_type != zipfile.ZIP_STORED
                    or info.date_time != (1980, 1, 1, 0, 0, 0)
                    or info.extra != b""
                    or info.comment != b""
                    or info.external_attr >> 16 != (stat.S_IFREG | 0o600)
                    or archive.read(info) != payload
                ):
                    raise ValueError("diagnostic bundle member mismatch")
        digest = hashlib.sha256()
        byte_length = 0
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(65_536), b""):
                byte_length += len(chunk)
                digest.update(chunk)
        return byte_length, digest.hexdigest()

    def _published_matches(
        self,
        destination: Path,
        public_payloads: tuple[tuple[str, bytes], ...],
        byte_length: int,
        bundle_sha256: str,
    ) -> bool:
        try:
            actual_length, actual_sha256 = self._verify_zip(destination, public_payloads)
        except Exception:
            return False
        return actual_length == byte_length and hmac.compare_digest(actual_sha256, bundle_sha256)


def _write_all(file_descriptor: int, payload: bytes) -> None:
    remaining = payload
    while remaining:
        written = os.write(file_descriptor, remaining)
        if written <= 0:
            raise OSError("diagnostic journal write made no progress")
        remaining = remaining[written:]


def _best_effort_unlink(path: Path) -> None:
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass
    except OSError:
        pass


def _bounded_or_omitted(value: str, maximum_bytes: int, fallback: str) -> str:
    try:
        if len(value.encode("utf-8", errors="strict")) <= maximum_bytes:
            return value
    except UnicodeEncodeError:
        pass
    return fallback


def _bounded_reservation_failure_record(record: JournalRecord) -> JournalRecord:
    export_basename = record.export_basename
    export_sha256 = record.export_sha256
    if (
        export_basename is None
        or export_sha256 is None
        or len(export_basename.encode("utf-8")) > 255
        or export_basename in {"", ".", ".."}
        or re.search(r"[\\/]", export_basename) is not None
    ):
        export_basename = None
        export_sha256 = None
    phase_flags = record.apply_phase_flags
    if len(phase_flags) > 32 or any(
        len(key.encode("utf-8")) > 128 for key, _value in phase_flags
    ):
        phase_flags = ()
    bounded = replace(
        record,
        timestamp_utc=_bounded_or_omitted(
            record.timestamp_utc,
            128,
            "timestamp-omitted",
        ),
        product_version=_bounded_or_omitted(
            record.product_version,
            128,
            "version-omitted",
        ),
        platform_version=_bounded_or_omitted(
            record.platform_version,
            512,
            "platform-version-omitted",
        ),
        workflow_stage=_stage_from_value(record.workflow_stage).value,
        capability_flags=(),
        outcome="failure",
        exception_type="DiagnosticRecordBoundExceeded",
        error_code="DIAGNOSTIC_RECORD_BOUND_EXCEEDED",
        technical_category="diagnostics",
        redacted_message="The final diagnostic record exceeded its reserved byte bound.",
        display_pseudonym=None,
        plan_sha256=None,
        asset_sha256=(),
        apply_phase_flags=phase_flags,
        recovery_guarantee=(
            record.recovery_guarantee
            if record.recovery_guarantee is not None
            and _bounded_or_omitted(record.recovery_guarantee, 512, "")
            == record.recovery_guarantee
            else None
        ),
        export_basename=export_basename,
        export_sha256=export_sha256,
    )
    _validate_record(bounded)
    return bounded


def _validate_record(record: JournalRecord) -> None:
    if type(record) is not JournalRecord:
        raise TypeError("record must be an exact JournalRecord instance")
    for field_name in _EXACT_STRING_FIELDS:
        value = getattr(record, field_name)
        if type(value) is not str:
            raise TypeError(f"{field_name} must be an exact str")
        _validate_utf8(field_name, value)
    for field_name in _OPTIONAL_STRING_FIELDS:
        value = getattr(record, field_name)
        if value is not None and type(value) is not str:
            raise TypeError(f"{field_name} must be None or an exact str")
        if value is not None:
            _validate_utf8(field_name, value)
    for field_name in _OPTIONAL_SHA256_FIELDS:
        value = getattr(record, field_name)
        if value is not None and _CANONICAL_SHA256_RE.fullmatch(value) is None:
            raise TypeError(f"{field_name} must be a canonical lowercase SHA-256")
    if record.runtime_mode not in {"source", "frozen", "fake_acceptance"}:
        raise TypeError("runtime_mode must be source, frozen, or fake_acceptance")
    if record.outcome not in {"success", "failure"}:
        raise TypeError("outcome must be success or failure")
    for field_name in _PAIR_TUPLE_FIELDS:
        value = getattr(record, field_name)
        if type(value) is not tuple:
            raise TypeError(f"{field_name} must be an exact tuple")
        for pair in value:
            if type(pair) is not tuple or len(pair) != 2:
                raise TypeError(f"{field_name} entries must be exact two-item tuples")
            if type(pair[0]) is not str or type(pair[1]) is not bool:
                raise TypeError(f"{field_name} entries must contain exact str and bool values")
            _validate_utf8(field_name, pair[0])
    if type(record.asset_sha256) is not tuple:
        raise TypeError("asset_sha256 must be an exact tuple")
    if any(type(digest) is not str for digest in record.asset_sha256):
        raise TypeError("asset_sha256 entries must be exact str values")
    for digest in record.asset_sha256:
        _validate_utf8("asset_sha256", digest)
        if _CANONICAL_SHA256_RE.fullmatch(digest) is None:
            raise TypeError("asset_sha256 entries must be canonical lowercase SHA-256 values")


def _validate_utf8(field_name: str, value: str) -> None:
    try:
        value.encode("utf-8", errors="strict")
    except UnicodeEncodeError as error:
        raise TypeError(f"{field_name} must contain valid UTF-8 text") from error


def _encode_record(
    record: JournalRecord,
    redactor: DiagnosticRedactor | None = None,
) -> str:
    _validate_record(record)
    selected_redactor = DiagnosticRedactor() if redactor is None else redactor
    payload: dict[str, object] = {}
    for field in dataclass_fields(JournalRecord):
        value = getattr(record, field.name)
        if field.name in _OPTIONAL_SHA256_FIELDS or field.name == "asset_sha256":
            payload[field.name] = value
        elif type(value) is str:
            payload[field.name] = (
                _normalize_export_basename(value, selected_redactor)
                if field.name == "export_basename"
                else selected_redactor.redact(value)
            )
        elif type(value) is tuple:
            if field.name in _PAIR_TUPLE_FIELDS:
                payload[field.name] = tuple(
                    (selected_redactor.redact(pair[0]), pair[1]) for pair in value
                )
            else:
                payload[field.name] = tuple(
                    selected_redactor.redact(item) for item in value
                )
        else:
            payload[field.name] = value
    return json.dumps(
        payload,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    ) + "\n"


def _normalize_export_basename(value: str, redactor: DiagnosticRedactor) -> str:
    basename = re.split(r"[\\/]", value.strip())[-1]
    if not basename or basename in {".", ".."}:
        return REDACTION_MARKER
    redacted = redactor.redact(basename)
    if not redacted or redacted in {".", ".."} or "\\" in redacted or "/" in redacted:
        return REDACTION_MARKER
    return redacted


def _stage_from_value(value: str) -> WorkflowStage:
    from calibrate_pro.workflow import WorkflowStage

    try:
        return WorkflowStage(value)
    except ValueError:
        return _fallback_stage()


def _fallback_stage() -> WorkflowStage:
    from calibrate_pro.workflow import WorkflowStage

    return next(iter(WorkflowStage))


def ActionSuccess(
    *,
    action_id: str,
    correlation_id: str,
    stage: WorkflowStage,
    value: None,
) -> ActionSuccessOutcome[None]:
    """Construct lazily to avoid the outcomes/journal import cycle."""
    from calibrate_pro.application.outcomes import ActionSuccess as OutcomeSuccess

    return OutcomeSuccess(
        action_id=action_id,
        correlation_id=correlation_id,
        stage=stage,
        value=value,
    )


def _diagnostic_error(
    *,
    action_id: str,
    correlation_id: str,
    stage: WorkflowStage,
    code: str,
    summary: str,
    retryable: bool = True,
    next_action: str = "Restore diagnostic journal access and retry.",
) -> ActionErrorOutcome:
    from calibrate_pro.application.outcomes import ActionError

    return ActionError(
        action_id=action_id,
        code=code,
        summary=summary,
        retryable=retryable,
        next_action=next_action,
        stage=stage,
        category="diagnostics",
        correlation_id=correlation_id,
        effect_state="none",
        published_artifact=None,
        apply_phase_flags=(),
        recovery_guarantee=None,
    )


__all__ = [
    "BundleMemberPreview",
    "BundlePreview",
    "CancellableJournalSink",
    "DIAGNOSTIC_ARCHIVE_BASENAMES",
    "DIAGNOSTIC_JOURNAL_MAX_BYTES",
    "DIAGNOSTIC_RECEIPT_RECORD_MAX_BYTES",
    "DiagnosticBundleManager",
    "DiagnosticBundleReceipt",
    "DiagnosticJournal",
    "DiagnosticRedactor",
    "DisplayPseudonymizer",
    "INVALID_UTF8_REDACTION_MARKER",
    "JournalRecord",
    "JournalSink",
    "PrivateSaltStore",
    "REDACTED_DEVICE_MARKER",
    "REDACTED_PATH_MARKER",
    "REDACTION_MARKER",
    "WindowsPrivateSaltStore",
    "resolve_diagnostic_root",
    "resolve_private_salt_path",
]
