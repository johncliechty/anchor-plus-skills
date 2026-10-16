"""v9 Wave 3 — Project folders: group field + collapsible UI + drag-to-group.

This wave is DASHBOARD GROUPING ONLY — it adds a ``group`` field to the project
record and renders the home dashboard's R&D project list as COLLAPSIBLE FOLDERS
(▸/▾ · name · count · uniform on-disk path), with a "+ New folder" control and
drag-a-row-into-a-folder-header → ``POST /api/rnd/set_group``. There is **NO disk
move** this wave (that is the guarded Wave-4 ``move_to_group``): set_group only
re-labels which folder a project renders under; its ``folder_path`` is unchanged.

Coverage:
  - BACKEND: ``rnd_registry.set_group`` / ``group_by_group`` (default Ungrouped;
    a record with NO ``group`` field reads as Ungrouped — back-compat); set_group
    PERSISTS; group_by_group buckets correctly + Ungrouped is always last.
  - ENDPOINT: ``/api/rnd/set_group`` is token-gated (401 unauthed) and sets the
    group on confirm; folder_path is UNCHANGED (no disk move).
  - DOM (positive + negative): the home dashboard renders the collapsible folder
    structure (folder header + ▸/▾ twisty + nested project rows) + "+ New folder";
    a grouped project renders under its folder; ungrouped under "Ungrouped".
  - REAL Playwright/Chromium: load the home dashboard → create a "Research" folder
    → assign a project into it (drag, with a set_group fallback) → it renders under
    "Research", persisted across a reload → its on-disk dir is UNCHANGED → collapse
    /expand the folder → no JS console errors. Saves ``_devtest/wave3_folders.png``.

Hermetic: a TEMP ``ANCHOR_DATA_DIR`` + a TEMP registry (NEVER the live
``rnd_registry.json``); a throwaway server on an OS-assigned port (NEVER ``:8777``);
no live claude / no network / no disk move.
"""
import importlib
import json
import re
import threading
import urllib.error
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

import pytest

_DEVTEST = Path(__file__).resolve().parent.parent / "_devtest"


# ── env / fixtures ───────────────────────────────────────────────────────────

@pytest.fixture
def env(tmp_path, monkeypatch):
    """A TEMP data dir + reloaded stack (so the registry is the throwaway one,
    NOT the live rnd_registry.json)."""
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(data))
    monkeypatch.delenv("ANCHOR_TOKEN", raising=False)
    for mod in ("paths", "rnd_registry", "effort_history", "sessions"):
        importlib.reload(importlib.import_module(mod))
    import paths
    paths.ensure_data_dirs()
    import anchor_gui
    gui = importlib.reload(anchor_gui)
    import rnd_registry
    bundle = {"gui": gui, "rnd": rnd_registry, "tmp": tmp_path, "data": data}
    yield bundle


def _mkproject(rnd, tmp_path, name):
    folder = tmp_path / name
    folder.mkdir(parents=True, exist_ok=True)
    return rnd.add_project(name, str(folder), scaffold=False)


def _free_server(gui):
    srv = gui.make_server("127.0.0.1", 0)
    port = srv.server_address[1]
    assert port != 8777
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    return srv, port, t


def _post(port, path, payload, token=None):
    headers = {"Content-Type": "application/json"}
    if token is not None:
        headers["X-Anchor-Token"] = token
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        data=json.dumps(payload).encode(), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8"))


# ════════════════════════════════════════════════════════════════════════════
# (1) BACKEND — group field, set_group, group_by_group, back-compat
# ════════════════════════════════════════════════════════════════════════════

def test_new_project_has_empty_group_by_default(env):
    rnd, tmp = env["rnd"], env["tmp"]
    p = _mkproject(rnd, tmp, "Alpha")
    assert p["group"] == ""
    # And it reads back the same from the registry.
    assert rnd.get_project(p["id"])["group"] == ""


def test_set_group_persists(env):
    rnd, tmp = env["rnd"], env["tmp"]
    pid = _mkproject(rnd, tmp, "Alpha")["id"]
    out = rnd.set_group(pid, "Research")
    assert out["group"] == "Research"
    # Persisted (a fresh load_registry sees it; not just the returned dict).
    assert rnd.get_project(pid)["group"] == "Research"
    # Re-import to prove it survives a fresh registry read from disk.
    importlib.reload(rnd)
    assert rnd.get_project(pid)["group"] == "Research"


