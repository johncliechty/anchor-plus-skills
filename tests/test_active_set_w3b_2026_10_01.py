"""W3b (his word, 2026-10-01 12:3x): "the tile when they're open shouldn't collapse automatically, I should be able to
dictate in that"; "when I click on the dialog ... take me to the bottom"; "the steward dialog that's automatically up
... you should be at the bottom of that, not the top"; "use my name instead of You". The page renews itself only when no
tile is open and he is quiet; the open tile and his unsent words survive a renewal; the conversation opens at its foot;
his name in the rows on both pages."""
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import campaign_page as cpg  # noqa: E402
import high_seat_page as hsp  # noqa: E402
import test_active_set_w2_2026_09_29 as w2  # noqa: E402
import test_active_set_w2c_2026_09_30 as w2c  # noqa: E402

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _turns(n=4):
    return [{"you": i % 2 == 0, "text": "turn %d" % i, "at": "10:%02d" % i, "goal": ""} for i in range(n)]


def test_his_name_in_every_dialogue_row_on_both_pages_and_in_the_boot():
    assert hsp.HIS_NAME == "John"
    ctx = w2c._ctx(); ctx["turns"] = _turns(); ctx["n_turns"] = 4; ctx["stamp"] = "s1"
    html = hsp.render_high_seat_html(ctx)
    assert 'class="cview-frame"' in html, "the conversation is the cockpit's own view, which names him its own way (2026-10-02)"
    assert 'steward: "Aladdin", stamp: "s1", you: "John"};' in html or 'stamp: "s1", you: "John"};' in html, "the script learns the name from the boot"
    cctx = w2._ctx(); cctx["turns"] = _turns(); cctx["n_turns"] = 4; cctx["stamp"] = "s1"
    cctx["goal_turns"] = {"trusts": [{"you": True, "text": "about the trusts", "at": "10:10"}, {"you": False, "text": "noted", "at": "10:11"}]}
    chtml = cpg.render_campaign_html(cctx, open_id="trusts")
    assert 'class="cview-frame"' in chtml
    place = chtml[chtml.index('id="place-trusts"'):chtml.index("</article>", chtml.index('id="place-trusts"'))]
    assert '<div class="exw you">John<span class="t">10:10</span></div>' in place, "the goal's thread too"
    assert 'you: "John"};</script>' in chtml


def test_the_scripts_renew_only_when_no_tile_is_open_and_he_is_quiet_and_keep_the_open_tile():
    hs = open(os.path.join(HERE, "static", "high-seat-page.js"), encoding="utf-8").read()
    # the one gate for the record's stamp and a new build
    assert "function typingNow() { var a = document.activeElement; return (Date.now() - lastKey < 10000) || !!(a && a.tagName === 'TEXTAREA' && a.value && a.value.trim()) || $$('.tile.open').some(function (c) { return !!c._typing; }); }" in hs
    # W4 (2026-10-08): a change to the RECORD is placed in the page (renewInPlace) - never a reload; only a NEW BUILD
    # reloads it, through the one gate: never under an open tile or his typing, finished when the card closes and he is quiet
    assert "function tileOpen() { return !!$('.tile.open'); }" in hs and "function renewBuild(text) {" in hs and "if (tileOpen() || typingNow()) { pendingBuild = text || pendingBuild" in hs
    assert "renewKey" not in hs and "renewSaid" not in hs and "pendingRenew" not in hs and "highseat_renewed_for" not in hs
    assert "function heldLine(card) {" in hs and "card._heldSaid = true; card._talk.appendLine('sys', 'a new build is live \\u2014 this page renews itself when you close the card', 'dim');" in hs and "$$('.tile.open').forEach(heldLine);" in hs
    assert "document.addEventListener('input', markKey, true);" in hs, "dictated text counts as typing"
    assert "you: YOU, onStamp: function () { renewInPlace(); }," in hs, "the steward's change is placed in the page"
    assert "renewVersion = String(v); renewBuild('A new build is live \\u2014 the page is renewed.');" in hs and "function typing()" not in hs
    assert "setInterval(function () { if (pendingBuild && !tileOpen() && !typingNow()) renewBuild(pendingBuild); }, 5000);" in hs, "a held reload finishes when he is quiet"
    assert "if (pendingBuild) renewBuild(pendingBuild);\n      else if (placeHeld) renewInPlace();" in hs and "closeTile(c, true); }" in hs
    assert hs.count("location.reload()") == 1, "the new build's reload is the page's only one"
    # in place: the nudge slot and the interrupt lane follow the record, the lane never while he types
    assert "['nudgeSlot', 'seedCount', 'seedLbl', 'seedPanel', 'ptileCount', 'apGroups'].forEach" in hs
    assert "if (!typing) {" in hs and "var l0 = $('#lane'), l1 = doc.getElementById('lane')" in hs
    assert "var b = e.target.closest('[data-nudge-act]'); if (!b) return;" in hs, "a nudge re-rendered in place keeps its click (delegated)"
    assert "var b = e.target.closest('.tile[data-tile] [data-part]'); if (!b || b.classList.contains('h-open')) return;" in hs and "$$('[data-part]', card).forEach" not in hs, "a card's act buttons and its wait line's open/see survive a face re-rendered in place (Grok W3b)"
    # the open tile and his words survive a renewal
    assert "sessionStorage.setItem('highseat_open_tile', JSON.stringify({ id: card.id, dir: openDir(card), big: !!big }))" in hs and "function forgetTile()" in hs
    assert "openTile(card, card.getAttribute('data-tile'), kept.dir || '');\n    if (kept.big) grow(card);" in hs
    # his words in a tile now live in the cockpit's own box and its own draft key; the old tile draft moves there once
    assert "oldKey = 'anchor:draft:tile:' + pid + ':' + (dir || ''), newKey = 'anchor:draft:say:' + pid + ':' + (dir || '')" in hs
    # opening the conversation takes him to its foot; his name in the tile's rows
    assert "gist.textContent = (m.who === 'you' ? YOU : STEWARD_NAME) + ': '" in hs   # by name (2026-10-02), from the cockpit view's own turn
    cp = open(os.path.join(HERE, "static", "campaign-page.js"), encoding="utf-8").read()
    assert "if (typingNow()) { pendingRenew = text || pendingRenew || 'The record moved \\u2014 the page is renewed.'; if (k) pendingKey = k; return; }" in cp and "if (k && sessionStorage.getItem('campaign_renewed_for') === k) return;" in cp and "if (stampKey) sessionStorage.setItem('campaign_renewed_for', stampKey);" in cp and "renewKey" not in cp
    assert "you: YOU, onStamp: function (st) { renew('The steward changed the record \\u2014 the page is renewed.', st); }" in cp and "function typing()" not in cp
    assert "var b = e.target.closest('[data-nudge-act]'); if (!b) return;" in cp
    m = open(os.path.join(HERE, "static", "steward-dialogue.js"), encoding="utf-8").read()
    assert "YOU = o.you || 'You';" in m and "li.querySelector('.w').textContent = who === 'you' ? YOU : (who === 'st' ? STEWARD : '');" in m
    assert "(function () { var ml = mainList(); if (!ml) return; $$('.exrow.st', ml).forEach(md); settle(ml); setTimeout(function () { settle(ml); }, 300); })();" in m, "the dialogue opens at its latest turn"
    for f in ("high-seat-page.js", "campaign-page.js", "steward-dialogue.js"):
        assert subprocess.run(["node", "--check", os.path.join(HERE, "static", f)], capture_output=True, text=True).returncode == 0, f
