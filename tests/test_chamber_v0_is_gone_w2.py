# chamber-m1 W2 — THE REPLACEMENT GUARD: v0 is DELETED, in BOTH trees, and
# its return is a CI failure that names the symbol AND the tree.
#
# AUTH-ON: not-a-surface
#
# The law this file enforces (chamber-m1, 2026-08-13):
#
#   When code is replaced, the replaced code is DELETED.
#
# A superseded surface left in the tree does not sit inert — it competes. For
# twelve waves the M1 chamber painted and the v0 renderer then dropped it on
# every open, and every automated gate stayed green. John's ruling closed it:
# "M1 exactly as drawn, no v0 rescue" — a test asserting a v0 behaviour is not
# a reason to keep v0, it is one more v0 artifact to retire.
#
# WHAT THIS GUARD IS AND IS NOT. It is a NAME grep, so it is deliberately NOT
# the load-bearing recurrence instrument: a future
# ``getElementById('ecgSealSlice').remove()`` or ``host.innerHTML = ''``
# evades a name grep entirely. THE SURVIVAL TEST
# (tests/test_chamber_m1_survives_w1.py) is what makes the law hold — it opens
# a real browser and asserts the painted M1 chamber is still on screen after
# the hydrate settles. This guard catches the cheaper, likelier regression:
# someone restoring the deleted renderer by name, in either repo.
#
# BY TREE matters as much as BY NAME (shark finding 6, 2026-08-13): the
# original draft of this guard greped the ANCHOR tree for a symbol that lives
# in ECGBERHT. It passed on day one and could never have caught anything. So
# every assertion here names the tree it read, and
# :func:`test_the_guard_reads_a_real_ecgberht_tree` proves the Ecgberht path
# resolved to a real file before any absence is claimed — an absence found in
# a directory that does not exist is not evidence.
import re
import sys
from pathlib import Path

import pytest

ANCHOR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ANCHOR))

import chamber_enforcement as ce  # noqa: E402

#: The v0 chamber renderer family, deleted by this wave. Every name here was
#: a function in static/project-window.js that painted, hydrated or removed
#: the pre-M1 dock.
V0_JS_SYMBOLS = (
    "_ecgRenderChamber",     # the v0 chamber dock renderer
    "_ecgRenderStandUp",     # the v0 stand-up dock renderer (2nd dock minter)
    "_ecgSealDropSlice",     # the drop that deleted the painted M1 chamber
    "_ecgHydrateDispatchV0",  # W1's unreachable string-satisfier (see below)
)

#: ``_ecgHydrateDispatchV0`` earns its own line in the record. W1's fix loop
#: created it: an unreachable copy of v0's ``j.mode === 'stand_up'`` dispatch,
#: kept solely so an Ecgberht canary's string-grep would pass. It was honestly
#: documented and nothing called it — and it was still wrong, because it
#: satisfied a criterion with a STRING rather than with the surface, which is
#: the exact pattern that let the C9 pin stay green on a deleted element for
#: twelve waves. W2 deletes it and retargets the canary onto M1's drawn state.

#: The v0-only CSS families deleted with the renderers. M1 ships its own
#: signed-mockup styles into the slice's shadow root, so page-level rules can
#: never reach it: a surviving ``.ecg-dock`` block styles nothing at all.
V0_CSS_SELECTORS = (
    ".ecg-dock",
    ".ecg-convo-col",
    ".ecg-saybox",
    ".ecg-goalbar",
    ".ecg-rail{",       # the v0 rail's own block (`.ecg-rail .ecg-step` rules
                        # belong to the board's run annotations, not the dock)
    ".ecg-footer",
)

#: Anchor product source — the shipped surface, not tests and not planning
#: prose (both legitimately NAME the deleted symbols: this file does).
ANCHOR_PRODUCT = (
    Path("static") / "project-window.js",
    Path("static") / "project-window.css",
)

