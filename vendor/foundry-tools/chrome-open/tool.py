#!/usr/bin/env python3
"""Foundry Tool: chrome-open — Deterministically open URLs or local HTML files in Google Chrome on WinSta0\\Default.

Bypasses offscreen agent sandbox desktops (WinSta0\\exebox-*) and Session-0
MSEdgeHTM association traps on Windows hosts.
"""
from __future__ import annotations

import argparse
import ctypes
import json
import os
import subprocess
import sys
import time
from ctypes import wintypes
from pathlib import Path

CHROME_CANDIDATES = (
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
)


class STARTUPINFOW(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("lpReserved", wintypes.LPWSTR),
        ("lpDesktop", wintypes.LPWSTR),
        ("lpTitle", wintypes.LPWSTR),
        ("dwX", wintypes.DWORD),
        ("dwY", wintypes.DWORD),
        ("dwXSize", wintypes.DWORD),
        ("dwYSize", wintypes.DWORD),
        ("dwXCountChars", wintypes.DWORD),
        ("dwYCountChars", wintypes.DWORD),
        ("dwFillAttribute", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("wShowWindow", wintypes.WORD),
        ("cbReserved2", wintypes.WORD),
        ("lpReserved2", ctypes.POINTER(ctypes.c_byte)),
        ("hStdInput", wintypes.HANDLE),
        ("hStdOutput", wintypes.HANDLE),
        ("hStdError", wintypes.HANDLE),
    ]


class PROCESS_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("hProcess", wintypes.HANDLE),
        ("hThread", wintypes.HANDLE),
        ("dwProcessId", wintypes.DWORD),
        ("dwThreadId", wintypes.DWORD),
    ]


def find_chrome() -> str:
    for c in CHROME_CANDIDATES:
        if c and Path(c).is_file():
            return str(Path(c))
    raise FileNotFoundError("Google Chrome (chrome.exe) not found in standard paths.")


def current_desktop_name() -> str:
    if os.name != "nt":
        return "posix"
    u32 = ctypes.windll.user32
    k32 = ctypes.windll.kernel32
    h_winsta = u32.GetProcessWindowStation()
    buf = ctypes.create_unicode_buffer(256)
    u32.GetUserObjectInformationW(h_winsta, 2, buf, 512, None)
    winsta = buf.value
    h_desk = u32.GetThreadDesktop(k32.GetCurrentThreadId())
    u32.GetUserObjectInformationW(h_desk, 2, buf, 512, None)
    return f"{winsta}\\{buf.value}"


def list_default_desktop_chrome_hwnds_and_titles() -> list[tuple[int, str]]:
    if os.name != "nt":
        return []
    u32 = ctypes.windll.user32
    h_def = u32.OpenDesktopW("Default", 0, False, 0x01FF)
    if not h_def:
        return []
    items: list[tuple[int, str]] = []
    WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def _cb(hwnd, _lparam):
        if u32.IsWindowVisible(hwnd):
            length = u32.GetWindowTextLengthW(hwnd)
            if length > 0:
                buf = ctypes.create_unicode_buffer(length + 1)
                u32.GetWindowTextW(hwnd, buf, length + 1)
                if "Chrome" in buf.value:
                    items.append((int(hwnd), buf.value))
        return True

    try:
        u32.EnumDesktopWindows(h_def, WNDENUMPROC(_cb), 0)
    finally:
        u32.CloseDesktop(h_def)
    return items


def list_default_desktop_chrome_windows() -> list[str]:
    return [t for _, t in list_default_desktop_chrome_hwnds_and_titles()]


def _top_desktop_title(u32, h_def) -> str:
    fg = u32.GetForegroundWindow()
    if fg:
        length = u32.GetWindowTextLengthW(fg)
        if length > 0:
            buf = ctypes.create_unicode_buffer(length + 1)
            u32.GetWindowTextW(fg, buf, length + 1)
            if buf.value:
                return buf.value
    top: list[str] = []
    WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def _cb(hwnd, _lp):
        if u32.IsWindowVisible(hwnd):
            n = u32.GetWindowTextLengthW(hwnd)
            if n > 0:
                b = ctypes.create_unicode_buffer(n + 1)
                u32.GetWindowTextW(hwnd, b, n + 1)
                if b.value and b.value not in ("Program Manager", "Windows Input Experience"):
                    top.append(b.value)
                    return False
        return True

    u32.EnumDesktopWindows(h_def, WNDENUMPROC(_cb), 0)
    return top[0] if top else ""


