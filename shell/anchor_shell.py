"""Anchor as a Windows program: one WebView2 window around static/app.html (PLAN v2.2 section 3.3,
Skill Foundry/planning/anchor-app-shell-2026-09-29).

Not product code: it runs from its own venv (%LOCALAPPDATA%/anchor-shell/.venv, pywebview + pywin32) and is
not on the ship list. The service is unchanged; this only opens a window onto it.

  - its own taskbar identity (AppUserModelID) and the new anchor as its icon, so it is not "Python";
  - a persistent WebView2 profile, so the token is pasted once and the 30-day cookie is kept;
  - downloads allowed; app links (ms-word:, mailto:) and other sites go to Windows / the default browser;
  - one instance: a second launch brings the open window forward;
  - Ctrl + / Ctrl - / Ctrl 0 (and Ctrl + wheel) zoom the whole window, remembered for the next start. pywebview
    turns WebView2's own browser keys off (F5 would reload the app and lose the open tiles), so the pages catch
    just these keys (static/app.js, app-frame.js) and call zoom() here;
  - its own title bar (his ask, 2026-10-03): the window has no Windows caption; the page draws the bar (the anchor,
    the tiles, the one/two-pane toggle, minimize/maximize/close). The bar's empty parts carry CSS app-region: drag,
    which WebView2 (non-client region support) turns into a real caption - smooth moves, snap, double-click to
    maximize. Windows 11 rounds the corners; the window's outer edges resize it.

  - (every-device D1, 2026-10-03) it finds Anchor itself (shell/connect.py): the local copy, else the owner's saved
    mother ship address; a plain page when that address does not answer; packaged for other PCs as Anchor.zip
    (shell/build_exe.ps1), whose first run puts its own Start-menu shortcut in place.

Usage:  pythonw shell/anchor_shell.py [--url ADDRESS] [--setup]      (or the packaged Anchor.exe, same flags)
"""
import argparse
import ctypes
import os
import sys
from ctypes import wintypes
from pathlib import Path

APP_ID = "GhostWorldLabs.Anchor"
TITLE = "Anchor"
DEFAULT_URL = "http://127.0.0.1:8777/static/app.html"
FROZEN = bool(getattr(sys, "frozen", False))           # the packaged Anchor.exe


def _resolve_package_root():
    if not FROZEN:
        return Path(__file__).resolve().parent.parent
    try:
        exe_dir = Path(sys.executable).resolve().parent
        for cand in (exe_dir, exe_dir.parent, Path(r"C:\dev\Anchor"), Path(r"C:\dev\anchor-plus-skills")):
            if (cand / "launch_anchor_dashboard.py").is_file() or (cand / "onboard.cmd").is_file():
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
# ANCHOR_SHELL_TEST=<name>: a test copy beside his running Anchor - its own settings and profile, window title and
# single-instance lock, and it never touches his Start-menu shortcut.
TEST = os.environ.get("ANCHOR_SHELL_TEST", "")
DATA = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / ("anchor-shell" + ("-test-" + TEST if TEST else ""))
if TEST:
    TITLE = "Anchor (test %s)" % TEST
PROFILE = DATA / "profile"
WEBVIEW2_URL = "https://go.microsoft.com/fwlink/p/?LinkId=2124703"
ZOOM_FILE = PROFILE.parent / "zoom.txt"
ZOOM_STEPS = (0.5, 0.67, 0.75, 0.8, 0.9, 1.0, 1.1, 1.25, 1.5, 1.75, 2.0, 2.5, 3.0)   # Chrome's ladder

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
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
ERROR_ALREADY_EXISTS = 183
EDGE = 5                                                # px of the window's edge that resize it


def bring_forward_existing():
    """A second launch: find the open Anchor window, restore it and bring it to the front."""
    hwnd = user32.FindWindowW(None, TITLE)
    if hwnd:
        if user32.IsIconic(hwnd):                       # restore only a minimised window; a maximised one stays
            user32.ShowWindow(hwnd, 9)                  # SW_RESTORE
        user32.SetForegroundWindow(hwnd)
    return bool(hwnd)


def set_window_icon(hwnd, path):
    """WM_SETICON with the anchor (the window frame and Alt+Tab); the taskbar uses the shortcut's icon."""
    LR_LOADFROMFILE, IMAGE_ICON, WM_SETICON = 0x10, 1, 0x0080
    for which, size in ((1, 256), (0, 32)):             # ICON_BIG, ICON_SMALL
        h = user32.LoadImageW(None, str(path), IMAGE_ICON, size, size, LR_LOADFROMFILE)
        if h:
            user32.SendMessageW(hwnd, WM_SETICON, which, h)