#: The Ecgberht data API that SURVIVES. Only the v0 RENDERER died; the
#: chamber route is kept as a data API because speak / converse /
#: commission_* compile against its view model. Reading this constant back is
#: also how the guard proves it resolved a real Ecgberht checkout.
ECG_ENGINE_REL = Path("engine") / "seal-chamber.mjs"
ECG_SURVIVING_SCHEMA_CONST = "SEAL_CHAMBER_SCHEMA_ID"


def _ecgberht_root() -> Path:
    """The REAL Ecgberht sibling.

    ``chamber_enforcement.ecgberht_root()`` honours ``ECGBERHT_ROOT``, which
    hermetic suites point at a stub bridge root carrying no engine. Same
    resolution law as :func:`chamber_mockup_diff.mockup_path`: prefer the env
    root when it actually carries the engine, else the checkout beside this
    tree. The guard must never report "v0 is gone" because it looked in a
    stub.
    """
    env = ce.ecgberht_root()
    if (env / ECG_ENGINE_REL).exists():
        return env
    return ANCHOR.parent / "Ecgberht"


def _ecgberht_sources(root: Path) -> list:
    """Every Ecgberht source file that could re-introduce a v0 symbol —
    engine, scripts and the test lane that Anchor's own gate runs."""
    out = []
    for sub in ("engine", "scripts", "test"):
        d = root / sub
        if not d.is_dir():
            continue
        for p in sorted(d.rglob("*.mjs")):
            if "node_modules" in p.parts:
                continue
            out.append(p)
    return out


def _strip_js_comments(text: str) -> str:
    """Blank // and /* */ comments, length-preserved.

    Comments are where the RETIREMENT gets explained, so they name the dead
    symbols on purpose — the w14 canary's header is three paragraphs about
    why it now asserts the absence. A guard that counted those as violations
    would punish the documentation and teach the next author to delete it.
    """
    out = list(text)
    i, n, state = 0, len(text), None
    while i < n:
        c, nxt = text[i], text[i + 1] if i + 1 < n else ""
        if state is None:
            if c == "/" and nxt == "/":
                state = "line"
            elif c == "/" and nxt == "*":
                state = "block"
            else:
                i += 1
                continue
            out[i] = out[i + 1] = " "
            i += 2
            continue
        if state == "line":
            if c == "\n":
                state = None
            else:
                out[i] = " "
            i += 1
            continue
        if c == "*" and nxt == "/":
            out[i] = out[i + 1] = " "
            state = None
            i += 2
            continue
        if c != "\n":
            out[i] = " "
        i += 1
    return "".join(out)


def _positive_pins(text: str, sym: str) -> list:
    """Places where `text` DEMANDS that `sym` exists.

    The distinction this function draws is the whole point of the check, and
    it is not pedantry: after W2 the sibling canaries name these symbols
    CONSTANTLY — in negative assertions (``!js.includes('_ecgRenderStandUp')``)
    and in dead-symbol lists — because asserting the absence is now their job.
    Those are the guard working, not the guard tripping.

    A violation is the symbol appearing as a literal argument to
    ``.includes(…)`` / ``.indexOf(…)``, or inside a regex literal (the
    ``assert.match(js, /function _ecgRenderChamber/)`` shape), in a position
    that is NOT negated. That is the shape which pressures a future fix loop
    into restoring v0 — and it is exactly the shape that made W1 mint an
    unreachable ``_ecgHydrateDispatchV0`` so a string grep would pass.
    """
    clean = _strip_js_comments(text)
    hits = []
    call = re.compile(
        r"(?:includes|indexOf)\(\s*['\"]%s['\"]" % re.escape(sym))
    for m in call.finditer(clean):
        # Walk back over the receiver chain (`js.`, `renderFn.`, …) and any
        # whitespace; a '!' immediately before it is an absence assertion.
        j = m.start() - 1
        while j >= 0 and (clean[j].isalnum() or clean[j] in "_$."):
            j -= 1
        while j >= 0 and clean[j].isspace():
            j -= 1
        if j >= 0 and clean[j] == "!":
            continue
        hits.append(clean[:m.start()].count("\n") + 1)
    for m in re.finditer(r"/[^/\n]*\b%s\b[^/\n]*/" % re.escape(sym), clean):
        hits.append(clean[:m.start()].count("\n") + 1)
    return sorted(set(hits))


