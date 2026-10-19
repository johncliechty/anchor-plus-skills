"""W15 — Per-engine independent diagnose for Claude, Gemini, Grok with depth labels.

Exercises every W15 deliverable under one scoped gate:

* ``anchor/doctor/engines/{claude,gemini,grok}.py``
* ``anchor/doctor/depth_label.py``
* ``anchor/ui/doctor_view.py`` (three independently-stated rows)
* ``artifacts/failure-states/doctor-engines.md``
* ``artifacts/traces/doctor-engines-e2e.json``

Gate: pytest -v tests/test_doctor_engines_2026_07_29.py

GWTs (frozen plan):

* Gemini probe times out while Claude and Grok succeed → Gemini shows timeout
  with its depth label; Claude and Grok show their own real results — no
  shared verdict, no blanked rows.
* Engine report without a depth label → depth_label validation fails naming
  the engine and the unlabelled report.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from anchor.build.trace_artifact import (
    PROOF_LEVEL_RENDERED_STRING,
    is_go_evidence,
    validate_trace,
)
from anchor.doctor import depth_label as dl
from anchor.doctor import engines as eng_pkg
from anchor.doctor.depth_label import (
    DEPTH_VALUES,
    ENGINE_CLAUDE,
    ENGINE_GEMINI,
    ENGINE_GROK,
    ENGINE_IDS,
    DepthLabel,
    EngineReport,
    UnlabelledReportError,
    attach_depth,
    make_engine_report,
    require_depth,
    validate_engine_report,
    validate_engine_reports,
)
from anchor.doctor.engines import claude as claude_eng
from anchor.doctor.engines import gemini as gemini_eng
from anchor.doctor.engines import grok as grok_eng
from anchor.doctor.engines import probe_all_engines, probe_engine
from anchor.ui import doctor_view as dv
from anchor.ui.doctor_view import (
    DoctorViewContext,
    build_doctor_engines_trace,
    collect_engine_reports,
    generate_html,
    load_engines_trace_set,
    render_doctor_surface,
    render_engine_row,
    render_engine_rows,
    write_doctor_engines_traces,
)
from anchor.ui.named_state import NamedState
from tests.conformance.html_assert import (
    assert_visible_text_contains,
    node_check_scripts,
)
from tests.conformance.table_validator import validate_failure_state_table
from tools.capability_inventory import EVIDENCE_LIVE, InventoryRow, Verdict

CONTAINMENT_ROOT = Path(__file__).resolve().parents[1]
FAILURE_TABLE_PATH = (
    CONTAINMENT_ROOT / "artifacts" / "failure-states" / "doctor-engines.md"
)
ENGINES_TRACE_PATH = (
    CONTAINMENT_ROOT / "artifacts" / "traces" / "doctor-engines-e2e.json"
)

#: Modules that must be imported and exercised by this gate.
W15_SOURCE_RELS = (
    "anchor/doctor/depth_label.py",
    "anchor/doctor/engines/__init__.py",
    "anchor/doctor/engines/claude.py",
    "anchor/doctor/engines/gemini.py",
    "anchor/doctor/engines/grok.py",
    "anchor/ui/doctor_view.py",
)


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def _present_row(control_id: str = "diagnose") -> InventoryRow:
    return InventoryRow(
        control_id=control_id,
        verdict=Verdict.PRESENT,
        transcript_path="artifacts/transcripts/%s.json" % control_id,
        source_paths=("artifacts/inventory-sources/%s.probe" % control_id,),
        source_hash="c" * 64,
        probe_date="2026-07-29",
        evidence_mode=EVIDENCE_LIVE,
        disposition="wire it",
        notes="test PRESENT row for W15",
        label="Diagnose (Doctor)",
    )


def _parse_engines_failure_table(text: str) -> list:
    rows = []
    in_table = False
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("| hardening"):
            in_table = True
            continue
        if in_table and line.startswith("|---"):
            continue
        if in_table and line.startswith("|"):
            cells = [c.strip() for c in line.strip("|").split("|")]
            if len(cells) < 4:
                continue
            if cells[0] in ("hardening",):
                continue
            rows.append(
                {
                    "hardening": cells[0],
                    "state": cells[1],
                    "user_visible": cells[2],
                    "trigger": cells[3],
                }
            )
        elif in_table and not line.startswith("|"):
            break
    return rows


def _visible_text(html: str) -> str:
    text = re.sub(r"<[^>]+>", " ", html)
    return " ".join(text.split())


def _row_for_engine(html: str, engine: str) -> str:
    """Extract the single engine-row div for *engine* from rendered HTML."""
    pattern = (
        r'<div class="doctor-engine-row"[^>]*data-engine="%s"[^>]*>.*?</div>'
        % re.escape(engine)
    )
    m = re.search(pattern, html, re.DOTALL | re.IGNORECASE)
    assert m is not None, "missing engine row for %r in HTML" % engine
    return m.group(0)


# --------------------------------------------------------------------------
# Acceptance: every new module is imported and exercised
# --------------------------------------------------------------------------


def test_w15_modules_importable_and_callable():
    assert callable(claude_eng.probe)
    assert callable(gemini_eng.probe)
    assert callable(grok_eng.probe)
    assert callable(probe_all_engines)
    assert callable(probe_engine)
    assert callable(validate_engine_report)
    assert callable(validate_engine_reports)
    assert callable(require_depth)
    assert callable(attach_depth)
    assert callable(make_engine_report)
    assert callable(render_engine_row)
    assert callable(render_engine_rows)
    assert callable(collect_engine_reports)
    assert callable(generate_html)
    assert callable(render_doctor_surface)
    assert callable(build_doctor_engines_trace)
    assert callable(write_doctor_engines_traces)
    assert callable(load_engines_trace_set)
    assert dl.WAVE_ID == "W15"
    assert dv.ENGINES_WAVE_ID == "W15"
    assert set(ENGINE_IDS) == {ENGINE_CLAUDE, ENGINE_GEMINI, ENGINE_GROK}
    assert DEPTH_VALUES == frozenset({"deep", "shallow", "unavailable"})
    for rel in W15_SOURCE_RELS:
        assert (CONTAINMENT_ROOT / rel).is_file(), "missing source %s" % rel


def test_w15_sources_have_no_absolute_host_paths():
    banned = re.compile(
        r"(C:\\\\Users\\\\|/Users/|C:/Users/)",
        re.IGNORECASE,
    )
    for rel in W15_SOURCE_RELS:
        text = (CONTAINMENT_ROOT / rel).read_text(encoding="utf-8")
        assert not banned.search(text), "absolute host path in %s" % rel


# --------------------------------------------------------------------------
# Independent probes + depth labels
# --------------------------------------------------------------------------


def test_each_engine_healthy_is_deep_ok():
    for eng, mod in (
        (ENGINE_CLAUDE, claude_eng),
        (ENGINE_GEMINI, gemini_eng),
        (ENGINE_GROK, grok_eng),
    ):
        report = mod.probe()
        assert report.engine == eng
        assert report.named_state is NamedState.ok
        assert report.depth is DepthLabel.DEEP
        assert report.ok is True
        validate_engine_report(report)


def test_probe_all_engines_independent_and_labelled():
    reports = probe_all_engines()
    assert set(reports) == set(ENGINE_IDS)
    depths = validate_engine_reports(reports)
    for eng in ENGINE_IDS:
        assert depths[eng] is DepthLabel.DEEP
        assert reports[eng].named_state is NamedState.ok
        # Reading identity is engine-specific (no shared reading name).
        assert reports[eng].reading_name is not None
        assert eng in reports[eng].reading_name or eng in (reports[eng].detail or "")


@pytest.mark.parametrize(
    "fault,expected_state,expected_depth",
    [
        ("timeout", NamedState.timeout, DepthLabel.SHALLOW),
        ("store_unreadable", NamedState.unknown, DepthLabel.UNAVAILABLE),
        ("empty", NamedState.empty, DepthLabel.SHALLOW),
        ("missing", NamedState.cannot_run, DepthLabel.UNAVAILABLE),
        ("garbage", NamedState.measurement_failed, DepthLabel.SHALLOW),
        ("zero_measured", NamedState.zero_measured, DepthLabel.DEEP),
    ],
)
def test_each_engine_fault_path_named_and_labelled(fault, expected_state, expected_depth):
    for mod in (claude_eng, gemini_eng, grok_eng):
        report = mod.probe(fault=fault)
        assert report.named_state is expected_state
        assert report.depth is expected_depth
        validate_engine_report(report)


# --------------------------------------------------------------------------
# GWT: Gemini timeout isolation — Claude and Grok unaffected
# --------------------------------------------------------------------------


def test_gemini_timeout_leaves_claude_and_grok_intact():
    """GWT: Gemini timeout → Gemini timeout+depth; Claude/Grok real results."""
    reports = probe_all_engines(faults={"gemini": "timeout"})
    # Gemini: timeout + shallow depth.
    gem = reports[ENGINE_GEMINI]
    assert gem.named_state is NamedState.timeout
    assert gem.depth is DepthLabel.SHALLOW
    assert gem.ok is False
    assert gem.fault == "timeout"
    # Claude and Grok: own real healthy results — not timeout, not blanked.
    for eng in (ENGINE_CLAUDE, ENGINE_GROK):
        r = reports[eng]
        assert r.named_state is NamedState.ok, "%s should stay ok, got %s" % (
            eng,
            r.named_state,
        )
        assert r.depth is DepthLabel.DEEP
        assert r.ok is True
        assert r.fault is None
    # No shared verdict object.
    assert reports[ENGINE_CLAUDE] is not reports[ENGINE_GEMINI]
    assert reports[ENGINE_GROK] is not reports[ENGINE_GEMINI]
    assert reports[ENGINE_CLAUDE].as_dict() != reports[ENGINE_GEMINI].as_dict()


def test_gemini_timeout_render_no_shared_verdict_no_blanked_rows():
    """GWT: Doctor view renders three independent rows under Gemini timeout."""
    result = render_doctor_surface(
        DoctorViewContext(
            capability_present=True,
            inventory_row=_present_row(),
            head_hash="c" * 64,
            run_diagnose=False,
            engine_faults={"gemini": "timeout"},
            run_engine_probes=True,
        )
    )
    html = result.html
    # All three rows present.
    for eng in ENGINE_IDS:
        assert 'data-engine="%s"' % eng in html
        row = _row_for_engine(html, eng)
        assert 'data-depth="' in row
        assert "data-depth-label=" in row

    gem_row = _row_for_engine(html, ENGINE_GEMINI)
    assert 'data-named-state="timeout"' in gem_row
    assert 'data-depth="shallow"' in gem_row
    assert_visible_text_contains(html, "timeout")

    for eng in (ENGINE_CLAUDE, ENGINE_GROK):
        row = _row_for_engine(html, eng)
        assert 'data-named-state="ok"' in row
        assert 'data-depth="deep"' in row
        assert 'data-named-state="timeout"' not in row

    # No shared-verdict flag.
    assert 'data-shared-verdict="false"' in html
    # Panel must not collapse to a single verdict token for all engines.
    assert html.count('data-engine="') >= 3
    # Sibling rows not blank.
    assert "Claude" in _visible_text(html) or "claude" in html.lower()
    assert "Grok" in _visible_text(html) or "grok" in html.lower()
    assert "Gemini" in _visible_text(html) or "gemini" in html.lower()


def test_fault_claude_does_not_affect_gemini_or_grok():
    reports = probe_all_engines(faults={"claude": "store_unreadable"})
    assert reports[ENGINE_CLAUDE].named_state is NamedState.unknown
    assert reports[ENGINE_CLAUDE].depth is DepthLabel.UNAVAILABLE
    assert reports[ENGINE_GEMINI].named_state is NamedState.ok
    assert reports[ENGINE_GROK].named_state is NamedState.ok


def test_fault_grok_does_not_affect_claude_or_gemini():
    reports = probe_all_engines(faults={"grok": "empty"})
    assert reports[ENGINE_GROK].named_state is NamedState.empty
    assert reports[ENGINE_CLAUDE].named_state is NamedState.ok
    assert reports[ENGINE_GEMINI].named_state is NamedState.ok


# --------------------------------------------------------------------------
# GWT: unlabelled report rejected naming engine + report
# --------------------------------------------------------------------------


def test_unlabelled_report_rejected_naming_engine_and_report():
    """GWT: report without depth label → validation fails naming engine + report."""
    bare = EngineReport(
        engine=ENGINE_GEMINI,
        named_state=NamedState.ok,
        depth=None,  # deliberately unlabelled
        ok=True,
        detail="missing depth on purpose",
    )
    with pytest.raises(UnlabelledReportError) as ei:
        validate_engine_report(bare)
    msg = str(ei.value)
    assert "gemini" in msg.lower()
    assert "unlabelled" in msg.lower()
    # Error object names the engine.
    assert ei.value.engine == ENGINE_GEMINI
    assert ei.value.report is not None


def test_unlabelled_report_rejected_on_render_row():
    bare = EngineReport(
        engine=ENGINE_CLAUDE,
        named_state=NamedState.timeout,
        depth=None,
        ok=False,
    )
    with pytest.raises(UnlabelledReportError) as ei:
        render_engine_row(bare)
    assert ei.value.engine == ENGINE_CLAUDE
    assert "claude" in str(ei.value).lower()


def test_require_depth_rejects_blank():
    with pytest.raises(UnlabelledReportError) as ei:
        require_depth(ENGINE_GROK, None)
    assert ei.value.engine == ENGINE_GROK
    with pytest.raises(UnlabelledReportError):
        require_depth(ENGINE_GROK, "")
    with pytest.raises(UnlabelledReportError):
        require_depth(ENGINE_GROK, "   ")


def test_make_engine_report_require_label_default():
    with pytest.raises(UnlabelledReportError):
        make_engine_report(
            ENGINE_CLAUDE,
            NamedState.ok,
            depth=None,
            require_label=True,
        )
    # Explicit opt-out for test construction only.
    bare = make_engine_report(
        ENGINE_CLAUDE,
        NamedState.ok,
        depth=None,
        require_label=False,
    )
    assert bare.depth is None
    assert bare.is_labelled is False


def test_attach_depth_labels_unlabelled():
    bare = make_engine_report(
        ENGINE_GEMINI,
        NamedState.timeout,
        depth=None,
        require_label=False,
    )
    labelled = attach_depth(bare, DepthLabel.SHALLOW)
    assert labelled.depth is DepthLabel.SHALLOW
    validate_engine_report(labelled)


def test_validate_engine_reports_fails_on_one_unlabelled():
    reports = probe_all_engines()
    reports[ENGINE_GROK] = EngineReport(
        engine=ENGINE_GROK,
        named_state=NamedState.ok,
        depth=None,
        ok=True,
    )
    with pytest.raises(UnlabelledReportError) as ei:
        validate_engine_reports(reports)
    assert ei.value.engine == ENGINE_GROK


# --------------------------------------------------------------------------
# Rendered HTML + node --check
# --------------------------------------------------------------------------


def test_generate_html_three_engine_rows_and_depth_labels():
    html = generate_html(
        DoctorViewContext(
            capability_present=True,
            inventory_row=_present_row(),
            head_hash="c" * 64,
            run_diagnose=True,
            engine_faults={"gemini": "timeout"},
        )
    )
    assert "<html" in html.lower()
    assert "<script>" in html.lower()
    assert "doctor-engine-panel" in html
    for eng in ENGINE_IDS:
        assert 'data-engine="%s"' % eng in html
        assert 'data-depth-label="' in html
    # Depth vocabulary tokens appear as visible labels.
    assert "deep" in html
    assert "shallow" in html
    assert_visible_text_contains(html, "timeout")


def test_node_check_doctor_engines_scripts():
    html = generate_html(
        DoctorViewContext(
            capability_present=True,
            inventory_row=_present_row(),
            head_hash="c" * 64,
            engine_faults={"gemini": "timeout"},
        )
    )
    node_check_scripts(html)


def test_engine_unknown_and_empty_distinct_in_html():
    unknown_reports = probe_all_engines(
        faults={
            ENGINE_CLAUDE: "store_unreadable",
            ENGINE_GEMINI: "store_unreadable",
            ENGINE_GROK: "store_unreadable",
        }
    )
    empty_reports = probe_all_engines(
        faults={
            ENGINE_CLAUDE: "empty",
            ENGINE_GEMINI: "empty",
            ENGINE_GROK: "empty",
        }
    )
    unknown_html = render_engine_rows(unknown_reports)
    empty_html = render_engine_rows(empty_reports)
    assert 'data-named-state="unknown"' in unknown_html
    assert 'data-named-state="empty"' in empty_html
    assert 'data-named-state="empty"' not in unknown_html
    assert 'data-named-state="unknown"' not in empty_html
    assert_visible_text_contains(unknown_html, "unknown")
    assert_visible_text_contains(empty_html, "empty")


# --------------------------------------------------------------------------
# Failure-state table
# --------------------------------------------------------------------------


def test_failure_state_table_unknown_and_empty_separate():
    text = FAILURE_TABLE_PATH.read_text(encoding="utf-8")
    rows = _parse_engines_failure_table(text)
    states = {r["state"] for r in rows}
    assert "unknown" in states
    assert "empty" in states
    for r in rows:
        assert "/" not in r["state"]
        assert "unknown" not in r["state"] or r["state"] == "unknown"
    report = validate_failure_state_table(rows, surface="doctor-engines")
    assert report["ok"] is True


def test_failure_state_table_surface_native_and_per_engine():
    text = FAILURE_TABLE_PATH.read_text(encoding="utf-8")
    low = text.lower()
    assert "claude" in low
    assert "gemini" in low
    assert "grok" in low
    assert "depth" in low
    rows = _parse_engines_failure_table(text)
    for r in rows:
        trig = r["trigger"].lower()
        assert not re.search(r"\brebuild\b", trig)
        assert not re.search(r"\breconcile\b", trig)
        assert "index" not in trig or "index" not in trig.split()  # honesty theater


def test_failure_state_table_mentions_isolation():
    text = FAILURE_TABLE_PATH.read_text(encoding="utf-8")
    low = text.lower()
    assert "independent" in low or "isolation" in low or "sibling" in low
    assert "shared verdict" in low or "no shared" in low


# --------------------------------------------------------------------------
# E2E trace artifact
# --------------------------------------------------------------------------


def test_write_and_load_doctor_engines_trace():
    path = write_doctor_engines_traces(root=CONTAINMENT_ROOT)
    assert path.is_file()
    assert path.name == "doctor-engines-e2e.json"
    bag = load_engines_trace_set(root=CONTAINMENT_ROOT)
    assert bag["wave_id"] == "W15"
    assert bag["control_id"] == "diagnose_engines"
    assert bag["proof_level"] == PROOF_LEVEL_RENDERED_STRING
    assert bag.get("shared_verdict") is False
    primary = {
        k: bag[k]
        for k in (
            "schema",
            "wave_id",
            "control_id",
            "proof_level",
            "proof_disclosure",
            "trace_result",
            "induced_fault",
            "rendered_state",
            "as_of",
            "notes",
            "hops",
        )
        if k in bag
    }
    art = validate_trace(primary)
    assert is_go_evidence(art)
    # Isolation primary scenario encoded in rendered_state.
    rs = bag["rendered_state"]
    assert "gemini:timeout:shallow" in rs
    assert "claude:ok:deep" in rs
    assert "grok:ok:deep" in rs
    # Induced fault reasons covered.
    assert set(bag.get("enumerated_faults") or []) >= {
        "timeout",
        "store_unreadable",
        "empty",
        "missing",
        "garbage",
    }


def test_build_engines_trace_isolation_payload():
    art = build_doctor_engines_trace(engine_faults={"gemini": "timeout"})
    assert art.wave_id == "W15"
    assert art.proof_level == PROOF_LEVEL_RENDERED_STRING
    assert "gemini:timeout" in art.rendered_state
    assert "claude:ok" in art.rendered_state
    assert "grok:ok" in art.rendered_state
    for hop in art.hops:
        assert hop.payload_id
        assert hop.payload_hash
        assert len(hop.payload_hash) == 64


def test_trace_file_exists_after_write():
    write_doctor_engines_traces(root=CONTAINMENT_ROOT)
    assert ENGINES_TRACE_PATH.is_file()


# --------------------------------------------------------------------------
# Depth vocabulary closed set
# --------------------------------------------------------------------------


def test_depth_vocabulary_is_closed():
    assert set(d.value for d in DepthLabel) == {"deep", "shallow", "unavailable"}
    for token in ("deep", "shallow", "unavailable"):
        assert require_depth(ENGINE_CLAUDE, token).value == token


def test_probe_engine_dispatch():
    r = probe_engine(ENGINE_GEMINI, fault="timeout")
    assert r.engine == ENGINE_GEMINI
    assert r.named_state is NamedState.timeout
    with pytest.raises(ValueError):
        probe_engine("not-an-engine")


def test_engines_package_exports():
    assert eng_pkg.ENGINE_CLAUDE == "claude"
    assert callable(eng_pkg.probe_all_engines)
