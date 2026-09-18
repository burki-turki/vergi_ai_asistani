"""Windows-local key custody for Row 19D Slice 1.

The local provider is explicit and fail-closed. Key generation belongs to the
operator CLI. This module owns the Windows namespace and ACL boundary.
"""
from __future__ import annotations

import asyncio
import base64
import binascii
import contextlib
import ctypes
from ctypes import wintypes
import json
import os
import re
import secrets
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterator, TypeVar

from .transient_secrets import UnknownKeyError

_DOCUMENT_FIELDS = frozenset({"version", "current_key_id", "keys", "server_pepper"})
_KEY_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_LOCAL_PROVIDER_KIND = "local_file"
_KMS_PROVIDER_KIND = "kms"
_AZURE_PROVIDER_KIND = "azure_key_vault_secret"
_LOCK_FILE_NAME = ".local_keys.mutation.lock"
_LOCK_TIMEOUT_SECONDS = 5.0
_RETRY_SECONDS = 0.01

_GENERIC_READ = 0x80000000
_GENERIC_WRITE = 0x40000000
_READ_CONTROL = 0x00020000
_FILE_READ_ATTRIBUTES = 0x00000080
_FILE_SHARE_READ = 1
_FILE_SHARE_WRITE = 2
_FILE_SHARE_DELETE = 4
_CREATE_NEW = 1
_OPEN_EXISTING = 3
_OPEN_ALWAYS = 4
_FILE_ATTRIBUTE_NORMAL = 0x80
_FILE_ATTRIBUTE_REPARSE_POINT = 0x400
_FILE_FLAG_OPEN_REPARSE_POINT = 0x00200000
_FILE_FLAG_BACKUP_SEMANTICS = 0x02000000
_ERROR_FILE_NOT_FOUND = 2
_ERROR_PATH_NOT_FOUND = 3
_ERROR_ACCESS_DENIED = 5
_ERROR_FILE_EXISTS = 80
_ERROR_ALREADY_EXISTS = 183
_ERROR_SHARING_VIOLATION = 32
_ERROR_LOCK_VIOLATION = 33
_LOCKFILE_FAIL_IMMEDIATELY = 1
_LOCKFILE_EXCLUSIVE_LOCK = 2
_OWNER_SECURITY_INFORMATION = 1
_DACL_SECURITY_INFORMATION = 4
_SE_FILE_OBJECT = 1
_SE_DACL_PROTECTED = 0x1000
_ACL_SIZE_INFORMATION_CLASS = 2
_ACCESS_ALLOWED_ACE_TYPE = 0
_INHERITED_ACE = 0x10
_FILE_ALL_ACCESS = 0x001F01FF
_TOKEN_QUERY = 8
_TOKEN_USER_CLASS = 1
_SDDL_REVISION_1 = 1
_FILE_ATTRIBUTE_TAG_INFO_CLASS = 9


class KeyCustodyError(RuntimeError):
    """Base class for fail-closed custody errors."""


class KeyCustodyConfigurationError(KeyCustodyError):
    """Raised when provider selection, path, or Windows security is unsafe."""


class KeyCustodyDocumentError(KeyCustodyError):
    """Raised when a local custody document cannot be trusted."""


class KeyCustodyProviderUnavailableError(KeyCustodyError):
    """Raised when the selected provider cannot supply custody material."""


class KeyCustodyTransientError(KeyCustodyProviderUnavailableError):
    """Raised for retry-exhausted or deadline-bound transient failures."""


class KmsProviderNotImplementedError(KeyCustodyProviderUnavailableError):
    """Slice 1 deliberately has no production KMS implementation."""


@dataclass(frozen=True, repr=False)
class _CustodyMaterial:
    current_key_id: str
    keys: dict[str, bytes]
    server_pepper: bytes


class _SECURITY_ATTRIBUTES(ctypes.Structure):
    _fields_ = [("nLength", wintypes.DWORD), ("lpSecurityDescriptor", ctypes.c_void_p), ("bInheritHandle", wintypes.BOOL)]


class _SID_AND_ATTRIBUTES(ctypes.Structure):
    _fields_ = [("Sid", ctypes.c_void_p), ("Attributes", wintypes.DWORD)]


class _TOKEN_USER(ctypes.Structure):
    _fields_ = [("User", _SID_AND_ATTRIBUTES)]


