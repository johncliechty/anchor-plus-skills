"""W8 — Tri-state conformance harness + failure-state table validator.

Exercises every W8 deliverable under one scoped gate:

* ``tests/conformance/tri_state.py``
* ``tests/conformance/table_validator.py``
* ``tests/conformance/html_assert.py``
* ``tools/delta_coverage.py``
* ``artifacts/STATE-VOCABULARY-MAP.md``

Gate: pytest -v tests/test_conformance_harness_2026_07_29.py
"""
from __future__ import annotations

from pathlib import Path

import pytest

from anchor.ui.named_state import NamedState, generate_html, render_state
from tests.conformance import html_assert as ha
from tests.conformance import table_validator as tv
from tests.conformance import tri_state as ts
from tests.conformance.html_assert import (
    HtmlAssertError,
    assert_visible_text_contains,
    extract_script_blocks,
    node_check_scripts,
    visible_text_nodes,
)
from tests.conformance.table_validator import (
    HARDENING_TERMS,
    HONESTY_THEATER_VERBS,
    HonestyTheaterError,
    TableValidationError,
    VocabularyMapError,
    load_vocabulary_map,
    make_conformant_table,
    parse_vocabulary_map_text,
    validate_failure_state_table,
)
from tests.conformance.tri_state import (
    TRI_STATE_FIXTURES,
    TriStateCollapseError,
    TriStateHarness,
    assert_tri_state,
    default_render,
    run_tri_state,
)
from tools import delta_coverage as dc
from tools.delta_coverage import (
    DeltaCoverageError,
    check_delta_coverage,
    delta_coverage_available,
    read_probe,
)

CONTAINMENT_ROOT = Path(__file__).resolve().parents[1]
MAP_PATH = CONTAINMENT_ROOT / "artifacts" / "STATE-VOCABULARY-MAP.md"


# --------------------------------------------------------------------------
# Imports / package surface (acceptance: every module imported by gate tests)
# --------------------------------------------------------------------------


def test_w8_modules_importable():
    assert callable(assert_tri_state)
    assert callable(run_tri_state)
    assert callable(validate_failure_state_table)
    assert callable(load_vocabulary_map)
    assert callable(visible_text_nodes)
    assert callable(node_check_scripts)
    assert callable(check_delta_coverage)
    assert MAP_PATH.is_file()


# --------------------------------------------------------------------------
# STATE-VOCABULARY-MAP bijection
# --------------------------------------------------------------------------


def test_vocabulary_map_loads_and_is_bijection():
    vmap = load_vocabulary_map(CONTAINMENT_ROOT)
    assert vmap.schema.startswith("state-vocabulary-map")
    assert set(vmap.hardening_terms) == {_norm_h(t) for t in HARDENING_TERMS}
    assert set(vmap.named_state_terms) == {s.value for s in NamedState}
    # Every named state appears exactly once (dict key uniqueness).
    assert len(vmap.named_to_hardening) == len(NamedState) == 13
    assert len(vmap.hardening_to_named) == 5


def _norm_h(t: str) -> str:
    return t.strip().lower().replace("_", "-")


def test_vocabulary_map_backing_store_maps_only_to_unknown():
    vmap = load_vocabulary_map(CONTAINMENT_ROOT)
    named = vmap.resolve_hardening("backing-store-unreadable")
    assert named == frozenset({"unknown"})
    assert vmap.resolve_named("unknown") == "backing-store-unreadable"


def test_vocabulary_map_rejects_duplicate_or_foreign_term():
    bad = """
```vocab-map
schema: state-vocabulary-map/v1
dependency-missing: cannot_open
dependency-slow-or-killed: timeout
dependency-returns-garbage: measurement_failed
backing-store-unreadable: unknown
empty-but-valid: empty
extra-foreign-term: ok
```
"""
    with pytest.raises(VocabularyMapError) as ei:
        parse_vocabulary_map_text(bad)
    msg = str(ei.value).lower()
    assert "foreign" in msg or "missing" in msg or "bijection" in msg


