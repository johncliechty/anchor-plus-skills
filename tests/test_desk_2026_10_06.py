"""The Desk (John 2026-10-06): small items in one small-item cockpit, substantial efforts in their own cockpits,
seatable in the Cave; a one-line Desk tile on the Cave. Hermetic: a temp Desk folder, no server, no model."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import desk  # noqa: E402
import desk_page  # noqa: E402
import high_seat_page as hsp  # noqa: E402

GRAY = lambda f: {"light": "gray", "word": "idle", "why": ""}  # noqa: E731


def test_small_items_live_in_their_own_folder_and_promote_to_a_cockpit(tmp_path):
    root = tmp_path / "Desk"
    desk.ensure_small_items(root)
    assert (root / "Small items" / "ECGBERHT.md").is_file(), "the small-item cockpit exists"
    a = desk.add_item("Renew the parking permit", root=root)["item"]
    b = desk.add_item("Expense claim, September", root=root)["item"]
    assert not desk.add_item("   ", root=root)["ok"]
    assert desk.set_done(a["id"], root=root)["ok"]
    out = desk.promote(b["id"], root=root)
    assert out["ok"] and (root / out["dir"] / "ECGBERHT.md").is_file()
    assert "Expense claim" in (root / out["dir"] / "ECGBERHT.md").read_text(encoding="utf-8")
    items = {i["id"]: i for i in desk.read_items(root=root)}
    assert items[a["id"]]["status"] == "done" and items[b["id"]]["status"] == "moved"
    assert desk.promote(b["id"], root=root).get("already"), "promoting twice makes no second cockpit"
    assert desk.cockpit_dirs(root=root) == [out["dir"]], "Small items is not one of the cockpits"


def test_a_cockpit_needs_a_plain_name(tmp_path):
    root = tmp_path / "Desk"
    for bad in ("", "Small items", "../escape", "a/b", "c:d"):
        assert not desk.new_cockpit(bad, root=root)["ok"], bad
    assert desk.new_cockpit("Travel November", root=root)["ok"]
    assert not desk.new_cockpit("Travel November", root=root)["ok"], "never a second cockpit with one name"


def test_a_waiting_item_makes_the_small_items_cockpit_orange_and_counts(tmp_path):
    root = tmp_path / "Desk"
    it = desk.add_item("Sign the form", root=root)["item"]
    data = json.loads((root / "Small items" / desk.ITEMS_FILE).read_text(encoding="utf-8"))
    data["items"][0].update(state="waits", note="ready to sign")            # what the steward writes
    (root / "Small items" / desk.ITEMS_FILE).write_text(json.dumps(data), encoding="utf-8")
    desk.new_cockpit("Trust paperwork", root=root)
    s = desk.summary(GRAY, seat_of=lambda d: "deck", root=root)
    assert s["small"]["light"] == "orange" and "Sign the form" in s["small"]["why"] and s["waits"] == 1
    assert s["cockpits"][0]["seat"] == "deck" and s["small"]["items"][0]["id"] == it["id"]


def test_the_cave_tile_is_one_line_that_expands_and_opens_the_desk(tmp_path):
    root = tmp_path / "Desk"
    desk.add_item("Book the furnace service", root=root)
    desk.new_cockpit("Travel November", root=root)
    summ = desk.summary(GRAY, root=root)
    html = hsp._desk_line({"desk": summ, "desk_pid": "p1"})
    assert 'id="deskHead"' in html and 'id="deskTog"' in html and 'href="/desk"' in html
    assert "Small items 1" in html and "1 cockpit" in html
    assert html.count('<a class="drow') == 2, "a row per cockpit, Small items first"
    assert "camp-body" in html, "the rows sit in the folded body (the Goals tile's own pattern)"
    assert 'href="/desk"' in hsp._desk_line({}), "not set up yet: opening it sets it up"


def test_the_desk_page_wears_the_cave_style_and_seats_through_the_campaign(tmp_path):
    root = tmp_path / "Desk"
    desk.add_item("Reply to the dean", root=root)
    desk.new_cockpit("Travel November", root=root)
    ctx = {"build": "b1", "steward": {"label": "Aladdin", "high_seat": "x.jpg"}, "entry": {"id": "p1"},
           "desk": desk.summary(GRAY, root=root), "campaign_pid": "c1", "logged_in": True}
    html = desk_page.render_desk_html(ctx)
    assert "/static/high-seat-page.css" in html and "/static/desk-page.css" in html
    assert 'data-ref="effort:p1/Travel November"' in html and 'data-seat="active"' in html
    assert "Own cockpit" in html and 'id="deskAdd"' in html and 'id="deskNew"' in html
    locked = desk_page.render_desk_html(dict(ctx, auth_required=True, logged_in=False))
    assert "Reply to the dean" not in locked, "nothing shows until he is logged in"
