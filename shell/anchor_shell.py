"""Anchor as a desktop program: one native WebView window around static/app.html (PLAN v2.2 section 3.3,
Skill Foundry/planning/anchor-app-shell-2026-09-29; Cross-Platform Shell 2026-10-29).

Not product code: it runs from its own venv (%LOCALAPPDATA%/anchor-shell/.venv on Windows,
~/Library/Application Support/anchor-shell/.venv on macOS, ~/.local/share/anchor-shell/.venv on Linux) and is
not on the ship list. The service is unchanged; this only opens a window onto it.

  - its own taskbar identity (AppUserModelID on Windows, .app bundle on macOS, .desktop on Linux) and the new anchor as its icon;
  - a persistent profile, so the token is pasted once and the 30-day cookie is kept;
  - downloads allowed; app links (ms-word:, mailto:) and other sites go to the OS / default browser;
  - one instance: a second launch brings the open window forward (CreateMutexW on Windows; fcntl.flock on macOS/Linux);
  - Ctrl + / Ctrl - / Ctrl 0 (and Ctrl + wheel) zoom the whole window, remembered for the next start. pywebview
    turns WebView2's own browser keys off (F5 would reload the app and lose the open tiles), so the pages catch
    just these keys (static/app.js, app-frame.js) and call zoom() here;
  - its own title bar (his ask, 2026-10-03): the window has no OS caption; the page draws the bar (the anchor,
    the tiles, the one/two-pane toggle, minimize/maximize/close). The bar's empty parts carry CSS app-region: drag,
    which WebView2 (non-client region support) turns into a real caption - smooth moves, snap, double-click to
    maximize. Windows 11 rounds the corners; the window's outer edges resize it.

  - (every-device D1, 2026-10-03) it finds Anchor itself (shell/connect.py): the local copy, else the owner's saved
    mother ship address; a plain page when that address does not answer; packaged for other machines as Anchor.zip /
    Anchor-macOS.zip / Anchor-Linux.tar.gz (shell/build_exe.ps1, shell/build_unix.sh).

Usage:  pythonw shell/anchor_shell.py [--url ADDRESS] [--setup]      (or the packaged Anchor binary, same flags)
"""
import argparse
import ctypes
import os
import sys
from pathlib import Path

IS_WIN32 = (sys.platform == "win32")
IS_MAC = (sys.platform == "darwin")
IS_LINUX = sys.platform.startswith("linux")
if IS_WIN32:
    from ctypes import wintypes
else:
    wintypes = None

APP_ID = "GhostWorldLabs.Anchor"
TITLE = "Anchor"
DEFAULT_URL = "http://127.0.0.1:8777/static/app.html"
FROZEN = bool(getattr(sys, "frozen", False))           # the packaged Anchor binary


def _resolve_package_root():
    if not FROZEN:
        return Path(__file__).resolve().parent.parent
    try:
        exe_dir = Path(sys.executable).resolve().parent
        cands = [exe_dir, exe_dir.parent]
        if IS_WIN32:
            cands.extend([Path(r"C:\dev") / "Anchor", Path(r"C:\dev") / "anchor-plus-skills"])
        else:
            home = Path.home()
            cands.extend([
                home / "dev" / "Anchor",
                home / "dev" / "anchor-plus-skills",
                home / "Anchor",
                Path("/Applications/Anchor.app/Contents/Resources"),
            ])
        for cand in cands:
            if (
                (cand / "launch_anchor_dashboard.py").is_file()
                or (cand / "onboard.cmd").is_file()
                or (cand / "onboard.sh").is_file()
            ):
                return cand
        return exe_dir
    except OSError:
        return Path(__file__).resolve().parent.parent


def unblock_extracted_files(base_dirs=None):
    """Strip Windows Mark-of-the-Web (:Zone.Identifier) streams from extracted package files before .NET loads."""
    if os.name != "nt":
        return 0
    dirs = list(base_dirs or [])
    if not dirs:
        try:
            exe_dir = Path(sys.executable).resolve().parent
            dirs.append(exe_dir)
            if (exe_dir.parent / "launch_anchor_dashboard.py").is_file() or (exe_dir.parent / "anchor_gui.py").is_file():
                dirs.append(exe_dir.parent)
        except OSError:
            pass
    removed = 0
    seen = set()
    for d in dirs:
        try:
            dp = Path(d).resolve()
        except OSError:
            dp = Path(d)
        key = str(dp).lower()
        if key in seen or not dp.exists():
            continue
        seen.add(key)
        try:
            os.remove(str(dp) + ":Zone.Identifier")
            removed += 1
        except OSError:
            pass
        for root_dir, subdirs, files in os.walk(str(dp)):
            # Skip deep git/venv folders if walking an outer workspace
            subdirs[:] = [s for s in subdirs if s not in (".git", ".venv", "node_modules", "__pycache__")]
            for name in files:
                fpath = os.path.join(root_dir, name)
                try:
                    os.remove(fpath + ":Zone.Identifier")
                    removed += 1
                except OSError:
                    pass
    return removed