def test_vocabulary_map_rejects_named_state_appearing_twice():
    bad = """
```vocab-map
schema: state-vocabulary-map/v1
dependency-missing: cannot_open, cannot_run, cannot_retry, cannot_restart
dependency-slow-or-killed: timeout, stale
dependency-returns-garbage: measurement_failed, unmeasured
backing-store-unreadable: unknown
empty-but-valid: empty, zero_measured, pending, unknown
```
"""
    with pytest.raises(VocabularyMapError) as ei:
        parse_vocabulary_map_text(bad)
    assert "unknown" in str(ei.value)


# --------------------------------------------------------------------------
# Tri-state harness
# --------------------------------------------------------------------------


def test_tri_state_default_render_passes():
    result = assert_tri_state(default_render, call_site="test:default_render")
    assert result.ok
    assert set(result.labels) >= set(TRI_STATE_FIXTURES)
    assert len(set(result.labels.values())) == 3


def test_gwt_collapsed_unknown_empty_fails_naming_pair_and_call_site():
    """Given a surface that renders the same string for unknown and empty,
    when the tri-state harness runs, then it fails naming the collapsed pair
    and the offending render call site.
    """

    def collapsed_surface(fixture: str) -> str:
        # Deliberately collapse unknown and empty to the same visible string.
        if fixture in ("unknown", "empty"):
            return '<span class="named-state">n/a</span>'
        return render_state(NamedState.zero_measured)

    site = "anchor.ui.fake_tile.render_collapsed"
    with pytest.raises(TriStateCollapseError) as ei:
        assert_tri_state(collapsed_surface, call_site=site)
    err = ei.value
    msg = str(err)
    assert "unknown" in msg and "empty" in msg
    assert site in msg
    assert err.collapsed_pair is not None
    assert set(err.collapsed_pair) == {"unknown", "empty"}
    assert err.call_site == site


def test_tri_state_harness_run_all_and_assert():
    h = TriStateHarness(call_site="harness:demo")
    h.register("honest", default_render)

    def bad(fixture: str) -> str:
        return "same"

    h.register("collapsed", bad)
    results = h.run_all()
    assert results["honest"].ok
    assert not results["collapsed"].ok
    with pytest.raises(TriStateCollapseError):
        h.assert_all()


def test_run_tri_state_does_not_raise_on_collapse():
    def bad(fixture: str) -> str:
        return render_state(NamedState.unknown)  # always unknown

    result = run_tri_state(bad, call_site="soft")
    assert result.ok is False
    assert result.collapsed_pair is not None


# --------------------------------------------------------------------------
# Table validator
# --------------------------------------------------------------------------


def test_conformant_table_passes():
    table = make_conformant_table("diagnose")
    report = validate_failure_state_table(
        table, surface="doctor", root=CONTAINMENT_ROOT
    )
    assert report["ok"] is True
    assert "backing-store-unreadable" in report["covered_hardening"]


def test_gwt_doctor_tile_index_rebuild_reconcile_is_honesty_theater():
    """Given a Doctor tile failure-state table written in index/rebuild/
    reconcile language, when table_validator runs, then it fails naming each
    unmapped/offending row and requires surface-native rows for Doctor actions.
    """
    # Complete hardening coverage but honesty-theater verbs in triggers.
    table = [
        {
            "hardening": "dependency-missing",
            "state": "cannot_run",
            "user_visible": "cannot_run",
            "trigger": "index missing — rebuild the doctor index",
        },
        {
            "hardening": "dependency-slow-or-killed",
            "state": "timeout",
            "user_visible": "timeout",
            "trigger": "reconcile timed out on doctor tile",
        },
        {
            "hardening": "dependency-returns-garbage",
            "state": "measurement_failed",
            "user_visible": "measurement_failed",
            "trigger": "rebuild returned garbage for diagnose",
        },
        {
            "hardening": "backing-store-unreadable",
            "state": "unknown",
            "user_visible": "unknown",
            "trigger": "index store unreadable",
        },
        {
            "hardening": "empty-but-valid",
            "state": "empty",
            "user_visible": "empty",
            "trigger": "reconcile found empty index",
        },
        {
            "hardening": "empty-but-valid",
            "state": "zero_measured",
            "user_visible": "zero_measured",
            "trigger": "index rebuild measured zero",
        },
    ]
    with pytest.raises(HonestyTheaterError) as ei:
        validate_failure_state_table(
            table, surface="doctor", root=CONTAINMENT_ROOT
        )
    msg = str(ei.value).lower()
    assert "honesty theater" in msg
    assert "doctor" in msg
    # Names at least one forbidden verb.
    assert any(v in msg for v in HONESTY_THEATER_VERBS)
    assert "surface-native" in msg or "diagnose" in msg or "open" in msg


