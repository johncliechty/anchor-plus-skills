"""Markdown-read resilience: one malformed file must not 500 the dashboard.

Regression for the 2026-06-11 incident where a stray Windows-1252 byte (0x97,
an em-dash) in a `domains/*.md` file made the server's strict
`read_text(encoding="utf-8")` raise UnicodeDecodeError and return HTTP 500 for
GET / and every mutation endpoint.

Fix under test: `anchor_gui._read_md_text` decodes leniently on a
UnicodeDecodeError, and `gather_all` skips-and-warns on any per-file parse
failure, so a single bad file degrades gracefully instead of taking down the
whole dashboard. The daily healthcheck still reads strictly, so a malformed
file is still surfaced for cleanup (not tested here).

All integration checks boot a throwaway server on an OS-assigned free port.
"""
import importlib
import threading
import urllib.error
import urllib.request

import paths


def _reload_gui(tmp_path, monkeypatch):
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(tmp_path))
    importlib.reload(paths)
    paths.ensure_data_dirs()
    import anchor_gui
    return importlib.reload(anchor_gui)


def _get(url):
    try:
        with urllib.request.urlopen(url, timeout=5) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


# The exact failure shape from the incident: a cp1252 em-dash (0x97), which is
# an invalid UTF-8 start byte.
_BAD_BYTES = b"- [ ] It's broken \x97 Priority: 1 \x97 [test]\n"


def test_read_md_text_does_not_raise_on_non_utf8(tmp_path, monkeypatch):
    gui = _reload_gui(tmp_path, monkeypatch)
    bad = tmp_path / "domains" / "bad.md"
    bad.write_bytes(_BAD_BYTES)
    # Strict read would raise UnicodeDecodeError; the helper must not.
    text = gui._read_md_text(bad)
    assert isinstance(text, str)
    assert "It's broken" in text  # content survived (the stray byte became U+FFFD)


def test_gather_all_skips_bad_file_and_keeps_good(tmp_path, monkeypatch):
    gui = _reload_gui(tmp_path, monkeypatch)
    (tmp_path / "domains" / "academic.md").write_text(
        "# Academic\n- [ ] good-task — Priority: 1 — [academic]\n", encoding="utf-8"
    )
    (tmp_path / "domains" / "bad.md").write_bytes(_BAD_BYTES)
    # Must not raise, and the good task from the sibling file must survive.
    projects, tasks, inbox = gui.gather_all()
    texts = [t["text"] for t in tasks]
    assert any("good-task" in t for t in texts)


def test_gather_all_warns_and_continues_when_a_parse_raises(tmp_path, monkeypatch):
    """A hard parse failure (not just encoding) on one file is skipped + warned,
    not fatal — proves the gather_all per-file try/except wrapper."""
    gui = _reload_gui(tmp_path, monkeypatch)
    (tmp_path / "domains" / "academic.md").write_text(
        "# Academic\n- [ ] good-task — Priority: 1 — [academic]\n", encoding="utf-8"
    )
    (tmp_path / "domains" / "boom.md").write_text("# Boom\n", encoding="utf-8")

    real_parse = gui.parse_tasks_from_md

    def flaky(fp, *a, **k):
        if getattr(fp, "name", "") == "boom.md":
            raise ValueError("synthetic parse failure")
        return real_parse(fp, *a, **k)

    monkeypatch.setattr(gui, "parse_tasks_from_md", flaky)
    projects, tasks, inbox = gui.gather_all()  # must not raise
    assert any("good-task" in t["text"] for t in tasks)
    assert any("boom.md" in w for w in gui.LAST_GATHER_WARNINGS)


def test_dashboard_get_is_200_with_a_malformed_domain_file(tmp_path, monkeypatch):
    """The headline regression: GET / returns 200 (not 500) with a bad file."""
    gui = _reload_gui(tmp_path, monkeypatch)
    gui.DASHBOARD_MD.write_text(
        "# Dashboard\n- [ ] dash-task — Priority: 2 — [academic]\n", encoding="utf-8"
    )
    (tmp_path / "domains" / "bad.md").write_bytes(_BAD_BYTES)

    server = gui.make_server("127.0.0.1", 0)
    port = server.server_address[1]
    assert port != 8777
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    try:
        code, body = _get(f"http://127.0.0.1:{port}/")
        assert code == 200, f"dashboard 500'd on a malformed domain file (code {code})"
        code2, _ = _get(f"http://127.0.0.1:{port}/api/status")
        assert code2 == 200
    finally:
        server.shutdown()


def test_mark_done_does_not_crash_with_a_malformed_sibling_file(tmp_path, monkeypatch):
    """Mutations loop ALL md files; a bad sibling must not crash the op
    (regression for POST /api/done 500)."""
    gui = _reload_gui(tmp_path, monkeypatch)
    (tmp_path / "domains" / "academic.md").write_text(
        "# Academic\n- [ ] finish-me — Priority: 1 — [academic]\n", encoding="utf-8"
    )
    (tmp_path / "domains" / "bad.md").write_bytes(_BAD_BYTES)
    # Must not raise even though a sibling file is malformed.
    gui.mark_done("finish-me")
    _, tasks, _ = gui.gather_all()
    done = [t for t in tasks if "finish-me" in t["text"]]
    assert done and done[0]["done"] is True
