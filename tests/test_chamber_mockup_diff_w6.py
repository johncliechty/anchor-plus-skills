# W6 gate — the C9 mockup-fidelity kill gate (chamber_mockup_diff), co-landing
# with the FIRST painted markup (chamber_open's vertical-slice shell).
#
# AUTH-ON: not-a-surface
#
# The plan's C9 law, proven mechanically here:
#   * the diff PINS to the signed post-amendment markup hash recorded at the
#     W1 batched amendment gate (chamber/MOCKUP-AMENDMENT-GATE.md) and
#     HARD-FAILS when the gate record or the signed hash is absent, or the
#     mockup's bytes hash differently — no mockup-verbatim claim can precede
#     (or outlive) the signature;
#   * the painted slice's DOM/class structure — healthy, degraded
#     (first-open-after-deploy), and every signed drawn state — diffs GREEN
#     against §m1 + §amendments of the signed mockup;
#   * an invented element or an invented nesting FAILS the diff by name;
#   * the diff is two-directional: an empty dock cannot diff green (the
#     drawn skeleton is REQUIRED), so the gate can never go vacuous.
#
# Pure module/fixture tests — no server involvement of any kind.
import json
import sys
from pathlib import Path

import pytest

ANCHOR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ANCHOR))

import chamber_coldopen as co  # noqa: E402
import chamber_mockup_diff as cmd  # noqa: E402
import chamber_open as copen  # noqa: E402
import chamber_reconcile as cr  # noqa: E402


@pytest.fixture(scope="module")
def spec():
    """The signed slice spec — ONE hash-verified sibling read per module."""
    return cmd.slice_spec()


# ── helpers (the recovery suite's real-campaign shape, kept in sync) ─────────