def bring_chrome_window_to_front_on_default_desktop(target_hwnds: list[int]) -> tuple[list[str], str]:
    """Switch thread desktop to WinSta0\\Default and raise the target Chrome window(s) to foreground (#1 Z-order)."""
    if os.name != "nt" or not target_hwnds:
        return list_default_desktop_chrome_windows(), ""
    u32 = ctypes.windll.user32
    k32 = ctypes.windll.kernel32
    cur_tid = k32.GetCurrentThreadId()
    h_orig = u32.GetThreadDesktop(cur_tid)
    h_def = u32.OpenDesktopW("Default", 0, False, 0x01FF)
    fg_title = ""
    if h_def:
        try:
            u32.SetThreadDesktop(h_def)
            # Raise target_hwnds in order so target_hwnds[-1] ends up at the very top (#1 foreground)
            for hwnd in target_hwnds:
                fg_hwnd = u32.GetForegroundWindow()
                fg_tid = u32.GetWindowThreadProcessId(fg_hwnd, None) if fg_hwnd else 0
                attached = False
                if fg_tid and fg_tid != cur_tid:
                    attached = bool(u32.AttachThreadInput(cur_tid, fg_tid, True))
                try:
                    if u32.IsIconic(hwnd):
                        u32.ShowWindow(hwnd, 9)  # SW_RESTORE
                    else:
                        u32.ShowWindow(hwnd, 5)  # SW_SHOW
                    # Satisfy Windows ForegroundLockTimeout for background callers without pressing a visible key
                    u32.keybd_event(0x12, 0, 0x0002, 0)  # VK_MENU keyup
                    u32.SetWindowPos(hwnd, -1, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0040)  # HWND_TOPMOST
                    u32.BringWindowToTop(hwnd)
                    u32.SetForegroundWindow(hwnd)
                    u32.SwitchToThisWindow(hwnd, True)
                    time.sleep(0.08)
                    u32.SetWindowPos(hwnd, -2, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0040)  # HWND_NOTOPMOST
                    u32.SetForegroundWindow(hwnd)
                finally:
                    if attached:
                        u32.AttachThreadInput(cur_tid, fg_tid, False)
            fg_title = _top_desktop_title(u32, h_def)
        finally:
            if h_orig:
                u32.SetThreadDesktop(h_orig)
            u32.CloseDesktop(h_def)
    return list_default_desktop_chrome_windows(), fg_title


def _extract_expected_titles(raw_targets: list[str]) -> list[str]:
    import re
    titles: list[str] = []
    for raw in raw_targets:
        try:
            if raw.startswith("file://"):
                from urllib.parse import unquote, urlparse
                p = Path(unquote(urlparse(raw).path.lstrip("/")))
            else:
                p = Path(raw)
            if p.is_file() and p.suffix.lower() in (".html", ".htm"):
                head = p.read_text(encoding="utf-8", errors="ignore")[:8192]
                m = re.search(r"<title[^>]*>(.*?)</title>", head, re.I | re.S)
                if m:
                    t = re.sub(r"\s+", " ", m.group(1)).strip()
                    if t:
                        titles.append(t)
        except Exception:
            pass
    return titles


