"""John, 2026-09-06: HTML deliverables render (in a browser sandbox, never in the dashboard's origin);
plan rows open on click and close on the next click, down and up the levels."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from steward_cockpit import steward_routes as routes  # noqa: E402


def test_html_and_svg_are_served_as_themselves_under_a_sandbox():
    assert routes.deliverable_content_type(".html")[0].startswith("text/html")
    assert routes.deliverable_content_type(".htm")[0].startswith("text/html")
    assert routes.deliverable_content_type(".svg")[0] == "image/svg+xml"
    csp = routes.sandbox_csp_for("text/html; charset=utf-8")
    assert csp and csp.startswith("sandbox") and "allow-same-origin" not in csp
    assert routes.sandbox_csp_for("image/svg+xml") == csp
    assert routes.sandbox_csp_for("application/pdf") is None
    assert routes.sandbox_csp_for("text/plain; charset=utf-8") is None


def test_both_file_routes_send_the_sandbox_header():
    gui = (ROOT / "anchor_gui.py").read_text(encoding="utf-8")
    assert 'self.send_header("Content-Security-Policy", obj["__csp__"])' in gui          # cockpit deliverable-file
    assert 'self.send_header("Content-Security-Policy", _csp(ctype) or "sandbox")' in gui  # /artifact
    src = (ROOT / "steward_cockpit" / "steward_routes.py").read_text(encoding="utf-8")
    assert '"__csp__": sandbox_csp_for(ctype)' in src


def test_outline_title_is_the_only_step_toggle_and_closing_closes_the_children():
    js = (ROOT / "steward_cockpit" / "static" / "shared.js").read_text(encoding="utf-8")
    assert 'const title = el("div", "stitle");' in js
    assert 'if (!ev.target.closest(".stitle")) return;' in js
    assert 'li.querySelectorAll(".sdrow.open").forEach((r) => {' in js
    assert "row.dataset.key = key;" in js
    assert "detail.onclick = (ev) => { ev.stopPropagation(); };" in js
    css = (ROOT / "steward_cockpit" / "static" / "shared.css").read_text(encoding="utf-8")
    assert ".steps li.open .stitle .tw::before" in css
