"""Portable mother ship selection, persistence, and connection/recovery pages."""
import http.server
import json
import re
import socketserver
import sys
import threading
import urllib.error
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "shell"))
import connect  # noqa: E402


RECIPIENT = "https://recipient-host.example.net"
LEGACY_AUTHOR_ADDRESS = "https://gwl-server.tailb49f65.ts.net"


class _Page(HTMLParser):
    """Read actual HTML attributes and displayed text, including escaped values."""

    def __init__(self, source):
        super().__init__(convert_charrefs=True)
        self.elements = {}
        self.text = []
        self.hidden_text = []
        self._hidden = 0
        self.feed(source)

    def handle_starttag(self, tag, attrs):
        self.elements.setdefault(tag, []).append(dict(attrs))
        if tag in {"script", "style"}:
            self._hidden += 1

    def handle_endtag(self, tag):
        if tag in {"script", "style"}:
            self._hidden -= 1

    def handle_data(self, data):
        if self._hidden:
            self.hidden_text.append(data)
        else:
            self.text.append(data)


def _address_input(page):
    inputs = _Page(page).elements.get("input", [])
    assert len(inputs) == 1
    return inputs[0]


def _assert_no_author_identity(text):
    for author_term in ("gwl-server", "tailb49f65"):
        assert author_term not in text.lower()
    assert not re.search(r"\b(?:puter|john)\b", text, re.IGNORECASE)


@pytest.mark.parametrize("typed, want", [
    ("recipient-host.example.net", RECIPIENT),
    (RECIPIENT + "/static/app.html", RECIPIENT),
    ("  " + RECIPIENT + "/  ", RECIPIENT),
    ("http://127.0.0.1:8777", "http://127.0.0.1:8777"),
    ("http://localhost:8777/x", "http://localhost:8777"),
    ("http://[::1]:8777/static/app.html", "http://[::1]:8777"),
])
def test_typed_addresses_become_one_origin(typed, want):
    assert connect.normalize(typed) == (want, None)


def test_legacy_saved_author_address_remains_valid():
    assert connect.normalize(LEGACY_AUTHOR_ADDRESS) == (LEGACY_AUTHOR_ADDRESS, None)


@pytest.mark.parametrize("typed", ["", "http://recipient-host.example.net", "ftp://x", "https://"])
def test_bad_addresses_are_refused_with_a_generic_reason(typed):
    address, why = connect.normalize(typed)
    assert address is None and why
    _assert_no_author_identity(why)
    if not typed:
        assert "mother ship" in why.lower()


@pytest.mark.parametrize("typed", [
    "mother-ship.example",
    "https://mother-ship.example",
    "https://mother-ship.example/static/app.html",
    "  https://MOTHER-SHIP.EXAMPLE/  ",
    "https://mother-ship.example.:8443/",
])
def test_the_displayed_example_is_refused_as_a_connection_address(typed, monkeypatch):
    def unexpected_probe(*args, **kwargs):
        pytest.fail("An example address must never trigger a network probe")

    monkeypatch.setattr(connect, "reachable", unexpected_probe)
    monkeypatch.setattr(connect.urllib.request, "urlopen", unexpected_probe)
    address, why = connect.normalize(typed)
    assert address is None
    assert why and "example" in why.lower()
    _assert_no_author_identity(why)


def test_a_fresh_client_has_no_selected_or_saved_address(tmp_path, monkeypatch):
    probes = []

    def local_probe(address, timeout=5.0):
        probes.append((address, timeout))
        assert address == connect.LOCAL
        return False

    monkeypatch.setattr(connect, "reachable", local_probe)
    assert connect.load_address(tmp_path) == ""
    assert connect.choose(tmp_path) == ""
    assert probes == [(connect.LOCAL, 1.5)]
    assert not connect.settings_file(tmp_path).exists()
    assert _address_input(connect.setup_page())["value"] == ""


def test_the_fresh_page_labels_its_blank_field_and_shows_an_inactive_example():
    page = connect.setup_page()
    parsed = _Page(page)
    field = _address_input(page)
    assert field["value"] == ""
    assert field.get("id")
    assert any(label.get("for") == field["id"] for label in parsed.elements.get("label", []))
    assert "mother ship" in " ".join(parsed.text).lower()
    assert "Example only: " + connect.EXAMPLE in "".join(parsed.text)
    assert all(connect.EXAMPLE not in (value or "")
               for elements in parsed.elements.values() for attributes in elements
               for value in attributes.values())
    assert connect.EXAMPLE not in "".join(parsed.hidden_text)
    assert connect.EXAMPLE not in field.get("placeholder", "")
    _assert_no_author_identity(page)