# ── the guard proves it is looking somewhere real ───────────────────────────

def test_the_guard_reads_a_real_ecgberht_tree():
    """Anti-vacuous: an absence proves nothing unless the tree was found.

    This is shark finding 6 made permanent — the draft guard greped the wrong
    repo and passed forever. If the sibling is missing the two-repo execution
    contract is broken and the gate must say so loudly, never skip.
    """
    root = _ecgberht_root()
    engine = root / ECG_ENGINE_REL
    assert engine.is_file(), (
        "the Ecgberht sibling was NOT found (%s) — this guard's by-tree "
        "assertions would be vacuous, so it fails instead of passing on an "
        "empty read" % engine)
    text = engine.read_text(encoding="utf-8", errors="replace")
    assert ECG_SURVIVING_SCHEMA_CONST in text, (
        "%s is gone from %s — the chamber ROUTE is kept as a data API by this "
        "plan (speak / converse / commission_* compile against its view "
        "model); only the v0 RENDERER was deleted"
        % (ECG_SURVIVING_SCHEMA_CONST, engine))
    assert _ecgberht_sources(root), (
        "the Ecgberht sibling resolved but carries no .mjs sources — the "
        "by-tree scan below would read nothing")


# ── by name, by tree: Anchor ────────────────────────────────────────────────

def test_v0_renderers_are_gone_from_anchor_product_source():
    for rel in ANCHOR_PRODUCT:
        p = ANCHOR / rel
        text = p.read_text(encoding="utf-8", errors="replace")
        for sym in V0_JS_SYMBOLS:
            assert sym not in text, (
                "V0 RETURNED: %s is back in the ANCHOR tree at %s. The M1 "
                "chamber replaced it; a replaced surface does not get to "
                "coexist — it competes, and last time it won." % (sym, rel))


def test_v0_dock_css_is_gone_from_anchor_product_source():
    css = (ANCHOR / "static" / "project-window.css").read_text(
        encoding="utf-8", errors="replace")
    for sel in V0_CSS_SELECTORS:
        assert sel not in css, (
            "V0 CSS RETURNED: %s is back in the ANCHOR tree at "
            "static/project-window.css. M1's styles ship into the slice's "
            "shadow root, which page CSS cannot cross — a v0 dock rule "
            "styles nothing and is dead weight at best." % sel)


def test_the_mount_paints_the_slice_and_nothing_else():
    """The mount path itself: M1 is painted, no v0 renderer is called, and the
    successor hydrate never touches the DOM."""
    js = (ANCHOR / "static" / "project-window.js").read_text(
        encoding="utf-8", errors="replace")
    mount = js[js.index("function ecgSealMountInline()"):]
    assert "_ecgSealPaintSlice(host)" in mount, \
        "the mount stopped painting the M1 slice"
    assert "/api/ecgberht/chamber?project_id=" in mount, \
        "the successor hydrate is gone — the chamber route is KEPT as a " \
        "data API by this plan"
    assert "ecg-dock" not in mount, "the error-path v0 dock is minted again"


# ── by name, by tree: Ecgberht ──────────────────────────────────────────────

