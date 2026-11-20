"""Cross-platform Anchor desktop shell verification suite (Windows, macOS, Linux).

Covers all 5 North Star criteria from planning/cross-platform-shell-2026-10-29/NORTH-STAR.md:
  1. Cross-platform shell/anchor_shell.py host (Win32 guards, _resolve_data_dir, POSIX single-instance lock,
     HostApi.apply CSS zoom fallback, HostApi.window_control maximize/restore/drag fallbacks, webview.start backend).
  2. Cross-platform shell/connect.py & onboard_bootstrap.py (_default_install_root, POSIX find_local_anchor_root,
     python3 preference on POSIX, stop_local_service_on_port POSIX lsof+SIGTERM excluding os.getpid(),
     installation_page platform-specific workspace paths & cold-start hints).
  3. POSIX cold-start (onboard.sh in repo root & dist_manifest.txt) and native shell builder (shell/build_unix.sh),
     preserving test_the_host_is_not_product_code (shell/ stays out of dist_manifest.txt).
  4. Automated Multi-OS GitHub Actions Build Workflow (.github/workflows/build-shell.yml).
  5. Deterministic cross-platform unit & integration checks + distro stdlib/manifest integrity.
"""
from __future__ import annotations

import os
import signal
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT / "shell") not in sys.path:
    sys.path.insert(0, str(ROOT / "shell"))

import anchor_shell
import connect
import onboard_bootstrap


class _FakeFlockMod:
    """In-memory POSIX fcntl.flock simulator for deterministic cross-platform testing."""
    LOCK_EX = 2
    LOCK_NB = 4
    LOCK_UN = 8

    def __init__(self):
        self.held_inodes: set[str] = set()
        self.fd_to_path: dict[int, str] = {}

    def register_fd(self, fd: int, path: Path):
        self.fd_to_path[fd] = str(path.resolve())

    def flock(self, fd: int, flags: int):
        key = self.fd_to_path.get(fd, str(fd))
        if flags & self.LOCK_UN:
            self.held_inodes.discard(key)
            return
        if (flags & self.LOCK_EX) and (key in self.held_inodes):
            raise BlockingIOError("Resource temporarily unavailable")
        self.held_inodes.add(key)


def test_resolve_data_dir_across_win32_darwin_and_linux():
    win_dir = anchor_shell._resolve_data_dir(
        platform="win32",
        env={"LOCALAPPDATA": r"C:\Users\example\AppData\Local"},
        home="/Users/example",
        test_name="",
    )
    assert win_dir == Path(r"C:\Users\example\AppData\Local") / "anchor-shell"

    mac_dir = anchor_shell._resolve_data_dir(
        platform="darwin",
        env={},
        home="/Users/example",
        test_name="",
    )
    assert mac_dir == Path("/Users/example/Library/Application Support/anchor-shell")

    linux_default = anchor_shell._resolve_data_dir(
        platform="linux",
        env={},
        home="/home/example",
        test_name="",
    )
    assert linux_default == Path("/home/example/.local/share/anchor-shell")

    linux_xdg = anchor_shell._resolve_data_dir(
        platform="linux",
        env={"XDG_DATA_HOME": "/custom/xdg"},
        home="/home/example",
        test_name="ci",
    )
    assert linux_xdg == Path("/custom/xdg/anchor-shell-test-ci")


def test_posix_single_instance_flock_acquire_contend_and_release(tmp_path):
    fake_fcntl = _FakeFlockMod()
    lock_file = tmp_path / "instance.lock"

    # Wrap flock to map any fd on lock_file to the same canonical path
    class _BoundFlock:
        LOCK_EX = _FakeFlockMod.LOCK_EX
        LOCK_NB = _FakeFlockMod.LOCK_NB
        LOCK_UN = _FakeFlockMod.LOCK_UN

        def __init__(self):
            self.locked = False

        def flock(self, _fd: int, flags: int):
            if flags & self.LOCK_UN:
                self.locked = False
                return
            if self.locked:
                raise BlockingIOError("already locked")
            self.locked = True

    bound = _BoundFlock()
    ok1, handle1 = anchor_shell._acquire_single_instance_lock(tmp_path, flock_mod=bound)
    assert ok1 is True and handle1 is not None
    assert lock_file.is_file()
    assert str(os.getpid()) in lock_file.read_text(encoding="utf-8")

    # Second instance contending on the same lock must fail non-blocking
    ok2, handle2 = anchor_shell._acquire_single_instance_lock(tmp_path, flock_mod=bound)
    assert ok2 is False and handle2 is None

    # After releasing the first lock, a new instance can acquire it cleanly
    anchor_shell._release_single_instance_lock(handle1, flock_mod=bound)
    ok3, handle3 = anchor_shell._acquire_single_instance_lock(tmp_path, flock_mod=bound)
    assert ok3 is True and handle3 is not None
    anchor_shell._release_single_instance_lock(handle3, flock_mod=bound)


