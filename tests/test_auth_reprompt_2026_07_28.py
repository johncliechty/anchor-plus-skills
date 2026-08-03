"""401 re-auth must not destroy the user's work (friction 2026-07-28-08).

John, verbatim: *"I just tried to give it input and it came back with asking me
for the Anchor token, which I gave it (actually it was still saved--that may be
a problem). Then it restarted anchor and lost/forgot what I had given it. So, we
are not able to use the High Seat yet."*

Two defects, both in the global fetch wrapper:

1. **Reload as the recovery path.** A 401 ran `location.reload()`, throwing away
   the in-memory High Seat dialogue (`high-seat.js` states the dialogue is
   ephemeral — there is no draft buffer) and the in-flight act itself. After the
   token rotation on 2026-07-27 this was guaranteed data loss on the first click
   from any device still holding the old token.
2. **Re-offering the rejected token.** `setAnchorToken()` pre-filled the prompt
   with the saved value even when the server had *just* refused it, so pressing
   OK re-sent the known-bad token. That is the "it was still saved" symptom.

These are asserted against the RENDERED dashboard, not the source, because the
JS lives inside a Python f-string — checking the source would not prove what the
browser receives.
"""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def rendered(tmp_path_factory, ):
    import os
    os.environ.setdefault("ANCHOR_DATA_DIR", str(tmp_path_factory.mktemp("data")))
    import anchor_gui as g
    projects, tasks, inbox = g.gather_all()
    return g.generate_html(projects, tasks, inbox)


def _wrapper(html):
    """The body of the global fetch wrapper as the browser receives it."""
    i = html.index("Global 401 auto-reprompt")
    return html[i:i + 3000]


def _code_only(text):
    """Strip `//` comments so ordering assertions test CODE, not prose.

    Needed because the fix's own comment quotes `location.reload()` while
    explaining why it was removed — the first version of this test matched that
    comment and reported a defect that did not exist.
    """
    return "\n".join(re.sub(r"//.*$", "", ln) for ln in text.splitlines())


def test_a_401_retries_the_request_instead_of_reloading(rendered):
    body = _code_only(_wrapper(rendered))
    assert "_origFetch(_retok(" in body, \
        "a 401 no longer re-issues the original request"
    # The reload must not be the FIRST thing a 401 does any more.
    first_reload = body.find("location.reload()")
    first_retry = body.find("_origFetch(_retok(")
    assert first_retry < first_reload, \
        "reload still precedes the retry — typed input is destroyed before recovery"


def test_reload_survives_only_as_the_last_resort(rendered):
    """A genuinely wrong token (not merely stale) must still end somewhere honest."""
    body = _wrapper(rendered)
    assert "location.reload()" in body, "the last-resort path was removed entirely"
    assert "r2.status === 401" in body, \
        "no second-401 check — a wrong token would retry forever or fail silently"


def test_the_retry_carries_the_NEW_token_in_the_query(rendered):
    """High Seat authenticates via ?token=, so a retry that reuses the stale
    query string would 401 again and reload — the original bug, one step later."""
    body = _wrapper(rendered)
    assert "function _retok" in body
    assert "[?&]token=" in body, "the stale ?token= is not rewritten on retry"


def test_a_rejected_token_is_not_offered_back_as_the_default(rendered):
    i = rendered.index("function setAnchorToken")
    body = rendered[i:i + 900]
    assert "rejected" in body, "setAnchorToken cannot distinguish a rejected token"
    assert "was REJECTED" in body, "the user is not told their saved token was refused"
    assert "rejected ? '' : cur" in body, \
        "the prompt still pre-fills the token the server just refused"


def test_a_first_time_prompt_still_prefills_normally(rendered):
    """Only the REJECTED path changes; a fresh origin keeps its old behaviour."""
    i = rendered.index("function setAnchorToken")
    body = rendered[i:i + 900]
    assert "Paste your Anchor access token:" in body, \
        "the ordinary first-time prompt text was lost"


def test_the_dashboard_javascript_parses(rendered):
    """Guard the f-string brace escaping: this JS is generated inside a Python
    f-string, so a doubling mistake yields syntactically broken script."""
    import shutil
    import subprocess
    import tempfile
    node = shutil.which("node")
    if not node:
        pytest.skip("node not on PATH")
    blocks = re.findall(r"<script(?:\s[^>]*)?>(.*?)</script>", rendered, re.S)
    js = "\n;\n".join(b for b in blocks if len(b) > 200)
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False,
                                     encoding="utf-8") as fh:
        fh.write(js)
        path = fh.name
    out = subprocess.run([node, "--check", path], capture_output=True, text=True)
    assert out.returncode == 0, f"rendered dashboard JS is invalid:\n{out.stderr}"
