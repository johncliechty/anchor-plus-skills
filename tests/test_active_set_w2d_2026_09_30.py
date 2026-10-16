"""W2d THE GOAL'S GUIDE (2026-09-30; PLAN v1.3.1 fit 11): each goal's high-level planning guide at goals/<goal id>/GUIDE.md
under the Campaign - written by the Campaign's steward on his word in the goal's conversation (the standing text), read
into the goal's place with its history, revised there by him through one act that writes the file whole with a dated
History line and commits it; the map stamp watches the guides so the page reloads when the steward writes one."""
import json
import os
import shutil
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import campaign_page as cpg  # noqa: E402
from steward_cockpit import campaign_acts as acts  # noqa: E402
from steward_cockpit import steward_campaign as sc  # noqa: E402
import test_active_set_w2_2026_09_29 as w2  # noqa: E402

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GUIDE = ("# The trusts and the holding company \u2014 the guide\n\n## The goal\nThe trusts settled and the holding company standing.\n\n"
         "## The plan, at a high level\n- Stanford's package first\n- then the holding company\n\n## Where we are\nStanford's drafts are pending.\n\n"
         "## Decisions\n- 2026-09-30: one trust, not two\n\n## Deliverables\n- the signed package\n\n## History\n- 2026-09-30 10:00 \u2014 written from the goal's conversation\n")


def _campaign(tmp_path, with_git=False):
    c = tmp_path / "Campaign"; c.mkdir()
    (c / "ECGBERHT.md").write_text("# Campaign\n\n## North star\nthe goals\n", encoding="utf-8")
    (c / "roadmap.json").write_text(json.dumps({"roadmap_events": [], "roadmap_projection": [
        {"id": "trusts", "name": "The trusts and the holding company", "status": "proposed", "tier": 1, "done_when": "settled", "navigation": {"path": ["trusts"], "groups": [{"id": "trusts", "label": "The trusts", "order": 0, "parent_id": None}]}},
        {"id": "trusts-pkg", "name": "Stanford's package", "status": "proposed", "navigation": {"path": ["trusts", "trusts-pkg"], "groups": [{"id": "trusts", "label": "The trusts", "order": 0, "parent_id": None}]}}]}), encoding="utf-8")
    if with_git:
        subprocess.run(["git", "init", "-q"], cwd=str(c), check=True)
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "root"], cwd=str(c), check=True)
    return c


def test_the_guide_is_read_from_the_goal_s_folder_with_its_history(tmp_path):
    c = _campaign(tmp_path)
    assert sc.read_guide(str(c), "trusts") == {"exists": False, "text": "", "updated": "", "history": [], "rel": "goals/trusts/GUIDE.md"}, "absent = not written yet, never an error"
    (c / "goals" / "trusts").mkdir(parents=True); (c / "goals" / "trusts" / "GUIDE.md").write_text(GUIDE, encoding="utf-8")
    g = sc.read_guide(str(c), "trusts")
    assert g["exists"] and g["text"].startswith("# The trusts") and g["history"] == ["2026-09-30 10:00 \u2014 written from the goal's conversation"] and len(g["updated"]) == 16
    for bad in ("../trusts", "trusts/../x", "", "a b", "x" * 90):
        assert sc.guide_rel(bad) is None and sc.read_guide(str(c), bad)["exists"] is False, bad
    assert sc.guide_body(GUIDE).rstrip("\n").endswith("## Deliverables\n- the signed package") and "## History" not in sc.guide_body(GUIDE), "the body without its History section (the page shows the history once)"
    assert sc.guide_body("# g\n\n## History\n- a\n\n## Deliverables\n- d\n") == "# g\n\n## Deliverables\n- d\n", "a History section in the middle is lifted out whole"


