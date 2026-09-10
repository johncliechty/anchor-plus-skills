"""Subscription Grok transport using the bounded, owned Steward broker.

Grok headless does not consume stdin. Each native turn therefore receives an
ephemeral prompt file outside the project, protected for the current OS user.
Windows files have an explicit protected owner-only ACL, locked owned handles,
and delete-on-close. File/descendant cleanup is a completion gate, not best effort.
"""

from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
import json
import math
import os
from pathlib import Path
import re
import shutil
import signal
import stat
import sys
import tempfile
import uuid
from typing import Any, Callable

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from steward_cockpit.codex_turn_bridge import (
    Broker, BridgeError, DEFAULT_TURN_TIMEOUT_SECONDS, DEFAULT_IDLE_TIMEOUT_SECONDS, EventNormalizer,
    MAX_INPUT_BYTES, _bounded_string, _identifier, emit_json,
)


PERMISSION_MODES = ("plan", "acceptEdits", "bypassPermissions", "dontAsk", "default")
MODEL_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/+\-]{0,191}\Z")


class PromptCleanupError(BridgeError):
    """A private prompt resource could not be proven absent after failure."""


def canonical_session_id(value: Any) -> str:
    if not isinstance(value, str):
        raise BridgeError("Grok session ID must be a UUID")
    try:
        parsed = str(uuid.UUID(value))
    except ValueError as exc:
        raise BridgeError("Grok session ID must be a UUID") from exc
    if parsed != value:
        raise BridgeError("Grok session ID must be a canonical UUID")
    return parsed


def build_argv(executable: str, *, model: str, effort: str, permission_mode: str,
               prompt_file: str, session_id: str, resume: bool) -> list[str]:
    _identifier(model, "model")
    _identifier(effort, "effort")
    canonical_session_id(session_id)
    if permission_mode not in PERMISSION_MODES:
        raise BridgeError("Unsupported Grok permission mode")
    if not isinstance(prompt_file, str) or not prompt_file or "\0" in prompt_file:
        raise BridgeError("Grok requires a private prompt file")
    # --prompt-file selects headless mode itself. -p requires literal text;
    # --prompt-file - is a literal file named '-', NOT standard input.
    return [
        executable, "--prompt-file", prompt_file,
        "--output-format", "streaming-messages-json", "--include-partial-messages",
        "--model", model, "--reasoning-effort", effort,
        "--permission-mode", permission_mode,
        "--resume" if resume else "--session-id", session_id,
    ]


def owner_only_sddl(sid: str) -> str:
    if not re.fullmatch(r"S-1-(?:[0-9]+-)*[0-9]+", sid):
        raise BridgeError("Could not identify the current Windows account")
    return f"O:{sid}D:P(A;OICI;FA;;;{sid})"