def test_gwt_missing_backing_store_unreadable_row_fails():
    """Given a surface table that omits the required backing-store-unreadable
    row, when table_validator runs, then the wave fails naming the missing row.

    Completeness requires an *explicit* hardening field for each of the five
    dependency terms. A bare NamedState.unknown satisfies W6's separate-row
    rule but does **not** count as answering backing-store-unreadable.
    """
    table = [
        {
            "hardening": "dependency-missing",
            "state": "cannot_open",
            "user_visible": "cannot_open",
            "trigger": "open capability absent",
        },
        {
            "hardening": "dependency-slow-or-killed",
            "state": "timeout",
            "user_visible": "timeout",
            "trigger": "open timed out",
        },
        {
            "hardening": "dependency-returns-garbage",
            "state": "measurement_failed",
            "user_visible": "measurement_failed",
            "trigger": "open returned garbage",
        },
        {
            "hardening": "empty-but-valid",
            "state": "empty",
            "user_visible": "empty",
            "trigger": "no projects in scope",
        },
        {
            "hardening": "empty-but-valid",
            "state": "zero_measured",
            "user_visible": "zero_measured",
            "trigger": "open count measured zero",
        },
        {
            # W6 separate-row: unknown present, but NO explicit
            # hardening=backing-store-unreadable → incomplete table.
            "state": "unknown",
            "user_visible": "unknown",
            "trigger": "open path did not successfully read",
        },
    ]
    with pytest.raises(TableValidationError) as ei:
        validate_failure_state_table(
            table, surface="open", root=CONTAINMENT_ROOT
        )
    msg = str(ei.value)
    assert "backing-store-unreadable" in msg
    assert "complete" in msg.lower() or "missing" in msg.lower()


def test_table_rejects_term_absent_from_map():
    table = make_conformant_table("run")
    table.append(
        {
            "state": "totally-invented-state",
            "user_visible": "nope",
            "trigger": "run invented",
        }
    )
    with pytest.raises(TableValidationError) as ei:
        validate_failure_state_table(
            table, surface="run", root=CONTAINMENT_ROOT
        )
    assert "absent" in str(ei.value).lower() or "totally-invented" in str(ei.value)


def test_table_requires_user_visible_and_trigger():
    table = make_conformant_table("attach")
    table[0] = {
        "hardening": "dependency-missing",
        "state": "cannot_retry",
        "user_visible": "",
        "trigger": "attach capability absent",
    }
    with pytest.raises(TableValidationError) as ei:
        validate_failure_state_table(
            table, surface="attach", root=CONTAINMENT_ROOT
        )
    assert "user-visible" in str(ei.value).lower()


def test_merged_unknown_empty_still_fails():
    table = [
        {
            "hardening": "dependency-missing",
            "state": "cannot_open",
            "user_visible": "cannot_open",
            "trigger": "x",
        },
        {
            "hardening": "dependency-slow-or-killed",
            "state": "timeout",
            "user_visible": "timeout",
            "trigger": "x",
        },
        {
            "hardening": "dependency-returns-garbage",
            "state": "measurement_failed",
            "user_visible": "measurement_failed",
            "trigger": "x",
        },
        {
            "hardening": "backing-store-unreadable",
            "state": "unknown/empty",
            "user_visible": "bad",
            "trigger": "collapsed",
        },
        {
            "hardening": "empty-but-valid",
            "state": "zero_measured",
            "user_visible": "zero_measured",
            "trigger": "x",
        },
    ]
    with pytest.raises(TableValidationError) as ei:
        validate_failure_state_table(
            table, surface="usage", root=CONTAINMENT_ROOT
        )
    assert "unknown" in str(ei.value).lower()
    assert "empty" in str(ei.value).lower()