class _ACL_SIZE_INFORMATION(ctypes.Structure):
    _fields_ = [("AceCount", wintypes.DWORD), ("AclBytesInUse", wintypes.DWORD), ("AclBytesFree", wintypes.DWORD)]


class _ACE_HEADER(ctypes.Structure):
    _fields_ = [("AceType", ctypes.c_ubyte), ("AceFlags", ctypes.c_ubyte), ("AceSize", wintypes.WORD)]


class _ACCESS_ALLOWED_ACE(ctypes.Structure):
    _fields_ = [("Header", _ACE_HEADER), ("Mask", wintypes.DWORD), ("SidStart", wintypes.DWORD)]


class _FILE_ATTRIBUTE_TAG_INFO(ctypes.Structure):
    _fields_ = [("FileAttributes", wintypes.DWORD), ("ReparseTag", wintypes.DWORD)]


class _OVERLAPPED(ctypes.Structure):
    _fields_ = [("Internal", ctypes.c_size_t), ("InternalHigh", ctypes.c_size_t), ("Offset", wintypes.DWORD), ("OffsetHigh", wintypes.DWORD), ("hEvent", wintypes.HANDLE)]


@dataclass(frozen=True)
class _WindowsApi:
    kernel32: Any
    advapi32: Any


_API: _WindowsApi | None = None
_CURRENT_USER_SID: str | None = None


def _windows_api() -> _WindowsApi:
    global _API
    if os.name != "nt":
        raise KeyCustodyConfigurationError("local_file custody requires Windows NTFS security APIs")
    if _API is not None:
        return _API
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    kernel32.CreateFileW.restype = wintypes.HANDLE
    kernel32.CreateDirectoryW.argtypes = [wintypes.LPCWSTR, ctypes.c_void_p]
    kernel32.CreateDirectoryW.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    kernel32.GetFileInformationByHandleEx.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    kernel32.GetFileInformationByHandleEx.restype = wintypes.BOOL
    kernel32.GetFinalPathNameByHandleW.argtypes = [wintypes.HANDLE, wintypes.LPWSTR, wintypes.DWORD, wintypes.DWORD]
    kernel32.GetFinalPathNameByHandleW.restype = wintypes.DWORD
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    kernel32.LockFileEx.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(_OVERLAPPED)]
    kernel32.LockFileEx.restype = wintypes.BOOL
    kernel32.UnlockFileEx.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(_OVERLAPPED)]
    kernel32.UnlockFileEx.restype = wintypes.BOOL
    advapi32.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
    advapi32.OpenProcessToken.restype = wintypes.BOOL
    advapi32.GetTokenInformation.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
    advapi32.GetTokenInformation.restype = wintypes.BOOL
    advapi32.ConvertSidToStringSidW.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.LPWSTR)]
    advapi32.ConvertSidToStringSidW.restype = wintypes.BOOL
    advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(wintypes.DWORD)]
    advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW.restype = wintypes.BOOL
    advapi32.GetSecurityInfo.argtypes = [wintypes.HANDLE, ctypes.c_int, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_void_p)]
    advapi32.GetSecurityInfo.restype = wintypes.DWORD
    advapi32.GetSecurityDescriptorControl.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.WORD), ctypes.POINTER(wintypes.DWORD)]
    advapi32.GetSecurityDescriptorControl.restype = wintypes.BOOL
    advapi32.GetAclInformation.argtypes = [ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.c_int]
    advapi32.GetAclInformation.restype = wintypes.BOOL
    advapi32.GetAce.argtypes = [ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p)]
    advapi32.GetAce.restype = wintypes.BOOL
    _API = _WindowsApi(kernel32, advapi32)
    return _API


def _winerror(error: int | None = None) -> OSError:
    return ctypes.WinError(ctypes.get_last_error() if error is None else error)


def _close_handle(handle: int) -> None:
    if handle:
        _windows_api().kernel32.CloseHandle(wintypes.HANDLE(handle))


def _sid_string(sid: ctypes.c_void_p) -> str:
    api = _windows_api()
    text = wintypes.LPWSTR()
    if not api.advapi32.ConvertSidToStringSidW(sid, ctypes.byref(text)):
        raise _winerror()
    try:
        return text.value
    finally:
        api.kernel32.LocalFree(ctypes.cast(text, ctypes.c_void_p))