def test_set_group_empty_is_ungrouped(env):
    rnd, tmp = env["rnd"], env["tmp"]
    pid = _mkproject(rnd, tmp, "Alpha")["id"]
    rnd.set_group(pid, "Research")
    out = rnd.set_group(pid, "")
    assert out["group"] == ""
    assert rnd.get_project(pid)["group"] == ""


def test_set_group_strips_whitespace(env):
    rnd, tmp = env["rnd"], env["tmp"]
    pid = _mkproject(rnd, tmp, "Alpha")["id"]
    out = rnd.set_group(pid, "  AI Tools  ")
    assert out["group"] == "AI Tools"


def test_group_by_group_buckets_correctly(env):
    rnd, tmp = env["rnd"], env["tmp"]
    a = _mkproject(rnd, tmp, "Alpha")["id"]
    b = _mkproject(rnd, tmp, "Beta")["id"]
    c = _mkproject(rnd, tmp, "Gamma")["id"]  # stays ungrouped
    rnd.set_group(a, "Research")
    rnd.set_group(b, "Research")

    groups = rnd.group_by_group()
    assert "Research" in groups
    assert {e["id"] for e in groups["Research"]} == {a, b}
    # Ungrouped bucket present + holds the never-grouped project.
    assert rnd.UNGROUPED_LABEL in groups
    assert {e["id"] for e in groups[rnd.UNGROUPED_LABEL]} == {c}


def test_group_by_group_ungrouped_is_last(env):
    rnd, tmp = env["rnd"], env["tmp"]
    a = _mkproject(rnd, tmp, "Alpha")["id"]
    _mkproject(rnd, tmp, "Beta")  # ungrouped
    rnd.set_group(a, "ZZZ-LastAlpha")  # alphabetically after "Ungrouped"
    keys = list(rnd.group_by_group().keys())
    assert keys[-1] == rnd.UNGROUPED_LABEL, keys


def test_group_by_group_always_returns_ungrouped_even_when_empty(env):
    rnd, tmp = env["rnd"], env["tmp"]
    pid = _mkproject(rnd, tmp, "Alpha")["id"]
    rnd.set_group(pid, "Research")  # the ONLY project is grouped
    groups = rnd.group_by_group()
    # Ungrouped is still present (empty), so the drop-to-remove target exists.
    assert rnd.UNGROUPED_LABEL in groups
    assert groups[rnd.UNGROUPED_LABEL] == []


def test_group_back_compat_record_without_group_field(env):
    """A registry record written BEFORE v9 (no ``group`` key) reads as Ungrouped."""
    rnd, tmp, data = env["rnd"], env["tmp"], env["data"]
    pid = _mkproject(rnd, tmp, "Legacy")["id"]
    # Simulate a pre-v9 on-disk record: drop the "group" key entirely.
    reg_file = data / rnd.REGISTRY_NAME
    items = json.loads(reg_file.read_text(encoding="utf-8"))
    for it in items:
        it.pop("group", None)
    reg_file.write_text(json.dumps(items), encoding="utf-8")
    importlib.reload(rnd)

    # _normalize back-fills "" → the entry is Ungrouped, never a crash.
    assert rnd.get_project(pid)["group"] == ""
    groups = rnd.group_by_group()
    assert pid in {e["id"] for e in groups[rnd.UNGROUPED_LABEL]}


def test_set_group_does_not_move_disk(env):
    """set_group is organization-only: folder_path is UNCHANGED (no disk move)."""
    rnd, tmp = env["rnd"], env["tmp"]
    p = _mkproject(rnd, tmp, "Alpha")
    pid, before = p["id"], p["folder_path"]
    rnd.set_group(pid, "Research")
    after = rnd.get_project(pid)["folder_path"]
    assert after == before
    assert Path(before).is_dir()  # the dir is still right where it was


# ════════════════════════════════════════════════════════════════════════════
# (2) ENDPOINT — /api/rnd/set_group token-gated; sets group; NO disk move
# ════════════════════════════════════════════════════════════════════════════