class _WindowsAPI:
    """Small Win32 boundary: no shell ACL utilities, environment-selected roots,
    shared temp directory, credential lookup, or process/PID adoption."""

    def __init__(self):
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.advapi = ctypes.WinDLL("advapi32", use_last_error=True)
        self.shell = ctypes.WinDLL("shell32", use_last_error=True)
        self._bind(self.kernel, "GetCurrentProcess", [], wintypes.HANDLE)
        self._bind(self.kernel, "CloseHandle", [wintypes.HANDLE], wintypes.BOOL)
        self._bind(self.kernel, "LocalFree", [ctypes.c_void_p], ctypes.c_void_p)
        self._bind(self.kernel, "GetDriveTypeW", [wintypes.LPCWSTR], wintypes.UINT)
        self._bind(self.kernel, "CreateDirectoryW", [wintypes.LPCWSTR, ctypes.c_void_p], wintypes.BOOL)
        self._bind(self.kernel, "RemoveDirectoryW", [wintypes.LPCWSTR], wintypes.BOOL)
        self._bind(self.kernel, "CreateFileW", [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                   ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE], wintypes.HANDLE)
        self._bind(self.kernel, "WriteFile", [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD,
                   ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p], wintypes.BOOL)
        self._bind(self.kernel, "FlushFileBuffers", [wintypes.HANDLE], wintypes.BOOL)
        self._bind(self.kernel, "SetFileInformationByHandle", [wintypes.HANDLE, ctypes.c_int,
                   ctypes.c_void_p, wintypes.DWORD], wintypes.BOOL)
        self._bind(self.kernel, "GetFileInformationByHandleEx", [wintypes.HANDLE, ctypes.c_int,
                   ctypes.c_void_p, wintypes.DWORD], wintypes.BOOL)
        self._bind(self.advapi, "OpenProcessToken", [wintypes.HANDLE, wintypes.DWORD,
                   ctypes.POINTER(wintypes.HANDLE)], wintypes.BOOL)
        self._bind(self.advapi, "GetTokenInformation", [wintypes.HANDLE, ctypes.c_int,
                   ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)], wintypes.BOOL)
        self._bind(self.advapi, "ConvertSidToStringSidW", [ctypes.c_void_p,
                   ctypes.POINTER(wintypes.LPWSTR)], wintypes.BOOL)
        self._bind(self.advapi, "ConvertStringSidToSidW", [wintypes.LPCWSTR,
                   ctypes.POINTER(ctypes.c_void_p)], wintypes.BOOL)
        self._bind(self.advapi, "ConvertStringSecurityDescriptorToSecurityDescriptorW",
                   [wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p),
                    ctypes.POINTER(wintypes.DWORD)], wintypes.BOOL)
        self._bind(self.advapi, "GetKernelObjectSecurity", [wintypes.HANDLE, wintypes.DWORD,
                   ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)], wintypes.BOOL)
        self._bind(self.advapi, "GetSecurityDescriptorControl", [ctypes.c_void_p,
                   ctypes.POINTER(wintypes.WORD), ctypes.POINTER(wintypes.DWORD)], wintypes.BOOL)
        self._bind(self.advapi, "GetSecurityDescriptorDacl", [ctypes.c_void_p,
                   ctypes.POINTER(wintypes.BOOL), ctypes.POINTER(ctypes.c_void_p),
                   ctypes.POINTER(wintypes.BOOL)], wintypes.BOOL)
        self._bind(self.advapi, "GetSecurityDescriptorOwner", [ctypes.c_void_p,
                   ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(wintypes.BOOL)], wintypes.BOOL)
        self._bind(self.advapi, "GetAce", [ctypes.c_void_p, wintypes.DWORD,
                   ctypes.POINTER(ctypes.c_void_p)], wintypes.BOOL)
        self._bind(self.advapi, "EqualSid", [ctypes.c_void_p, ctypes.c_void_p], wintypes.BOOL)
        self._bind(self.shell, "SHGetFolderPathW", [wintypes.HWND, ctypes.c_int, wintypes.HANDLE,
                   wintypes.DWORD, wintypes.LPWSTR], ctypes.c_long)

    @staticmethod
    def _bind(library, name, arguments, result):
        function = getattr(library, name)
        function.argtypes, function.restype = arguments, result

    def current_sid(self) -> str:
        token = wintypes.HANDLE()
        if not self.advapi.OpenProcessToken(self.kernel.GetCurrentProcess(), 0x0008, ctypes.byref(token)):
            raise BridgeError("Could not inspect current Windows account")
        try:
            required = wintypes.DWORD()
            self.advapi.GetTokenInformation(token, 1, None, 0, ctypes.byref(required))
            if not required.value:
                raise BridgeError("Could not identify current Windows account")
            buffer = ctypes.create_string_buffer(required.value)
            if not self.advapi.GetTokenInformation(token, 1, buffer, required, ctypes.byref(required)):
                raise BridgeError("Could not identify current Windows account")
            sid = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_void_p))[0]
            string_sid = wintypes.LPWSTR()
            if not self.advapi.ConvertSidToStringSidW(sid, ctypes.byref(string_sid)):
                raise BridgeError("Could not format current Windows account")
            try:
                return string_sid.value
            finally:
                self.kernel.LocalFree(string_sid)
        finally:
            self.kernel.CloseHandle(token)

    def private_root(self) -> Path:
        buffer = ctypes.create_unicode_buffer(32768)
        if self.shell.SHGetFolderPathW(None, 0x001C, None, 0, buffer) != 0:
            raise BridgeError("Current account has no local application-data directory")
        root = Path(buffer.value).resolve(strict=True)
        drive = os.path.splitdrive(str(root))[0]
        if not drive or str(root).startswith("\\\\") or self.kernel.GetDriveTypeW(drive + "\\") != 3:
            raise BridgeError("Private Grok prompts require current-account storage on a local fixed drive")
        if not root.is_dir():
            raise BridgeError("Current account application-data directory is unavailable")
        return root

    def assert_private(self, handle, sid: str) -> None:
        required = wintypes.DWORD()
        self.advapi.GetKernelObjectSecurity(handle, 0x00000005, None, 0, ctypes.byref(required))
        if not required.value:
            raise BridgeError("Cannot verify private prompt permissions")
        descriptor = ctypes.create_string_buffer(required.value)
        if not self.advapi.GetKernelObjectSecurity(handle, 5, descriptor, required, ctypes.byref(required)):
            raise BridgeError("Cannot verify private prompt permissions")
        control, revision = wintypes.WORD(), wintypes.DWORD()
        present, defaulted, acl = wintypes.BOOL(), wintypes.BOOL(), ctypes.c_void_p()
        owner, expected_sid = ctypes.c_void_p(), ctypes.c_void_p()
        if not self.advapi.ConvertStringSidToSidW(sid, ctypes.byref(expected_sid)):
            raise BridgeError("Cannot verify private prompt owner")
        try:
            checks = (
                self.advapi.GetSecurityDescriptorControl(descriptor, ctypes.byref(control), ctypes.byref(revision)),
                self.advapi.GetSecurityDescriptorDacl(descriptor, ctypes.byref(present), ctypes.byref(acl), ctypes.byref(defaulted)),
                self.advapi.GetSecurityDescriptorOwner(descriptor, ctypes.byref(owner), ctypes.byref(defaulted)),
            )
            if not all(checks) or not control.value & 0x1000 or not present.value or not acl.value:
                raise BridgeError("Private prompt ACL is not protected")
            if not self.advapi.EqualSid(owner, expected_sid):
                raise BridgeError("Private prompt owner does not match the current account")
            # ACL header: revision, reserved, size, ACE count, reserved.
            if ctypes.c_ushort.from_address(acl.value + 4).value != 1:
                raise BridgeError("Private prompt ACL grants additional access")
            ace = ctypes.c_void_p()
            if not self.advapi.GetAce(acl, 0, ctypes.byref(ace)):
                raise BridgeError("Cannot verify private prompt access entry")
            if (ctypes.c_ubyte.from_address(ace.value).value != 0
                    or ctypes.c_uint32.from_address(ace.value + 4).value != 0x001F01FF
                    or not self.advapi.EqualSid(ace.value + 8, expected_sid)):
                raise BridgeError("Private prompt ACL is not current-account-only")
        finally:
            self.kernel.LocalFree(expected_sid)

    def mark_delete(self, handle) -> bool:
        delete = wintypes.BOOL(True)
        return bool(self.kernel.SetFileInformationByHandle(handle, 4, ctypes.byref(delete), ctypes.sizeof(delete)))


