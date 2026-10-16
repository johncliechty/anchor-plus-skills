"""W2c-2 of the active set (2026-09-30), his word on the W2c preview: "take a look at the dialogues for both the High
Seat and the Campaign page. They need to engage the steward and then show the dialogue between the user and the
steward. Please make sure that this is in place, operational." ONE dialogue mechanism (static/steward-dialogue.js and
.css) on both pages: the Campaign's one conversation log shown, live from the open through the cockpit's stream, the
steward's state at its head. The High Seat's composer stays one box: a Campaign verb and the new-project ask are
answered by its own route as before; anything else is said to the Campaign's steward (the Desk) and the exchange
shows below. Both contexts read the log through one reader."""
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import campaign_page as cpg  # noqa: E402
import high_seat_page as hsp  # noqa: E402
import test_active_set_w2c_2026_09_30 as w2c  # noqa: E402
import test_active_set_w1_2026_09_29 as w1  # noqa: E402
import test_active_set_w2_2026_09_29 as w2  # noqa: E402

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _turns():
    return [{"you": True, "text": "what is starving here?", "at": "10:40", "goal": "trusts"},
            {"you": False, "text": "The Stanford package: nothing moved on it for 12 days.", "at": "10:41", "goal": "trusts"},
            {"you": True, "text": "what should I pick up?", "at": "11:02", "goal": ""}]


def test_the_high_seat_shows_the_one_conversation_under_the_composer_and_boots_the_dialogue():
    ctx = w2c._ctx(); ctx["turns"] = _turns(); ctx["n_turns"] = 3; ctx["goal_names"] = {"trusts": "The trusts"}; ctx["stamp"] = "s9"
    html = hsp.render_high_seat_html(ctx)
    panel = html[html.index('<aside class="panel"'):html.index("</aside>")]
    assert panel.index('id="nudgeSlot"') < panel.index('id="dialogue"') < panel.index('class="composer"') and 'id="todayBlock"' not in panel and 'id="brief"' not in panel, "the nudge slot (the brief is gone, 2026-10-03), the dialogue, then the composer at its foot; Today is under the board"
    assert 'id="todayBlock"' not in html and "raised by:" not in html, "his word 2026-10-02: the dated deliveries are enough - no Today block"
    assert '/steward/v1?embed=1&amp;view=talk&amp;inst=cave&amp;pid=' in panel and '&amp;dir=Cave%20of%20Wonders"' in panel   # the Cave's own conversation (2026-10-02) and 'id="exState"' in panel and 'id="exList"' in panel   # the cockpit's own view (2026-10-02)
    assert 'steward: "Jarvis", stamp: "s9"' in html, "the boot carries the steward's label and the record's stamp for the live lines"
    assert "it answers above as it writes; a Campaign verb applies on the record" in panel and "the Cave&rsquo;s steward answers above &middot; start a new project called" in panel, "the composer says where the answer lands"
    hcss = open(os.path.join(HERE, "static", "high-seat-page.css"), encoding="utf-8").read()
    assert "grid-template-columns:minmax(0,1fr) 480px" in hcss and "height:calc(100vh - 24px);display:flex;flex-direction:column" in hcss and "max-height:38vh" not in hcss, "W2c-3: the column is wider, the panel is the cockpit's shape, the dialogue fills it"
    assert '<link rel="stylesheet" href="/static/steward-dialogue.css?v=test">' in html and '<script src="/static/steward-dialogue.js?v=test"></script><script src="/static/high-seat-page.js?v=test">' in html
    ctx["turns"] = []; ctx["n_turns"] = 0
    assert "open in the cockpit &#8599;" in hsp.render_high_seat_html(ctx)   # the cockpit view says an empty log its own way (2026-10-02)
    ctx["campaign"] = None
    assert 'id="dialogue"' not in hsp.render_high_seat_html(ctx), "no dialogue without a Campaign"


def test_the_campaign_page_uses_the_same_dialogue():
    ctx = w2._ctx(w1._steps()); ctx["turns"] = _turns(); ctx["n_turns"] = 3
    html = cpg.render_campaign_html(ctx)
    assert '<link rel="stylesheet" href="/static/steward-dialogue.css?v=' in html and '<script src="/static/steward-dialogue.js?v=' in html
    assert html.index("steward-dialogue.js") < html.index("campaign-page.js"), "the module loads before the page script"
    assert 'id="dialogue"' in html and 'id="exState"' in html