def test_host_api_zoom_and_window_control_posix_fallbacks(monkeypatch, tmp_path):
    monkeypatch.setattr(anchor_shell, "IS_WIN32", False)
    monkeypatch.setattr(anchor_shell, "user32", None)
    monkeypatch.setattr(anchor_shell, "ZOOM_FILE", tmp_path / "zoom.txt")

    js_calls = []
    actions = []
    win = SimpleNamespace(
        native=None,
        evaluate_js=lambda code: js_calls.append(code),
        minimize=lambda: actions.append("minimize"),
        maximize=lambda: actions.append("maximize"),
        restore=lambda: actions.append("restore"),
        destroy=lambda: actions.append("destroy"),
    )
    host = anchor_shell.HostApi()
    host.bind(win)

    # Zoom steps up (+1 from 1.0 -> 1.1) and uses CSS zoom fallback on non-Win32
    new_z = host.zoom(1)
    assert new_z == 1.1
    assert any("document.documentElement.style.zoom = '1.1'" in c for c in js_calls)
    assert (tmp_path / "zoom.txt").read_text(encoding="utf-8").strip() == "1.1"

    # Window controls: minimize, maximize toggle (maximize -> restore), drag no-op, close
    host.window_control("minimize")
    host.window_control("maximize")
    assert host._maximized is True
    host.window_control("maximize")
    assert host._maximized is False
    host.window_control("drag")
    host.window_control("close")
    assert actions == ["minimize", "maximize", "restore", "destroy"]


def test_main_posix_mode_uses_flock_and_native_webview_backend(monkeypatch, tmp_path):
    monkeypatch.setattr(anchor_shell, "IS_WIN32", False)
    monkeypatch.setattr(anchor_shell, "IS_MAC", True)
    monkeypatch.setattr(anchor_shell, "kernel32", None)
    monkeypatch.setattr(anchor_shell, "user32", None)
    monkeypatch.setattr(anchor_shell, "DATA", tmp_path)
    monkeypatch.setattr(anchor_shell, "PROFILE", tmp_path / "profile")

    starts = []
    windows = []

    class _Events(list):
        def __iadd__(self, cb):
            self.append(cb)
            return self

    dummy_win = SimpleNamespace(
        native=None,
        events=SimpleNamespace(loaded=_Events(), shown=_Events()),
        load_html=lambda *_: None,
        load_url=lambda *_: None,
        evaluate_js=lambda *_: None,
    )
    fake_webview = SimpleNamespace(
        settings={},
        create_window=lambda title, **kw: (windows.append((title, kw)), dummy_win)[1],
        start=lambda **kw: starts.append(kw),
    )
    monkeypatch.setitem(sys.modules, "webview", fake_webview)
    monkeypatch.setattr(connect, "choose", lambda *_a, **_k: "")

    rc = anchor_shell.main([])
    assert rc == 0
    assert len(starts) == 1
    assert "gui" not in starts[0]
    assert starts[0]["storage_path"] == str(tmp_path / "profile")


def test_connect_default_install_root_and_installation_page_posix_vs_windows(monkeypatch):
    assert connect._default_install_root("win32", {}, "/Users/example") == r"C:\dev"
    assert connect._default_install_root("darwin", {}, "/Users/example") == str(Path("/Users/example") / "dev")
    assert connect._default_install_root("linux", {}, "/home/example") == str(Path("/home/example") / "dev")
    assert connect._default_install_root(
        "darwin", {"ANCHOR_SHELL_INSTALL_ROOT": "/opt/anchor-ws"}, "/Users/example"
    ) == "/opt/anchor-ws"

    monkeypatch.setattr(connect.sys, "platform", "darwin")
    mac_html = connect.installation_page(ROOT, default_dir="/Users/example/dev")
    assert "~/dev" in mac_html
    assert "./onboard.sh" in mac_html
    assert "/Users/example/dev" in mac_html
    assert "&lt;folder&gt;/Anchor" in mac_html

    monkeypatch.setattr(connect.sys, "platform", "win32")
    win_html = connect.installation_page(ROOT, default_dir=r"C:\dev")
    assert r"C:\dev" in win_html
    assert "onboard.cmd" in win_html


