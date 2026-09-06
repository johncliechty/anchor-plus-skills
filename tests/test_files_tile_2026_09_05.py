"""Files and links (John, 2026-09-05): clickable links in the plan, the deliverables and the files; links
labelled by the document's name and opening rendered (md in the Reader, pdf inline, Office as a preview
page); file search plus sort by name, type and date; a file opens in a new window."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SHARED = (ROOT / "steward_cockpit" / "static" / "shared.js").read_text(encoding="utf-8")
COCKPIT = (ROOT / "steward_cockpit" / "static" / "cockpit.html").read_text(encoding="utf-8")
V1 = (ROOT / "steward_cockpit" / "static" / "v1.html").read_text(encoding="utf-8")
GUI = (ROOT / "anchor_gui.py").read_text(encoding="utf-8")


def test_routes_open_rendered_and_office_files_preview():
    assert "function routeHref(route)" in SHARED
    assert 'sep + "render=1"' in SHARED and 'sep + "view=1"' in SHARED
    assert '(/\\.(docx|pptx|xlsx)$/i.test(it.path) ? "&view=1" : "")' in SHARED     # effort tile file rows
    assert '_sep + "render=1"' in COCKPIT and '_sep + "view=1"' in COCKPIT          # project list route rows
    # the server side: /artifact renders markdown with the mark, previews Office, downloads on request
    assert 'elif want_view and ext in (".docx", ".pptx", ".xlsx"):' in GUI
    assert "_op.render_preview(data, Path(rel).name, dl)" in GUI


def test_link_label_is_the_document_name_not_the_route():
    assert 'a.textContent = "• " + (it.what || routeName(it.route));' in SHARED
    assert 'a.textContent = "Open ↗ " + it.route' not in SHARED


def test_files_search_and_sort_by_name_type_date_on_both_pages():
    assert "<button data-sort-type>type</button>" in COCKPIT
    assert 'SORT === "type"' in COCKPIT
    assert '["name", "type", "date"].forEach(k => {' in COCKPIT
    assert 'data-fsort="type"' in V1 and 'data-fsearch' in V1
    assert 'sort === "type"' in SHARED and "_filesSort" in SHARED


def test_files_open_in_a_new_window_with_the_app_as_the_secondary():
    # project page: a file row is an anchor to a rendering URL; the app button keeps the old path
    assert 'const fn = el(f.dir ? "span" : "a", "fn", (f.dir ? "📁 " : "· ") + f.name);' in COCKPIT
    assert 'fn.target = "_blank"; fn.rel = "noopener";' in COCKPIT
    assert 'el("button", "fapp", "app")' in COCKPIT
    # effort cockpit: a produced file inside the effort opens rendered; outside it the app opens it
    assert "function openProducedFile(f)" in SHARED
    assert 'window.open("/report?dir=" + encodeURIComponent(DIR) + "&path=" + encodeURIComponent(rel))' in SHARED
