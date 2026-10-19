"""W5 — Wave-list freeze + freeze_gate."""
from __future__ import annotations

from tools import freeze_gate as fg


def test_bootstrap_freeze_is_stamped_and_go():
    doc, path = fg.bootstrap_phase1(
        john_review_line="John Phase-1 review: freeze accepted via steward 2026-07-29."
    )
    assert path.is_file()
    assert doc.stamped is True
    assert set(doc.decisions) == set(fg.NORTH_STAR_CONTROLS)
    for cid, d in doc.decisions.items():
        assert d.state is fg.DecisionState.BUILD_NOW, cid
        assert d.build_wave, cid
    result = fg.phase1_go_decision()
    assert result.status == fg.GO


def test_bootstrap_all_writes_supporting_docs():
    paths = fg.bootstrap_all()
    for rel, p in paths.items():
        assert p.is_file(), rel


def test_unstamped_freeze_halts():
    doc, _ = fg.bootstrap_phase1(
        stamped=False,
        john_review_line="",
    )
    # If bootstrap forces stamp, load and clear
    doc = fg.load_freeze()
    doc.stamped = False
    doc.john_review_line = ""
    r = fg.validate_freeze_document(doc, require_stamped=True)
    assert r.status == fg.HALT


def test_insertion_cap_halt_rebaseline():
    doc, _ = fg.bootstrap_phase1(
        john_review_line="John Phase-1 review: freeze accepted via steward 2026-07-29."
    )
    doc = fg.load_freeze()
    doc.inserted_build_it_count = fg.INSERTION_CAP + 1
    doc.rebaseline_recorded = False
    r = fg.validate_freeze_document(doc, require_stamped=True)
    assert r.status == fg.HALT_REBASELINE


def test_normalize_control_id_from_display_cells():
    assert fg._normalize_control_id("`open` (open)") == "open"
    assert fg._normalize_control_id("doctor_diagnose (Doctor diagnose)") == "doctor_diagnose"
    assert fg._normalize_control_id("session_attach (session attach)") == "session_attach"


def test_evidence_hash_strips_markdown_backticks():
    doc = fg.load_freeze()
    assert doc.evidence_hash
    assert "`" not in doc.evidence_hash
    assert len(doc.evidence_hash) == 64