def test_index_bearing_surface_may_use_reconcile_language():
    table = make_conformant_table("render")
    # Inject index language on an index-bearing surface — must pass.
    table[0]["trigger"] = "index rebuild reconcile for discovery registry"
    report = validate_failure_state_table(
        table, surface="index", root=CONTAINMENT_ROOT
    )
    assert report["ok"] is True


# --------------------------------------------------------------------------
# html_assert
# --------------------------------------------------------------------------


def test_html_assert_visible_text_nodes_on_generate_html():
    doc = generate_html([NamedState.unknown, NamedState.empty, NamedState.zero_measured])
    nodes = visible_text_nodes(doc)
    assert "unknown" in nodes
    assert "empty" in nodes
    assert "zero_measured" in nodes
    assert_visible_text_contains(doc, ["unknown", "empty", "zero_measured"])


def test_html_assert_missing_label_raises():
    doc = generate_html([NamedState.ok])
    with pytest.raises(HtmlAssertError):
        assert_visible_text_contains(doc, "unknown")


def test_html_assert_extract_and_node_check_scripts():
    doc = generate_html()
    blocks = extract_script_blocks(doc)
    assert blocks, "generate_html must emit script for node --check"
    # node --check when available; never fails the suite if node absent.
    checked = node_check_scripts(doc, require_node=False)
    assert checked == blocks


def test_html_assert_node_check_rejects_syntax_error(tmp_path: Path):
    bad_html = "<html><body><script>function ( {</script></body></html>"
    # Only run the failure assertion when node is present.
    import shutil

    if not shutil.which("node"):
        pytest.skip("node not on PATH")
    with pytest.raises(HtmlAssertError) as ei:
        node_check_scripts(bad_html, work_dir=tmp_path, require_node=True)
    assert "node --check" in str(ei.value)


# --------------------------------------------------------------------------
# delta_coverage
# --------------------------------------------------------------------------


def test_delta_coverage_probe_reads_w1_record():
    probe = read_probe(CONTAINMENT_ROOT)
    assert probe is not None
    # This box recorded tooling absent (W1) — E4 path is live.
    # Do not hard-require false forever; just ensure the reader works.
    assert "delta_coverage" in probe


def test_gwt_uncovered_route_fails_or_e4_substitute(tmp_path: Path):
    """Given a new route without a dated test naming it, when delta_coverage
    runs, then the wave gate fails listing the uncovered route, or records a
    signed E4 with the enumerated per-handler list as substitute.
    """
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    # Dated test that does NOT mention the new route.
    (tests_dir / "test_other_2026_07_29.py").write_text(
        "def test_placeholder():\n    assert True\n",
        encoding="utf-8",
    )
    # Probe: tooling absent (E4 degrade path).
    probe_absent = {
        "delta_coverage": {
            "available": False,
            "fact": "delta-coverage unavailable",
        }
    }
    new_route = "/api/rnd/brand_new_route_w8"

    # Without E4 list → fail naming the uncovered route.
    with pytest.raises(DeltaCoverageError) as ei:
        check_delta_coverage(
            [new_route],
            root=tmp_path,
            tests_dir=tests_dir,
            probe=probe_absent,
            e4_enumerated_list=None,
        )
    assert new_route in str(ei.value) or "uncovered" in str(ei.value).lower()

    # With complete E4 enumerated list → substitute passes.
    report = check_delta_coverage(
        [new_route],
        root=tmp_path,
        tests_dir=tests_dir,
        probe=probe_absent,
        e4_enumerated_list=[new_route],
        raise_on_fail=False,
    )
    assert report.ok is True
    assert report.mode == "e4-enumerated-list"
    assert report.e4_enumerated_list == [new_route]


def test_delta_coverage_dated_test_names_handler(tmp_path: Path):
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    handler = "open_work_handler_w8"
    (tests_dir / "test_open_work_2026_07_29.py").write_text(
        "def test_open_work_handler_w8():\n    assert '%s'\n" % handler,
        encoding="utf-8",
    )
    probe_absent = {
        "delta_coverage": {"available": False, "fact": "delta-coverage unavailable"}
    }
    report = check_delta_coverage(
        [handler],
        root=tmp_path,
        tests_dir=tests_dir,
        probe=probe_absent,
    )
    assert report.ok
    assert handler in report.covered