def test_stop_local_service_on_port_posix_uses_lsof_and_sigterm_without_killing_self(monkeypatch):
    monkeypatch.setattr(connect.sys, "platform", "darwin")
    my_pid = os.getpid()
    target_pid = my_pid + 4242
    run_calls = []
    killed = []

    def fake_run(cmd, **kwargs):
        run_calls.append((cmd, kwargs))
        assert kwargs.get("shell") is not True
        return SimpleNamespace(returncode=0, stdout=f"{my_pid}\n{target_pid}\n", stderr="")

    monkeypatch.setattr(connect.subprocess, "run", fake_run)
    monkeypatch.setattr(connect.os, "kill", lambda pid, sig: killed.append((pid, sig)))
    monkeypatch.setattr(
        connect.socket,
        "create_connection",
        lambda *_a, **_k: (_ for _ in ()).throw(OSError("closed")),
    )

    assert connect.stop_local_service_on_port(8777) is True
    assert run_calls[0][0] == ["lsof", "-ti", "tcp:8777", "-sTCP:LISTEN"]
    assert killed == [(target_pid, getattr(signal, "SIGTERM", 15))]


def test_onboard_bootstrap_prefers_python3_and_brew_on_posix(monkeypatch, tmp_path):
    monkeypatch.setattr(onboard_bootstrap.sys, "platform", "darwin")
    resolved = onboard_bootstrap.resolve_python_command(
        which_fn=lambda name: "/opt/homebrew/bin/python3" if name == "python3" else None,
        version_check_fn=lambda _exe: True,
    )
    assert resolved["ok"] is True
    assert resolved["command"] == "/opt/homebrew/bin/python3"
    assert resolved["note"] == "path_python3"

    plan_brew = onboard_bootstrap.bootstrap_plan(
        which_fn=lambda name: "/opt/homebrew/bin/brew" if name == "brew" else None,
        version_check_fn=lambda _exe: False,
    )
    assert plan_brew["action"] == "install_python_then_run"
    assert plan_brew.get("brew") is True

    # Cold-start check on POSIX accepts onboard.sh + share_onboard.py + USER-ONBOARD.md
    (tmp_path / "onboard.sh").write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    (tmp_path / "share_onboard.py").write_text("# stub\n", encoding="utf-8")
    (tmp_path / "USER-ONBOARD.md").write_text("# docs\n", encoding="utf-8")
    cold = onboard_bootstrap.package_root_has_cold_start(tmp_path)
    assert cold["ok"] is True
    assert cold["missing"] == []


def test_onboard_sh_build_unix_sh_and_github_workflow_contracts():
    onboard_sh = ROOT / "onboard.sh"
    assert onboard_sh.is_file()
    sh_txt = onboard_sh.read_text(encoding="utf-8")
    assert sh_txt.startswith("#!/usr/bin/env bash")
    assert "-m share_onboard" in sh_txt

    manifest = (ROOT / "dist_manifest.txt").read_text(encoding="utf-8")
    assert "\nonboard.sh\n" in manifest
    # Host separation invariant: shell/ must NEVER appear in dist_manifest.txt
    assert "shell/" not in manifest and "anchor_shell" not in manifest

    build_unix = ROOT / "shell" / "build_unix.sh"
    assert build_unix.is_file()
    bu_txt = build_unix.read_text(encoding="utf-8")
    assert "PyInstaller" in bu_txt
    assert "Anchor-macOS.zip" in bu_txt
    assert "Anchor-macOS.dmg" in bu_txt
    assert "Anchor-Linux.tar.gz" in bu_txt
    assert "codesign --force --deep --sign -" in bu_txt

    wf = ROOT / ".github" / "workflows" / "build-shell.yml"
    assert wf.is_file()
    wf_txt = wf.read_text(encoding="utf-8")
    for runner in ("windows-latest", "macos-latest", "ubuntu-latest"):
        assert runner in wf_txt
    for artifact in ("Anchor-Windows", "Anchor-macOS", "Anchor-Linux"):
        assert artifact in wf_txt
    assert "workflow_dispatch" in wf_txt
    assert "build_unix.sh" in wf_txt
    assert "build_exe.ps1" in wf_txt

    import distro
    patterns = distro.load_manifest(ROOT / "dist_manifest.txt")
    allows = [p for p in patterns if not p.startswith("!")]
    assert distro._match_any("onboard.sh", allows) is True
    assert distro._match_any("shell/anchor_shell.py", allows) is False
    assert distro._match_any("shell/build_unix.sh", allows) is False
    for rel in ("onboard.sh", "onboard_bootstrap.py", "tests/test_cross_platform_shell_2026_10_29.py"):
        hits = list(distro._scan_text(rel, (ROOT / rel).read_text(encoding="utf-8")))
        assert hits == [], f"Unexpected PII hits in {rel}: {hits}"


