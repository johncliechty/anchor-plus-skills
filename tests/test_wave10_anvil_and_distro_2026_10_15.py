"""Wave 10 — Second Anvil Refactoring & Hardening Pass + Full Distro Bundle Verification (2026-10-15)."""
from __future__ import annotations

import ast
from datetime import date
from pathlib import Path
import warnings

import comms_connector as cc
import distro


REPO = Path(__file__).resolve().parents[1]


def test_all_shippable_python_files_parse_with_zero_syntax_warnings():
    """Anvil Pass 2 gate: every shippable .py file in dist_manifest.txt parses with zero SyntaxWarnings."""
    selected = distro.select_shippable(root=REPO)
    py_files = [rel for rel in selected if rel.endswith(".py")]
    assert len(py_files) >= 50
    caught = []
    for rel in py_files:
        src = (REPO / rel).read_text(encoding="utf-8")
        with warnings.catch_warnings(record=True) as wlist:
            warnings.simplefilter("always", SyntaxWarning)
            ast.parse(src, filename=rel)
            for w in wlist:
                if issubclass(w.category, SyntaxWarning):
                    caught.append((rel, w.lineno, str(w.message)))
    assert caught == [], f"Unexpected SyntaxWarnings in shippable files: {caught}"


def test_comms_connector_ics_parser_differential_equivalence_folded_vs_unfolded():
    """Anvil Essential Core equivalence: folded RFC 5545 ICS lines produce identical event dicts to unfolded lines."""
    unfolded_ics = (
        "BEGIN:VCALENDAR\r\n"
        "BEGIN:VEVENT\r\n"
        "UID:eq-check-001@example.com\r\n"
        "SUMMARY:Confirm Merrill Exmera LP -> Holding Co transfer language with Stanford\r\n"
        "DTSTART:20261017T150000Z\r\n"
        "DTEND:20261017T160000Z\r\n"
        "LOCATION:Boardroom & Zoom\r\n"
        "DESCRIPTION:Review final LP assignment schedule and trust signatures.\r\n"
        "END:VEVENT\r\n"
        "END:VCALENDAR\r\n"
    )
    folded_ics = (
        "BEGIN:VCALENDAR\r\n"
        "BEGIN:VEVENT\r\n"
        "UID:eq-check-001@\r\n"
        " example.com\r\n"
        "SUMMARY:Confirm Merrill Exmera LP -> Hold\r\n"
        " ing Co transfer language with Stanford\r\n"
        "DTSTART:20261017T150000Z\r\n"
        "DTEND:20261017T160000Z\r\n"
        "LOCATION:Boardroom & \r\n"
        "\tZoom\r\n"
        "DESCRIPTION:Review final LP assignment \r\n"
        " schedule and trust signatures.\r\n"
        "END:VEVENT\r\n"
        "END:VCALENDAR\r\n"
    )
    ev_unfolded = cc.parse_ics_text(unfolded_ics, today=date(2026, 10, 15))
    ev_folded = cc.parse_ics_text(folded_ics, today=date(2026, 10, 15))
    assert ev_unfolded == ev_folded
    assert len(ev_unfolded) == 1
    assert ev_unfolded[0]["uid"] == "eq-check-001@example.com"


def test_full_distro_build_stages_wave9_and_passes_all_four_gates(tmp_path):
    """Wave 10 Distro Gate: build_distro stages comms_connector.py and passes PII, import-closure, scrub-residue, and startup-import gates."""
    out_dir = tmp_path / "anchor-export"
    report = distro.build_distro(
        root=REPO,
        output_dir=out_dir,
        emit_readme_file=True,
        cleanup_on_fail=False,
        vendor_skills_=False,
    )
    assert "comms_connector.py" in report["files"]
    assert (out_dir / "comms_connector.py").is_file()
    assert (out_dir / "README.md").is_file()
    assert (out_dir / "CLAUDE.md").is_file()