class WindowsPrivatePrompt:
    """Atomic owner-only ACL creation; owned handles identify cleanup targets."""

    def __init__(self, payload: bytes):
        self.api = _WindowsAPI()
        self.file_handle = self.directory_handle = None
        self.path = self.directory = None
        descriptor = ctypes.c_void_p()
        try:
            sid = self.api.current_sid()
            root = self.api.private_root()
            if not self.api.advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW(
                owner_only_sddl(sid), 1, ctypes.byref(descriptor), None,
            ):
                raise BridgeError("Could not establish private prompt permissions")

            class SecurityAttributes(ctypes.Structure):
                _fields_ = [("nLength", wintypes.DWORD), ("lpSecurityDescriptor", ctypes.c_void_p),
                            ("bInheritHandle", wintypes.BOOL)]

            attributes = SecurityAttributes(ctypes.sizeof(SecurityAttributes), descriptor, False)
            self.directory = root / ("anchor-grok-" + uuid.uuid4().hex)
            if not self.api.kernel.CreateDirectoryW(str(self.directory), ctypes.byref(attributes)):
                self.directory = None  # Never remove a directory that we did not create.
                raise BridgeError("Could not create a private Grok prompt directory")
            self.path = self.directory / "prompt.txt"
            invalid = ctypes.c_void_p(-1).value
            self.directory_handle = self.api.kernel.CreateFileW(
                str(self.directory), 0x00010000 | 0x00020000 | 0x80, 1,
                None, 3, 0x02000000 | 0x00200000, None,
            )
            if self.directory_handle in (None, invalid):
                self.directory_handle = None
                raise BridgeError("Could not lock the owned prompt directory")
            self.api.assert_private(self.directory_handle, sid)
            self.file_handle = self.api.kernel.CreateFileW(
                str(self.path), 0x80000000 | 0x40000000 | 0x00010000 | 0x00020000,
                1, ctypes.byref(attributes), 1,
                0x00000100 | 0x00200000 | 0x04000000, None,
            )
            if self.file_handle in (None, invalid):
                self.file_handle = None
                raise BridgeError("Could not create a private Grok prompt file")
            self.api.assert_private(self.file_handle, sid)
            for handle in (self.directory_handle, self.file_handle):
                attributes_and_tag = (wintypes.DWORD * 2)()
                if not self.api.kernel.GetFileInformationByHandleEx(
                    handle, 9, attributes_and_tag, ctypes.sizeof(attributes_and_tag),
                ):
                    raise BridgeError("Could not verify the owned prompt path attributes")
                if attributes_and_tag[0] & 0x400:
                    raise BridgeError("Private prompt paths cannot be reparse points")
            for offset in range(0, len(payload), 65536):
                chunk = payload[offset:offset + 65536]
                buffer = ctypes.create_string_buffer(chunk)
                written = wintypes.DWORD()
                if (not self.api.kernel.WriteFile(self.file_handle, buffer, len(chunk), ctypes.byref(written), None)
                        or written.value != len(chunk)):
                    raise BridgeError("Could not write the private Grok prompt")
            if not self.api.kernel.FlushFileBuffers(self.file_handle):
                raise BridgeError("Could not flush the private Grok prompt")
        except Exception as exc:
            try:
                self.close()
            except Exception as cleanup:
                raise PromptCleanupError("Private prompt setup and owned cleanup failed") from cleanup
            if isinstance(exc, BridgeError):
                raise
            raise BridgeError("Could not establish a private Grok prompt file") from exc
        finally:
            if descriptor.value:
                self.api.kernel.LocalFree(descriptor)

    def close(self) -> None:
        failures = []
        if self.file_handle is not None:
            if not self.api.mark_delete(self.file_handle):
                failures.append("Prompt file deletion was not confirmed")
            if not self.api.kernel.CloseHandle(self.file_handle):
                failures.append("Prompt file handle cleanup failed")
            self.file_handle = None
        if self.path is not None and os.path.lexists(self.path):
            failures.append("Private prompt file remains after cleanup")
        if self.directory_handle is not None:
            if not self.api.mark_delete(self.directory_handle):
                failures.append("Prompt directory deletion was not confirmed")
            if not self.api.kernel.CloseHandle(self.directory_handle):
                failures.append("Prompt directory handle cleanup failed")
            self.directory_handle = None
        elif self.directory is not None and os.path.lexists(self.directory):
            # This fallback only follows our own successful CreateDirectory
            # when opening its handle failed; never recursive and never shared.
            if not self.api.kernel.RemoveDirectoryW(str(self.directory)):
                failures.append("Owned prompt directory cleanup failed")
        if self.directory is not None and os.path.lexists(self.directory):
            failures.append("Private prompt directory remains after cleanup")
        if failures:
            raise BridgeError("; ".join(failures))


