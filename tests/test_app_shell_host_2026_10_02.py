"""The Anchor program's host (shell/anchor_shell.py), PLAN v2.2 section 3.3: the identity and icon it wears,
and that it stays off the stdlib product (its third-party imports live only under shell/)."""
import html
import json
import struct
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parent.parent
pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="the host is a Windows program")


def test_the_host_wears_his_anchor_and_its_own_taskbar_identity():
    sys.path.insert(0, str(ROOT / "shell"))
    import anchor_shell
    assert anchor_shell.ICON == ROOT / "vendor" / "brand" / "anchor-icon.ico"
    assert anchor_shell.APP_ID == "GhostWorldLabs.Anchor"
    assert anchor_shell.DEFAULT_URL.endswith("/static/app.html") and ":8777" in anchor_shell.DEFAULT_URL
    data = anchor_shell.ICON.read_bytes()
    reserved, kind, count = struct.unpack("<HHH", data[:6])
    sizes = {data[6 + 16 * i] or 256 for i in range(count)}
    assert (reserved, kind) == (0, 1) and {32, 256} <= sizes      # the frame's small and big icons exist


def test_the_host_is_not_product_code():
    ship = (ROOT / "dist_manifest.txt").read_text(encoding="utf-8") if (ROOT / "dist_manifest.txt").is_file() else ""
    assert "shell/" not in ship and "anchor_shell" not in ship
    for py in (ROOT / "shell").glob("*.py"):
        assert "import webview" not in py.read_text(encoding="utf-8").split("def main", 1)[0] or py.name != "anchor_shell.py"


@pytest.fixture
def connection_host(monkeypatch, tmp_path):
    """Keep the host API on temporary settings and an inert, recording window."""
    monkeypatch.syspath_prepend(str(ROOT / "shell"))
    import anchor_shell
    import connect

    monkeypatch.setattr(anchor_shell, "DATA", tmp_path / "settings")
    monkeypatch.setattr(anchor_shell, "ZOOM_FILE", tmp_path / "zoom.json")

    def unexpected_probe(*_args, **_kwargs):
        pytest.fail("A host test attempted an unmocked reachability check")

    monkeypatch.setattr(connect, "reachable", unexpected_probe)
    window = SimpleNamespace(html=[], urls=[])
    window.load_html = window.html.append
    window.load_url = window.urls.append
    host = anchor_shell.HostApi()
    host.bind(window)
    return SimpleNamespace(shell=anchor_shell, connection=connect, host=host,
                           window=window, data=anchor_shell.DATA)


@pytest.mark.parametrize("address", ["", " \t ", "http://other-host.example"])
def test_invalid_host_connection_never_probes_saves_or_opens(connection_host, address):
    h = connection_host
    assert h.host.connect(address)
    assert h.host._address == ""
    assert h.host._html == ""
    assert h.window.urls == [] and h.window.html == []
    assert not h.data.exists()


def test_example_host_connection_never_probes_saves_or_opens(connection_host):
    h = connection_host
    assert h.host.connect(h.connection.EXAMPLE)
    assert h.host._address == ""
    assert h.window.urls == [] and h.window.html == []
    assert not h.data.exists()


def _existing_settings(h, address):
    h.data.mkdir(parents=True)
    path = h.data / "settings.json"
    path.write_text(json.dumps({"address": address, "theme": "dark",
                               "provider": {"kind": "local"}}), encoding="utf-8")
    return path


def test_failed_host_connection_preserves_opened_address_and_settings(connection_host, monkeypatch):
    h = connection_host
    previous = "https://previous-host.example"
    settings = _existing_settings(h, previous)
    before = settings.read_bytes()
    h.host._open(previous)
    probes = []

    def offline(address):
        probes.append(address)
        return False

    monkeypatch.setattr(h.connection, "reachable", offline)
    selected = "https://selected-host.example"
    error = h.host.connect(selected)
    assert selected in error and "selected mother ship" in error
    assert "PUTER" not in error
    assert probes == [selected]
    assert h.host._address == previous and h.host._html == ""
    assert h.window.urls == [previous + h.connection.APP_PATH]
    assert h.window.html == []
    assert settings.read_bytes() == before


def test_successful_host_connection_normalizes_saves_and_clears_recovery_page(connection_host, monkeypatch):
    h = connection_host
    settings = _existing_settings(h, "https://previous-host.example")
    page = h.connection.setup_page("")
    h.host._show(page)
    probes = []

    def online(address):
        probes.append(address)
        return True

    monkeypatch.setattr(h.connection, "reachable", online)
    selected = "https://selected-host.example:8443"
    assert h.host.connect(" selected-host.example:8443/ ") == ""
    assert probes == [selected]
    assert h.host._address == selected and h.host._html == ""
    assert h.window.html == [page]
    assert h.window.urls == [selected + h.connection.APP_PATH]
    assert json.loads(settings.read_text(encoding="utf-8")) == {
        "address": selected, "theme": "dark", "provider": {"kind": "local"}}


def test_retry_keeps_selected_address_and_settings_until_same_host_answers(connection_host, monkeypatch):
    h = connection_host
    selected = "https://selected-host.example:8443"
    settings = _existing_settings(h, selected)
    before = settings.read_bytes()
    h.host._address = selected
    page = h.connection.offline_page(selected)
    h.host._show(page)
    answers = iter([False, True])
    probes = []

    def answer(address):
        probes.append(address)
        return next(answers)

    monkeypatch.setattr(h.connection, "reachable", answer)
    error = h.host.retry()
    assert "selected mother ship" in error and "awake" in error and "Anchor" in error
    assert "PUTER" not in error
    assert h.host._address == selected and h.host._html == page
    assert h.window.urls == [] and h.window.html == [page]
    assert settings.read_bytes() == before

    assert h.host.retry() == ""
    assert probes == [selected, selected]
    assert h.host._address == selected and h.host._html == ""
    assert h.window.urls == [selected + h.connection.APP_PATH]
    assert settings.read_bytes() == before