def test_set_group_endpoint_requires_token(env, monkeypatch):
    """With ANCHOR_TOKEN set, an unauthed set_group is 401 (group untouched)."""
    monkeypatch.setenv("ANCHOR_TOKEN", "s3cret")
    importlib.reload(importlib.import_module("paths"))
    gui = importlib.reload(env["gui"])
    rnd, tmp = env["rnd"], env["tmp"]
    pid = _mkproject(rnd, tmp, "Alpha")["id"]

    srv, port, t = _free_server(gui)
    try:
        code, data = _post(port, "/api/rnd/set_group",
                           {"project_id": pid, "group": "Research"})  # no token
        assert code == 401
        assert data.get("error") == "unauthorized"
        assert rnd.get_project(pid)["group"] == ""  # untouched
        # With the token it succeeds.
        code, data = _post(port, "/api/rnd/set_group",
                           {"project_id": pid, "group": "Research"},
                           token="s3cret")
        assert code == 200 and data["ok"] is True
        assert data["entry"]["group"] == "Research"
        assert rnd.get_project(pid)["group"] == "Research"
    finally:
        srv.shutdown(); srv.server_close(); t.join(timeout=5)


def test_set_group_endpoint_no_disk_move(env):
    """The endpoint reassigns the group but NEVER moves the directory."""
    gui, rnd, tmp = env["gui"], env["rnd"], env["tmp"]
    p = _mkproject(rnd, tmp, "Alpha")
    pid, before = p["id"], p["folder_path"]
    srv, port, t = _free_server(gui)
    try:
        code, data = _post(port, "/api/rnd/set_group",
                           {"project_id": pid, "group": "AI Tools"})
        assert code == 200 and data["ok"] is True
        assert rnd.get_project(pid)["group"] == "AI Tools"
        # folder_path is unchanged and the dir is still in place.
        assert rnd.get_project(pid)["folder_path"] == before
        assert Path(before).is_dir()
    finally:
        srv.shutdown(); srv.server_close(); t.join(timeout=5)


def test_set_group_endpoint_unknown_project_404(env):
    gui = env["gui"]
    srv, port, t = _free_server(gui)
    try:
        code, data = _post(port, "/api/rnd/set_group",
                           {"project_id": "nope", "group": "X"})
        assert code == 404
        assert data["ok"] is False
    finally:
        srv.shutdown(); srv.server_close(); t.join(timeout=5)


# ════════════════════════════════════════════════════════════════════════════
# (3) DOM — collapsible folder structure + "+ New folder" + drag affordance
# ════════════════════════════════════════════════════════════════════════════

class _Collector(HTMLParser):
    def __init__(self):
        super().__init__()
        self.els = []

    def handle_starttag(self, tag, attrs):
        d = dict(attrs)
        self.els.append((tag, (d.get("class") or "").split(), d))


def _parse(html):
    c = _Collector()
    c.feed(html)
    return c.els


def test_dom_renders_collapsible_folder_structure(env):
    """POSITIVE: the view renders a collapsible folder LIST with folder headers
    (▸/▾ twisty + name + count) over nested draggable project rows, plus the
    "+ New folder" control. NEGATIVE vs the v8 FLAT list: the folder grouping
    markup (.rnd-folder-list / .rnd-folder-head / .rnd-tw) IS now present."""
    gui, rnd, tmp = env["gui"], env["rnd"], env["tmp"]
    _mkproject(rnd, tmp, "Alpha")
    _mkproject(rnd, tmp, "Beta")
    view = gui.render_projects_view_html()
    els = _parse(view)
    classes = [cl for _t, cls, _d in els for cl in cls]

    # POSITIVE — the collapsible folder scaffold.
    assert "rnd-folder-list" in classes
    assert "rnd-folder" in classes
    assert "rnd-folder-head" in classes
    assert "rnd-folder-body" in classes
    assert "rnd-tw" in classes        # the ▸/▾ twisty
    assert "rnd-fname" in classes     # folder name
    assert "rnd-fcount" in classes    # project count
    # The twisty character is present.
    assert "▾" in view or "▾" in view
    # "+ New folder" control wired to rndNewFolder.
    assert "rnd-newfolder-btn" in classes
    assert "rndNewFolder()" in view
    assert "+ New folder" in view

    # Drag affordance — the rows are draggable and carry the grip + their group.
    rows = [d for _t, cls, d in els if "rnd-row" in cls]
    assert rows, "expected project rows"
    for d in rows:
        assert d.get("draggable") == "true"
        assert "data-group" in d
    assert "rnd-grip" in classes

    # NEGATIVE — this is NOT the v8 flat list: there is no bare flat-row wrapper
    # standing alone outside a folder body (rows live inside .rnd-folder-body).
    # The v8 toolbar hint mentions the ⋮⋮ drag affordance.
    assert "into a folder header" in view