if FROZEN:
    unblock_extracted_files()

ROOT = _resolve_package_root()
ICON = (Path(sys._MEIPASS) / "anchor-icon.ico") if FROZEN else ROOT / "vendor" / "brand" / "anchor-icon.ico"
IS_ADMIN_EXE = False
try:
    import json as _json
    _exe_dir = Path(sys.executable).resolve().parent if FROZEN else ROOT
    if FROZEN and "admin" in Path(sys.executable).stem.lower():
        IS_ADMIN_EXE = True
    for _ecand in (_exe_dir / "anchor-edition.json", _exe_dir.parent / "anchor-edition.json", ROOT / "anchor-edition.json"):
        if _ecand.is_file():
            _edoc = _json.loads(_ecand.read_text(encoding="utf-8"))
            _eval = str(_edoc.get("edition") or "").strip().lower()
            if _eval == "admin":
                IS_ADMIN_EXE = True
                os.environ.setdefault("ANCHOR_EDITION", "admin")
                os.environ.setdefault("ANCHOR_ADMIN_EDITION", "1")
            elif _eval == "collaborator":
                IS_ADMIN_EXE = False
                os.environ.setdefault("ANCHOR_EDITION", "collaborator")
                os.environ.setdefault("ANCHOR_ADMIN_EDITION", "0")
            break
except Exception:
    pass
if IS_ADMIN_EXE:
    APP_ID = "GhostWorldLabs.AnchorAdmin"
    TITLE = "Anchor Admin"
    _adm_ico = (Path(sys._MEIPASS) / "anchor-admin-key.ico") if FROZEN else (ROOT / "vendor" / "brand" / "anchor-admin-key.ico")
    if _adm_ico.is_file():
        ICON = _adm_ico
if FROZEN:
    try:
        import json as _json
        for _cand in (Path(sys.executable).resolve().parent / 'anchor-test-mode.json', Path(sys.executable).resolve().parent.parent / 'anchor-test-mode.json'):
            if _cand.is_file():
                for _k, _v in _json.loads(_cand.read_text(encoding='utf-8')).items():
                    if _k.startswith('ANCHOR_SHELL_') and _v:
                        os.environ.setdefault(_k, str(_v))
                break
    except Exception:
        pass
# ANCHOR_SHELL_TEST=<name>: a test copy beside his running Anchor - its own settings and profile, window title and
# single-instance lock, and it never touches his Start-menu shortcut.
TEST = os.environ.get("ANCHOR_SHELL_TEST", "")


def _resolve_data_dir(platform=None, env=None, home=None, test_name=None):
    """Resolve platform-native user application data directory for anchor-shell."""
    plat = sys.platform if platform is None else str(platform)
    environ = os.environ if env is None else env
    home_dir = Path(home) if home is not None else Path.home()
    tname = TEST if test_name is None else str(test_name)
    folder = "anchor-shell" + ("-test-" + tname if tname else "")
    if plat == "win32":
        base = Path(environ.get("LOCALAPPDATA") or str(home_dir))
    elif plat == "darwin":
        base = home_dir / "Library" / "Application Support"
    else:
        xdg = str(environ.get("XDG_DATA_HOME") or "").strip()
        base = Path(xdg) if xdg else (home_dir / ".local" / "share")
    return base / folder


DATA = _resolve_data_dir()
if TEST:
    TITLE = "Anchor (test %s)" % TEST
PROFILE = DATA / "profile"
WEBVIEW2_URL = "https://go.microsoft.com/fwlink/p/?LinkId=2124703"
ZOOM_FILE = PROFILE.parent / "zoom.txt"
ZOOM_STEPS = (0.5, 0.67, 0.75, 0.8, 0.9, 1.0, 1.1, 1.25, 1.5, 1.75, 2.0, 2.5, 3.0)   # Chrome's ladder