def launch_on_default_desktop(urls: list[str], new_window: bool = False, raw_targets: list[str] | None = None) -> dict:
    chrome = find_chrome()
    caller_desktop = current_desktop_name()
    before_pairs = list_default_desktop_chrome_hwnds_and_titles()
    before_hwnds = {h for h, _ in before_pairs}
    before_titles = [t for _, t in before_pairs]
    expected_titles = _extract_expected_titles(raw_targets or urls)

    args = [chrome]
    if new_window:
        args.append("--new-window")
    args.extend(urls)
    cmd_line = subprocess.list2cmdline(args)

    si = STARTUPINFOW()
    si.cb = ctypes.sizeof(STARTUPINFOW)
    si.lpDesktop = "WinSta0\\Default"
    si.dwFlags = 0x00000001  # STARTF_USESHOWWINDOW
    si.wShowWindow = 1       # SW_SHOWNORMAL
    pi = PROCESS_INFORMATION()

    k32 = ctypes.windll.kernel32
    launched_pid = None
    for flags in (0x01000000, 0):
        buf = ctypes.create_unicode_buffer(cmd_line)
        ok = k32.CreateProcessW(
            chrome,
            buf,
            None,
            None,
            False,
            flags,
            None,
            None,
            ctypes.byref(si),
            ctypes.byref(pi),
        )
        if ok:
            launched_pid = int(pi.dwProcessId)
            k32.CloseHandle(pi.hThread)
            k32.CloseHandle(pi.hProcess)
            break

    if launched_pid is None:
        raise RuntimeError(f"CreateProcessW failed with WinError {k32.GetLastError()}")

    # Poll until the newly spawned non-"What's New" Chrome window appears and finishes setting its title
    mid_pairs: list[tuple[int, str]] = []
    new_non_promo: list[tuple[int, str]] = []
    deadline = time.time() + 3.0
    while time.time() < deadline:
        time.sleep(0.15)
        mid_pairs = list_default_desktop_chrome_hwnds_and_titles()
        fresh = [(h, t) for h, t in mid_pairs if h not in before_hwnds]
        new_non_promo = [(h, t) for h, t in fresh if not t.startswith("What's New")]
        if new_non_promo and all("Untitled" not in t for _, t in new_non_promo):
            break

    # Order hwnds so the actual target window is LAST (= raised on top of everything, never under "What's New")
    raise_order: list[int] = []
    if new_non_promo:
        # Put matching expected_titles at the very end so they become #1 foreground
        non_matching = [h for h, t in new_non_promo if not any(et in t for et in expected_titles)]
        matching = [h for h, t in new_non_promo if any(et in t for et in expected_titles)]
        raise_order = non_matching + matching
    elif mid_pairs:
        for h, t in mid_pairs:
            if expected_titles and any(et in t for et in expected_titles):
                raise_order.append(h)
                break
        if not raise_order:
            for h, t in mid_pairs:
                if not t.startswith("What's New"):
                    raise_order.append(h)
                    break
        if not raise_order:
            raise_order = [mid_pairs[0][0]]

    after_titles, fg_after = bring_chrome_window_to_front_on_default_desktop(raise_order)
    return {
        "ok": True,
        "chrome": chrome,
        "caller_desktop": caller_desktop,
        "target_desktop": "WinSta0\\Default",
        "launched_pid": launched_pid,
        "urls": urls,
        "raised_hwnds": raise_order,
        "foreground_window_after": fg_after,
        "visible_chrome_windows_before": before_titles,
        "visible_chrome_windows_after": after_titles,
    }


def _normalize_target(arg: str) -> str:
    if arg.startswith(("http://", "https://", "file://", "--")):
        return arg
    p = Path(arg)
    if p.exists():
        return p.resolve().as_uri()
    return arg


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser(description="Open URLs or local HTML files in visible Chrome on WinSta0\\Default.")
    parser.add_argument("urls", nargs="*", help="URLs or local HTML files to open in Chrome")
    parser.add_argument("--new-window", action="store_true", help="Open in a new Chrome window")
    parser.add_argument("--selftest", action="store_true", help="Verify WinSta0\\Default access and Chrome installation")
    ns = parser.parse_args(args)

    if ns.selftest:
        chrome = find_chrome()
        wins = list_default_desktop_chrome_windows()
        out = {
            "ok": True,
            "chrome": chrome,
            "caller_desktop": current_desktop_name(),
            "target_desktop": "WinSta0\\Default",
            "visible_chrome_windows": wins,
        }
        print(json.dumps(out, indent=2))
        return 0

    if not ns.urls:
        parser.error("Provide at least one URL/file or --selftest.")

    normalized = [_normalize_target(a) for a in ns.urls]
    res = launch_on_default_desktop(normalized, new_window=ns.new_window, raw_targets=ns.urls)
    print(json.dumps(res, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
