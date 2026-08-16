"""Every client-side token read must go through the ONE canonical accessor.

WHY THIS EXISTS (2026-08-04). John hit this defect by hand on 2026-07-29 — a
steward window that "asked for a token again (which it had stored in the
window)". It was fixed. Then Wave 18 shipped ``static/chamber-ui.js``, which
invented its own accessor chain:

    window._anchorTokenQuery   -- defined NOWHERE in the codebase
    window.ANCHOR_TOKEN        -- not set on the project window
    window.anchorToken         -- not set anywhere

so every chamber fetch went out unauthenticated, 401'd, and the 401 path
re-prompted for a token the window already held. Same bug, new file, because
nothing forced the new file through the existing helper.

The canonical accessor is ``_anchorToken()`` (localStorage key ``anchor_token``),
defined in ``static/project-window.js`` and used by ``static/high-seat.js``.

This is the sibling guard to
``test_self_service_token.test_every_migrated_route_has_a_registered_handler``:
that one stops a new route 404ing, this one stops a new fetch re-prompting.
"""

import re
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parent.parent / "static"

CANONICAL = "_anchorToken"

# Must be an actual CALL. A plain substring test is VACUOUS here: the buggy
# spelling `_anchorTokenQuery` CONTAINS `_anchorToken`, so `"_anchorToken" in src`
# passes on the very code this guard exists to reject. `_anchorToken\s*\(` does
# not match `_anchorTokenQuery(` because the next char after the name is `Q`.
CANONICAL_CALL = re.compile(r"\b_anchorToken\s*\(")

# The globals a new module reaches for when it does NOT find the real helper.
# Reading these is only legitimate as a FALLBACK *after* _anchorToken is tried.
TEMPTING_GLOBALS = ("_anchorTokenQuery", "ANCHOR_TOKEN", "anchorToken")


def _js_files():
    return sorted(p for p in STATIC.glob("*.js"))


def test_static_dir_is_present_and_nonempty():
    """Guard the guard: a moved static dir must not silently pass everything."""
    files = _js_files()
    assert files, "no static/*.js found — this test would vacuously pass"


@pytest.mark.parametrize("path", _js_files(), ids=lambda p: p.name)
def test_no_js_file_reads_a_token_without_the_canonical_accessor(path):
    """A file that reads any token global must ALSO call ``_anchorToken()``.

    Reading ``window.ANCHOR_TOKEN`` is permitted only as a fallback in a file
    that tries the canonical accessor first — which is how chamber-ui.js and
    high-seat.js are both written after the fix. A file that reads ONLY the
    tempting globals is the re-prompt bug.
    """
    src = path.read_text(encoding="utf-8", errors="replace")

    reads_tempting = [g for g in TEMPTING_GLOBALS if re.search(r"\b%s\b" % re.escape(g), src)]
    if not reads_tempting:
        return  # file has no token concept at all

    assert CANONICAL_CALL.search(src), (
        "%s reads %s but never calls %s(). That is the 2026-07-29 re-prompt bug: "
        "the window holds a valid token in localStorage['anchor_token'] and this "
        "file cannot see it, so its fetches 401 and the user is asked to type the "
        "token again. Read the token via %s()."
        % (path.name, " / ".join(reads_tempting), CANONICAL, CANONICAL)
    )


def test_the_canonical_accessor_still_reads_the_expected_storage_key():
    """If the key or helper name moves, every guard above becomes a no-op."""
    src = (STATIC / "project-window.js").read_text(encoding="utf-8", errors="replace")
    assert "function _anchorToken()" in src, (
        "the canonical accessor _anchorToken() is gone from project-window.js — "
        "update this contract test deliberately, do not delete it")
    assert "anchor_token" in src, (
        "the localStorage key 'anchor_token' is gone — the other guards in this "
        "file are now checking a name that means nothing")