if IS_WIN32:
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.restype = wintypes.HANDLE
    user32.SendMessageW.argtypes = (wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
    user32.SendMessageW.restype = wintypes.LPARAM
    user32.LoadImageW.restype = wintypes.HANDLE
    user32.FindWindowW.restype = wintypes.HWND
    user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
    user32.GetWindowLongPtrW.argtypes = (wintypes.HWND, ctypes.c_int)
    user32.SetWindowLongPtrW.restype = ctypes.c_ssize_t
    user32.SetWindowLongPtrW.argtypes = (wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t)
    user32.SetWindowPos.argtypes = (wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                    wintypes.UINT)
    comctl32 = ctypes.WinDLL("comctl32")
    SUBCLASSPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM,
                                      ctypes.c_size_t, ctypes.c_size_t)
    comctl32.SetWindowSubclass.argtypes = (wintypes.HWND, SUBCLASSPROC, ctypes.c_size_t, ctypes.c_size_t)
    comctl32.DefSubclassProc.argtypes = (wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
    comctl32.DefSubclassProc.restype = ctypes.c_ssize_t
else:
    user32 = None
    kernel32 = None
    comctl32 = None
    SUBCLASSPROC = None

ERROR_ALREADY_EXISTS = 183
EDGE = 5                                                # px of the window's edge that resize it


def _acquire_single_instance_lock(data_dir=None, flock_mod=None):
    """Acquire non-blocking single-instance file lock on DATA / 'instance.lock' (POSIX fcntl.flock)."""
    target_dir = Path(DATA if data_dir is None else data_dir)
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
        lock_path = target_dir / "instance.lock"
        fh = open(lock_path, "a+", encoding="utf-8")
    except OSError:
        return True, None
    fmod = flock_mod
    if fmod is None:
        try:
            import fcntl as _fcntl
            fmod = _fcntl
        except ImportError:
            fmod = None
    if fmod is not None:
        try:
            fmod.flock(fh.fileno(), fmod.LOCK_EX | fmod.LOCK_NB)
            fh.seek(0)
            fh.truncate()
            fh.write(str(os.getpid()))
            fh.flush()
            return True, (fh, "fcntl", fmod)
        except (BlockingIOError, OSError):
            try:
                fh.close()
            except OSError:
                pass
            return False, None
    try:
        import msvcrt as _msvcrt
        fh.seek(0)
        if lock_path.stat().st_size == 0:
            fh.write(str(os.getpid()).ljust(16))
            fh.flush()
            fh.seek(0)
        _msvcrt.locking(fh.fileno(), _msvcrt.LK_NBLCK, 1)
        return True, (fh, "msvcrt", _msvcrt)
    except OSError:
        try:
            fh.close()
        except OSError:
            pass
        return False, None


def _release_single_instance_lock(lock_handle, flock_mod=None):
    """Release the single-instance file lock acquired by _acquire_single_instance_lock."""
    if not lock_handle:
        return
    if isinstance(lock_handle, tuple) and len(lock_handle) == 3:
        fh, kind, mod = lock_handle
    else:
        fh, kind, mod = lock_handle, "fcntl", flock_mod
    try:
        if kind == "fcntl" and mod is not None:
            mod.flock(fh.fileno(), mod.LOCK_UN)
        elif kind == "msvcrt" and mod is not None:
            fh.seek(0)
            mod.locking(fh.fileno(), mod.LK_UNLCK, 1)
    except OSError:
        pass
    try:
        fh.close()
    except OSError:
        pass


def bring_forward_existing():
    """A second launch: find the open Anchor window, restore it and bring it to the front.
    If the existing window is hung (Not Responding), terminate it and return False so a fresh window opens.
    """
    if not IS_WIN32 or user32 is None:
        import shutil
        import subprocess
        if IS_MAC:
            try:
                subprocess.run(
                    ["osascript", "-e", 'tell application "Anchor" to activate'],
                    capture_output=True,
                    timeout=3,
                )
            except Exception:
                pass
            return True
        if IS_LINUX and shutil.which("wmctrl"):
            try:
                subprocess.run(["wmctrl", "-a", TITLE], capture_output=True, timeout=3)
            except Exception:
                pass
        return True
    hwnd = user32.FindWindowW(None, TITLE)
    if hwnd:
        try:
            if user32.IsHungAppWindow(hwnd):
                pid = wintypes.DWORD(0)
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                if pid.value and pid.value != os.getpid():
                    import subprocess
                    subprocess.run(["taskkill", "/PID", str(pid.value), "/T", "/F"],
                                   capture_output=True, timeout=5, creationflags=0x08000000)
                return False
        except Exception:
            pass
        if user32.IsIconic(hwnd):                       # restore only a minimised window; a maximised one stays
            user32.ShowWindow(hwnd, 9)                  # SW_RESTORE
        user32.SetForegroundWindow(hwnd)
    return bool(hwnd)


def set_window_icon(hwnd, path):
    """WM_SETICON with the anchor (the window frame and Alt+Tab); the taskbar uses the shortcut's icon."""
    if not IS_WIN32 or user32 is None:
        return
    LR_LOADFROMFILE, IMAGE_ICON, WM_SETICON = 0x10, 1, 0x0080
    for which, size in ((1, 256), (0, 32)):             # ICON_BIG, ICON_SMALL
        h = user32.LoadImageW(None, str(path), IMAGE_ICON, size, size, LR_LOADFROMFILE)
        if h:
            user32.SendMessageW(hwnd, WM_SETICON, which, h)


def _own_title_bar(hwnd):
    """Run on the window's UI thread. A resizable window (snap, minimize animation, Windows 11 rounded corners) whose
    caption and frame nobody draws: WM_NCCALCSIZE gives the page the whole window; WM_NCHITTEST answers the outer
    edges with the resize codes; the bar's app-region is the caption."""
    if not IS_WIN32 or user32 is None or comctl32 is None:
        return
    GWL_STYLE, WS_THICKFRAME, WS_MAXIMIZEBOX, WS_MINIMIZEBOX, WS_SYSMENU = -16, 0x40000, 0x10000, 0x20000, 0x80000
    WS_CAPTION = 0xC00000
    WM_NCCALCSIZE, WM_NCHITTEST = 0x0083, 0x0084
    style = user32.GetWindowLongPtrW(hwnd, GWL_STYLE)
    user32.SetWindowLongPtrW(hwnd, GWL_STYLE,
                             style | WS_CAPTION | WS_THICKFRAME | WS_MAXIMIZEBOX | WS_MINIMIZEBOX | WS_SYSMENU)
    codes = {(1, 0, 1, 0): 13, (0, 1, 1, 0): 14, (1, 0, 0, 1): 16, (0, 1, 0, 1): 17,
             (1, 0, 0, 0): 10, (0, 1, 0, 0): 11, (0, 0, 1, 0): 12, (0, 0, 0, 1): 15}

    def proc(h, msg, wp, lp, _id, _ref):
        if msg == WM_NCCALCSIZE and wp:
            if user32.IsZoomed(h):                      # maximised: keep the page inside the screen
                rc = ctypes.cast(lp, ctypes.POINTER(wintypes.RECT)).contents
                dpi = user32.GetDpiForWindow(h)         # SM_CXFRAME + SM_CXPADDEDBORDER at this window's DPI
                pad = user32.GetSystemMetricsForDpi(32, dpi) + user32.GetSystemMetricsForDpi(92, dpi)
                rc.left += pad
                rc.top += pad
                rc.right -= pad
                rc.bottom -= pad
            return 0
        if msg == WM_NCHITTEST and not user32.IsZoomed(h):
            x, y = ctypes.c_short(lp & 0xFFFF).value, ctypes.c_short((lp >> 16) & 0xFFFF).value
            r = wintypes.RECT()
            user32.GetWindowRect(h, ctypes.byref(r))
            key = (int(x < r.left + EDGE), int(x >= r.right - EDGE), int(y < r.top + EDGE), int(y >= r.bottom - EDGE))
            if key in codes:
                return codes[key]                       # HTLEFT/RIGHT/TOP/BOTTOM and the corners
        return comctl32.DefSubclassProc(h, msg, wp, lp)

    cb = SUBCLASSPROC(proc)
    _own_title_bar.keep = cb                           # the callback must outlive this call
    comctl32.SetWindowSubclass(hwnd, cb, 1, 0)
    pref = ctypes.c_int(2)                              # DWMWA_WINDOW_CORNER_PREFERENCE = DWMWCP_ROUND
    ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 33, ctypes.byref(pref), 4)
    user32.SetWindowPos(hwnd, None, 0, 0, 0, 0, 0x0027)    # SWP_FRAMECHANGED | NOMOVE | NOSIZE | NOZORDER


