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


def put(identity, secret):
    if not available():
        raise ValueError("Secure host API storage is unavailable on this platform")
    dll = ctypes.WinDLL("advapi32", use_last_error=True)
    dll.CredWriteW.argtypes = [ctypes.POINTER(Credential), wintypes.DWORD]
    dll.CredWriteW.restype = wintypes.BOOL
    raw = secret.encode("utf-8")
    blob = (ctypes.c_ubyte * len(raw)).from_buffer_copy(raw)
    credential = Credential(Type=1, TargetName=_target(identity), CredentialBlobSize=len(raw),
                            CredentialBlob=blob, Persist=2, UserName="Anchor API connection")
    try:
        if not dll.CredWriteW(ctypes.byref(credential), 0):
            raise ValueError("Secure host API credential storage failed")
    finally:
        ctypes.memset(blob, 0, len(raw))


def get(identity):
    if not available():
        return None
    dll = ctypes.WinDLL("advapi32", use_last_error=True)
    dll.CredReadW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(ctypes.POINTER(Credential))]
    dll.CredReadW.restype = wintypes.BOOL
    dll.CredFree.argtypes = [ctypes.c_void_p]
    credential = ctypes.POINTER(Credential)()
    if not dll.CredReadW(_target(identity), 1, 0, ctypes.byref(credential)):
        return None
    try:
        return ctypes.string_at(credential.contents.CredentialBlob, credential.contents.CredentialBlobSize).decode("utf-8")
    finally:
        dll.CredFree(credential)