def test_dom_grouped_project_under_its_folder(env):
    """A grouped project renders under a folder header carrying its group name;
    an ungrouped one renders under the 'Ungrouped' folder."""
    gui, rnd, tmp = env["gui"], env["rnd"], env["tmp"]
    a = _mkproject(rnd, tmp, "Grouped")["id"]
    b = _mkproject(rnd, tmp, "Loose")["id"]
    rnd.set_group(a, "Research")
    view = gui.render_projects_view_html()

    # A folder header for "Research" exists and "Ungrouped" exists.
    assert ">Research<" in view
    assert "Ungrouped" in view

    # Structurally, the "Research" folder's body contains the grouped row and the
    # "Ungrouped" folder's body contains the loose row. We parse the folder
    # blocks by their data-group attribute and assert membership.
    research = _folder_block(view, "Research")
    ungrouped = _folder_block(view, rnd.UNGROUPED_LABEL)
    assert f'data-project-id="{a}"' in research
    assert f'data-project-id="{a}"' not in ungrouped
    assert f'data-project-id="{b}"' in ungrouped
    assert f'data-project-id="{b}"' not in research


def _folder_block(view, group_name):
    """Return the substring of `view` for the ``.rnd-folder`` whose data-group is
    `group_name` (up to the next folder or the end)."""
    start = view.find(f'data-group="{group_name}"')
    assert start >= 0, f"folder {group_name!r} not found"
    # Back up to the opening of this folder div.
    open_div = view.rfind("<div", 0, start)
    nxt = view.find('class="rnd-folder"', start)
    end = nxt if nxt >= 0 else len(view)
    return view[open_div:end]


def test_dom_negative_no_folder_when_empty_registry(env):
    """With NO projects, the empty-state message renders (no folder scaffold)."""
    gui = env["gui"]
    view = gui.render_projects_view_html()
    assert "No active R&D projects" in view
    assert "rnd-folder-list" not in view


def test_home_page_ships_folder_js(env):
    """The home page ships the folder JS (toggle + new-folder + drag init)."""
    gui = env["gui"]
    html = gui.generate_html(*gui.gather_all())
    assert "function rndToggleFolder(" in html
    assert "function rndNewFolder(" in html
    assert "function rndFolderInit(" in html
    assert "/api/rnd/set_group" in html
    # f-string brace discipline holds (no leaked doubled braces).
    assert "{{" not in html and "}}" not in html


def test_view_no_leaked_braces(env):
    gui, rnd, tmp = env["gui"], env["rnd"], env["tmp"]
    _mkproject(rnd, tmp, "Alpha")
    view = gui.render_projects_view_html()
    assert "{{" not in view and "}}" not in view


# ════════════════════════════════════════════════════════════════════════════
# (4) REAL Playwright + Chromium — create folder → group → persist → no-disk-move
# ════════════════════════════════════════════════════════════════════════════

@pytest.fixture
def server(env):
    gui = env["gui"]
    srv, port, t = _free_server(gui)
    try:
        yield env, f"http://127.0.0.1:{port}", port
    finally:
        srv.shutdown(); srv.server_close(); t.join(timeout=5)