def _at(i):
    return "2026-08-09T%02d:%02d:%02dZ" % (i // 3600, (i // 60) % 60, i % 60)


def _write_roadmap(folder, steps, events, as_of):
    (Path(folder) / "roadmap.json").write_text(json.dumps(
        {"project_id": "proj-w6-diff", "as_of": as_of,
         "roadmap_projection": steps, "roadmap_events": events}),
        encoding="utf-8")


def _write_run_record(folder, sid, *, step_id, outcome, at,
                      skill="gandalf", say="did the thing"):
    root = Path(folder) / cr.RUN_RECORDS_REL
    root.mkdir(parents=True, exist_ok=True)
    rec = {"session_id": sid, "commission_id": "c-" + sid,
           "step_id": step_id, "skill": skill, "lane": "research",
           "outcome": outcome, "at": at, "elapsed_s": 12.5,
           "report": {"say": say}, "reflection": {"say": say, "at": at}}
    (root / (sid + ".json")).write_text(json.dumps(rec), encoding="utf-8")


def _campaign(tmp_path, name="camp"):
    folder = tmp_path / name
    folder.mkdir()
    steps = [
        {"id": "s1", "name": "Draft memo", "status": "done",
         "skill": "gandalf"},
        {"id": "s2", "name": "Verify memo", "status": None,
         "skill": "researchPrime"},
    ]
    events = [
        {"kind": "scaffold_proposal", "proposal_id": "prop-1",
         "goal": "A verified memo.", "at": _at(10)},
        {"kind": "step_done", "step_id": "s1", "at": _at(20)},
    ]
    _write_roadmap(folder, steps, events, as_of=_at(20))
    _write_run_record(folder, "sess-done", step_id="s1", outcome="done",
                      at=_at(15))
    _write_run_record(folder, "sess-live", step_id="s2",
                      outcome=cr.OUTCOME_LIVE, at=_at(25))
    co.cold_open_rebuild(folder)
    return folder


# ── the pin: signed hash, hard-fail law ─────────────────────────────────────

def test_signed_hash_parses_from_the_gate_record():
    h = cmd.signed_hash()
    assert isinstance(h, str) and len(h) == 64
    int(h, 16)  # 64 hex digits — a real sha256


def test_load_signed_mockup_verifies_the_pin(spec):
    text = cmd.load_signed_mockup()
    assert 'id="m1"' in text and 'id="amendments"' in text
    # The compiled spec carries the drawn M1 skeleton.
    assert ("div", ("dock",)) in spec["sigs"]
    assert ("div", ("degrail",)) in spec["sigs"]
    assert (("div", ("dock",)), ("div", ("dbar",))) in spec["edges"]


def test_pin_hard_fails_on_absent_record_or_hash_or_mismatch(tmp_path):
    # Absent gate record — HARD fail, never a skip.
    with pytest.raises(cmd.MockupPinError):
        cmd.signed_hash(tmp_path / "no-such-gate.md")
    # A gate record carrying no signed hash line.
    unsigned = tmp_path / "gate-unsigned.md"
    unsigned.write_text("# gate\nno hash here\n", encoding="utf-8")
    with pytest.raises(cmd.MockupPinError):
        cmd.signed_hash(unsigned)
    # A mockup whose bytes moved after the signature (tampered sibling copy).
    root = tmp_path / "sibling"
    mp = root.joinpath(*cmd.MOCKUP_REL)
    mp.parent.mkdir(parents=True)
    mp.write_text(cmd.load_signed_mockup() + "<!-- drifted -->",
                  encoding="utf-8")
    with pytest.raises(cmd.MockupPinError) as exc:
        cmd.load_signed_mockup(root=root)
    assert "MISMATCH" in str(exc.value)
    # An absent mockup file under an otherwise-valid root.
    with pytest.raises(cmd.MockupPinError):
        cmd.load_signed_mockup(root=tmp_path / "empty-root")


# ── the diff: painted slices green; inventions named; skeleton required ──────

def test_healthy_slice_from_the_real_pipeline_diffs_green(tmp_path, spec):
    folder = _campaign(tmp_path)
    view = copen.seal_open_view(folder)
    assert view["degraded"] is None
    html = copen.render_seal_slice_html(view)
    assert cmd.verify_slice_render(html, spec, mode="healthy") == []


def test_degraded_first_open_slice_diffs_green(tmp_path, spec):
    folder = tmp_path / "fresh"
    folder.mkdir()
    _write_roadmap(folder,
                   [{"id": "s1", "name": "Draft memo", "status": None,
                     "skill": "gandalf"}],
                   [{"kind": "note", "at": _at(1)}], as_of=_at(1))
    view = copen.seal_open_view(folder)
    assert view["degraded"] is not None
    html = copen.render_seal_slice_html(view)
    assert cmd.verify_slice_render(html, spec, mode="degraded") == []


def test_signed_drawn_state_variants_diff_green(spec):
    # AG-STEP-NO-SKILL + AG-YIELD-MISSING + AG-GOAL-UNREADABLE +
    # AG-NO-RUNNING-STEP + AG-ZERO-HISTORY-ETA, all in one painted slice.
    view = {
        "degraded": None, "progress": {"done": 1, "total": 2},
        "steps": [
            {"id": "s1", "name": "Done bare", "status": "done"},
            {"id": "s2", "name": "Next up", "status": None},
        ],
        "goal": {}, "brief": {}, "live_run": None, "deliverable": None,
    }
    html = copen.render_seal_slice_html(view)
    assert cmd.verify_slice_render(html, spec, mode="healthy") == []
    # And the pre-emission running face (runcard.warm) with a deliverable.
    view2 = {
        "degraded": None, "progress": {"done": 0, "total": 1},
        "steps": [{"id": "s1", "name": "Scan", "status": None,
                   "skill": "researchPrime",
                   "running": {"session_id": "x", "step_id": "s1",
                               "skill": "researchPrime", "at": _at(1)}}],
        "goal": {"text": "A goal."}, "brief": {},
        "live_run": {"session_id": "x", "step_id": "s1",
                     "skill": "researchPrime", "at": _at(1)},
        "deliverable": {"declared": True, "description": "A memo.",
                        "output_path": "memo.md", "landed": False,
                        "landing": None},
    }
    html2 = copen.render_seal_slice_html(view2)
    assert cmd.verify_slice_render(html2, spec, mode="healthy") == []


def test_invented_element_and_nesting_fail_by_name(spec):
    # An element class the signed mockup never drew.
    bad = ('<div class="dock"><div class="dbar"><div class="hackbar">x'
           '</div></div></div>')
    problems = cmd.diff_render(bad, spec)
    assert any("invented element" in p and "hackbar" in p for p in problems)
    # A drawn element in an undrawn nesting (saybox inside the goalbar).
    bad2 = ('<div class="dock"><div class="goalbar"><div class="saybox">'
            '<input /></div></div></div>')
    problems2 = cmd.diff_render(bad2, spec)
    assert any("invented nesting" in p and "saybox" in p for p in problems2)


def test_required_direction_fails_an_empty_dock(spec):
    problems = cmd.verify_slice_render('<div class="dock"></div>', spec,
                                       mode="healthy")
    assert problems, "an empty dock must never diff green"
    assert any("required drawn element missing" in p for p in problems)
    # The degraded skeleton is required too: a dock without the drawn
    # degraded rail is not the signed first-open face.
    problems2 = cmd.verify_slice_render(
        '<div class="dock"><div class="dbar"></div></div>', spec,
        mode="degraded")
    assert any("degrail" in p for p in problems2)
