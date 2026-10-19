# W11 — the REFINE overlay: talk-to-edit draft, SECTION-SCOPED hash-bound
# confirm surviving a concurrent writer, the drawn 'plan moved' card WITH
# diff, and the C9 DOM diff against the hash-pinned overlays spec
# (steward-chamber W11, C7).
#
# AUTH-ON: not-a-surface
#
# The wave's own words drive these tests:
#   * "Given a REFINE confirm bound to a section hash while reflections and
#     landings occur elsewhere, and separately a genuine plan-region
#     conflict, when John confirms, then the unrelated activity never
#     invalidates the confirm, and the genuine conflict shows the drawn
#     'plan moved' card WITH a diff — ledger writes only on hash-bound
#     confirm."
#   * "simulated-concurrent-writer test at steward-loop cadence"
#   * "DOM-diffed against the hash-pinned overlays spec"
import json
import threading
import time
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import chamber_mockup_diff as cmd  # noqa: E402
import chamber_projections as cp  # noqa: E402
import chamber_refine as cref  # noqa: E402

MANIFEST = {
    "schema_version": 1,
    "steps": [
        {"id": "s1", "name": "External scan", "skill": "researchPrime"},
        {"id": "s2", "name": "Syllabus plan", "skill": "crucible"},
    ],
    "goal": {"text": "the locked goal"},
    "deliverable": {"declared": True, "output_path": "out/deck.md"},
}


def _project(tmp_path):
    folder = tmp_path / "proj"
    (folder / ".anchor" / "chamber").mkdir(parents=True)
    (folder / ".anchor" / "chamber" / "pipeline-manifest.json").write_text(
        json.dumps(MANIFEST), encoding="utf-8")
    return folder


# ── sections seed deterministically from the manifest ───────────────────────

def test_sections_seed_from_the_sidecar_manifest(tmp_path):
    folder = _project(tmp_path)
    state = cref.plan_sections(folder)
    assert state["ok"]
    assert set(state["sections"]) == {"s1", "s2", "goal", "deliverable"}
    for sec in state["sections"].values():
        assert sec["hash"] and sec["text"]


def test_manifestless_project_is_empty_but_valid(tmp_path):
    folder = tmp_path / "bare"
    (folder / ".anchor" / "chamber").mkdir(parents=True)
    state = cref.plan_sections(folder)
    assert state["ok"]
    assert state["sections"] == {}


# ── the hash-bound confirm: writes ONLY on a matching section hash ──────────

def test_hash_bound_confirm_applies_and_clears_the_applied_draft(tmp_path):
    folder = _project(tmp_path)
    h = cref.section_hash(folder, "s2")
    drafted = "SYLLABUS v2 — 3 decisions named; dry-run added"
    assert cref.open_draft(folder, "s2", drafted)["ok"]
    out = cref.confirm_refine(folder, "s2", h, drafted)
    assert out["ok"]
    assert out["applied"]["from_hash"] == h
    state = cref.plan_sections(folder)
    assert "SYLLABUS v2" in state["sections"]["s2"]["text"]
    assert cref.current_draft(folder, "s2") is None  # applied → draft done


def test_talk_stays_draft_discard_writes_nothing(tmp_path):
    folder = _project(tmp_path)
    before = cref.plan_sections(folder)["sections"]["s1"]["text"]
    assert cref.open_draft(folder, "s1", "never applied")["ok"]
    assert cref.discard_draft(folder, "s1")["ok"]
    after = cref.plan_sections(folder)["sections"]["s1"]["text"]
    assert after == before
    assert cref.current_draft(folder, "s1") is None


def test_unknown_section_and_empty_text_are_named_refusals(tmp_path):
    folder = _project(tmp_path)
    out = cref.confirm_refine(folder, "no-such", "x", "text")
    assert out["error"] == cref.ERROR_UNKNOWN_SECTION
    out2 = cref.confirm_refine(folder, "s1", cref.section_hash(folder, "s1"),
                               "   ")
    assert out2["error"] == cref.ERROR_EMPTY_DRAFT


# ── the simulated CONCURRENT WRITER at steward-loop cadence ─────────────────