def _current_user_sid() -> str:
    global _CURRENT_USER_SID
    if _CURRENT_USER_SID is not None:
        return _CURRENT_USER_SID
    api = _windows_api()
    token = wintypes.HANDLE()
    if not api.advapi32.OpenProcessToken(api.kernel32.GetCurrentProcess(), _TOKEN_QUERY, ctypes.byref(token)):
        raise KeyCustodyConfigurationError("cannot resolve the current Windows identity") from _winerror()
    try:
        needed = wintypes.DWORD()
        api.advapi32.GetTokenInformation(token, _TOKEN_USER_CLASS, None, 0, ctypes.byref(needed))
        buffer = ctypes.create_string_buffer(needed.value)
        if not api.advapi32.GetTokenInformation(token, _TOKEN_USER_CLASS, buffer, needed, ctypes.byref(needed)):
            raise _winerror()
        user = ctypes.cast(buffer, ctypes.POINTER(_TOKEN_USER)).contents
        _CURRENT_USER_SID = _sid_string(user.User.Sid)
        return _CURRENT_USER_SID
    except OSError as exc:
        raise KeyCustodyConfigurationError("cannot resolve the current Windows identity") from exc
    finally:
        api.kernel32.CloseHandle(token)


@contextlib.contextmanager
def _private_security_attributes(*, directory: bool) -> Iterator[_SECURITY_ATTRIBUTES]:
    api = _windows_api()
    flags = "OICI" if directory else ""
    sddl = f"D:P(A;{flags};FA;;;SY)(A;{flags};FA;;;BA)(A;{flags};FA;;;{_current_user_sid()})"
    descriptor = ctypes.c_void_p()
    size = wintypes.DWORD()
    if not api.advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW(sddl, _SDDL_REVISION_1, ctypes.byref(descriptor), ctypes.byref(size)):
        raise KeyCustodyConfigurationError("cannot construct the private Windows DACL") from _winerror()
    attributes = _SECURITY_ATTRIBUTES(ctypes.sizeof(_SECURITY_ATTRIBUTES), descriptor, False)
    try:
        yield attributes
    finally:
        api.kernel32.LocalFree(descriptor)


def _validate_private_dacl(handle: int, *, directory: bool) -> None:
    api = _windows_api()
    owner = ctypes.c_void_p()
    dacl = ctypes.c_void_p()
    descriptor = ctypes.c_void_p()
    status = api.advapi32.GetSecurityInfo(wintypes.HANDLE(handle), _SE_FILE_OBJECT, _OWNER_SECURITY_INFORMATION | _DACL_SECURITY_INFORMATION, ctypes.byref(owner), None, ctypes.byref(dacl), None, ctypes.byref(descriptor))
    if status:
        raise KeyCustodyConfigurationError("cannot inspect the local custody DACL") from _winerror(status)
    try:
        control = wintypes.WORD()
        revision = wintypes.DWORD()
        if not api.advapi32.GetSecurityDescriptorControl(descriptor, ctypes.byref(control), ctypes.byref(revision)):
            raise _winerror()
        if not (control.value & _SE_DACL_PROTECTED) or not dacl.value:
            raise KeyCustodyConfigurationError("local custody DACL is not protected")
        if _sid_string(owner).upper() != _current_user_sid().upper():
            raise KeyCustodyConfigurationError("local custody owner is not the current operator")
        info = _ACL_SIZE_INFORMATION()
        if not api.advapi32.GetAclInformation(dacl, ctypes.byref(info), ctypes.sizeof(info), _ACL_SIZE_INFORMATION_CLASS):
            raise _winerror()
        ace_flags = 3 if directory else 0
        expected = {"S-1-5-18": (_FILE_ALL_ACCESS, ace_flags), "S-1-5-32-544": (_FILE_ALL_ACCESS, ace_flags), _current_user_sid().upper(): (_FILE_ALL_ACCESS, ace_flags)}
        observed: dict[str, tuple[int, int]] = {}
        for index in range(info.AceCount):
            pointer = ctypes.c_void_p()
            if not api.advapi32.GetAce(dacl, index, ctypes.byref(pointer)):
                raise _winerror()
            ace = ctypes.cast(pointer, ctypes.POINTER(_ACCESS_ALLOWED_ACE)).contents
            if ace.Header.AceType != _ACCESS_ALLOWED_ACE_TYPE:
                raise KeyCustodyConfigurationError("local custody DACL contains an unexpected ACE type")
            if ace.Header.AceFlags & _INHERITED_ACE:
                raise KeyCustodyConfigurationError("local custody DACL contains inherited access")
            sid = _sid_string(ctypes.c_void_p(pointer.value + _ACCESS_ALLOWED_ACE.SidStart.offset)).upper()
            if sid in observed:
                raise KeyCustodyConfigurationError("local custody DACL contains duplicate trustees")
            observed[sid] = (int(ace.Mask), int(ace.Header.AceFlags))
        if observed != expected:
            raise KeyCustodyConfigurationError("local custody DACL grants unexpected access")
    except KeyCustodyConfigurationError:
        raise
    except OSError as exc:
        raise KeyCustodyConfigurationError("cannot validate the local custody DACL") from exc
    finally:
        api.kernel32.LocalFree(descriptor)