def test_macos_cocoa_patches_bypass_modal_save_panel_and_selected_range_crash(tmp_path, monkeypatch):
    import base64
    import subprocess as _sp

    # 1. HostApi.save_download writes unique files to ~/Downloads without modal dialogs
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    host = anchor_shell.HostApi()
    res1 = host.save_download("Report Draft.docx", base64.b64encode(b"DOCX-1").decode("ascii"))
    res2 = host.save_download("Report Draft.docx", base64.b64encode(b"DOCX-2").decode("ascii"))
    assert res1["ok"] is True and res1["filename"] == "Report Draft.docx"
    assert res2["ok"] is True and res2["filename"] == "Report Draft (1).docx"
    assert Path(res1["path"]).read_bytes() == b"DOCX-1"
    assert Path(res2["path"]).read_bytes() == b"DOCX-2"

    # 2. _install_macos_cocoa_patches patches DownloadDelegate, BrowserDelegate, and WebKitHost.keyDown_
    modal_called = []

    class _FakeDownloadDelegate:
        def download_decideDestinationUsingResponse_suggestedFilename_completionHandler_(
            self, _dl, _resp, _suggested, _handler
        ):
            modal_called.append("dd_modal")

    dl_started = []

    class _FakeBrowserDelegate:
        _file_name = None

        def download_completionHandler_error_(self, _tmp, _resp, _err):
            return "orig_done"

        def webView_decidePolicyForNavigationResponse_decisionHandler_(self, _wv, _nav_resp, _handler):
            modal_called.append("bd_modal")

    key_actions = []

    class _FakeResponder:
        # Mirrors WKWebView: implements copy_/paste_/cut_/selectAll_ WITHOUT selectedRange()
        def copy_(self, _sender):
            key_actions.append("copy")

        def paste_(self, _sender):
            key_actions.append("paste")

        def selectAll_(self, _sender):
            key_actions.append("selectAll")

    class _FakeWindow:
        def firstResponder(self):
            return _FakeResponder()

        def performClose_(self, _ev):
            key_actions.append("close")

    class _FakeWebKitHost:
        def window(self):
            return _FakeWindow()

        def keyDown_(self, _ev):
            key_actions.append("super_keydown")

    fake_cocoa = SimpleNamespace(
        webview_settings={"ALLOW_DOWNLOADS": True},
        WebKit=SimpleNamespace(WKNavigationResponsePolicyCancel=0),
        BrowserView=SimpleNamespace(
            DownloadDelegate=_FakeDownloadDelegate,
            BrowserDelegate=_FakeBrowserDelegate,
            WebKitHost=_FakeWebKitHost,
            app=SimpleNamespace(stop_=lambda _s: key_actions.append("quit")),
        ),
    )
    fake_foundation = SimpleNamespace(
        NSURL=SimpleNamespace(fileURLWithPath_=lambda p: f"file://{p}"),
        NSFileManager=SimpleNamespace(
            defaultManager=lambda: SimpleNamespace(
                fileExistsAtPath_=lambda _p: False,
                removeItemAtURL_error_=lambda *_a: None,
            )
        ),
        NSURLSession=SimpleNamespace(
            sharedSession=lambda: SimpleNamespace(
                downloadTaskWithURL_completionHandler_=lambda u, cb: SimpleNamespace(
                    resume=lambda: dl_started.append((u, cb))
                )
            )
        ),
    )
    fake_appkit = SimpleNamespace(NSCommandKeyMask=1 << 20)

    dl_dir = tmp_path / "MacDownloads"
    anchor_shell._install_macos_cocoa_patches(fake_cocoa, fake_foundation, fake_appkit, downloads_dir=dl_dir)

    # Exercise DownloadDelegate (<a download> path)
    dest_urls = []
    dd_inst = _FakeDownloadDelegate()
    dd_inst.download_decideDestinationUsingResponse_suggestedFilename_completionHandler_(
        None, None, "Brief.docx", lambda u: dest_urls.append(u)
    )
    assert modal_called == []
    assert len(dest_urls) == 1 and dest_urls[0].endswith("Brief.docx")

    # Exercise BrowserDelegate (Content-Disposition: attachment path)
    decisions = []
    bd_inst = _FakeBrowserDelegate()
    nav_resp = SimpleNamespace(
        canShowMIMEType=lambda: False,
        response=lambda: SimpleNamespace(
            suggestedFilename=lambda: "Slides.pptx",
            URL=lambda: "https://selected-host.example/api/steward/deliverable-file?download=1",
        ),
    )
    bd_inst.webView_decidePolicyForNavigationResponse_decisionHandler_(None, nav_resp, lambda pol: decisions.append(pol))
    assert modal_called == []
    assert decisions == [0]
    assert bd_inst._file_name.endswith("Slides.pptx")
    assert len(dl_started) == 1

    # Exercise WebKitHost.keyDown_ (Cmd+C, Cmd+V, Cmd+W, Cmd+Q without selectedRange())
    wk_inst = _FakeWebKitHost()
    for ch in ("c", "v", "w", "q"):
        ev = SimpleNamespace(
            modifierFlags=lambda: 1 << 20,
            charactersIgnoringModifiers=lambda c=ch: c,
            characters=lambda c=ch: c,
        )
        wk_inst.keyDown_(ev)
    assert key_actions == ["copy", "paste", "close", "quit"]

    # 3. bring_forward_existing reaps a hung macOS PID when osascript times out
    monkeypatch.setattr(anchor_shell, "IS_WIN32", False)
    monkeypatch.setattr(anchor_shell, "IS_MAC", True)
    monkeypatch.setattr(anchor_shell, "user32", None)
    monkeypatch.setattr(anchor_shell, "DATA", tmp_path)
    hung_pid = os.getpid() + 5555
    (tmp_path / "instance.lock").write_text(str(hung_pid), encoding="utf-8")
    reaped = []
    monkeypatch.setattr(
        _sp,
        "run",
        lambda cmd, **kw: (_ for _ in ()).throw(_sp.TimeoutExpired(cmd, 3)),
    )
    monkeypatch.setattr(anchor_shell.os, "kill", lambda pid, sig: reaped.append((pid, sig)))
    assert anchor_shell.bring_forward_existing() is False
    assert reaped == [(hung_pid, getattr(signal, "SIGKILL", 9))]


