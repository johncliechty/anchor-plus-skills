"""Gate 5 — the kickoff RENDER PATH (2026-09-01).

Waves 7-9 shipped the pass-through reader, the GET /api/ecgberht/kickoff_show route,
and a pytest that painted the staged efforts THROUGH THE ROUTE — and the cockpit UI
never called it: a real-browser check found no kickoff text on the hub or inside an
effort. Same class as the 2026-08-27 setup-message bug ("server emitted, browser
dropped, test asserted the JSON and passed"). This test is the LINT half of the fix
(the mount exists, the client calls the route, the goal bar auto-opens, the engine's
prose goes through the one markdown renderer); the RENDER half is the Playwright
sign-off recorded in the completion journal — a lint cannot see pixels.
"""
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "steward_cockpit" / "static"


def _read(name: str) -> str:
    return (STATIC / name).read_text(encoding="utf-8")


def test_effort_view_carries_the_kickoff_mount_first_in_the_goal_bar():
    html = _read("v1.html")
    assert 'data-kickoff' in html
    gfull = html.index('class="gfull"')
    assert html.index("data-kickoff") > gfull
    # the kickoff block precedes the tag-derived goal text: confirmed intent has display precedence
    assert html.index("data-kickoff") < html.index("data-goalfull")


def test_client_paints_the_kickoff_from_anchors_route_not_from_its_own_composition():
    js = _read("shared.js")
    assert "/api/ecgberht/kickoff_show" in js
    assert "function paintKickoff" in js
    # the engine's rendered prose goes through THE renderer; the open draft is a plain line
    assert "renderRich(box, j.rendered)" in js
    assert "not applied" in js
    # XHR on purpose: the client shim rewrites fetch('/api/...') to /api/steward/
    assert "new XMLHttpRequest()" in js
    # (2026-09-02, John) the goal bar must NOT auto-open — the outcome rides the one-line brief;
    # the full bundle is one click away
    assert 'bar.classList.add("open")' not in js
    assert "draft, not applied — " in js
    # never composes prose from record fields — no goal/parts/plan template strings here
    assert "Outcome:" not in js.split("function paintKickoff")[1].split("/* ---------- markdown")[0].replace("/^Outcome:", "")


def test_kickoff_block_styles_exist_and_hide_when_empty():
    css = _read("shared.css")
    assert ".gfull .gkick:empty { display: none; }" in css
    assert ".gfull .gkick.confirmed" in css
    assert ".gfull .gkick.draft" in css
