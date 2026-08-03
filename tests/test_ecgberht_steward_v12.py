"""Ecgberht steward stub gate (v1.2 hardening, 2026-07-27).

The steward shipped with EIGHT routes, thirteen functions and ~670 lines of
Python + JS and **not one test**. Every other subsystem in this repo has a stub
gate. The wiring happened to be correct on arrival — the risk was never that it
was born broken, it was that nothing kept it correct. Both defects found in this
codebase the same week were "correct once, then silently rotted":

  * `foundry_map_v2.schema.json` was required at import and never listed in the
    deny-by-default manifest, so the public v1.1.0 tag could not start at all;
  * the 10-minute status cadence was documented and never armed.

So this file pins the STRUCTURE (every route reaches a handler, every handler is
routed, every endpoint the UI calls exists, every route is token-authed) and the
HONESTY properties (an unreadable registry never renders as an empty portfolio;
an unknown queue never renders as 0; a too-large artifact is refused, not
allocated; a path outside the project is refused).

Contract-level and hermetic: no server boot, no Node, no model, no PTY.
"""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
GUI = (ROOT / "anchor_gui.py").read_text(encoding="utf-8", errors="replace")
RT = (ROOT / "route_table.py").read_text(encoding="utf-8", errors="replace")
HS_JS = (ROOT / "static" / "high-seat.js").read_text(encoding="utf-8",
                                                     errors="replace")
PW_JS = (ROOT / "static" / "project-window.js").read_text(encoding="utf-8",
                                                          errors="replace")

ROUTE_RE = re.compile(
    r'_r\("(\w+)",\s*"(/api/ecgberht/[^"]+)"(.*?)handler="(\w+)"', re.S)


def _routes():
    return [(m.group(1), m.group(2), m.group(3), m.group(4))
            for m in ROUTE_RE.finditer(RT)]


# ── structure: the wiring cannot silently come apart ────────────────────────

def test_there_is_a_steward_surface_at_all():
    """If this fails, the steward was removed and the rest is vacuous."""
    assert len(_routes()) >= 8, "steward routes disappeared"


def test_every_route_reaches_a_defined_handler():
    defined = set(re.findall(r"^def (handle_ecgberht\w*)\(", GUI, re.M))
    for method, path, _mid, handler in _routes():
        assert handler in defined, \
            f"{method} {path} routes to {handler}(), which does not exist"


def test_every_steward_handler_is_routed():
    """An unrouted handler is dead code that reads as a working feature."""
    defined = set(re.findall(r"^def (handle_ecgberht\w*)\(", GUI, re.M))
    routed = {h for _, _, _, h in _routes()}
    assert defined - routed == set(), \
        f"handlers defined but unreachable: {sorted(defined - routed)}"


def test_every_endpoint_the_ui_calls_exists():
    declared = {p for _, p, _, _ in _routes()}
    called = set(re.findall(r"['\"](/api/ecgberht/[a-z_]+)", HS_JS + PW_JS))
    assert called - declared == set(), \
        f"UI calls routes that do not exist: {sorted(called - declared)}"


def test_every_steward_route_is_token_authed():
    """No unauthenticated steward surface, ever."""
    for method, path, mid, _handler in _routes():
        assert "AUTH_TOKEN" in mid, f"unauthed steward route: {method} {path}"


# ── honesty: unknown must never render as a reassuring zero ─────────────────

def test_portfolio_roots_reports_failure_separately_from_emptiness():
    """It used to swallow every exception and return [], so a BROKEN registry
    was shown to the user as the cheerful 'no projects to steward'."""
    body = GUI.split("def _ecgberht_portfolio_roots", 1)[1].split("\ndef ", 1)[0]
    assert "return [], skipped, True" in body, \
        "a registry failure is not distinguished from an empty portfolio"
    assert "return roots, skipped, False" in body


def test_high_seat_surfaces_an_unreadable_registry_as_an_error():
    body = GUI.split("def handle_ecgberht_high_seat(", 1)[1].split("\ndef ", 1)[0]
    assert "registry_unreadable" in body
    assert "502" in body, "a broken registry must not return 200 OK"


def test_the_badge_never_reports_a_fake_zero_queue():
    """queue_length 0 means 'nothing needs you'. An unknown must not say that."""
    body = GUI.split("def handle_ecgberht_high_seat_badge(", 1)[1] \
              .split("\ndef ", 1)[0]
    assert "registry_unreadable" in body
    assert '"queue_length": None' in body, \
        "an unreadable registry reports a queue length of 0 (a lie)"
    # ...and the client must not paint a 0 from a failed response either.
    assert "if (!ok)" in HS_JS and "badge.textContent = '';" in HS_JS


# ── containment + resource bounds ───────────────────────────────────────────

def test_artifact_route_contains_paths_to_the_project():
    body = GUI.split("def handle_ecgberht_artifact", 1)[1].split("\ndef ", 1)[0]
    assert ".resolve()" in body and "relative_to(root)" in body, \
        "artifact serving lost its traversal containment"
    assert "artifact_outside_project" in body