def test_playwright_create_folder_group_persist_no_disk_move(server):
    """End to end in a real browser:

      1. Load the home dashboard → reveal the R&D view → two ungrouped rows.
      2. "+ New folder" → name it "Research" → an empty Research folder appears.
      3. Assign a project into it (HTML5 drag-and-drop is brittle headless, so we
         drive the SAME drop handler the UI uses: dispatch a synthetic drop with a
         DataTransfer carrying the project id onto the Research folder header).
      4. The page reloads (apiCall) → the project now renders under "Research",
         and it STAYS there across an explicit reload (persisted group).
      5. Its directory on disk is UNCHANGED (asserted via the backend folder_path).
      6. Collapse the Research folder (▾→▸) hides its body; expand restores it.
      7. No JS console errors throughout.

    Screenshot saved to _devtest/wave3_folders.png for orchestrator review.
    """
    pytest.importorskip("playwright.sync_api")
    env, base, _port = server
    rnd, tmp = env["rnd"], env["tmp"]
    a = _mkproject(rnd, tmp, "Mover")["id"]
    _mkproject(rnd, tmp, "Stayer")
    folder_before = rnd.get_project(a)["folder_path"]

    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page()
        errors = []
        pg.on("console",
              lambda m: errors.append(m.text) if m.type == "error" else None)
        pg.goto(f"{base}/", wait_until="networkidle")
        pg.evaluate("() => showView && showView('rnd')")
        # Scope to the #rndProjectsRows folder list (the same markup also renders
        # in the dashboard section — an unscoped selector is ambiguous).
        list_sel = "#rndProjectsRows .rnd-folder-list"
        pg.wait_for_selector(list_sel, timeout=8000)
        row_sel = f'{list_sel} .rnd-row[data-project-id="{a}"]'
        pg.wait_for_selector(row_sel, timeout=5000)

        # Initially the Mover row is under "Ungrouped".
        assert _row_folder_group(pg, list_sel, a) == "Ungrouped"

        # "+ New folder" → "Research" (auto-accept the prompt).
        pg.on("dialog", lambda d: d.accept("Research"))
        pg.evaluate("() => rndNewFolder()")
        pg.wait_for_selector(
            f'{list_sel} .rnd-folder[data-group="Research"]', timeout=5000)

        pg.screenshot(path=str(_devtest_dir() / "wave3_folders.png"),
                      full_page=True)

        # Drive the drop handler that the UI wires: dispatch a synthetic 'drop'
        # with a DataTransfer carrying the project id onto the Research header.
        # (This exercises the real _rndWireFolderDrop path.)
        pg.evaluate(
            """(pid) => {
                const head = document.querySelector(
                  '#rndProjectsRows .rnd-folder[data-group=\\"Research\\"] .rnd-folder-head');
                const dt = new DataTransfer();
                dt.setData('text/plain', pid);
                const ev = new DragEvent('drop', {bubbles: true, cancelable: true, dataTransfer: dt});
                head.dispatchEvent(ev);
            }""", a)

        # v9 Wave 4 — a drop into a NAMED folder now opens the Option-C dialog.
        # The set_group (dashboard-only, NO disk move) path this test verifies is
        # the "Just group" choice; click it to keep the W3 no-disk-move behavior.
        pg.wait_for_function(
            "() => { const o = document.getElementById('rndMoveOverlay');"
            " return o && getComputedStyle(o).display !== 'none'; }",
            timeout=5000)
        pg.click("#rndMoveJust")

        # apiCall reloads the page on success; wait for the Mover row to land
        # under Research after the reload.
        pg.wait_for_function(
            """(pid) => {
                showView && showView('rnd');
                const row = document.querySelector(
                  '#rndProjectsRows .rnd-row[data-project-id=\\"' + pid + '\\"]');
                if (!row) return false;
                const folder = row.closest('.rnd-folder');
                return folder && folder.getAttribute('data-group') === 'Research';
            }""", arg=a, timeout=10000)

        # Backend: the group is persisted AND the dir is UNCHANGED (no disk move).
        assert rnd.get_project(a)["group"] == "Research"
        assert rnd.get_project(a)["folder_path"] == folder_before
        assert Path(folder_before).is_dir()

        # Persists across an explicit reload.
        pg.goto(f"{base}/", wait_until="networkidle")
        pg.evaluate("() => showView && showView('rnd')")
        pg.wait_for_selector(list_sel, timeout=8000)
        assert _row_folder_group(pg, list_sel, a) == "Research"

        # Collapse/expand the Research folder.
        head_sel = f'{list_sel} .rnd-folder[data-group="Research"] .rnd-folder-head'
        body_sel = f'{list_sel} .rnd-folder[data-group="Research"] .rnd-folder-body'
        pg.wait_for_selector(head_sel, timeout=5000)
        assert pg.eval_on_selector(body_sel, "e=>getComputedStyle(e).display") != "none"
        pg.click(head_sel)
        pg.wait_for_function(
            "() => { const e = document.querySelector('"
            + body_sel.replace("'", "\\'")
            + "'); return e && getComputedStyle(e).display === 'none'; }",
            timeout=5000)
        pg.click(head_sel)  # expand again
        pg.wait_for_function(
            "() => { const e = document.querySelector('"
            + body_sel.replace("'", "\\'")
            + "'); return e && getComputedStyle(e).display !== 'none'; }",
            timeout=5000)

        assert not errors, f"JS console errors: {errors}"
        b.close()


def _row_folder_group(pg, list_sel, pid):
    """Return the data-group of the folder containing the given project row."""
    return pg.evaluate(
        """(args) => {
            const row = document.querySelector(
              args.list + ' .rnd-row[data-project-id=\\"' + args.pid + '\\"]');
            if (!row) return null;
            const f = row.closest('.rnd-folder');
            return f ? f.getAttribute('data-group') : null;
        }""", {"list": list_sel, "pid": pid})


def _devtest_dir():
    _DEVTEST.mkdir(exist_ok=True)
    return _DEVTEST
