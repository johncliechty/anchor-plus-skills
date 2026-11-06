"""Optional API credentials in the host OS credential vault, never in JSON."""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import hashlib
import os

import paths


def available():
    return os.name == "nt"


def _target(identity):
    namespace = hashlib.sha256(str(paths.data_dir()).encode()).hexdigest()[:24]
    return "Anchor/provider-api/" + namespace + "/" + identity


class Credential(ctypes.Structure):
    _fields_ = [("Flags", wintypes.DWORD), ("Type", wintypes.DWORD), ("TargetName", wintypes.LPWSTR),
                ("Comment", wintypes.LPWSTR), ("LastWritten", wintypes.FILETIME),
                ("CredentialBlobSize", wintypes.DWORD), ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
                ("Persist", wintypes.DWORD), ("AttributeCount", wintypes.DWORD), ("Attributes", ctypes.c_void_p),
                ("TargetAlias", wintypes.LPWSTR), ("UserName", wintypes.LPWSTR)]


_MAX_BLOB_BYTES = 2000
_CHUNK_PREFIX = "__ANCHOR_CHUNKED__:"


def _cred_write_raw(target_name: str, raw: bytes) -> None:
    dll = ctypes.WinDLL("advapi32", use_last_error=True)
    dll.CredWriteW.argtypes = [ctypes.POINTER(Credential), wintypes.DWORD]
    dll.CredWriteW.restype = wintypes.BOOL
    blob = (ctypes.c_ubyte * len(raw)).from_buffer_copy(raw)
    credential = Credential(
        Type=1,
        TargetName=target_name,
        CredentialBlobSize=len(raw),
        CredentialBlob=blob,
        Persist=2,
        UserName="Anchor API connection",
    )
    try:
        if not dll.CredWriteW(ctypes.byref(credential), 0):
            raise ValueError("Secure host API credential storage failed")
    finally:
        ctypes.memset(blob, 0, len(raw))


def _cred_read_raw(target_name: str) -> str | None:
    dll = ctypes.WinDLL("advapi32", use_last_error=True)
    dll.CredReadW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.POINTER(ctypes.POINTER(Credential)),
    ]
    dll.CredReadW.restype = wintypes.BOOL
    dll.CredFree.argtypes = [ctypes.c_void_p]
    credential = ctypes.POINTER(Credential)()
    if not dll.CredReadW(target_name, 1, 0, ctypes.byref(credential)):
        return None
    try:
        return ctypes.string_at(
            credential.contents.CredentialBlob,
            credential.contents.CredentialBlobSize,
        ).decode("utf-8")
    finally:
        dll.CredFree(credential)


def _cred_delete_raw(target_name: str) -> None:
    dll = ctypes.WinDLL("advapi32", use_last_error=True)
    dll.CredDeleteW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
    dll.CredDeleteW.restype = wintypes.BOOL
    dll.CredDeleteW(target_name, 1, 0)


def put(identity, secret):
    if not available():
        raise ValueError("Secure host API storage is unavailable on this platform")
    raw = secret.encode("utf-8")
    base_target = _target(identity)
    if len(raw) <= _MAX_BLOB_BYTES:
        _cred_write_raw(base_target, raw)
        return
    chunks = [raw[i : i + _MAX_BLOB_BYTES] for i in range(0, len(raw), _MAX_BLOB_BYTES)]
    for idx, ch in enumerate(chunks):
        _cred_write_raw(f"{base_target}#chunk{idx}", ch)
    header = f"{_CHUNK_PREFIX}{len(chunks)}".encode("utf-8")
    _cred_write_raw(base_target, header)


def get(identity):
    if not available():
        return None
    base_target = _target(identity)
    val = _cred_read_raw(base_target)
    if val is None:
        return None
    if val.startswith(_CHUNK_PREFIX):
        try:
            count = int(val[len(_CHUNK_PREFIX) :])
        except ValueError:
            return None
        parts = []
        for idx in range(count):
            part = _cred_read_raw(f"{base_target}#chunk{idx}")
            if part is None:
                return None
            parts.append(part)
        return "".join(parts)
    return val


def delete(identity):
    if not available():
        return
    base_target = _target(identity)
    val = _cred_read_raw(base_target)
    if val and val.startswith(_CHUNK_PREFIX):
        try:
            count = int(val[len(_CHUNK_PREFIX) :])
            for idx in range(count):
                _cred_delete_raw(f"{base_target}#chunk{idx}")
        except ValueError:
            pass
    _cred_delete_raw(base_target)