def _normalize_handle_path(value: str) -> Path:
    if value.startswith("\\\\?\\UNC\\"):
        value = "\\\\" + value[8:]
    elif value.startswith("\\\\?\\"):
        value = value[4:]
    return Path(os.path.abspath(value))


def _same_path(left: Path, right: Path) -> bool:
    return os.path.normcase(os.path.abspath(left)) == os.path.normcase(os.path.abspath(right))


def _is_within(path: Path, root: Path) -> bool:
    try:
        common = os.path.commonpath([os.path.abspath(path), os.path.abspath(root)])
    except ValueError:
        return False
    return os.path.normcase(common) == os.path.normcase(os.path.abspath(root))


def _validate_handle_path(handle: int, expected: Path) -> None:
    api = _windows_api()
    tag = _FILE_ATTRIBUTE_TAG_INFO()
    if not api.kernel32.GetFileInformationByHandleEx(wintypes.HANDLE(handle), _FILE_ATTRIBUTE_TAG_INFO_CLASS, ctypes.byref(tag), ctypes.sizeof(tag)):
        raise KeyCustodyConfigurationError("cannot inspect the opened custody object") from _winerror()
    if tag.FileAttributes & _FILE_ATTRIBUTE_REPARSE_POINT:
        raise KeyCustodyConfigurationError("reparse points are forbidden in the custody namespace")
    size = api.kernel32.GetFinalPathNameByHandleW(wintypes.HANDLE(handle), None, 0, 0)
    if not size:
        raise KeyCustodyConfigurationError("cannot resolve the opened custody object") from _winerror()
    buffer = ctypes.create_unicode_buffer(size + 1)
    written = api.kernel32.GetFinalPathNameByHandleW(wintypes.HANDLE(handle), buffer, len(buffer), 0)
    if not written or written >= len(buffer):
        raise KeyCustodyConfigurationError("cannot resolve the opened custody object") from _winerror()
    actual = _normalize_handle_path(buffer.value)
    if not _same_path(actual, expected):
        raise KeyCustodyConfigurationError("opened custody object does not match its configured path")
    if _is_within(actual, _repository_root()):
        raise KeyCustodyConfigurationError("local key custody path must remain outside the repository")


def _create_file_handle(path: Path, *, access: int, share: int, disposition: int, directory: bool = False, private_acl: bool = False) -> int:
    api = _windows_api()
    flags = _FILE_FLAG_OPEN_REPARSE_POINT | (_FILE_FLAG_BACKUP_SEMANTICS if directory else _FILE_ATTRIBUTE_NORMAL)
    with contextlib.ExitStack() as stack:
        attributes = None
        if private_acl:
            security = stack.enter_context(_private_security_attributes(directory=directory))
            attributes = ctypes.byref(security)
        raw = api.kernel32.CreateFileW(str(path), access, share, attributes, disposition, flags, None)
    value = ctypes.cast(raw, ctypes.c_void_p).value
    if value == ctypes.c_void_p(-1).value:
        error = ctypes.get_last_error()
        if error in {_ERROR_FILE_NOT_FOUND, _ERROR_PATH_NOT_FOUND}:
            raise FileNotFoundError(error, os.strerror(error), str(path))
        if error in {_ERROR_FILE_EXISTS, _ERROR_ALREADY_EXISTS}:
            raise FileExistsError(error, os.strerror(error), str(path))
        if error == _ERROR_ACCESS_DENIED:
            raise PermissionError(error, os.strerror(error), str(path))
        raise _winerror(error)
    return int(value)