@pytest.mark.parametrize("address", [RECIPIENT, LEGACY_AUTHOR_ADDRESS])
def test_saved_addresses_are_used_as_exact_prefills_and_preserved(tmp_path, monkeypatch, address):
    connect.save_address(tmp_path, address)
    before = connect.settings_file(tmp_path).read_bytes()
    monkeypatch.setattr(connect, "reachable", lambda address, timeout=5.0: False)
    assert connect.load_address(tmp_path) == address
    assert connect.choose(tmp_path) == address
    assert _address_input(connect.setup_page(connect.load_address(tmp_path)))["value"] == address
    assert connect.settings_file(tmp_path).read_bytes() == before


def test_saving_an_address_preserves_unrelated_nested_settings(tmp_path):
    settings = {
        "address": "https://old-host.example.net",
        "window": {"width": 940, "position": [12, 34]},
        "providers": {"selected": "local", "options": {"enabled": True}},
        "theme": "dark",
    }
    connect.settings_file(tmp_path).write_text(json.dumps(settings), encoding="utf-8")
    connect.save_address(tmp_path, RECIPIENT)
    assert connect.load_address(tmp_path) == RECIPIENT
    assert json.loads(connect.settings_file(tmp_path).read_text(encoding="utf-8")) == {
        **settings, "address": RECIPIENT,
    }


def test_an_explicit_address_skips_probes_and_does_not_overwrite_the_saved_one(tmp_path, monkeypatch):
    connect.save_address(tmp_path, RECIPIENT)
    before = connect.settings_file(tmp_path).read_bytes()

    def unexpected_probe(*args, **kwargs):
        pytest.fail("Explicit selection must not probe local or saved addresses")

    monkeypatch.setattr(connect, "reachable", unexpected_probe)
    given = "https://explicit-host.example.net"
    assert connect.choose(tmp_path, given) == given
    assert connect.load_address(tmp_path) == RECIPIENT
    assert connect.settings_file(tmp_path).read_bytes() == before


@pytest.mark.parametrize("local_answers, expected", [(True, connect.LOCAL), (False, RECIPIENT)])
def test_local_then_saved_selection_only_probes_the_local_app(tmp_path, monkeypatch, local_answers, expected):
    connect.save_address(tmp_path, RECIPIENT)
    before = connect.settings_file(tmp_path).read_bytes()
    probes = []

    def local_probe(address, timeout=5.0):
        probes.append((address, timeout))
        assert address == connect.LOCAL
        return local_answers

    monkeypatch.setattr(connect, "reachable", local_probe)
    assert connect.choose(tmp_path) == expected
    assert probes == [(connect.LOCAL, 1.5)]
    assert connect.settings_file(tmp_path).read_bytes() == before


class _App(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        body = b"<!doctype html><title>Anchor</title>" if self.path == connect.APP_PATH else b"no"
        self.send_response(200 if self.path == connect.APP_PATH else 404)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def test_reachable_means_anchors_app_page_answers(monkeypatch):
    # Disable ambient proxies and allow this test to contact only its own loopback server.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with socketserver.TCPServer(("127.0.0.1", 0), _App) as server:
        origin = "http://127.0.0.1:%d" % server.server_address[1]

        def open_loopback(url, timeout, context):
            assert url == origin + connect.APP_PATH
            return opener.open(url, timeout=timeout)

        monkeypatch.setattr(connect.urllib.request, "urlopen", open_loopback)
        thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
        thread.start()
        try:
            assert connect.reachable(origin)
        finally:
            server.shutdown()
            thread.join(timeout=2)
        assert not thread.is_alive()


@pytest.mark.parametrize("failure", [
    urllib.error.URLError("fixture unreachable"),
    OSError("fixture connection refused"),
    ValueError("fixture invalid address"),
])
def test_reachability_failures_are_reported_without_real_network(monkeypatch, failure):
    calls = []

    def fail_open(url, timeout, context):
        calls.append((url, timeout))
        raise failure

    monkeypatch.setattr(connect.urllib.request, "urlopen", fail_open)
    assert not connect.reachable(RECIPIENT, timeout=0.25)
    assert calls == [(RECIPIENT + connect.APP_PATH, 0.25)]


def test_connection_page_escapes_prefill_and_recovery_message():
    prefill = 'x" onmouseover="bad'
    message = '<img src=x onerror="bad"> & "failure"'
    page = connect.setup_page(prefill, message)
    parsed = _Page(page)
    assert _address_input(page)["value"] == prefill
    assert "onmouseover" not in _address_input(page)
    assert not parsed.elements.get("img")
    assert message in "".join(parsed.text)
    assert "window_control('close')" in page


def test_recovery_page_keeps_the_selected_address_and_recovery_controls():
    address = RECIPIENT + '/<img src=x onerror="bad"> & "failure"'
    page = connect.offline_page(address)
    parsed = _Page(page)
    text = "".join(parsed.text)
    assert address in text
    assert "Retry" in text
    assert "Change address" in text
    assert "mother ship" in text.lower()
    assert not parsed.elements.get("img")
    assert "window_control('close')" in page
    _assert_no_author_identity(page)


def test_default_recovery_page_contains_no_author_identity():
    _assert_no_author_identity(connect.offline_page(RECIPIENT))