def test_no_ecgberht_source_re_pins_a_deleted_v0_symbol():
    """The sibling lane may not resurrect v0 by asserting it.

    Both Ecgberht canaries that pinned these symbols were retargeted in this
    wave (`test/w14-standup-canaries.test.mjs` onto M1's drawn state,
    `test/w11-seal-chamber.test.mjs`'s two Anchor-dev mount-detail rows
    retired on the debt register). A test that demands a v0 symbol exist is
    how v0 comes back: W1 minted an unreachable dispatch copy for exactly
    that reason.
    """
    root = _ecgberht_root()
    hits = []
    for p in _ecgberht_sources(root):
        text = p.read_text(encoding="utf-8", errors="replace")
        for sym in V0_JS_SYMBOLS:
            for line in _positive_pins(text, sym):
                hits.append("%s:%d demands %s"
                            % (p.relative_to(root), line, sym))
    assert not hits, (
        "V0 RE-PINNED in the ECGBERHT tree (%s):\n  %s\nA sibling assertion "
        "that DEMANDS a deleted Anchor symbol will pressure the next fix loop "
        "into restoring it — that is how the unreachable _ecgHydrateDispatchV0 "
        "came to exist. Retarget the assertion onto M1's drawn surface or "
        "retire it on the TEST-DEBT-REGISTER. (Asserting the ABSENCE of these "
        "symbols is fine and expected — this check only fails positive pins.)"
        % (root, "\n  ".join(hits)))


# ── the guard BITES (a green guard that cannot fail is not a guard) ─────────

@pytest.mark.parametrize("sym", V0_JS_SYMBOLS)
def test_the_guard_fails_by_name_on_a_reintroduction(tmp_path, sym):
    """Negative proof, per symbol: reintroduce it in a synthetic tree and the
    same predicate the real assertions use finds it and names it."""
    fake = tmp_path / "project-window.js"
    fake.write_text("function %s(host, j) { /* it came back */ }\n" % sym,
                    encoding="utf-8")
    text = fake.read_text(encoding="utf-8")
    found = [s for s in V0_JS_SYMBOLS if s in text]
    assert found == [sym], \
        "the by-name predicate missed a reintroduced %s" % sym


def test_the_positive_pin_detector_tells_demand_from_absence():
    """The sibling half's discrimination, proven both ways.

    This matters because after W2 the retargeted canaries name the dead
    symbols on nearly every line — in negative assertions, in dead-symbol
    lists and in the comments explaining the retirement. A detector that
    could not tell those from a real demand would either fail forever (and be
    deselected, which is how coverage dies quietly) or be loosened until it
    caught nothing.
    """
    sym = "_ecgRenderChamber"
    demands = [
        "assert.ok(js.includes('%s'));" % sym,
        'assert.ok(js.includes("%s"));' % sym,
        "const fn = js.slice(js.indexOf('%s'));" % sym,
        "assert.match(js, /function %s\\(/);" % sym,
    ]
    for src in demands:
        assert _positive_pins(src, sym), "a real v0 demand slipped past: %s" % src

    absences = [
        "assert.ok(!js.includes('%s'));" % sym,
        "assert.ok(! js.includes('%s'), 'v0 returned');" % sym,
        "for (const dead of ['%s', '_ecgSealDropSlice']) "
        "{ assert.ok(!js.includes(dead)); }" % sym,
        "// %s was deleted by chamber-m1 W2 — see the debt register" % sym,
        "/* the %s dock is gone; M1 paints the slice instead */" % sym,
    ]
    for src in absences:
        assert not _positive_pins(src, sym), \
            "an absence assertion was miscounted as a v0 demand: %s" % src


def test_the_guard_fails_when_the_tree_is_not_there(tmp_path, monkeypatch):
    """Negative proof for the by-TREE half: pointed at a directory with no
    engine, the resolver must not silently 'find nothing and pass'."""
    empty = tmp_path / "not-ecgberht"
    (empty / "engine").mkdir(parents=True)
    monkeypatch.setenv("ECGBERHT_ROOT", str(empty))
    # The resolver falls back to the sibling beside Anchor rather than
    # accepting a rootless read — and if THAT is absent too, the guard's
    # own precondition test above is the one that fails, by name.
    root = _ecgberht_root()
    assert (root / ECG_ENGINE_REL).is_file() or not _ecgberht_sources(root), (
        "the resolver accepted a tree with no engine as the Ecgberht sibling")