def test_macos_clean_close_releases_lock_exits_without_destroy_deadlock_and_wires_empty_api_race(tmp_path, monkeypatch):
    import threading as _th

    monkeypatch.setattr(anchor_shell, "IS_WIN32", False)
    monkeypatch.setattr(anchor_shell, "IS_MAC", True)
    monkeypatch.setattr(anchor_shell, "user32", None)
    monkeypatch.setattr(anchor_shell, "DATA", tmp_path)
    monkeypatch.setattr(anchor_shell, "_MAC_TERMINATING", False)

    # 1. Acquire single-instance lock, then trigger _terminate_macos_app and verify immediate lock release + exit
    class _LockTracker:
        LOCK_EX = 2
        LOCK_NB = 4
        LOCK_UN = 8

        def __init__(self):
            self.locked = False

        def flock(self, _fd, flags):
            if flags & self.LOCK_UN:
                self.locked = False
            else:
                if self.locked:
                    raise BlockingIOError("locked")
                self.locked = True

    tracker = _LockTracker()
    ok, lock_handle = anchor_shell._acquire_single_instance_lock(tmp_path, flock_mod=tracker)
    assert ok is True and tracker.locked is True
    monkeypatch.setattr(anchor_shell, "_ACTIVE_POSIX_LOCK", lock_handle)

    exited = _th.Event()
    exit_codes = []
    ordered_out = []
    destroy_calls = []

    fake_ns_win = SimpleNamespace(orderOut_=lambda arg: ordered_out.append(arg))
    fake_win = SimpleNamespace(native=fake_ns_win, destroy=lambda: destroy_calls.append("destroy"))

    # Stub PyObjCTools.AppHelper so callAfter runs immediately in test
    fake_app_helper = SimpleNamespace(
        callAfter=lambda fn, *a: fn(*a),
        stopEventLoop=lambda: ordered_out.append("stopEventLoop"),
    )
    monkeypatch.setitem(sys.modules, "PyObjCTools", SimpleNamespace(AppHelper=fake_app_helper))

    # HostApi.window_control('close') on macOS with native NSWindow must call _terminate_macos_app (NOT w.destroy())
    term_calls = []
    orig_term = anchor_shell._terminate_macos_app
    monkeypatch.setattr(
        anchor_shell,
        "_terminate_macos_app",
        lambda w=None, **kw: (
            term_calls.append((w, kw.get("reason"))),
            orig_term(
                w,
                exit_fn=lambda code: (exit_codes.append(code), exited.set()),
                exit_delay=0.0,
                reason=kw.get("reason") or "test",
            ),
        ),
    )

    host = anchor_shell.HostApi()
    host.bind(fake_win)
    host.window_control("close")

    assert exited.wait(timeout=2.0) is True
    assert exit_codes == [0]
    assert destroy_calls == []
    assert tracker.locked is False
    assert not (tmp_path / "instance.lock").exists()
    assert ordered_out == [None, "stopEventLoop"]
    assert term_calls == [(fake_win, "window_control:close")]

    # Immediately re-opening Anchor must acquire instance.lock cleanly with zero Force Quit needed
    ok_reopen, handle_reopen = anchor_shell._acquire_single_instance_lock(tmp_path, flock_mod=tracker)
    assert ok_reopen is True
    anchor_shell._release_single_instance_lock(handle_reopen, flock_mod=tracker)

    # 2. Verify main() on macOS disables native ALLOW_DOWNLOADS (no PyObjC selector monkeypatching needed)
    #    and wires BOTH win.events.closing (Menu/Dock Quit & Cmd+Q) and win.events.closed
    closing_cbs = []
    closed_cbs = []

    class _Events:
        def __init__(self, target):
            self._target = target

        def __iadd__(self, cb):
            self._target.append(cb)
            return self

    dummy_win = SimpleNamespace(
        native=fake_ns_win,
        events=SimpleNamespace(
            loaded=_Events([]),
            shown=_Events([]),
            closing=_Events(closing_cbs),
            closed=_Events(closed_cbs),
        ),
        load_html=lambda *_: None,
        load_url=lambda *_: None,
        evaluate_js=lambda *_: None,
    )
    fake_wv = SimpleNamespace(
        settings={},
        create_window=lambda *_a, **_k: dummy_win,
        start=lambda **_k: None,
    )
    monkeypatch.setitem(sys.modules, "webview", fake_wv)
    monkeypatch.setattr(anchor_shell, "kernel32", None)
    monkeypatch.setattr(anchor_shell, "PROFILE", tmp_path / "profile")
    monkeypatch.setattr(connect, "choose", lambda *_a, **_k: "")
    assert anchor_shell.main([]) == 0
    assert fake_wv.settings["ALLOW_DOWNLOADS"] is False
    assert len(closing_cbs) == 1
    assert len(closed_cbs) == 1
    term_calls.clear()
    assert closing_cbs[0]() is True
    closed_cbs[0]()
    assert term_calls == [(dummy_win, "events.closing"), (dummy_win, "events.closed")]

    # 3. Verify bring_forward_existing reaps a windowless ghost process (count of windows == 0)
    import subprocess as _sp

    ghost_pid = os.getpid() + 7777
    (tmp_path / "instance.lock").write_text(str(ghost_pid), encoding="utf-8")
    reaped_ghost = []
    monkeypatch.setattr(
        _sp,
        "run",
        lambda *_a, **_k: SimpleNamespace(returncode=0, stdout="0\n", stderr=""),
    )
    monkeypatch.setattr(anchor_shell.os, "kill", lambda pid, sig: reaped_ghost.append((pid, sig)))
    assert anchor_shell.bring_forward_existing() is False
    assert reaped_ghost == [(ghost_pid, getattr(signal, "SIGKILL", 9))]

    # 4. Verify static/app.js + build_unix.sh + update-mac-app.sh invariants
    app_js = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
    assert "if (!wireWindow()) {" in app_js
    assert 'window.addEventListener("pywebviewready", wireWindow);' in app_js
    assert 'h.window_control("close")' in app_js
    assert "classAddMethods" not in (ROOT / "shell" / "anchor_shell.py").read_text(encoding="utf-8")
    build_sh = (ROOT / "shell" / "build_unix.sh").read_text(encoding="utf-8")
    assert 'cp -f "$OVERLAY_ZIP" "$APP_BUNDLE/Contents/MacOS/' not in build_sh
    updater_sh = (ROOT / "update-mac-app.sh").read_text(encoding="utf-8")
    assert "ditto " in updater_sh
    assert "codesign --verify --deep --strict" in updater_sh