def test_concurrent_writer_elsewhere_never_invalidates_the_confirm(tmp_path):
    """Reflections, landings, and OTHER-section refinements churn at
    steward-loop cadence the whole time the s2 draft is open; the s2 confirm
    still lands on its original bound hash — section-scoped means exactly
    this."""
    folder = _project(tmp_path)
    bound = cref.section_hash(folder, "s2")
    assert cref.open_draft(folder, "s2", "the held draft")["ok"]

    stop = threading.Event()
    wrote = {"count": 0}

    def steward_loop():
        i = 0
        while not stop.is_set():
            i += 1
            # a landing/reflection projection event …
            cp.record_step_yield(folder, "c-1", "s1",
                                 "loop yield %d" % i, session_id="sess-1")
            # … and a refinement landing on the OTHER section.
            h1 = cref.section_hash(folder, "s1")
            r = cref.confirm_refine(folder, "s1", h1,
                                    "scan revision %d" % i)
            assert r["ok"], r
            wrote["count"] += 1
            time.sleep(0.01)  # steward-loop cadence

    t = threading.Thread(target=steward_loop, daemon=True)
    t.start()
    time.sleep(0.25)  # the draft sits open while the campaign churns
    out = cref.confirm_refine(folder, "s2", bound, "confirmed under churn")
    stop.set()
    t.join(timeout=10)
    assert wrote["count"] >= 3, "the concurrent writer never actually wrote"
    assert out["ok"], (
        "unrelated activity invalidated a section-scoped confirm: %s" % out)
    assert "confirmed under churn" in \
        cref.plan_sections(folder)["sections"]["s2"]["text"]


def test_genuine_same_section_conflict_shows_plan_moved_card_with_diff(tmp_path):
    folder = _project(tmp_path)
    bound = cref.section_hash(folder, "s2")
    assert cref.open_draft(folder, "s2", "my careful draft")["ok"]
    # The genuine conflict: a concurrent writer moves THE SAME section.
    moved = cref.confirm_refine(folder, "s2", cref.section_hash(folder, "s2"),
                                "scan findings re-shaped this step")
    assert moved["ok"]
    out = cref.confirm_refine(folder, "s2", bound, "my careful draft")
    assert not out["ok"]
    assert out["error"] == cref.ERROR_PLAN_MOVED
    assert out["finding"] == cref.FINDING_PLAN_MOVED
    card = out["card"]
    assert card["title"] == cref.PLAN_MOVED_TITLE
    diff = card["diff"]
    assert diff, "the 'plan moved' card must carry a REAL diff"
    assert any(ln.startswith("+") for ln in diff)
    assert any(ln.startswith("-") for ln in diff)
    assert any("re-shaped" in ln for ln in diff if ln.startswith("+"))
    # Draft preserved — [Re-apply my draft on top] stays possible.
    assert out["draft_preserved"] is True
    assert cref.current_draft(folder, "s2")["text"] == "my careful draft"
    assert card["actions"] == [cref.BTN_REAPPLY, cref.BTN_TAKE_NEW]
    # And NOTHING was written by the refused confirm.
    assert "scan findings" in cref.plan_sections(folder)["sections"]["s2"]["text"]


# ── C9: DOM-diffed against the HASH-PINNED overlays spec ────────────────────

def _signed_spec():
    text = cmd.load_signed_mockup()  # hash-verified load — pin enforced
    return cmd.spec_from_sections(
        text, (cmd.SECTION_OVERLAYS, cmd.SECTION_AMENDMENTS))


def test_refine_overlay_render_diffs_green_against_the_signed_spec():
    spec = _signed_spec()
    html = cref.render_refine_overlay_html({
        "steward_label": "Jarvis",
        "summary": "Done in draft: Syllabus plan now names its 3 decisions.",
        "messages": [
            {"who": "john", "text": "more detail on the syllabus step"},
            {"who": "steward", "text": "Done in draft."},
        ],
    })
    problems = cmd.diff_render(html, spec)
    assert problems == [], "invented structure vs the signed overlays:\n%s" \
        % "\n".join(problems)
    missing = cmd.missing_required(html, cref.REQUIRED_REFINE_OVERLAY)
    assert missing == [], "drawn skeleton missing: %s" % missing
    for label in (cref.BTN_CONFIRM, cref.BTN_KEEP, cref.BTN_DISCARD):
        assert label in html


def test_plan_moved_card_render_diffs_green_against_the_signed_spec():
    spec = _signed_spec()
    card = cref.plan_moved_card(
        "s2", "Syllabus plan · rides in: rubric facts",
        "Syllabus plan · rides in: scan findings (11 sources) + rubric facts")
    html = cref.render_plan_moved_card_html(card)
    problems = cmd.diff_render(html, spec)
    assert problems == [], "invented structure vs the signed AG card:\n%s" \
        % "\n".join(problems)
    missing = cmd.missing_required(html, cref.REQUIRED_PLAN_MOVED)
    assert missing == [], "drawn plan-moved skeleton missing: %s" % missing
    assert cref.BTN_REAPPLY in html and cref.BTN_TAKE_NEW in html
    assert 'class="del"' in html and 'class="add"' in html


def test_store_unreadable_fails_closed_by_name(tmp_path):
    folder = _project(tmp_path)
    cref.store_path(folder).parent.mkdir(parents=True, exist_ok=True)
    cref.store_path(folder).write_text("{garbled", encoding="utf-8")
    state = cref.plan_sections(folder)
    assert state == {"ok": False, "error": cref.ERROR_STORE_UNREADABLE}
    out = cref.confirm_refine(folder, "s1", "h", "text")
    assert out["error"] == cref.ERROR_STORE_UNREADABLE