def test_change_address_keeps_and_escapes_selected_address_without_probing(connection_host):
    h = connection_host
    selected = 'https://selected-host.example/?label="<ship>&'
    settings = _existing_settings(h, selected)
    before = settings.read_bytes()
    h.host._address = selected
    assert h.host.change_address() == ""
    assert h.host._address == selected
    assert h.host._html == h.connection.setup_page(selected)
    assert 'value="%s"' % html.escape(selected, quote=True) in h.host._html
    assert selected not in h.host._html
    assert h.window.html == [h.host._html] and h.window.urls == []
    assert settings.read_bytes() == before


class _EventCallbacks(list):
    def __iadd__(self, callback):
        self.append(callback)
        return self


@pytest.fixture
def inert_host_launch(connection_host, monkeypatch):
    """Exercise page selection without a native window, singleton, or browser."""
    h = connection_host
    calls = SimpleNamespace(windows=[], starts=[], closed=[], app_ids=[], shortcuts=[])
    monkeypatch.setattr(h.shell, "PROFILE", h.data / "profile")
    monkeypatch.setattr(h.shell, "kernel32", SimpleNamespace(
        CreateMutexW=lambda *_: 123,
        CloseHandle=calls.closed.append))
    monkeypatch.setattr(h.shell.ctypes, "get_last_error", lambda: 0)
    monkeypatch.setattr(h.shell.ctypes, "windll", SimpleNamespace(
        shell32=SimpleNamespace(SetCurrentProcessExplicitAppUserModelID=calls.app_ids.append)))
    monkeypatch.setattr(h.shell, "ensure_shortcut", lambda: calls.shortcuts.append(True))
    monkeypatch.setattr(h.shell, "bring_forward_existing", lambda: pytest.fail("Unexpected singleton activation"))
    monkeypatch.setattr(h.shell, "_message", lambda *_: pytest.fail("Unexpected native message"))
    h.window.events = SimpleNamespace(loaded=_EventCallbacks(), shown=_EventCallbacks())

    def create_window(title, **kwargs):
        calls.windows.append((title, kwargs))
        return h.window

    webview = SimpleNamespace(settings={}, create_window=create_window,
                              start=lambda **kwargs: calls.starts.append(kwargs))
    monkeypatch.setitem(sys.modules, "webview", webview)
    return SimpleNamespace(h=h, calls=calls, webview=webview)


@pytest.mark.parametrize("mode", ["fresh", "saved-offline", "saved-online", "setup", "override", "local"])
def test_main_uses_existing_connection_path_without_native_side_effects(inert_host_launch, monkeypatch, mode):
    launch = inert_host_launch
    h = launch.h
    saved = "https://saved-host.example"
    override = "https://explicit-host.example"
    settings = None if mode == "fresh" else _existing_settings(h, saved)
    before = settings.read_bytes() if settings else None
    probes = []

    def reachable(address, **kwargs):
        probes.append((address, kwargs))
        if address == h.connection.LOCAL:
            return mode in {"override", "local"}
        return mode in {"saved-online", "override"}

    monkeypatch.setattr(h.connection, "reachable", reachable)
    args = ["--setup"] if mode == "setup" else []
    if mode == "override":
        args = ["--url", override + h.connection.APP_PATH]
    assert h.shell.main(args) == 0

    assert len(launch.calls.windows) == 1 and len(launch.calls.starts) == 1
    title, page = launch.calls.windows[0]
    host = page["js_api"]
    assert title == h.shell.TITLE and host._window is h.window
    assert launch.calls.closed == [123] and launch.calls.app_ids == [h.shell.APP_ID]
    assert launch.calls.shortcuts == [True]
    assert len(h.window.events.loaded) == 1 and len(h.window.events.shown) == 1
    assert h.window.html == [] and h.window.urls == []
    assert launch.webview.settings == {"ALLOW_DOWNLOADS": True, "OPEN_EXTERNAL_LINKS_IN_BROWSER": True}

    if mode == "fresh":
        assert host._address == ""
        assert page["html"] == h.connection.setup_page("")
        assert 'value=""' in page["html"]
        assert probes == [(h.connection.LOCAL, {"timeout": 1.5})]
    elif mode == "saved-offline":
        assert host._address == saved and page["html"] == h.connection.offline_page(saved)
        assert "selected mother ship" in page["html"] and "PUTER" not in page["html"]
        assert probes == [(h.connection.LOCAL, {"timeout": 1.5}), (saved, {})]
    elif mode == "setup":
        assert host._address == saved and page["html"] == h.connection.setup_page(saved)
        assert probes == []
    else:
        selected = {"saved-online": saved, "override": override, "local": h.connection.LOCAL}[mode]
        assert host._address == selected and page["url"] == selected + h.connection.APP_PATH
        assert host._html == ""
        if mode == "override":
            assert probes == [(override, {})]
        elif mode == "local":
            assert probes == [(h.connection.LOCAL, {"timeout": 1.5})]
        else:
            assert probes == [(h.connection.LOCAL, {"timeout": 1.5}), (saved, {})]
    if settings:
        assert settings.read_bytes() == before
    else:
        assert not (h.data / "settings.json").exists()