class PosixPrivatePrompt:
    """A 0700 directory in the current account's home, with a 0600 file."""

    def __init__(self, payload: bytes):
        self.directory = self.path = None
        self.directory_fd = self.file_fd = None
        self.directory_identity = self.file_identity = None
        try:
            root = Path.home().resolve(strict=True)
            root_stat = root.stat()
            if root_stat.st_uid != os.getuid() or root_stat.st_mode & 0o022:
                raise BridgeError("Private Grok prompts require a current-account-owned, non-shared home")
            self.directory = Path(tempfile.mkdtemp(prefix=".anchor-grok-", dir=str(root)))
            self.path = self.directory / "prompt.txt"
            self.directory_fd = os.open(self.directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            directory_stat = os.fstat(self.directory_fd)
            self.directory_identity = (directory_stat.st_dev, directory_stat.st_ino)
            if directory_stat.st_uid != os.getuid() or stat.S_IMODE(directory_stat.st_mode) != 0o700:
                raise BridgeError("Private Grok prompt directory permissions were not confirmed")
            self.file_fd = os.open("prompt.txt", os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                                   0o600, dir_fd=self.directory_fd)
            file_stat = os.fstat(self.file_fd)
            self.file_identity = (file_stat.st_dev, file_stat.st_ino)
            if file_stat.st_uid != os.getuid() or stat.S_IMODE(file_stat.st_mode) != 0o600:
                raise BridgeError("Private Grok prompt file permissions were not confirmed")
            view = memoryview(payload)
            while view:
                written = os.write(self.file_fd, view)
                if written <= 0:
                    raise BridgeError("Could not write the private Grok prompt")
                view = view[written:]
            os.fsync(self.file_fd)
        except Exception as exc:
            try:
                self.close()
            except Exception as cleanup:
                raise PromptCleanupError("Private prompt setup and owned cleanup failed") from cleanup
            if isinstance(exc, BridgeError):
                raise
            raise BridgeError("Could not establish a private Grok prompt file") from exc

    def close(self) -> None:
        failures = []
        if self.file_fd is not None:
            try:
                found = os.stat("prompt.txt", dir_fd=self.directory_fd, follow_symlinks=False)
                if (found.st_dev, found.st_ino) != self.file_identity or not stat.S_ISREG(found.st_mode):
                    raise BridgeError("Owned private prompt identity changed")
                os.unlink("prompt.txt", dir_fd=self.directory_fd)
            except FileNotFoundError:
                pass
            except Exception:
                failures.append("Owned private prompt cleanup failed")
            finally:
                os.close(self.file_fd)
                self.file_fd = None
        if self.directory_fd is not None:
            os.close(self.directory_fd)
            self.directory_fd = None
        if self.directory is not None:
            try:
                found = self.directory.lstat()
                if (found.st_dev, found.st_ino) != self.directory_identity or not stat.S_ISDIR(found.st_mode):
                    raise BridgeError("Owned private directory identity changed")
                self.directory.rmdir()
            except FileNotFoundError:
                pass
            except Exception:
                failures.append("Owned private prompt directory cleanup failed")
        if failures:
            raise BridgeError("; ".join(failures))


def private_prompt(payload: bytes):
    return WindowsPrivatePrompt(payload) if os.name == "nt" else PosixPrivatePrompt(payload)


class GrokNormalizer(EventNormalizer):
    def __init__(self, model: str, effort: str, *, expected_id: str, resume: str | None = None):
        super().__init__(model, effort, resume)
        self.expected_id = canonical_session_id(expected_id)
        self.models_served: list[str] = []
        self._current_message = "partial"
        self._blocks: dict[tuple[str, int], str] = {}

    def _receipt(self):
        return {**super()._receipt(), "provider": "grok", "models_served": list(self.models_served)}

    def _text_delta(self, text: str):
        if not text:
            return []
        self.text.append(text)
        return [{"type": "stream_event", "session_id": self.thread_id, "event": {
            "type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": text},
        }}]

    def _tool(self, block: dict[str, Any]):
        tool_id = _bounded_string(block.get("id"), 256)
        name = _bounded_string(block.get("name"), 120)
        if not tool_id or tool_id in self._tool_items:
            return []
        self._tool_items.add(tool_id)
        return [{"type": "assistant", "session_id": self.thread_id, "message": {
            "role": "assistant", "content": [{"type": "tool_use", "id": tool_id,
                "name": name or "grok_tool", "input": {"provider_tool": name or "grok_tool"}}],
        }}]

    def accept(self, event: dict[str, Any]):
        if self._finished:
            raise BridgeError("Grok event received after its result was finalized")
        if not isinstance(event, dict):
            raise BridgeError("Grok event must be an object")
        session = event.get("session_id")
        if session is not None and canonical_session_id(session) != self.expected_id:
            raise BridgeError("Grok emitted an unexpected session identity")
        kind = event.get("type")
        if kind in ("assistant", "stream_event", "result", "user") and session is None:
            raise BridgeError("Grok turn event omitted its session identity")
        if kind == "system" and event.get("subtype") == "init":
            if session is None:
                raise BridgeError("Grok init omitted its session identity")
            if event.get("apiKeySource") != "oauth":
                raise BridgeError("Grok did not confirm subscription OAuth authentication")
            self.thread_id = self.expected_id
            if self._initialized:
                return []
            self._initialized = True
            return [{"type": "system", "subtype": "init", "session_id": self.thread_id, **self._receipt()}]
        if not self._initialized:
            raise BridgeError("Grok emitted turn data before subscription/session confirmation")
        if kind == "stream_event":
            data = event.get("event")
            if not isinstance(data, dict):
                raise BridgeError("Malformed Grok stream event")
            if data.get("type") == "message_start":
                message = data.get("message", {})
                if isinstance(message, dict) and isinstance(message.get("id"), str):
                    self._current_message = _bounded_string(message["id"], 256)
            index = data.get("index", 0)
            if not isinstance(index, int) or isinstance(index, bool) or index < 0:
                raise BridgeError("Malformed Grok content block index")
            key = (self._current_message, index)
            if data.get("type") == "content_block_start":
                block = data.get("content_block", {})
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    return self._tool(block)
                if isinstance(block, dict) and block.get("type") == "text":
                    text = block.get("text", "")
                    if not isinstance(text, str):
                        raise BridgeError("Malformed Grok text block")
                    self._blocks[key] = self._blocks.get(key, "") + text
                    return self._text_delta(text)
            if data.get("type") == "content_block_delta":
                delta = data.get("delta", {})
                if isinstance(delta, dict) and delta.get("type") == "text_delta":
                    text = delta.get("text")
                    if not isinstance(text, str):
                        raise BridgeError("Malformed Grok text delta")
                    self._blocks[key] = self._blocks.get(key, "") + text
                    return self._text_delta(text)
            return []  # Never forward thinking/signature/partial tool JSON.
        if kind == "assistant":
            message = event.get("message")
            if not isinstance(message, dict) or not isinstance(message.get("content"), list):
                raise BridgeError("Malformed Grok assistant message")
            message_id = _bounded_string(message.get("id"), 256) or self._current_message
            output = []
            for index, block in enumerate(message["content"]):
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "tool_use":
                    output.extend(self._tool(block))
                elif block.get("type") == "text":
                    final_text = block.get("text")
                    if not isinstance(final_text, str):
                        raise BridgeError("Malformed Grok completed text")
                    key = (message_id, index)
                    streamed = self._blocks.get(key)
                    if streamed is None and self._current_message == "partial":
                        streamed = self._blocks.pop(("partial", index), "")
                    streamed = streamed or ""
                    if not final_text.startswith(streamed):
                        raise BridgeError("Grok completed text disagreed with its partial stream")
                    output.extend(self._text_delta(final_text[len(streamed):]))
                    self._blocks[key] = final_text
            self._current_message = message_id
            return output
        if kind == "result":
            if self.terminal == "failed":
                return []
            if not isinstance(event.get("is_error"), bool):
                raise BridgeError("Grok result omitted explicit success/failure status")
            self.terminal = "failed" if event["is_error"] or str(event.get("subtype", "")).startswith("error") else "completed"
            usage = event.get("usage")
            if isinstance(usage, dict):
                self.usage = {key: value for key, value in usage.items() if key in (
                    "input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens",
                ) and isinstance(value, int) and not isinstance(value, bool) and value >= 0}
            models = event.get("modelUsage")
            evidence = []
            if isinstance(models, dict):
                for model_id, model_usage in models.items():
                    if not isinstance(model_id, str) or not MODEL_ID.fullmatch(model_id) or not isinstance(model_usage, dict):
                        continue
                    if any(isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0
                           and (not isinstance(value, float) or math.isfinite(value))
                           for key, value in model_usage.items() if key in (
                               "inputTokens", "outputTokens", "cacheReadInputTokens", "cacheCreationInputTokens",
                               "input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens",
                           )):
                        evidence.append(model_id)
            self.models_served = sorted(evidence)
            self.model_served = evidence[0] if len(evidence) == 1 else None
            if self.terminal == "failed":
                errors = event.get("errors")
                messages = [_bounded_string(error) for error in errors] if isinstance(errors, list) else []
                self.error_message = "; ".join(message for message in messages if message)[:2000]
                if not self.error_message:
                    self.error_message = _bounded_string(event.get("result")) or "Grok reported a failed turn"
                self.error_code = _bounded_string(event.get("subtype"), 120) or "provider_error"
            result_text = event.get("result")
            return self._text_delta(result_text) if self.terminal == "completed" and not self.text and isinstance(result_text, str) else []
        return []

    def finish(self, *args, **kwargs):
        result = super().finish(*args, **kwargs)
        if result is not None and result.get("error", {}).get("code") == "unconfirmed_turn":
            message = "Grok exited before a successful turn was confirmed"
            result["error"]["message"], result["errors"] = message, [message]
        return result