def test_one_dialogue_script_and_one_stylesheet_carry_the_mechanism():
    dlg = open(os.path.join(HERE, "static", "steward-dialogue.js"), encoding="utf-8").read()
    for s in ("window.StewardDialogue = { init: init, authHeaders: authHeaders, loginBox: loginBox }", "primeSeq().then(function () { if (!refused) pollLoop(); })", "'/api/steward/events'", "'/api/steward/say'", "function catchUp", "'build-mismatch'", "function stateText", "pair.mi = put(main",
              "function authHeaders(base)", "h.Authorization = 'Bearer ' + t", "headers: getHeaders()", "function refusedOnce()", "if (r.status === 401 || r.status === 403)", "if (!j || !j.events) { setTimeout(step, 3000); return; }"):
        assert s in dlg, s
    cp = open(os.path.join(HERE, "static", "campaign-page.js"), encoding="utf-8").read()
    hs = open(os.path.join(HERE, "static", "high-seat-page.js"), encoding="utf-8").read()
    for page in (cp, hs):
        assert "window.StewardDialogue.init({" in page and "'/api/steward/events'" not in page and "function pollLoop" not in page, "the pages do not carry a second copy"
    assert "receiptKey: 'campaign_receipt'" in cp and "receiptKey: 'highseat_receipt'" in hs
    assert "openGoal: function (id) { window.open('/project/' + encodeURIComponent(CAMPAIGN) + '?open=' + encodeURIComponent(id), '_blank', 'noopener'); }" in hs, "the live chip opens the goal's place, as the rendered chip does (Grok W2c-2)"
    assert "openGoal: function (id) { openPlace(id); }" in cp
    assert "verbs_only: !!dlg" in hs and "if (j && j.ok && j.talk && dlg) { dlg.send(text, null, dlg.mainList(), send, say, DRAFT_KEY); return; }" in hs, "the High Seat's composer: a verb answered by its route; talk said to the steward"
    for f in ("steward-dialogue.js", "campaign-page.js", "high-seat-page.js"):
        r = subprocess.run(["node", "--check", os.path.join(HERE, "static", f)], capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
    css = open(os.path.join(HERE, "static", "steward-dialogue.css"), encoding="utf-8").read()
    ccss = open(os.path.join(HERE, "static", "campaign-page.css"), encoding="utf-8").read()
    for s in (".exwrap{flex:1 1 auto", ".exstate[data-state=\"busy\"]", ".gchip{font-size", ".exrow.live .ext::after", "@keyframes blink", ".exrow{padding"):
        assert s in css and s not in ccss, s


def test_the_high_seat_say_route_answers_talk_for_free_text_and_keeps_the_verbs_and_the_new_project_ask():
    import anchor_gui as ag
    assert ag._NEW_PROJECT_ASK.search("start a new project called Bread at C:/dev/Bread") and ag._NEW_PROJECT_ASK.search("create a project for the AI club")
    assert not ag._NEW_PROJECT_ASK.search("what should I pick up next?") and not ag._NEW_PROJECT_ASK.search("summarize the trusts goal") and not ag._NEW_PROJECT_ASK.search("show me the new project list"), "the imperative only (Grok W2c-2)"
    src = open(os.path.join(HERE, "anchor_gui.py"), encoding="utf-8").read()
    i = src.index("def handle_ecgberht_high_seat_say")
    body = src[i:i + 4000]
    assert 'if b.get("verbs_only") and not _NEW_PROJECT_ASK.search(text):' in body and '{"ok": True, "talk": True}' in body
    assert body.index('b.get("verbs_only")') < body.index("say_campaign(str(_cd), text)") < body.index('_ecgberht_project_folder("__dashboard__")'), "talk answered before the grammar compile (Grok W2c-2: the say route applies the verb itself); the dashboard steward only for the new-project ask"
    assert src.count("def _conversation_turns(folder)") == 1 and src.count("_conversation_turns(") >= 3, "one reader of the log for both contexts"
