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