def ensure_shortcut():
    """The packaged program's first run (and any run after it moved): the Start-menu Anchor.lnk points at THIS exe,
    with the app ID, so the pinned icon and the running window are one taskbar button."""
    if not IS_WIN32 or not FROZEN or TEST:
        return
    link = Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Anchor.lnk"
    try:
        import pythoncom
        from win32com.propsys import propsys, pscon
        from win32com.shell import shell
        lnk = pythoncom.CoCreateInstance(shell.CLSID_ShellLink, None, pythoncom.CLSCTX_INPROC_SERVER, shell.IID_IShellLink)
        if link.is_file():
            lnk.QueryInterface(pythoncom.IID_IPersistFile).Load(str(link))
            if Path(lnk.GetPath(0)[0]).resolve() == Path(sys.executable).resolve():
                return
        lnk.SetPath(sys.executable)
        lnk.SetArguments("")
        lnk.SetWorkingDirectory(str(Path(sys.executable).parent))
        lnk.SetIconLocation(sys.executable, 0)
        lnk.SetDescription("Anchor")
        store = lnk.QueryInterface(propsys.IID_IPropertyStore)
        store.SetValue(pscon.PKEY_AppUserModel_ID, propsys.PROPVARIANTType(APP_ID))
        store.Commit()
        lnk.QueryInterface(pythoncom.IID_IPersistFile).Save(str(link), 0)
    except Exception as exc:                             # the program still runs; he can pin the exe itself
        print("shortcut:", exc, file=sys.stderr)