@pytest.mark.skipif(shutil.which("git") is None, reason="git")
def test_his_revision_writes_the_guide_whole_with_a_dated_history_line_and_commits(tmp_path):
    c = _campaign(tmp_path, with_git=True)
    before = sc.map_stamp(str(c))
    r = sc.write_guide(str(c), "trusts", "# The trusts \u2014 the guide\n\n## The goal\nSettled.\n")
    assert r["ok"] and r["rel"] == "goals/trusts/GUIDE.md" and r["note"] == "committed" and len(r["updated"]) == 16
    text = (c / "goals" / "trusts" / "GUIDE.md").read_text(encoding="utf-8")
    assert text.endswith("## History\n- %s \u2014 revised by John in the goal\u2019s place\n" % r["updated"]), "no History section: made last, the line in it"
    assert not (c / "goals" / "trusts" / "GUIDE.md.tmp").exists() and sc.map_stamp(str(c)) != before, "written whole; the stamp moved so the page reloads"
    # the History section in the middle: the line lands at ITS end, the section after it untouched
    mid = "# g\n\n## History\n- 2026-09-30 10:00 \u2014 written\n\n## Deliverables\n- the package\n"
    r2 = sc.write_guide(str(c), "trusts", mid)
    text = (c / "goals" / "trusts" / "GUIDE.md").read_text(encoding="utf-8")
    assert text == "# g\n\n## History\n- 2026-09-30 10:00 \u2014 written\n- %s \u2014 revised by John in the goal\u2019s place\n\n## Deliverables\n- the package\n" % r2["updated"]
    assert r2["history"] == ["2026-09-30 10:00 \u2014 written", "%s \u2014 revised by John in the goal\u2019s place" % r2["updated"]]
    log = subprocess.run(["git", "log", "--format=%s", "--", "goals/trusts/GUIDE.md"], cwd=str(c), capture_output=True, text=True).stdout.strip().splitlines()
    assert len(log) == 2 and log[0] == "guide of trusts revised by John in the goal's place", "each revision a commit of that path only"
    assert sc.write_guide(str(c), "trusts", "   \n")["error"].startswith("an empty guide is not written")
    assert sc.write_guide(str(c), "../trusts", "# x")["error"] == "no such goal"


@pytest.mark.skipif(shutil.which("git") is None, reason="git")
def test_a_campaign_inside_a_parent_repo_takes_the_revision_but_commits_nothing_there(tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=str(tmp_path), check=True)      # the PARENT is a repo; the Campaign folder is not its root (Grok's read of W2d)
    c = _campaign(tmp_path)
    r = sc.write_guide(str(c), "trusts", "# g\n\n## The goal\nSettled.")
    assert r["ok"] and (c / "goals" / "trusts" / "GUIDE.md").is_file()
    assert r["note"] == "not committed (the Campaign is not a repo here)", r["note"]
    assert subprocess.run(["git", "log", "--oneline"], cwd=str(tmp_path), capture_output=True, text=True).stdout.strip() == "", "nothing landed in the parent repo"


def test_the_guide_act_is_his_hand_on_the_file_and_only_a_goal_takes_it(tmp_path, monkeypatch):
    c = _campaign(tmp_path)
    assert "guide" in acts.ACTS
    r = acts.act(str(c), {"act": "guide", "step": "trusts", "text": "# The trusts \u2014 the guide\n\n## The goal\nSettled."})
    assert r["ok"] and r["receipt"].startswith("the guide of The trusts and the holding company revised") and r["undo"] is None and len(r["updated"]) == 16
    assert (c / "goals" / "trusts" / "GUIDE.md").read_text(encoding="utf-8").startswith("# The trusts")
    assert acts.act(str(c), {"act": "guide", "step": "trusts-pkg", "text": "# x"}) == {"ok": False, "receipt": "no such goal"}, "a part is not a goal"
    assert acts.act(str(c), {"act": "guide", "step": "nope", "text": "# x"})["ok"] is False
    assert acts.act(str(c), {"act": "guide", "step": "trusts", "text": ""})["receipt"].startswith("an empty guide is not written")