def test_artifact_route_refuses_an_oversized_file():
    """It reads the whole file into memory on a shared server thread."""
    body = GUI.split("def handle_ecgberht_artifact", 1)[1].split("\ndef ", 1)[0]
    assert "_ECGBERHT_ARTIFACT_MAX_BYTES" in body
    assert "artifact_too_large" in body and "413" in body
    assert "st_size" in body, "the size is checked AFTER reading the bytes"


def test_a_project_with_no_folder_never_reaches_the_bridge():
    body = GUI.split("def _ecgberht_project_folder", 1)[1].split("\ndef ", 1)[0]
    assert "project_has_no_folder" in body, \
        "a blank folder_path still spawns Node with --project ''"


def test_roots_containing_the_delimiter_are_dropped_not_mis_split():
    """Roots go to the engine as one `--roots a;b;c` argument, and a semicolon
    is legal in a Windows directory name."""
    assert "_ECGBERHT_ROOT_DELIM" in GUI
    body = GUI.split("def _ecgberht_portfolio_roots", 1)[1].split("\ndef ", 1)[0]
    assert "skipped.append(folder)" in body
    assert '";".join(roots)' not in GUI, \
        "a raw ';'.join bypasses the delimiter guard"


# ── the bridge fails honestly, never open ───────────────────────────────────

@pytest.mark.parametrize("mode", ["ecgberht_engine_missing",
                                  "bridge_spawn_failed",
                                  "bridge_no_output",
                                  "bridge_bad_json"])
def test_bridge_failure_modes_are_explicit(mode):
    for fn in ("_ecgberht_bridge", "_ecgberht_hs_bridge"):
        body = GUI.split("def " + fn, 1)[1].split("\ndef ", 1)[0]
        assert mode in body, f"{fn} lost its {mode} path"
        assert '"ok": False' in body


def test_bridge_spawns_without_a_console_window():
    """Standing rule on this host: no popup PowerShell/console windows."""
    for fn in ("_ecgberht_bridge", "_ecgberht_hs_bridge"):
        body = GUI.split("def " + fn, 1)[1].split("\ndef ", 1)[0]
        assert "NO_WINDOW" in body, f"{fn} can flash a console window"
        assert "timeout=" in body, f"{fn} can hang a server thread forever"


# ── the ambient poller must not become a slow restart storm ─────────────────

def test_the_badge_poll_is_gated_and_backs_off():
    """The badge endpoint SPAWNS A NODE SUBPROCESS. A plain setInterval means
    every open tab spawns one forever, at full rate even while failing — the
    zombie-hunter restart storm, just slower."""
    assert "document.hidden" in HS_JS, "the poll runs while the tab is hidden"
    assert "visibilitychange" in HS_JS, "no refresh when the tab returns"
    assert re.search(r"fails\s*=\s*ok\s*\?\s*0\s*:\s*fails\s*\+\s*1", HS_JS), \
        "consecutive failures do not back the poll off"
    assert "clearTimeout" in HS_JS, "the timer is never cleared"
    assert "setInterval(ecgHighSeatBadge" not in HS_JS, \
        "the un-gated fixed-rate interval is back"


# ── mutating handlers: argv bounds + closed acts ────────────────────────────

def test_spoken_text_is_bounded_before_it_becomes_argv():
    """This is NOT the PTY path. rnd_terminal.MAX_TURN_CHARS (100_000) writes to
    a child's stdin, which has no size limit. Here the text becomes argv, and
    Windows caps the whole command line near 32_767 - so an oversized paste
    fails as an opaque spawn error, surfacing as the misleading
    `bridge_spawn_failed`, not as "your text was too long"."""
    assert "_ECGBERHT_MAX_SPOKEN_CHARS" in GUI
    assert GUI.count("_ecgberht_reject_oversized(handler, text)") >= 2, (
        "a speak path can still hand unbounded text to argv")
    body = GUI.split("def _ecgberht_reject_oversized", 1)[1].split(chr(10)+"def ", 1)[0]
    assert "text_too_long" in body and "413" in body


def test_the_cap_is_well_inside_the_windows_command_line_limit():
    import re as _re
    m = _re.search(r"_ECGBERHT_MAX_SPOKEN_CHARS = ([0-9_]+)", GUI)
    assert m, "the cap constant vanished"
    assert int(m.group(1).replace("_", "")) < 32767


def test_high_seat_act_refuses_unknown_kinds_with_the_allowed_list():
    """Closed acts only - an unknown kind must not fall through to a bridge."""
    body = GUI.split("def handle_ecgberht_high_seat_act", 1)[1].split(chr(10)+"def ", 1)[0]
    assert "unknown_act" in body and "400" in body
    for act in ("speak", "override", "decide", "capacity_choice"):
        assert act in body


def test_stand_up_refuses_to_invent_a_goal():
    """The steward never invents a north star; an empty goal is a refusal."""
    body = GUI.split("def handle_ecgberht_stand_up", 1)[1].split(chr(10)+"def ", 1)[0]
    assert "empty_goal_refused" in body and "400" in body
