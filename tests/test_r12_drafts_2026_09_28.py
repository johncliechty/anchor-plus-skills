"""R12 (John, 2026-09-28): "conversations are saved as they are put in" — the unsent text in every steward composer
(the cockpit, the High Seat, the Campaign page) is kept in the browser on each keystroke and put back after a crash,
a restart or a reload; a delivered turn clears it. Plus the token-rotation script, which never prints the token."""
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(rel):
    return open(os.path.join(ROOT, rel), encoding="utf-8").read()


def test_lint_the_cockpit_composer_keeps_its_unsent_text():
    js = _read("steward_cockpit/static/shared.js")
    assert 'const DRAFT_KEY = "anchor:draft:say:" + (PARAMS.get("pid") || "") + ":" + DIR;' in js, "keyed to the record"
    assert 'ta.addEventListener("input", () => { clearTimeout(_draftT); _draftT = setTimeout(saveDraft, 250); });' in js
    assert 'window.addEventListener("beforeunload", saveDraft);' in js
    assert 'addLine("sys", "your unsent text is back in the box")' in js
    assert 'if (!j.ok) { ta.value = keep; grow(); saveDraft(); } else { clearDraft(); }' in js, "delivered clears, undelivered keeps"


def test_lint_the_high_seat_and_campaign_composers_keep_their_unsent_text():
    hs = _read("static/high-seat-page.js")
    assert "var DRAFT_KEY = 'anchor:draft:highseat'" in hs and "window.addEventListener('beforeunload', saveDraft);" in hs
    assert "receipt('Your unsent text is back in the box.')" in hs
    assert "say.value = ''; clearDraft(); receipt(j.say" in hs, "a delivered turn clears the draft"
    cp = _read("static/campaign-page.js")
    assert "var DRAFT_KEY = 'anchor:draft:campaign:' + PID" in cp and "receipt('Your unsent text is back in the box.')" in cp
    dlg = _read("static/steward-dialogue.js")      # W2c-2: the one send path lives in the shared dialogue module, for both pages
    assert "if (DK) localStorage.removeItem(DK); } catch (e) {}\n          if (j.campaign_act" in dlg.replace("\r\n", "\n"), "cleared before the Campaign verb's reload (W2b-1: the one send path for both composers)"

def test_the_rotation_script_never_prints_the_token():
    ps = _read("tools/rotate_token.ps1")
    assert "AppEnvironmentExtra" in ps and "Set-Clipboard -Value $new" in ps and "nssm restart" in ps
    for line in ps.splitlines():
        if "Write-Host" in line or "Write-Output" in line:
            assert "$new" not in line and "$map[" not in line and "$pairs" not in line, line
    assert "IsInRole" in ps, "elevated only"
