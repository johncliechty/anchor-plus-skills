"""The Cave of Wonders' tidy-up (his word, 2026-10-02): the Workbench retired for plain terminals at the board's foot;
the Today block gone (the dated deliveries are enough); the composer kept in view; a wordless steward turn said."""
import os

import high_seat_page as hsp
import terminal_session as ts

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(rel):
    return open(os.path.join(HERE, rel), encoding="utf-8").read()


def test_the_terminal_section_offers_the_engines_with_the_terminal_seat_selected():
    html = hsp._terminal({"default_cli": "grok", "rows": []})
    assert 'id="shTerm"' in html and 'id="termNew"' in html and 'id="termDock" hidden' in html
    assert '<option value="grok" selected>Grok</option>' in html and '<option value="claude">Claude</option>' in html
    assert "Workbench" not in html and "Open cockpit" not in html


def test_a_plain_record_holds_every_shell_guard():
    assert ts._is_shell_record({"backend": "claude", "plain": True})
    assert ts._is_shell_record({"backend": "shell"})
    assert not ts._is_shell_record({"backend": "claude"})


def test_the_routes_and_the_page_wiring():
    rt = _read("route_table.py")
    assert '"/api/cave/terminal", AUTH_TOKEN' in rt and '"/api/cave/terminals", AUTH_TOKEN' in rt
    js = _read("static/cave-terminal.js")
    assert "/api/cave/terminal'" in js and "/api/rnd/term_ws?session=" in js and "/api/rnd/term_kill" in js and "convertEol: false" in js
    hs = _read("static/high-seat-page.js")
    assert "term: '#shTerm'" in hs and "bench:" not in hs and "#termTabs .ttab" not in hs, "an open terminal does not hold the reload (its tabs re-attach)"


def test_a_wordless_turn_is_said_and_the_box_stays_in_view():
    dlg = _read("static/steward-dialogue.js")
    assert "var SILENT = " in dlg and "live.sent = true" in dlg and "if (mine) appendLine('st', SILENT, 'dim')" in dlg
    hs = _read("static/high-seat-page.js")
    assert "panel.style.height = Math.max(320, window.innerHeight - top - 12)" in hs and "Math.round(window.innerHeight / 3)" in hs


def test_the_plain_mark_survives_the_registry(tmp_path, monkeypatch):
    # found driving the page (2026-10-02): the registry rebuilds each record from its known fields and dropped `plain`,
    # so a reload found no terminals and the shell guards would not have held
    import session_registry as sr
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(tmp_path))
    rec = sr.register_session(project_id="__dashboard__", lane="general", backend="claude", worktree_path=str(tmp_path),
                              branch="", status=sr.STATUS_RUNNING, label="Terminal 1", session_id="t1")
    assert rec.get("plain") is False
    sr.update_session("t1", plain=True)
    assert sr.get_session("t1")["plain"] is True and [r["plain"] for r in sr.list_sessions()] == [True]


def test_the_health_banner_shows_only_when_the_check_found_issues():
    rows = [{"rule": "health", "text": "Health check found issues", "why": "2026-10-02 \u2014 Doctor can diagnose it", "href": "/doctor?x=1"}]
    html = hsp._health_banner({"rows": rows, "build": "t"})
    assert 'class="healthbar"' in html and 'data-tool="doctor"' in html and 'data-tool="zombie"' in html and 'href="/doctor?x=1"' in html
    assert hsp._health_banner({"rows": [], "build": "t"}) == ""
    assert "Health check found issues" not in hsp._terminal({"rows": rows}), "the health row lives in the banner, not under the Terminal"


def test_the_header_has_no_old_dashboard_and_tiles_name_the_steward():
    src = _read("high_seat_page.py")
    assert "the old dashboard</a>" not in src
    hs = _read("static/high-seat-page.js")
    assert "STEWARD_NAME + ' — this cockpit" in hs


def test_kill_never_touches_the_live_tree_of_a_plain_terminal():
    # Grok 2026-10-02: a plain terminal's path is C:/dev itself - no swarm job there is its own, no worktree is removed
    src = _read("terminal_session.py")
    assert "if wt and not _is_shell_record(rec):" in src
    assert 'if _is_shell_record(record)\n              else _wt.remove_worktree(session_id, project_id=project_id))' in src
    assert "if is_shell or plain:" in src and "plain=bool(plain)," in src


def test_kill_never_touches_the_live_tree_of_a_plain_terminal():
    # Grok 2026-10-02: a plain terminal's path is C:/dev itself - no swarm job there is its own, no worktree is removed
    src = _read("terminal_session.py")
    assert "if wt and not _is_shell_record(rec):" in src
    assert 'if _is_shell_record(record)\n              else _wt.remove_worktree(session_id, project_id=project_id))' in src
    assert "if is_shell or plain:" in src and "plain=bool(plain)," in src


def test_a_slow_page_says_where_it_waited(capsys):
    # 2026-10-02: the Cave answered in 2.5-5.5 s with the server's Python idle; the watcher names the wait
    import time as _t
    import anchor_gui as g

    def a_slow_read():
        _t.sleep(2.4)
    with g._SlowWatch("a test page"):
        a_slow_read()
    out = capsys.readouterr().out
    assert "SLOW a test page at 2s:" in out and "a_slow_read" in out and "SLOW a test page took 2." in out
    with g._SlowWatch("a quick page"):
        pass
    assert "a quick page" not in capsys.readouterr().out
    assert '"/api/debug/threads", AUTH_TOKEN' in _read("route_table.py")
