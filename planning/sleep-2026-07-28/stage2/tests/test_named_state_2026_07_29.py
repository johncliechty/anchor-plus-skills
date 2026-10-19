"""W6 — Named-state vocabulary + render primitive (unknown ≠ empty ≠ zero).

Exercises ``anchor.ui.named_state`` and ``tools.zero_inference_lint`` under
the frozen plan contract:

* NamedState has exactly thirteen members with distinct rendered labels
* trichotomy members (unknown, empty, zero_measured, pending) carry the
  Binding definitions section wording verbatim as docstrings
* render_state emits a labelled visible text node for every state
* render_state raises on None / blank input (never an empty cell)
* FAILURE_STATE_TABLE schema rejects merged unknown/empty (and
  pending/zero_measured) rows — hardening gates 0080/0081
* zero_inference_lint flags ``if cost == 0: return "(subscription)"``
* generate_html rendered output carries visible labels; script block is
  syntax-valid for node --check

Gate: pytest -v tests/test_named_state_2026_07_29.py
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from anchor.ui import named_state as ns
from anchor.ui.named_state import (
    BINDING_EMPTY,
    BINDING_PENDING,
    BINDING_UNKNOWN,
    BINDING_ZERO_MEASURED,
    FAILURE_STATE_TABLE,
    NAMED_STATE_COUNT,
    BlankStateError,
    FailureStateTableError,
    NamedState,
    all_labels,
    generate_html,
    render_state,
    trichotomy_docstrings,
    validate_failure_state_table,
)
from tools import zero_inference_lint as zil

# --------------------------------------------------------------------------
# NamedState enum shape
# --------------------------------------------------------------------------

EXPECTED_STATES = (
    "ok",
    "unknown",
    "empty",
    "zero_measured",
    "pending",
    "unmeasured",
    "measurement_failed",
    "timeout",
    "stale",
    "cannot_retry",
    "cannot_open",
    "cannot_run",
    "cannot_restart",
)

TRICHOTOMY = ("unknown", "empty", "zero_measured", "pending")


def test_named_state_has_exactly_thirteen_members():
    assert len(NamedState) == NAMED_STATE_COUNT == 13
    assert len(NamedState) == len(EXPECTED_STATES)


def test_named_state_member_tokens_match_plan():
    tokens = {s.value for s in NamedState}
    assert tokens == set(EXPECTED_STATES)


def test_each_state_has_distinct_user_visible_label():
    labels = [s.label for s in NamedState]
    assert all(lab and str(lab).strip() for lab in labels)
    assert len(set(labels)) == len(labels), "labels must be pairwise distinct: %r" % labels


def test_all_labels_helper_covers_thirteen():
    m = all_labels()
    assert set(m) == set(EXPECTED_STATES)
    assert len(set(m.values())) == 13


# --------------------------------------------------------------------------
# Binding definitions — docstring verbatim lock
# --------------------------------------------------------------------------


def test_trichotomy_docstrings_match_binding_definitions_verbatim():
    """A second vocabulary cannot drift into existence."""
    docs = trichotomy_docstrings()
    assert docs["empty"] == BINDING_EMPTY
    assert docs["zero_measured"] == BINDING_ZERO_MEASURED
    assert docs["unknown"] == BINDING_UNKNOWN
    assert docs["pending"] == BINDING_PENDING

    assert NamedState.empty.__doc__ == BINDING_EMPTY
    assert NamedState.zero_measured.__doc__ == BINDING_ZERO_MEASURED
    assert NamedState.unknown.__doc__ == BINDING_UNKNOWN
    assert NamedState.pending.__doc__ == BINDING_PENDING


def test_binding_definition_constants_match_plan_wording():
    # Spot-check key phrases from IMPLEMENTATION-PLAN Binding definitions.
    assert "legitimately no series and no scope" in BINDING_EMPTY
    assert "total is 0" in BINDING_ZERO_MEASURED
    assert "trustworthy zero" in BINDING_ZERO_MEASURED
    assert "did not successfully read" in BINDING_UNKNOWN
    assert "never fetched" in BINDING_UNKNOWN
    assert "no aggregator exists yet" in BINDING_PENDING
    assert "has not been built" in BINDING_PENDING


def test_every_member_has_nonempty_docstring_definition():
    for state in NamedState:
        assert state.__doc__ and state.__doc__.strip(), state.value
        assert state.definition and state.definition.strip(), state.value


# --------------------------------------------------------------------------
# render_state — single render primitive
# --------------------------------------------------------------------------


def test_render_state_emits_distinct_nonblank_visible_label_for_all_thirteen():
    rendered = {s.value: render_state(s) for s in NamedState}
    assert len(rendered) == 13
    visibles = []
    for token, html in rendered.items():
        assert html.strip(), token
        assert 'class="named-state"' in html, token
        assert 'data-named-state="%s"' % token in html, token
        # Visible text node: content between > and </span>
        m = re.search(r">([^<]+)</span>", html)
        assert m, "no visible text node for %s: %r" % (token, html)
        text = m.group(1).strip()
        assert text, token
        assert text not in {"", "—", "-", "0", "0.0"}
        visibles.append(text)
    assert len(set(visibles)) == 13


def test_trichotomy_four_distinct_rendered_strings_match_binding_tokens():
    strings = {t: render_state(NamedState(t)) for t in TRICHOTOMY}
    texts = {}
    for t, html in strings.items():
        m = re.search(r">([^<]+)</span>", html)
        assert m, t
        texts[t] = m.group(1)
        # Label matches the binding vocabulary token (and is present visibly).
        assert t in texts[t]
    assert len(set(texts.values())) == 4


def test_render_state_accepts_string_token():
    html = render_state("unknown")
    assert "unknown" in html
    assert 'data-named-state="unknown"' in html


def test_render_state_raises_on_none():
    with pytest.raises(BlankStateError):
        render_state(None)


def test_render_state_raises_on_blank_string():
    with pytest.raises(BlankStateError):
        render_state("")
    with pytest.raises(BlankStateError):
        render_state("   ")


def test_render_state_raises_on_forbidden_placeholder():
    with pytest.raises(BlankStateError):
        render_state("—")
    with pytest.raises(BlankStateError):
        render_state("0")


# --------------------------------------------------------------------------
# GWT: None value → unknown label, never 0 / — / empty cell
# --------------------------------------------------------------------------


def test_gwt_unread_value_renders_unknown_not_zero_or_dash_or_empty():
    """Given a tile whose value is None because the query never ran,
    when render_state is called (as NamedState.unknown), then the rendered
    HTML contains the 'unknown' label as a visible text node and does not
    contain '0', '—', or an empty cell.
    """
    # Business value is None → caller maps to unknown (never blank).
    value = None
    assert value is None
    state = NamedState.unknown  # the only legal render for "never fetched"
    html = render_state(state)

    assert "unknown" in html
    m = re.search(r">([^<]+)</span>", html)
    assert m is not None
    visible = m.group(1)
    assert visible.strip() == "unknown"
    # Must not look like a measured zero or a placeholder empty cell.
    assert visible.strip() not in {"0", "—", "-", "–", ""}
    assert ">0<" not in html
    assert ">—</" not in html and ">—</span>" not in html
    # Not an empty span
    assert not re.search(r"<span[^>]*>\s*</span>", html)


# --------------------------------------------------------------------------
# FAILURE_STATE_TABLE schema (0080 / 0081)
# --------------------------------------------------------------------------


def test_failure_state_table_schema_exports_required_separate_states():
    assert FAILURE_STATE_TABLE["schema"]
    assert "unknown" in FAILURE_STATE_TABLE["required_separate_states"]
    assert "empty" in FAILURE_STATE_TABLE["required_separate_states"]
    assert "0080" in FAILURE_STATE_TABLE["hardening_gates"]
    assert "0081" in FAILURE_STATE_TABLE["hardening_gates"]


def test_valid_failure_state_table_with_separate_unknown_and_empty():
    table = [
        {"state": "unknown", "user_visible": "unknown", "trigger": "read failed"},
        {"state": "empty", "user_visible": "empty", "trigger": "scope empty"},
        {
            "state": "zero_measured",
            "user_visible": "zero_measured",
            "trigger": "measured zero",
        },
        {"state": "pending", "user_visible": "pending", "trigger": "no aggregator"},
    ]
    validate_failure_state_table(table)  # does not raise


def test_gwt_merged_unknown_empty_row_fails_naming_merged_row():
    """Given a failure-state table declaring one combined 'unknown/empty' row,
    when the table schema validator runs, then it fails naming the merged row.
    """
    bad = [
        {
            "state": "unknown/empty",
            "user_visible": "n/a",
            "trigger": "collapsed",
        },
        {"state": "pending", "user_visible": "pending", "trigger": "x"},
    ]
    with pytest.raises(FailureStateTableError) as ei:
        validate_failure_state_table(bad)
    msg = str(ei.value)
    assert "unknown/empty" in msg or "unknown" in msg
    assert "empty" in msg
    assert "0080" in msg or "0081" in msg or "SEPARATE" in msg


def test_merged_pending_zero_measured_row_fails():
    bad = [
        {"state": "unknown", "user_visible": "unknown", "trigger": "x"},
        {"state": "empty", "user_visible": "empty", "trigger": "y"},
        {
            "state": "pending/zero_measured",
            "user_visible": "bad",
            "trigger": "collapsed",
        },
    ]
    with pytest.raises(FailureStateTableError) as ei:
        validate_failure_state_table(bad)
    assert "pending" in str(ei.value)
    assert "zero_measured" in str(ei.value)


def test_missing_empty_row_fails():
    bad = [
        {"state": "unknown", "user_visible": "unknown", "trigger": "x"},
        {"state": "pending", "user_visible": "pending", "trigger": "y"},
    ]
    with pytest.raises(FailureStateTableError) as ei:
        validate_failure_state_table(bad)
    assert "empty" in str(ei.value)


def test_validate_accepts_rows_mapping_shape():
    table = {
        "rows": [
            {"state": "unknown", "user_visible": "unknown", "trigger": "x"},
            {"state": "empty", "user_visible": "empty", "trigger": "y"},
        ]
    }
    validate_failure_state_table(table)


# --------------------------------------------------------------------------
# zero_inference_lint
# --------------------------------------------------------------------------


def test_gwt_zero_inference_lint_flags_subscription_when_cost_eq_zero():
    """Given code that renders '(subscription)' when cost == 0,
    when zero_inference_lint.py scans it, then it reports a zero-inference
    violation with file and line.
    """
    src = (
        "def render_cost(cost):\n"
        "    if cost == 0:\n"
        '        return "(subscription)"\n'
        "    return '$' + str(cost)\n"
    )
    violations = zil.lint_source(src, path="fake_cost_view.py")
    assert violations, "expected at least one zero-inference violation"
    v = violations[0]
    assert v.path == "fake_cost_view.py"
    assert v.line >= 1
    assert "zero-inference" in v.message.lower() or "zero" in v.message.lower()
    assert "cost" in v.message.lower() or "subscription" in (v.snippet or "").lower()


def test_zero_inference_lint_clean_when_label_from_state():
    src = (
        "from anchor.ui.named_state import NamedState, render_state\n"
        "\n"
        "def render_cost(cost, cost_state):\n"
        "    if cost_state == 'subscription_covered':\n"
        '        return "(subscription)"\n'
        "    if cost_state == 'unmeasured':\n"
        "        return render_state(NamedState.unmeasured)\n"
        "    return '$' + str(cost)\n"
    )
    violations = zil.lint_source(src, path="honest_cost_view.py")
    assert violations == []


def test_zero_inference_lint_format_report_and_main_exit():
    src = "if total == 0:\n    return 'empty'\n"
    viols = zil.lint_source(src, path="t.py")
    assert viols
    report = zil.format_report(viols)
    assert "violation" in report
    assert zil.main([]) == 2  # usage


def test_zero_inference_lint_path_roundtrip(tmp_path: Path):
    p = tmp_path / "bad.py"
    p.write_text(
        "def f(cost):\n    if cost == 0:\n        return '(subscription)'\n",
        encoding="utf-8",
    )
    viols = zil.lint_path(p)
    assert viols
    assert viols[0].line >= 1


# --------------------------------------------------------------------------
# generate_html + node --check
# --------------------------------------------------------------------------


def test_generate_html_contains_all_state_labels_as_visible_text():
    doc = generate_html()
    assert "<!DOCTYPE html>" in doc
    assert 'data-surface="named-state"' in doc
    for token in EXPECTED_STATES:
        assert 'data-named-state="%s"' % token in doc
        # Visible label present as text node content
        assert ">%s</span>" % token in doc


def test_generate_html_unknown_tile_gwt_constraints():
    doc = generate_html([NamedState.unknown])
    assert "unknown" in doc
    # The unknown tile must not present a bare measured-zero or dash cell.
    assert re.search(r'data-named-state="unknown"[^>]*>unknown</span>', doc)
    # No empty named-state span
    assert not re.search(r'class="named-state"[^>]*>\s*</span>', doc)


def test_generate_html_script_block_node_check():
    """node --check on any emitted script block (skip if node absent)."""
    doc = generate_html()
    scripts = re.findall(r"<script>\s*(.*?)\s*</script>", doc, flags=re.DOTALL)
    assert scripts, "generate_html must emit a script block for node --check"
    node = shutil.which("node")
    if not node:
        pytest.skip("node binary not on PATH — script extracted but not checked")
    for idx, body in enumerate(scripts):
        # Write relative to a temp file via subprocess stdin check:
        # node --check -  is not portable; use a temp sibling under tests.
        out = Path(__file__).resolve().parent / ("_w6_script_check_%d.js" % idx)
        try:
            out.write_text(body, encoding="utf-8")
            proc = subprocess.run(
                [node, "--check", str(out)],
                capture_output=True,
                text=True,
                timeout=30,
            )
            assert proc.returncode == 0, (
                "node --check failed for script block %d:\n%s\n%s"
                % (idx, proc.stdout, proc.stderr)
            )
        finally:
            if out.exists():
                out.unlink()


def test_module_exports_importable_by_gate():
    # Acceptance: every new module is imported by at least one gate test.
    assert ns.NamedState is NamedState
    assert callable(ns.render_state)
    assert isinstance(ns.FAILURE_STATE_TABLE, dict)
    assert zil.lint_source is not None