def _open_directory(path: Path, *, private: bool) -> int:
    handle = _create_file_handle(path, access=_READ_CONTROL | _FILE_READ_ATTRIBUTES, share=_FILE_SHARE_READ | _FILE_SHARE_WRITE, disposition=_OPEN_EXISTING, directory=True)
    try:
        _validate_handle_path(handle, path)
        if private:
            _validate_private_dacl(handle, directory=True)
        return handle
    except BaseException:
        _close_handle(handle)
        raise


def _create_secure_directory(path: Path) -> None:
    api = _windows_api()
    with _private_security_attributes(directory=True) as security:
        if not api.kernel32.CreateDirectoryW(str(path), ctypes.byref(security)):
            error = ctypes.get_last_error()
            if error != _ERROR_ALREADY_EXISTS:
                raise KeyCustodyConfigurationError("cannot create the private custody directory") from _winerror(error)


def _directory_chain(path: Path) -> list[Path]:
    absolute = Path(os.path.abspath(path))
    current = Path(absolute.anchor)
    result = [current]
    for part in absolute.parts[1:]:
        current /= part
        result.append(current)
    return result


def _default_parts(path: Path) -> tuple[Path, list[Path]] | None:
    value = os.environ.get("LOCALAPPDATA")
    if not value:
        return None
    base = Path(os.path.abspath(value))
    expected = base / "vergi_ai" / "key_custody" / "local_keys.json"
    if not _same_path(path, expected):
        return None
    return base, [base / "vergi_ai", base / "vergi_ai" / "key_custody"]


@contextlib.contextmanager
def _trusted_namespace(path: Path, *, create: bool) -> Iterator[None]:
    """Hold all directory handles so path components cannot be renamed."""
    _windows_api()
    default = _default_parts(path)
    if default is None:
        if path.parent == Path(path.anchor):
            raise KeyCustodyConfigurationError("custody file cannot live in a volume root")
        anchor, secure_directories = path.parent.parent, [path.parent]
    else:
        anchor, secure_directories = default
    handles: list[int] = []
    try:
        for component in _directory_chain(anchor):
            handles.append(_open_directory(component, private=False))
        for directory in secure_directories:
            if create:
                _create_secure_directory(directory)
            handles.append(_open_directory(directory, private=True))
        if not _same_path(secure_directories[-1], path.parent):
            raise KeyCustodyConfigurationError("custody namespace has an invalid parent")
        yield
    except KeyCustodyError:
        raise
    except FileExistsError:
        raise
    except (FileNotFoundError, PermissionError, OSError) as exc:
        error_type = KeyCustodyConfigurationError if create else KeyCustodyProviderUnavailableError
        raise error_type("local custody namespace is unavailable or unsafe") from exc
    finally:
        for handle in reversed(handles):
            _close_handle(handle)


def _open_validated_file(path: Path) -> int:
    last_error: BaseException | None = None
    for attempt in range(50):
        try:
            handle = _create_file_handle(path, access=_GENERIC_READ | _READ_CONTROL | _FILE_READ_ATTRIBUTES, share=_FILE_SHARE_READ | _FILE_SHARE_WRITE | _FILE_SHARE_DELETE, disposition=_OPEN_EXISTING)
            try:
                _validate_handle_path(handle, path)
                _validate_private_dacl(handle, directory=False)
                return handle
            except BaseException:
                _close_handle(handle)
                raise
        except PermissionError as exc:
            last_error = exc
            if attempt == 49:
                break
            time.sleep(_RETRY_SECONDS)
    raise KeyCustodyProviderUnavailableError("local key custody file is unavailable") from last_error


def _read_handle_bytes(handle: int) -> bytes:
    import msvcrt
    try:
        descriptor = msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY)
    except BaseException:
        _close_handle(handle)
        raise
    with os.fdopen(descriptor, "rb", closefd=True) as stream:
        return stream.read()