class GrokBroker(Broker):
    provider_label = "Grok"
    prompt_available_on_launch = True

    def __init__(self, *, prompt_factory: Callable[[bytes], Any] = private_prompt, **kwargs):
        self._prompt_factory = prompt_factory
        self._prompt_resource = None
        self._prompt_cleanup_unconfirmed = False
        self._fresh_id = str(uuid.uuid4())
        if not kwargs.get("executable"):
            kwargs["executable"] = (shutil.which("grok.exe") if os.name == "nt" else shutil.which("grok-cli")) or shutil.which("grok")
            if not kwargs["executable"]:
                raise BridgeError("Subscription Grok CLI is not installed")
        super().__init__(**kwargs)

    def _validate_launch(self, executable, model, effort, permission_mode, resume):
        build_argv(executable, model=model, effort=effort, permission_mode=permission_mode,
                   prompt_file="pending-private-prompt", session_id=resume or self._fresh_id, resume=resume is not None)

    def _make_normalizer(self):
        if self.thread_id is None:
            self._fresh_id = str(uuid.uuid4())
        return GrokNormalizer(self.model, self.effort, expected_id=self.thread_id or self._fresh_id, resume=self.thread_id)

    def _prepare_prompt(self, encoded_prompt):
        try:
            self._prompt_resource = self._prompt_factory(encoded_prompt)
        except PromptCleanupError:
            self._prompt_cleanup_unconfirmed = True
            raise
        return build_argv(
            self.executable, model=self.model, effort=self.effort, permission_mode=self.permission_mode,
            prompt_file=str(self._prompt_resource.path), session_id=self.thread_id or self._fresh_id,
            resume=self.thread_id is not None,
        ), None

    def _cleanup_prompt(self):
        if self._prompt_cleanup_unconfirmed:
            raise PromptCleanupError("Private prompt cleanup remains unconfirmed")
        if self._prompt_resource is not None:
            if self._prompt_resource.close() is False:
                raise PromptCleanupError("Private prompt resource did not confirm cleanup")
            self._prompt_resource = None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--effort", required=True)
    parser.add_argument("--permission-mode", required=True, choices=PERMISSION_MODES)
    parser.add_argument("--resume")
    parser.add_argument("--turn-timeout-seconds", type=float, default=DEFAULT_TURN_TIMEOUT_SECONDS)
    parser.add_argument("--idle-timeout-seconds", type=float, default=DEFAULT_IDLE_TIMEOUT_SECONDS)
    args = parser.parse_args(argv)
    try:
        broker = GrokBroker(target=args.target, model=args.model, effort=args.effort,
                            permission_mode=args.permission_mode, resume=args.resume,
                            turn_timeout_seconds=args.turn_timeout_seconds,
                            idle_timeout_seconds=args.idle_timeout_seconds)
    except BridgeError as exc:
        emit_json({"type": "result", "is_error": True, "replay_safe": True, "provider": "grok",
                   "model_attested": False, "error": {"code": "setup_error", "message": str(exc)}})
        return 2

    def on_signal(_signum, _frame):
        broker.stop()

    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, on_signal)
    if hasattr(signal, "SIGBREAK"):
        signal.signal(signal.SIGBREAK, on_signal)
    try:
        while not broker._stop.is_set():
            raw = sys.stdin.buffer.readline(MAX_INPUT_BYTES + 1)
            if not raw:
                break
            if len(raw) > MAX_INPUT_BYTES:
                emit_json({"type": "result", "is_error": True, "replay_safe": True,
                           "model_attested": False, "error": {"code": "input_too_large",
                           "message": "Input envelope exceeds the byte limit"}})
                return 2
            try:
                envelope = json.loads(raw.decode("utf-8"))
            except (UnicodeError, json.JSONDecodeError):
                emit_json({"type": "result", "is_error": True, "replay_safe": True,
                           "model_attested": False, "error": {"code": "invalid_input",
                           "message": "Input envelope must be UTF-8 JSON"}})
                continue
            broker.turn(envelope)
    finally:
        broker.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
