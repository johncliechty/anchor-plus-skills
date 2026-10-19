"""R11 of the High Seat (John, 2026-09-28): a new project without the old dashboard — say it to the steward and
confirm the card here, or ONE button that opens the old dashboard's folder-creation dialog alone in a small window;
either way the project is placed in a dashboard folder of his choosing, not only in Ungrouped."""
import inspect
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import anchor_gui  # noqa: E402
import high_seat_page as hsp  # noqa: E402
import rnd_registry  # noqa: E402


class _Handler:
    def __init__(self):
        self.sent = []

    def _send_json(self, payload, code=200):
        self.sent.append((payload, code))


def test_the_dialogs_folder_choices_are_the_dashboards_folders_then_ungrouped_then_new(monkeypatch):
    monkeypatch.setattr(rnd_registry, "group_by_group", lambda **k: {"Teaching": [1], "Writing <b>": [2], "Ungrouped": [3]})
    html = anchor_gui._np_group_options()
    assert html.index('<option value="Teaching">Teaching</option>') < html.index('<option value="Writing &lt;b&gt;">Writing &lt;b&gt;</option>') < html.index('<option value="" selected>Ungrouped</option>') < html.index('value="__new__"')
    assert html.count("selected") == 1, "Ungrouped is selected until he picks (Grok R11)"
    monkeypatch.setattr(rnd_registry, "group_by_group", lambda **k: (_ for _ in ()).throw(OSError("registry")))
    assert anchor_gui._np_group_options().startswith('<option value="" selected>Ungrouped</option>'), "a registry that cannot be read still offers Ungrouped and a new folder"


def test_a_new_project_is_placed_in_the_folder_he_chose(monkeypatch):
    placed = []
    monkeypatch.setattr(anchor_gui, "create_new_folder_project", lambda name, parent, priority=2, git_init=False: {"entry": {"id": "p1", "name": name, "group": ""}, "folder_created": True})
    monkeypatch.setattr(anchor_gui, "select_existing_project", lambda name, folder, priority=2: {"entry": {"id": "p2", "name": name, "group": ""}, "folder_created": False})
    monkeypatch.setattr(rnd_registry, "set_group", lambda pid, group: placed.append((pid, group)) or {"id": pid, "group": group, "name": "x"})
    h = _Handler()
    anchor_gui.handle_new_project(h, "/api/rnd/new_project", {"mode": "new_folder", "name": "Bread 2", "parent_path": "C:/dev", "group": "Nutrition"})
    payload, code = h.sent[-1]
    assert code == 200 and payload["ok"] and payload["entry"]["group"] == "Nutrition" and payload["group"] == "Nutrition"
    assert payload["message"] == "Project \u201cBread 2\u201d created in the folder Nutrition."
    anchor_gui.handle_new_project(h, "/api/rnd/new_project", {"mode": "existing", "name": "Old", "folder_path": "C:/dev/old", "group": "Teaching"})
    assert h.sent[-1][0]["entry"]["group"] == "Teaching"
    # the composer's confirm card: mode auto, an existing folder
    monkeypatch.setattr(anchor_gui.Path, "exists", lambda self: True)
    anchor_gui.handle_new_project(h, "/api/rnd/new_project", {"mode": "auto", "name": "Spoken", "folder_path": "C:/dev/spoken", "group": "Writing"})
    assert h.sent[-1][0]["entry"]["group"] == "Writing" and h.sent[-1][0]["path_existed"] is True
    assert placed == [("p1", "Nutrition"), ("p2", "Teaching"), ("p2", "Writing")]
    # no folder chosen: nothing placed, Ungrouped as before
    anchor_gui.handle_new_project(h, "/api/rnd/new_project", {"mode": "existing", "name": "Plain", "folder_path": "C:/dev/plain"})
    assert "group" not in h.sent[-1][0] and len(placed) == 3
    # a placement that fails never loses the creation
    monkeypatch.setattr(rnd_registry, "set_group", lambda pid, group: (_ for _ in ()).throw(OSError("locked")))
    anchor_gui.handle_new_project(h, "/api/rnd/new_project", {"mode": "existing", "name": "Late", "folder_path": "C:/dev/late", "group": "Teaching"})
    payload, code = h.sent[-1]
    assert code == 200 and payload["ok"] and "could not be placed" in payload["group_error"]
    assert "could not be placed in the folder Teaching (OSError)" in payload["message"], "the failed placement is said in the sentence both surfaces show"
    # a retry that finds the project already registered still places it in the folder he chose
    monkeypatch.setattr(rnd_registry, "set_group", lambda pid, group: placed.append((pid, group)) or {"id": pid, "group": group, "name": "Plain"})
    monkeypatch.setattr(rnd_registry, "group_by_group", lambda **k: {})
    monkeypatch.setattr(rnd_registry, "group_by_folder", lambda: {str(anchor_gui.Path("C:/dev/plain").expanduser()): [{"id": "p9", "name": "Plain", "group": ""}]})
    monkeypatch.setattr(rnd_registry, "_effective_state", lambda e: rnd_registry.STATE_ACTIVE)
    anchor_gui.handle_new_project(h, "/api/rnd/new_project", {"mode": "existing", "name": "Plain", "folder_path": "C:/dev/plain", "group": "Math"})
    payload, code = h.sent[-1]
    assert payload["already_registered"] and payload["group"] == "Math" and placed[-1] == ("p9", "Math")