def test_the_place_shows_the_guide_revisable_with_its_history_and_the_chips_ask_for_it():
    ctx = w2._ctx()
    ctx["guides"] = {"trusts": {"exists": True, "text": GUIDE, "updated": "2026-09-30 10:00", "history": ["2026-09-30 10:00 \u2014 written from the goal's conversation"], "rel": "goals/trusts/GUIDE.md"}}
    html = cpg.render_campaign_html(ctx, open_id="trusts")
    place = html[html.index('id="place-trusts"'):html.index("</article>", html.index('id="place-trusts"'))]
    assert '<div class="k">The guide <span class="h">(the steward writes it on your word' in place
    assert '<div class="guide" data-guide="trusts" data-updated="2026-09-30 10:00"><div class="gbody">' in place and "<h2>The plan, at a high level</h2>" in place and "<li>Stanford&#x27;s package first</li>" in place, "the steward's writing, rendered"
    body = place[place.index('<div class="gbody">'):place.index('<div class="gfoot">')]
    assert "<h2>History</h2>" not in body and "written from the goal" not in body, "the history once on the page: folded, not in the body too (Grok W2d)"
    assert '<button class="linkish" data-guide-edit="trusts">revise</button>' in place and '<details class="ghist"><summary>history &middot; 1</summary><ul><li>2026-09-30 10:00 \u2014 written from the goal&#x27;s conversation</li></ul></details>' in place
    assert '<textarea class="gsrc" hidden># The trusts and the holding company \u2014 the guide' in place and "## History" in place[place.index('<textarea class="gsrc"'):], "the raw markdown for the editor, History and all"
    ctx["guides"]["trusts"]["history"] = ["line %d" % k for k in range(15)]
    html15 = cpg.render_campaign_html(ctx, open_id="trusts")
    assert "<summary>history &middot; the last 12 of 15</summary>" in html15 and "<li>line 3</li>" in html15 and "<li>line 2</li>" not in html15, "the count is of the lines shown"
    assert place.index('data-guide="trusts"') < place.index('<div class="obody">'), "the guide before the parts: the plan at a high level, then the parts in order"
    assert '<button data-say="write the guide">write the guide</button><button data-say="update the guide">update the guide</button>' in place, "his word, one click"
    other = html[html.index('id="place-magi"'):html.index("</article>", html.index('id="place-magi"'))] if 'id="place-magi"' in html else html
    assert 'class="guide empty"' in other and "No guide yet &mdash; say &ldquo;write the guide&rdquo; below" in other, "absent = how it gets written"
    js = open(os.path.join(HERE, "static", "campaign-page.js"), encoding="utf-8").read()
    for s in ("$$('.place [data-guide-edit]').forEach(function (b) {", "act({ act: 'guide', step: box.getAttribute('data-guide'), text: ta.value });", "ed.className = 'gedit';", "body.hidden = true; box.insertBefore(ed, body);"):
        assert s in js, s
    r = subprocess.run(["node", "--check", os.path.join(HERE, "static", "campaign-page.js")], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    css = open(os.path.join(HERE, "static", "campaign-page.css"), encoding="utf-8").read()
    for s in (".place .guide{", ".place .guide.empty{", ".place .guide .gedit textarea{", ".place .guide .ghist summary{"):
        assert s in css, s


def test_the_page_context_reads_every_goal_s_guide_and_the_stamp_watches_them():
    src = open(os.path.join(HERE, "anchor_gui.py"), encoding="utf-8").read()
    assert 'guides = {i["id"]: _read_guide(folder, i["id"]) for i in initiatives}' in src and '"guides": guides' in src
    ms = open(os.path.join(HERE, "steward_cockpit", "steward_campaign.py"), encoding="utf-8").read()
    assert 'for gp in sorted((root / "goals").glob("*/GUIDE.md")):' in ms


def test_the_standing_text_tells_the_steward_the_guide():
    skill = open(r"C:\dev\Ecgberht\SKILL.md", encoding="utf-8").read() if os.path.exists(r"C:\dev\Ecgberht\SKILL.md") else ""
    if not skill:
        pytest.skip("no engine here")
    assert "goals/<goal id>/GUIDE.md" in skill and '"write the guide" / "update the guide"' in skill and "never unasked" in skill
    for sec in ("## The goal", "## The plan,", "## Where we are", "## Decisions", "## Deliverables", "## History"):
        assert sec in skill, sec
    assert "their seats AND their guides before any project's record" in skill and "W2d and W3 of the active set" not in skill