def test_delta_coverage_rejects_e4_when_tooling_present(tmp_path: Path):
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    handler = "covered_handler"
    (tests_dir / "test_x_2026_07_29.py").write_text(
        "assert '%s'\n" % handler, encoding="utf-8"
    )
    probe_present = {
        "delta_coverage": {
            "available": True,
            "fact": "delta-coverage available via diff-cover 1.0",
            "tool": "diff-cover",
            "version": "1.0",
        }
    }
    with pytest.raises(DeltaCoverageError) as ei:
        check_delta_coverage(
            [handler],
            root=tmp_path,
            tests_dir=tests_dir,
            probe=probe_present,
            e4_enumerated_list=[handler],
        )
    assert "illegal" in str(ei.value).lower() or "E4" in str(ei.value)


def test_delta_coverage_uncovered_when_tooling_present(tmp_path: Path):
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_x_2026_07_29.py").write_text(
        "def test_x():\n    pass\n", encoding="utf-8"
    )
    probe_present = {
        "delta_coverage": {
            "available": True,
            "fact": "delta-coverage available via diff-cover 1.0",
        }
    }
    route = "/api/rnd/missing_from_tests"
    with pytest.raises(DeltaCoverageError) as ei:
        check_delta_coverage(
            [route],
            root=tmp_path,
            tests_dir=tests_dir,
            probe=probe_present,
        )
    assert route in str(ei.value)


def test_this_gate_file_covers_w8_symbols_for_delta_list():
    """W8's own handlers/modules appear in this dated test file."""
    handlers = [
        "tri_state",
        "table_validator",
        "html_assert",
        "delta_coverage",
        "STATE-VOCABULARY-MAP",
        "assert_tri_state",
        "validate_failure_state_table",
    ]
    # Live probe on this box (likely unavailable → E4 or dated-test path).
    report = check_delta_coverage(
        handlers,
        root=CONTAINMENT_ROOT,
        tests_dir=CONTAINMENT_ROOT / "tests",
        e4_enumerated_list=handlers,  # valid only when tooling absent
        raise_on_fail=False,
    )
    # Either dated-test coverage alone makes ok, or E4 list does.
    # If tooling present, E4 is illegal — but our handlers are named here
    # so dated-test path should pass without needing E4.
    if delta_coverage_available(read_probe(CONTAINMENT_ROOT)):
        report = check_delta_coverage(
            handlers,
            root=CONTAINMENT_ROOT,
            tests_dir=CONTAINMENT_ROOT / "tests",
            e4_enumerated_list=None,
            raise_on_fail=False,
        )
    assert report.ok, report.message


# --------------------------------------------------------------------------
# Integration: honest surface through all four engines
# --------------------------------------------------------------------------


def test_integration_honest_surface_through_all_engines():
    """Single surface driven through tri-state + html + table + delta."""

    def surface(fixture: str) -> str:
        key = (fixture or "").strip().lower().replace("-", "_")
        if key in ("zero", "zero_measured", "measured_zero"):
            state = NamedState.zero_measured
        elif key == "empty":
            state = NamedState.empty
        else:
            state = NamedState.unknown
        return generate_html([state], title="w8-surface")

    result = assert_tri_state(surface, call_site="tests.integration.w8_surface")
    assert result.ok
    for fix, html in result.rendered.items():
        assert_visible_text_contains(html, result.labels[fix])
        node_check_scripts(html, require_node=False)

    table = make_conformant_table("diagnose")
    report = validate_failure_state_table(
        table, surface="doctor", root=CONTAINMENT_ROOT
    )
    assert report["ok"]

    # Package re-exports
    assert ts.TRI_STATE_FIXTURES
    assert tv.HARDENING_TERMS
    assert ha.visible_text_nodes is visible_text_nodes
    assert dc.SCHEMA.startswith("delta-coverage")