def test_lint_the_old_dashboards_dialog_carries_the_folder_and_can_stand_alone_in_a_small_window():
    """A LINT on the dialog's source (Grok R11): what it says is on the page is proved on his screen."""
    src = inspect.getsource(anchor_gui.generate_html)
    assert '<select id="npGroup" onchange="npGroupChanged()">{np_group_options}</select>' in src
    assert 'id="npNewGroup"' in src and "window.prompt" not in src.split("function npGroupChanged")[1].split("function npSay")[0], "a name field in the dialog, no second dialog"
    assert "group: npGroupValue()" in src and "_npCreateInPopup(body)" in src
    assert "body.only-new-project > *:not(#newProjectModal)" in src
    assert "_npPopup = q.get('only') === '1';" in src, "the cloak only when asked for"
    assert 'id="npResult"' in src and "npSay(sentence, !!data.group_error)" in src and "if (data.group_error) return;" in src
    assert "function npCancel() {{ if (_npPopup) {{ window.close(); return; }}" in src
    assert "postMessage({{ anchor: 'project-created'" in src and "window.close()" in src


def test_the_projects_tile_offers_one_real_button_and_no_trip_to_the_old_dashboard():
    ctx = {"groups": {"Teaching": [1, 2], "Writing": [3], "Ungrouped": [4]}, "quiet_n": 0, "projects_html": "<ul></ul>"}
    html = hsp._projects_tile(ctx)
    assert '<button type="button" class="tog np" id="apNew"' in html and "New project" in html
    head = html.split('id="ptileToggle"', 1)[1].split("</button>", 1)[0]
    assert "apNew" not in head, "a real button on the line, OUTSIDE the toggle (Grok R11)"
    assert 'id="apCreate"' not in html and 'href="/dashboard"' not in html
    assert '<select id="apGroups" hidden><option value="Teaching">Teaching</option><option value="Writing">Writing</option><option value="" selected>Ungrouped</option></select>' in html
    assert "start a new project called" in html


def test_lint_the_page_opens_the_dialog_alone_and_confirms_a_spoken_project_here():
    """A LINT on the page script (Grok R11): the dialog alone, the message back, the confirm card."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    js = open(os.path.join(root, "static", "high-seat-page.js"), encoding="utf-8").read()
    assert "window.open('/dashboard?new=1&only=1', 'anchor-new-project'" in js
    assert "ev.data.anchor !== 'project-created'" in js and "renewInPlace(text, null, !!ev.data.group_error);" in js   # W4: placed, never reloaded
    assert "function projectCard(pc)" in js and "mode: 'auto', name: name, folder_path: folder, group: sel.value || ''" in js
    assert "o.value === pc.group" in js, "the spoken folder preselects only when it is one of the folders"
    assert "confirm it on the old dashboard" not in js
    css = open(os.path.join(root, "static", "high-seat-page.css"), encoding="utf-8").read()
    assert ".pc-card{" in css and ".ptile-line .np{" in css