def _message(text, title="Anchor"):
    if IS_WIN32 and user32 is not None:
        user32.MessageBoxW(None, text, title, 0x40)
        return
    if IS_MAC:
        try:
            import json as _json
            import subprocess
            subprocess.run(
                [
                    "osascript",
                    "-e",
                    "display dialog %s with title %s buttons {\"OK\"} default button \"OK\""
                    % (_json.dumps(str(text)), _json.dumps(str(title))),
                ],
                capture_output=True,
                timeout=15,
            )
            return
        except Exception:
            pass
    print("%s: %s" % (title, text), file=sys.stderr)


def _read_zoom():
    try:
        z = float(ZOOM_FILE.read_text(encoding="utf-8").strip())
        return z if ZOOM_STEPS[0] <= z <= ZOOM_STEPS[-1] else 1.0
    except (OSError, ValueError):
        return 1.0


class HostApi:
    """What the page may ask of the program: zoom(step) (+1 / -1 along the ladder, 0 = 100 %) and
    window_control(act) for the bar's own minimize / maximize-restore / close."""

    def __init__(self):
        self._window = None
        self._level = _read_zoom()
        self._address = ""
        self._html = ""                                  # the page the program drew itself (setup / offline), if any
        self._maximized = False

    def bind(self, window):
        self._window = window

    def zoom(self, step):
        step = int(step)
        if step == 0:
            z = 1.0
        else:
            i = min(range(len(ZOOM_STEPS)), key=lambda k: abs(ZOOM_STEPS[k] - self._level))
            z = ZOOM_STEPS[max(0, min(len(ZOOM_STEPS) - 1, i + (1 if step > 0 else -1)))]
        self.apply(z)
        try:
            ZOOM_FILE.write_text(str(z), encoding="utf-8")
        except OSError:
            pass
        return z

    def apply(self, z=None):
        self._level = self._level if z is None else z
        level = self._level
        if IS_WIN32 and getattr(self._window, "native", None) is not None:
            try:
                from System import Action               # pythonnet, pywebview's WinForms backend
                form = self._window.native
                form.Invoke(Action(lambda: setattr(form.browser.webview, "ZoomFactor", level)))
                return
            except Exception as exc:                    # zoom is a convenience; fall back to CSS zoom
                print("zoom:", exc, file=sys.stderr)
        try:
            if self._window is not None and hasattr(self._window, "evaluate_js"):
                self._window.evaluate_js("document.documentElement.style.zoom = '%s';" % level)
        except Exception as exc:
            print("zoom:", exc, file=sys.stderr)

    def window_control(self, act="", *_args):
        w = self._window
        if act == "minimize":
            w.minimize()
        elif act == "maximize":
            native = getattr(w, "native", None)
            if user32 is not None and native is not None and getattr(native, "Handle", None) is not None:
                if user32.IsZoomed(int(str(native.Handle))):
                    w.restore()
                    self._maximized = False
                else:
                    w.maximize()
                    self._maximized = True
            else:
                if self._maximized:
                    w.restore()
                    self._maximized = False
                else:
                    w.maximize()
                    self._maximized = True
        elif act == "close":
            w.destroy()
        elif act == "drag":
            if user32 is not None and getattr(w, "native", None) is not None:
                try:
                    from System import Action
                    form = w.native
                    hwnd = int(str(form.Handle))
                    form.Invoke(Action(lambda: (user32.ReleaseCapture(), user32.SendMessageW(hwnd, 0x00A1, 2, 0))))
                except Exception:
                    pass

    # ---------- finding Anchor (the setup and offline pages call these) ----------
    def connect(self, text="", *_args):
        import connect
        address, why = connect.normalize(text)
        if not address:
            return why
        if not connect.reachable(address):
            return "No answer from your selected mother ship at %s. Is Tailscale on here, and is your mother ship awake with Anchor running there?" % address
        connect.save_address(DATA, address)
        self._open(address)
        return ""

    def select_mother_ship(self, *_args):
        import connect
        auto_boot = bool(FROZEN or getattr(connect.reachable, "__name__", "") == "reachable")
        try:
            if hasattr(self._window, "evaluate_js"):
                self._window.evaluate_js("window._updateInstallProgress && window._updateInstallProgress(28, 2, 'Step 2/4: Verifying Mother Ship repository & 19 Foundry Skills...')")
        except Exception:
            pass
        result = connect.select_mother_ship(DATA, ROOT, auto_bootstrap=auto_boot)
        if not result["ok"]:
            err = str(result.get("message") or "")
            self._show(connect.installation_page(ROOT, error_message=err) if err else connect.installation_page(ROOT))
            return ""
        self._address = result["address"]
        self._html = ""
        self._window.load_url(self._address + result["path"])
        return ""

    def retry(self, *_args):
        import connect
        if self._address == connect.LOCAL and not connect.reachable(self._address):
            connect.ensure_local_service_running(ROOT, check_system_dirs=True)
        if connect.reachable(self._address):
            self._open(self._address)
            return ""
        return "Still no answer from your selected mother ship. Check Tailscale here and that your mother ship is awake with Anchor running, then Retry."

    def change_address(self, *_args):
        import connect
        self._show(connect.setup_page(self._address))
        return ""

    def install_from_github(self, repo_url="", target_dir="", *_args):
        import connect
        import time
        if isinstance(repo_url, dict):
            target_dir = repo_url.get("target_dir") or target_dir
            repo_url = repo_url.get("repo_url") or ""
        try:
            self._window.evaluate_js("window._updateInstallProgress && window._updateInstallProgress(22, 2, 'Step 2/4: Pulling Anchor Mother Ship & 19 Foundry Skills...')")
        except Exception:
            pass
        result = connect.pull_and_install_mothership(
            repo_url=repo_url or connect.DEFAULT_GITHUB_REPO,
            workspace_dir=target_dir or connect.DEFAULT_INSTALL_ROOT,
            run_onboard=False,
        )
        target_path = os.environ.get("ANCHOR_SHELL_ONBOARD_PATH") or "/setup"
        if result.get("target_dir"):
            try:
                self._window.evaluate_js("window._updateInstallProgress && window._updateInstallProgress(82, 4, 'Step 4/4: Starting local Anchor service & opening Onboarding Wizard...')")
            except Exception:
                pass
            connect._apply_bundled_core_overlay(Path(result["target_dir"]))
            if connect.reachable(connect.LOCAL) and target_path != "/setup" and not connect.route_reachable(connect.LOCAL, target_path):
                connect.stop_local_service_on_port(connect.LOCAL_PORT)
            if not connect.reachable(connect.LOCAL):
                connect.ensure_local_service_running(result["target_dir"], check_system_dirs=True)
        for _ in range(16 if result.get("onboard_ready") else 1):
            if connect.reachable(connect.LOCAL):
                if target_path != "/setup" and not connect.route_reachable(connect.LOCAL, target_path) and connect.route_reachable(connect.LOCAL, "/setup"):
                    target_path = "/setup"
                connect.save_address(DATA, connect.LOCAL)
                self._address = connect.LOCAL
                self._html = ""
                self._window.load_url(self._address + target_path)
                return ""
            time.sleep(0.5)
        hint = "onboard.cmd" if IS_WIN32 else "./onboard.sh"
        return result.get("message") or ("Mother ship repository pulled. Run %s to start Anchor." % hint)

    def discover_tailscale(self, *_args):
        import connect
        result = connect.discover_tailscale_motherships()
        online = [p for p in (result.get("peers") or []) if p.get("online")]
        if online and not self._address:
            self._show(connect.setup_page(online[0]["https_url"], result.get("message") or ""))
            return ""
        return result.get("message") or "No online Tailscale mother ships found."

    def _show(self, page):
        self._html = page
        self._window.load_html(page)

    def _open(self, address):
        import connect
        self._address = address
        self._html = ""
        self._window.load_url(address + connect.APP_PATH)

    def _frame(self):
        """WebView2's app-region support on; True when it was off (the page then reloads once so it takes)."""
        if not IS_WIN32 or getattr(self._window, "native", None) is None:
            return False
        from System import Action
        form = self._window.native
        changed = []

        def on_ui():                                    # WebView2 is touched on its own thread only
            core = form.browser.webview.CoreWebView2
            settings = core.Settings
            try:
                from Microsoft.Web.WebView2.Core import CoreWebView2PermissionState
                if not getattr(core, "_anchor_mic_wired", False):
                    def _on_perm(sender, e):
                        try:
                            e.State = CoreWebView2PermissionState.Allow
                        except Exception:
                            pass
                    core.PermissionRequested += _on_perm
                    core._anchor_mic_wired = True
            except Exception:
                pass
            if not settings.IsNonClientRegionSupportEnabled:
                settings.IsNonClientRegionSupportEnabled = True
                changed.append(True)

        form.Invoke(Action(on_ui))
        return bool(changed)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="", help="Anchor's address (else local Anchor, else the saved mother ship address)")
    ap.add_argument("--setup", action="store_true", help="ask for the address again")
    args = ap.parse_args(argv)
    import connect
    if args.url:
        try:
            args.url = connect.choose(DATA, args.url)
        except ValueError as exc:
            ap.error(str(exc))

    mutex = None
    posix_lock = None
    if kernel32 is not None:
        mutex = kernel32.CreateMutexW(None, False, "Local\\" + APP_ID + ("." + TEST if TEST else ""))
        if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
            if bring_forward_existing():
                return 0
            mutex = kernel32.CreateMutexW(None, False, "Local\\" + APP_ID + ("." + TEST if TEST else ""))
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
        except Exception:
            pass
        ensure_shortcut()
    else:
        acquired, posix_lock = _acquire_single_instance_lock(DATA)
        if not acquired:
            if bring_forward_existing():
                return 0

    if FROZEN:
        unblock_extracted_files()

    import webview                                      # the venv's; imported after the single-instance check
    webview.settings["ALLOW_DOWNLOADS"] = True
    webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = True   # ms-word:, mailto:, other sites -> OS browser
    if IS_WIN32:
        try:
            from webview.platforms import edgechromium as _edge
            _orig_new_win = getattr(_edge.EdgeChrome, "on_new_window_request", None)
            if callable(_orig_new_win) and not getattr(_edge.EdgeChrome, "_anchor_patched", False):
                def _anchor_new_window_request(self_ec, sender, args):
                    try:
                        uri = str(args.get_Uri() or "").strip()
                        if not uri or uri.lower().startswith("about:"):
                            args.set_Handled(True)
                            return
                        base = (host._address or connect.LOCAL or "http://127.0.0.1:8777").rstrip("/")
                        if uri.startswith(base) or uri.startswith("http://127.0.0.1:") or uri.startswith("http://localhost:"):
                            args.set_Handled(True)
                            if "download=1" not in uri:
                                import json as _json
                                import threading as _threading
                                _js = "window.ANCHOR_APP && window.ANCHOR_APP.open(" + _json.dumps(uri) + ", '_blank')"
                                _wv = getattr(self_ec, "webview", None)
                                if _wv is not None and hasattr(_wv, "ExecuteScriptAsync"):
                                    _wv.ExecuteScriptAsync(_js)
                                elif getattr(self_ec, "pywebview_window", None) is not None and not hasattr(self_ec, "webview"):
                                    self_ec.pywebview_window.evaluate_js(_js)
                                else:
                                    _threading.Thread(
                                        target=lambda: self_ec.pywebview_window.evaluate_js(_js),
                                        daemon=True,
                                    ).start()
                            return
                    except Exception:
                        pass
                    return _orig_new_win(self_ec, sender, args)
                _edge.EdgeChrome.on_new_window_request = _anchor_new_window_request
                _orig_ready = getattr(_edge.EdgeChrome, "on_webview_ready", None)
                if callable(_orig_ready):
                    def _anchor_webview_ready(self_ec, sender, args):
                        try:
                            if getattr(args, "IsSuccess", True):
                                core = self_ec.webview.CoreWebView2
                                core.Settings.IsNonClientRegionSupportEnabled = True
                                from Microsoft.Web.WebView2.Core import CoreWebView2PermissionState
                                if not getattr(core, "_anchor_mic_wired", False):
                                    def _on_perm(_s, e):
                                        try:
                                            e.State = CoreWebView2PermissionState.Allow
                                        except Exception:
                                            pass
                                    core.PermissionRequested += _on_perm
                                    core._anchor_mic_wired = True
                        except Exception:
                            pass
                        return _orig_ready(self_ec, sender, args)
                    _edge.EdgeChrome.on_webview_ready = _anchor_webview_ready
                _edge.EdgeChrome._anchor_patched = True
        except Exception:
            pass
    PROFILE.mkdir(parents=True, exist_ok=True)

    host = HostApi()
    address = "" if args.setup else connect.choose(DATA, args.url)
    if FROZEN and not args.url and address == connect.LOCAL:
        if connect.load_attempted_upgrade_version(DATA) != connect.BUNDLED_VERSION:
            vcheck = connect.inspect_local_anchor_version(ROOT, check_system_dirs=True)
            if vcheck.get("needs_install"):
                address = ""
            elif vcheck.get("needs_upgrade"):
                if vcheck.get("root"):
                    connect._apply_bundled_core_overlay(Path(vcheck["root"]))
                connect.ensure_mothership_up_to_date_and_running(package_root=vcheck.get("root") or ROOT)
                connect.save_attempted_upgrade_version(DATA, connect.BUNDLED_VERSION)
                if not connect.reachable(connect.LOCAL):
                    address = ""
    host._address = address or connect.load_address(DATA)
    if not address:
        host._html = connect.setup_page(host._address) if (host._address and host._address != connect.LOCAL) else connect.first_launch_page()
        page = dict(html=host._html)
    elif address == connect.LOCAL and FROZEN and not connect.reachable(address):
        connect.ensure_local_service_running(ROOT, check_system_dirs=True)
        if not connect.reachable(address):
            host._html = connect.offline_page(address)
            page = dict(html=host._html)
        else:
            page = dict(url=address + connect.APP_PATH)
    elif address != connect.LOCAL and not connect.reachable(address):
        host._html = connect.offline_page(address)
        page = dict(html=host._html)
    else:
        page = dict(url=address + connect.APP_PATH)
    win = webview.create_window(TITLE, js_api=host, width=1500, height=950, min_size=(420, 500),
                                background_color="#0f141c", frameless=True, easy_drag=False, **page)
    host.bind(win)

    def on_loaded():
        host.apply()                                    # the remembered zoom
        try:
            if host._frame():                           # a page drawn here is drawn again; Anchor's page reloads
                if host._html:
                    win.load_html(host._html)
                elif host._address:
                    win.load_url(host._address + connect.APP_PATH)
        except Exception as exc:                         # without it the bar does not move the window
            print("app-region:", exc, file=sys.stderr)

    win.events.loaded += on_loaded

    def on_shown():
        if not IS_WIN32 or user32 is None or getattr(win, "native", None) is None:
            return
        try:
            hwnd = int(str(win.native.Handle))
            set_window_icon(hwnd, ICON)
            from System import Action, EventHandler
            import System.Windows.Forms as WinForms
            form = win.native

            def inset(*_):                              # the page stops EDGE px short of the edges, so the edges
                pad = 0 if user32.IsZoomed(hwnd) else EDGE      # are the window's and resize it (not when maximised)
                if form.Padding.Left != pad:
                    form.Padding = WinForms.Padding(pad)

            def on_ui():
                _own_title_bar(hwnd)
                inset()
                form.Resize += EventHandler(inset)

            form.Invoke(Action(on_ui))
        except Exception as exc:                         # the window still works with the defaults
            print("frame:", exc, file=sys.stderr)

    win.events.shown += on_shown
    try:
        start_kwargs = dict(private_mode=False, storage_path=str(PROFILE))
        if IS_WIN32:
            start_kwargs["gui"] = "edgechromium"
        webview.start(**start_kwargs)
    except Exception as exc:                             # no WebView2 runtime or Mark-of-the-Web blocked DLL
        err_text = str(exc)
        if IS_WIN32 and any(tok in err_text for tok in ("0x80131515", "FileLoadException", "Zone.Identifier", "clr_loader", "Unblock")):
            unblock_extracted_files()
            _message("Windows blocked the downloaded WebView2 DLLs (Mark-of-the-Web).\n\n"
                     "Anchor just unblocked its files automatically — please launch Anchor.exe one more time.\n\n(%s)" % exc)
        elif IS_WIN32:
            _message("Anchor needs Microsoft's WebView2 runtime, which this PC doesn't have yet.\n\n"
                     "Install it from %s and start Anchor again.\n\n(%s)" % (WEBVIEW2_URL, exc))
        else:
            _message("Anchor could not start the native WebView window on this system.\n\n"
                     "On Linux, ensure python3-gi and gir1.2-webkit2-4.1 (or gir1.2-webkit2-4.0) are installed.\n\n(%s)" % exc)
        return 1
    if kernel32 is not None and mutex is not None:
        kernel32.CloseHandle(mutex)
    if posix_lock is not None:
        _release_single_instance_lock(posix_lock)
    return 0


if __name__ == "__main__":
    sys.exit(main())