def _write_secure_temporary(path: Path, payload: bytes) -> Path:
    import msvcrt
    for _ in range(100):
        temporary = path.parent / f".{path.name}.{secrets.token_hex(16)}.tmp"
        try:
            handle = _create_file_handle(temporary, access=_GENERIC_READ | _GENERIC_WRITE | _READ_CONTROL | _FILE_READ_ATTRIBUTES, share=_FILE_SHARE_READ, disposition=_CREATE_NEW, private_acl=True)
        except FileExistsError:
            continue
        try:
            _validate_handle_path(handle, temporary)
            _validate_private_dacl(handle, directory=False)
            descriptor = msvcrt.open_osfhandle(handle, os.O_WRONLY | os.O_BINARY)
            handle = 0
            with os.fdopen(descriptor, "wb", closefd=True) as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            return temporary
        except BaseException:
            if handle:
                _close_handle(handle)
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass
            raise
    raise KeyCustodyProviderUnavailableError("cannot allocate a secure custody temporary file")


def _publish_payload(path: Path, payload: bytes, *, replace: bool) -> None:
    """Publish at one commit point; no fallible hardening follows it."""
    temporary = _write_secure_temporary(path, payload)
    committed = False
    try:
        operation = os.replace if replace else os.rename
        for attempt in range(50):
            try:
                operation(temporary, path)  # The single commit point.
                committed = True
                return
            except PermissionError:
                if attempt == 49:
                    raise
                time.sleep(_RETRY_SECONDS)
    finally:
        if not committed:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass


@contextlib.contextmanager
def _mutation_lock(path: Path, *, timeout: float = _LOCK_TIMEOUT_SECONDS) -> Iterator[None]:
    api = _windows_api()
    lock_path = path.parent / _LOCK_FILE_NAME
    handle = _create_file_handle(lock_path, access=_GENERIC_READ | _GENERIC_WRITE | _READ_CONTROL | _FILE_READ_ATTRIBUTES, share=_FILE_SHARE_READ | _FILE_SHARE_WRITE, disposition=_OPEN_ALWAYS, private_acl=True)
    overlap = _OVERLAPPED()
    locked = False
    try:
        _validate_handle_path(handle, lock_path)
        _validate_private_dacl(handle, directory=False)
        deadline = time.monotonic() + timeout
        while True:
            if api.kernel32.LockFileEx(wintypes.HANDLE(handle), _LOCKFILE_EXCLUSIVE_LOCK | _LOCKFILE_FAIL_IMMEDIATELY, 0, 1, 0, ctypes.byref(overlap)):
                locked = True
                break
            error = ctypes.get_last_error()
            if error not in {_ERROR_LOCK_VIOLATION, _ERROR_SHARING_VIOLATION}:
                raise KeyCustodyProviderUnavailableError("local key custody mutation lock is unavailable") from _winerror(error)
            if time.monotonic() >= deadline:
                raise KeyCustodyProviderUnavailableError("local key custody mutation lock timed out")
            time.sleep(_RETRY_SECONDS)
        yield
    finally:
        if locked:
            api.kernel32.UnlockFileEx(wintypes.HANDLE(handle), 0, 1, 0, ctypes.byref(overlap))
        _close_handle(handle)