def _own_title_bar(hwnd):
    """Run on the window's UI thread. A resizable window (snap, minimize animation, Windows 11 rounded corners) whose
    caption and frame nobody draws: WM_NCCALCSIZE gives the page the whole window; WM_NCHITTEST answers the outer
    edges with the resize codes; the bar's app-region is the caption."""
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
    if not FROZEN or TEST:
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
    user32.MessageBoxW(None, text, title, 0x40)


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
        try:
            from System import Action                   # pythonnet, pywebview's WinForms backend
            form = self._window.native
            form.Invoke(Action(lambda: setattr(form.browser.webview, "ZoomFactor", level)))
        except Exception as exc:                         # zoom is a convenience; the window works without it
            print("zoom:", exc, file=sys.stderr)

    def window_control(self, act="", *_args):
        w = self._window
        if act == "minimize":
            w.minimize()
        elif act == "maximize":
            if user32.IsZoomed(int(str(w.native.Handle))):
                w.restore()
            else:
                w.maximize()
        elif act == "close":
            w.destroy()

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
        result = connect.select_mother_ship(DATA, ROOT, auto_bootstrap=auto_boot)
        if not result["ok"]:
            self._show(connect.installation_page(ROOT))
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
        result = connect.pull_and_install_mothership(
            repo_url=repo_url or connect.DEFAULT_GITHUB_REPO,
            workspace_dir=target_dir or connect.DEFAULT_INSTALL_ROOT,
        )
        for _ in range(10 if result.get("onboard_ready") else 1):
            if connect.reachable(connect.LOCAL):
                connect.save_address(DATA, connect.LOCAL)
                self._address = connect.LOCAL
                self._html = ""
                self._window.load_url(self._address + "/setup")
                return ""
            time.sleep(0.5)
        return result.get("message") or "Mother ship repository pulled. Run onboard.cmd to start Anchor."

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
        from System import Action
        form = self._window.native
        changed = []

        def on_ui():                                    # WebView2 is touched on its own thread only
            settings = form.browser.webview.CoreWebView2.Settings
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

    mutex = kernel32.CreateMutexW(None, False, "Local\\" + APP_ID + ("." + TEST if TEST else ""))
    if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
        bring_forward_existing()
        return 0

    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    ensure_shortcut()
    if FROZEN:
        unblock_extracted_files()

    import webview                                      # the venv's; imported after the single-instance check
    webview.settings["ALLOW_DOWNLOADS"] = True
    webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = True   # ms-word:, mailto:, other sites -> Windows
    try:
        from webview.platforms import edgechromium as _edge
        _orig_new_win = getattr(_edge.EdgeChrome, "on_new_window_request", None)
        if callable(_orig_new_win) and not getattr(_edge.EdgeChrome, "_anchor_patched", False):
            def _anchor_new_window_request(self_ec, sender, args):
                try:
                    uri = str(args.get_Uri() or "")
                    base = (host._address or connect.LOCAL or "http://127.0.0.1:8777").rstrip("/")
                    if uri.startswith(base) or uri.startswith("http://127.0.0.1:") or uri.startswith("http://localhost:"):
                        args.set_Handled(True)
                        if "download=1" not in uri:
                            import json as _json
                            self_ec.pywebview_window.evaluate_js(
                                "window.ANCHOR_APP && window.ANCHOR_APP.open(" + _json.dumps(uri) + ", '_blank')"
                            )
                        return
                except Exception:
                    pass
                return _orig_new_win(self_ec, sender, args)
            _edge.EdgeChrome.on_new_window_request = _anchor_new_window_request
            _edge.EdgeChrome._anchor_patched = True
    except Exception:
        pass
    PROFILE.mkdir(parents=True, exist_ok=True)

    host = HostApi()
    address = "" if args.setup else connect.choose(DATA, args.url)
    if FROZEN and not args.url and address == connect.LOCAL:
        vcheck = connect.inspect_local_anchor_version(ROOT, check_system_dirs=True)
        if vcheck.get("needs_upgrade") or vcheck.get("needs_install"):
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
                else:
                    win.evaluate_js("location.reload()")
        except Exception as exc:                         # without it the bar does not move the window
            print("app-region:", exc, file=sys.stderr)

    win.events.loaded += on_loaded

    def on_shown():
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
        webview.start(gui="edgechromium", private_mode=False, storage_path=str(PROFILE))
    except Exception as exc:                             # no WebView2 runtime or Mark-of-the-Web blocked DLL
        err_text = str(exc)
        if any(tok in err_text for tok in ("0x80131515", "FileLoadException", "Zone.Identifier", "clr_loader", "Unblock")):
            unblock_extracted_files()
            _message("Windows blocked the downloaded WebView2 DLLs (Mark-of-the-Web).\n\n"
                     "Anchor just unblocked its files automatically — please launch Anchor.exe one more time.\n\n(%s)" % exc)
        else:
            _message("Anchor needs Microsoft's WebView2 runtime, which this PC doesn't have yet.\n\n"
                     "Install it from %s and start Anchor again.\n\n(%s)" % (WEBVIEW2_URL, exc))
        return 1
    kernel32.CloseHandle(mutex)
    return 0


if __name__ == "__main__":
    sys.exit(main())