def _reject_duplicate_fields(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for name, value in pairs:
        if name in result:
            raise KeyCustodyDocumentError(f"duplicate JSON field: {name}")
        result[name] = value
    return result


def _reject_non_json_number(value: str) -> None:
    raise KeyCustodyDocumentError(f"non-JSON numeric value is not allowed: {value}")


def _decode_base64(value: Any, *, field_name: str) -> bytes:
    if not isinstance(value, str) or not value:
        raise KeyCustodyDocumentError(f"{field_name} must be a non-empty base64 string")
    try:
        decoded = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise KeyCustodyDocumentError(f"{field_name} is not valid base64") from exc
    if base64.b64encode(decoded).decode("ascii") != value:
        raise KeyCustodyDocumentError(f"{field_name} is not canonical base64")
    return decoded


def _validate_key_id(value: Any, *, field_name: str) -> str:
    if not isinstance(value, str) or _KEY_ID_PATTERN.fullmatch(value) is None:
        raise KeyCustodyDocumentError(f"{field_name} is not a valid local key id")
    return value


def _parse_document_bytes(raw: bytes) -> _CustodyMaterial:
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise KeyCustodyDocumentError("local key custody file is not valid UTF-8") from exc
    try:
        document = json.loads(text, object_pairs_hook=_reject_duplicate_fields, parse_constant=_reject_non_json_number)
    except KeyCustodyDocumentError:
        raise
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        raise KeyCustodyDocumentError("local key custody file is not valid JSON") from exc
    if not isinstance(document, dict):
        raise KeyCustodyDocumentError("local key custody document must be an object")
    fields = frozenset(document)
    if fields != _DOCUMENT_FIELDS:
        missing = sorted(_DOCUMENT_FIELDS - fields)
        extra = sorted(fields - _DOCUMENT_FIELDS)
        detail = []
        if missing:
            detail.append(f"missing fields: {', '.join(missing)}")
        if extra:
            detail.append(f"unexpected fields: {', '.join(extra)}")
        raise KeyCustodyDocumentError("invalid local key custody fields (" + "; ".join(detail) + ")")
    version = document["version"]
    if isinstance(version, bool) or not isinstance(version, int) or version != 1:
        raise KeyCustodyDocumentError("local key custody version must be integer 1")
    current_key_id = _validate_key_id(document["current_key_id"], field_name="current_key_id")
    encoded_keys = document["keys"]
    if not isinstance(encoded_keys, dict):
        raise KeyCustodyDocumentError("keys must be an object")
    keys: dict[str, bytes] = {}
    for raw_key_id, encoded_key in encoded_keys.items():
        key_id = _validate_key_id(raw_key_id, field_name="keys field")
        key = _decode_base64(encoded_key, field_name=f"key {key_id}")
        if len(key) != 32:
            raise KeyCustodyDocumentError(f"key {key_id} must decode to exactly 32 bytes")
        keys[key_id] = key
    if current_key_id not in keys:
        raise KeyCustodyDocumentError("current_key_id is absent from keys")
    server_pepper = _decode_base64(document["server_pepper"], field_name="server_pepper")
    if len(server_pepper) < 32:
        raise KeyCustodyDocumentError("server_pepper must decode to at least 32 bytes")
    return _CustodyMaterial(current_key_id, keys, server_pepper)


def _repository_root() -> Path:
    return Path(__file__).absolute().parents[2]


def resolve_local_key_path(path: str | os.PathLike[str] | None = None) -> Path:
    """Normalize without following links and reject repository-contained paths."""
    if path is None:
        local_app_data = os.environ.get("LOCALAPPDATA")
        if not local_app_data:
            raise KeyCustodyConfigurationError("LOCALAPPDATA is required for the local_file key provider")
        candidate = Path(local_app_data) / "vergi_ai" / "key_custody" / "local_keys.json"
    else:
        candidate = Path(path)
    if not candidate.is_absolute():
        raise KeyCustodyConfigurationError("local key custody path must be absolute")
    normalized = Path(os.path.abspath(os.path.normpath(candidate)))
    if _is_within(normalized, _repository_root()):
        raise KeyCustodyConfigurationError("local key custody path must remain outside the repository")
    return normalized


def _load_material_from_trusted_namespace(path: Path) -> _CustodyMaterial:
    try:
        handle = _open_validated_file(path)
    except FileNotFoundError as exc:
        raise KeyCustodyProviderUnavailableError("local key custody file is missing") from exc
    return _parse_document_bytes(_read_handle_bytes(handle))


def _load_material(path: str | os.PathLike[str] | None = None) -> _CustodyMaterial:
    resolved = resolve_local_key_path(path)
    with _trusted_namespace(resolved, create=False):
        return _load_material_from_trusted_namespace(resolved)


def _serialize_material(material: _CustodyMaterial) -> bytes:
    document = {
        "version": 1,
        "current_key_id": material.current_key_id,
        "keys": {key_id: base64.b64encode(key).decode("ascii") for key_id, key in sorted(material.keys.items())},
        "server_pepper": base64.b64encode(material.server_pepper).decode("ascii"),
    }
    return (json.dumps(document, indent=2, ensure_ascii=True) + "\n").encode("utf-8")


def initialize_secure_document(create: Callable[[], _CustodyMaterial], path: str | os.PathLike[str] | None = None) -> Path:
    resolved = resolve_local_key_path(path)
    with _trusted_namespace(resolved, create=True):
        with _mutation_lock(resolved):
            try:
                existing = _open_validated_file(resolved)
            except FileNotFoundError:
                existing = 0
            if existing:
                _close_handle(existing)
                raise FileExistsError(f"local key custody file already exists: {resolved}")
            material = create()
            _publish_payload(resolved, _serialize_material(material), replace=False)
    return resolved


_T = TypeVar("_T")


def mutate_secure_document(transform: Callable[[_CustodyMaterial], tuple[_CustodyMaterial, _T]], path: str | os.PathLike[str] | None = None) -> tuple[Path, _T]:
    """Serialize the complete read/modify/secure-temp/publish transaction."""
    resolved = resolve_local_key_path(path)
    with _trusted_namespace(resolved, create=False):
        with _mutation_lock(resolved):
            material = _load_material_from_trusted_namespace(resolved)
            replacement, result = transform(material)
            _publish_payload(resolved, _serialize_material(replacement), replace=True)
    return resolved, result


class LocalFileKeyProvider:
    """Immutable snapshot implementing ``transient_secrets.KeyProvider``."""

    def __init__(self, path: str | os.PathLike[str] | None = None) -> None:
        self._material = _load_material(path)

    def get_key(self, key_id: str) -> bytes:
        try:
            return self._material.keys[key_id]
        except KeyError:
            raise UnknownKeyError(key_id) from None

    def current_key_id(self) -> str:
        return self._material.current_key_id


def _selected_provider_kind() -> str:
    kind = os.environ.get("VERGI_KEY_PROVIDER_KIND")
    if kind is None:
        raise KeyCustodyConfigurationError("VERGI_KEY_PROVIDER_KIND is required; choose local_file or kms explicitly")
    if kind == "":
        raise KeyCustodyConfigurationError("VERGI_KEY_PROVIDER_KIND must not be empty; choose local_file or kms explicitly")
    if kind not in {_LOCAL_PROVIDER_KIND, _KMS_PROVIDER_KIND, _AZURE_PROVIDER_KIND}:
        raise KeyCustodyConfigurationError(f"unknown VERGI_KEY_PROVIDER_KIND: {kind!r}; expected local_file or kms")
    return kind


def get_configured_key_provider() -> Any:
    kind = _selected_provider_kind()
    if kind == _KMS_PROVIDER_KIND:
        raise KmsProviderNotImplementedError("VERGI_KEY_PROVIDER_KIND='kms' is not implemented in Row 19D Slice 1")
    if kind == _AZURE_PROVIDER_KIND:
        from .azure_key_vault_custody import get_azure_custody_manager

        return get_azure_custody_manager().get_key_provider()
    return LocalFileKeyProvider()


def get_configured_server_pepper() -> bytes:
    kind = _selected_provider_kind()
    if kind == _KMS_PROVIDER_KIND:
        raise KmsProviderNotImplementedError("VERGI_KEY_PROVIDER_KIND='kms' is not implemented in Row 19D Slice 1")
    if kind == _AZURE_PROVIDER_KIND:
        from .azure_key_vault_custody import get_azure_custody_manager

        return get_azure_custody_manager().get_server_pepper()
    return _load_material().server_pepper


async def get_configured_key_provider_async() -> Any:
    kind = _selected_provider_kind()
    if kind == _KMS_PROVIDER_KIND:
        raise KmsProviderNotImplementedError("VERGI_KEY_PROVIDER_KIND='kms' is not implemented in Row 19D Slice 1")
    if kind == _AZURE_PROVIDER_KIND:
        from .azure_key_vault_custody import get_azure_custody_manager

        return await get_azure_custody_manager().get_key_provider_async()
    return await asyncio.to_thread(LocalFileKeyProvider)


async def get_configured_server_pepper_async() -> bytes:
    kind = _selected_provider_kind()
    if kind == _KMS_PROVIDER_KIND:
        raise KmsProviderNotImplementedError("VERGI_KEY_PROVIDER_KIND='kms' is not implemented in Row 19D Slice 1")
    if kind == _AZURE_PROVIDER_KIND:
        from .azure_key_vault_custody import get_azure_custody_manager

        return await get_azure_custody_manager().get_server_pepper_async()
    return await asyncio.to_thread(lambda: _load_material().server_pepper)
